import hashlib
import logging
from typing import Callable, Iterable, List, Optional

from langchain_core.embeddings import Embeddings
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.shared.models import Portafolio, PortafolioVersion

logger = logging.getLogger(__name__)


def huella_capacidad(tecnologia: str, categoria: str, descripcion: str) -> str:
    """Identifica el contenido de una capacidad: igual huella, igual vector (RF-010)."""
    texto = "\x1f".join(" ".join((v or "").split()) for v in (tecnologia, categoria, descripcion))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def texto_para_embedding(tecnologia: str, descripcion: str) -> str:
    return f"{tecnologia}. {descripcion}"


class PortfolioRepository:
    """
    Consulta del portafolio de capacidades y búsqueda de evidencia (RAG).

    Búsqueda en dos niveles:
      1. Vectorial (pgvector, distancia coseno) si hay modelo de embeddings y
         registros vectorizados.
      2. Texto completo de PostgreSQL ('spanish') como respaldo, para que el
         sistema siga siendo verificable sin el deployment de embeddings.
    Si ninguna encuentra coincidencias devuelve una lista vacía: el evaluador
    entonces dictamina "No verificable" en lugar de inventar evidencia.

    Sin version_id se consulta la versión vigente (capacidades activas). Un análisis
    pasa la versión que fijó al crearse, para que el resultado sea reproducible
    aunque se publique otra versión mientras corre (RN-03, RN-06).
    """

    def __init__(self, db: Session, modelo_embeddings: Optional[Embeddings] = None):
        """
        :param modelo_embeddings: se obtiene de LLMGateway.obtener_modelo_embeddings().
            Se inyecta en lugar de importar la pasarela para que src.shared no dependa
            del worker de análisis.
        """
        self.db = db
        self.modelo_embeddings = modelo_embeddings

    def listar(self, version_id: Optional[int] = None) -> List[dict]:
        stmt = self._de_version(select(Portafolio), version_id).order_by(Portafolio.id)
        return [self.a_dict(p) for p in self.db.execute(stmt).scalars().all()]

    @staticmethod
    def a_dict(item: Portafolio) -> dict:
        return {
            "id": item.id,
            "version": item.version_id,
            "tecnologia": item.tecnologia,
            "categoria": item.categoria,
            "descripcion": item.descripcion,
            "vectorizado": item.embedding is not None,
            "activo": item.activo,
        }

    @staticmethod
    def _de_version(stmt, version_id: Optional[int]):
        if version_id is None:
            return stmt.where(Portafolio.activo.is_(True))
        return stmt.where(Portafolio.version_id == version_id)

    # --- Búsqueda de evidencia ---

    def search_similar_capacities(self, query: str, limit: int = 4, version_id: Optional[int] = None) -> List[dict]:
        """Devuelve hasta `limit` capacidades relevantes para el requisito."""
        resultados: List[Portafolio] = []
        vector = self._generate_embedding(query)
        if vector is not None:
            stmt = (
                self._de_version(select(Portafolio), version_id)
                .where(Portafolio.embedding.is_not(None))
                .order_by(Portafolio.embedding.cosine_distance(vector))
                .limit(limit)
            )
            resultados = list(self.db.execute(stmt).scalars().all())

        if not resultados:
            resultados = self._buscar_texto_completo(query, limit, version_id)

        return [self.a_dict(r) for r in resultados]

    def _buscar_texto_completo(self, query: str, limit: int, version_id: Optional[int] = None) -> List[Portafolio]:
        documento = func.to_tsvector(
            "spanish",
            func.coalesce(Portafolio.tecnologia, "") + " " + func.coalesce(Portafolio.descripcion, ""),
        )
        # websearch_to_tsquery tolera texto libre; se combinan los términos con OR
        # para que un requisito largo no exija que todas sus palabras coincidan.
        terminos = " OR ".join(t for t in query.replace('"', " ").split() if len(t) > 3)
        if not terminos:
            return []
        consulta = func.websearch_to_tsquery("spanish", terminos)
        stmt = (
            self._de_version(select(Portafolio), version_id)
            .where(documento.op("@@")(consulta))
            .order_by(func.ts_rank(documento, consulta).desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        if self.modelo_embeddings is None:
            return None
        try:
            return self.modelo_embeddings.embed_query(text)
        except Exception as e:
            # Sin vector el registro sigue disponible para la búsqueda por texto.
            logger.warning(f"No se pudo generar el embedding ({type(e).__name__}); se usa búsqueda por texto.")
            return None


# ---------------------------------------------------------------------------
# Versionado del portafolio (RF-008, RF-009, RF-010, RN-03)
# ---------------------------------------------------------------------------

class ErrorPortafolio(Exception):
    """Error con mensaje apto para mostrar al usuario."""


class CapacidadNoEncontradaError(ErrorPortafolio):
    pass


class RepositorioVersionesPortafolio:
    """
    Cada cambio publica una versión nueva y completa del portafolio; la anterior queda
    como histórico consultable y sus capacidades no se modifican. Una capacidad que no
    cambió conserva su vector, de modo que solo se indexa el contenido nuevo o
    modificado (RF-010). La indexación la hace el trabajador de análisis al recibir el
    mensaje portafolio.indexar, o la API en segundo plano cuando no hay Service Bus.
    """

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None, auditoria=None):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones
        self._auditoria = auditoria

    @property
    def auditoria(self):
        if self._auditoria is None:
            from src.worker_analysis.reports.auditoria import RegistradorAuditoria
            self._auditoria = RegistradorAuditoria()
        return self._auditoria

    # --- Consulta ---

    def vigente(self) -> Optional[int]:
        with self._sesiones() as db:
            fila = db.execute(select(PortafolioVersion.id).where(PortafolioVersion.vigente.is_(True))).first()
            return fila[0] if fila else None

    def versiones(self) -> List[dict]:
        with self._sesiones() as db:
            totales = dict(db.execute(
                select(Portafolio.version_id, func.count()).group_by(Portafolio.version_id)).all())
            vectorizadas = dict(db.execute(
                select(Portafolio.version_id, func.count())
                .where(Portafolio.embedding.is_not(None)).group_by(Portafolio.version_id)).all())
            versiones = db.execute(select(PortafolioVersion).order_by(PortafolioVersion.id.desc())).scalars().all()
            return [{
                "version": v.id,
                "vigente": v.vigente,
                "descripcion_cambio": v.descripcion_cambio,
                "creada_por": v.creada_por,
                "creada_en": v.creada_en.isoformat() if v.creada_en else None,
                "capacidades": totales.get(v.id, 0),
                "vectorizadas": vectorizadas.get(v.id, 0),
            } for v in versiones]

    def capacidades(self, version_id: Optional[int] = None) -> List[dict]:
        with self._sesiones() as db:
            return PortfolioRepository(db).listar(version_id)

    # --- Publicación ---

    def publicar(self, capacidades: Iterable[dict], usuario: str, descripcion_cambio: Optional[str] = None) -> dict:
        """
        Publica una versión con exactamente estas capacidades (cada una con tecnologia,
        categoria y descripcion). Las repetidas se registran una sola vez.
        """
        nuevas, vistas = [], set()
        for c in capacidades:
            datos = {k: " ".join(str(c[k]).split()) for k in ("tecnologia", "categoria", "descripcion")}
            huella = huella_capacidad(**datos)
            if huella not in vistas:
                vistas.add(huella)
                nuevas.append((huella, datos))

        with self._sesiones() as db:
            # Bloquea la versión vigente: dos publicaciones simultáneas no parten de la misma base.
            anterior = db.execute(
                select(PortafolioVersion).where(PortafolioVersion.vigente.is_(True)).with_for_update()
            ).scalar_one_or_none()
            vectores = {}
            if anterior is not None:
                for p in db.execute(select(Portafolio).where(Portafolio.version_id == anterior.id)).scalars():
                    vectores[p.huella] = p.embedding
                anterior.vigente = False
                db.execute(update(Portafolio).where(Portafolio.version_id == anterior.id).values(activo=False))
                db.flush()  # El índice único admite una sola versión vigente.

            version = PortafolioVersion(vigente=True, creada_por=usuario,
                                        descripcion_cambio=(descripcion_cambio or "").strip() or None)
            db.add(version)
            db.flush()
            pendientes = 0
            for huella, datos in nuevas:
                embedding = vectores.get(huella)
                pendientes += embedding is None
                db.add(Portafolio(version_id=version.id, huella=huella, embedding=embedding, activo=True, **datos))

            previas = set(vectores)
            resumen = {
                "version": version.id,
                "version_anterior": anterior.id if anterior else None,
                "capacidades": len(nuevas),
                "agregadas_o_modificadas": len(vistas - previas),
                "retiradas": len(previas - vistas),
                "pendientes_de_indexar": pendientes,
            }
            self.auditoria.registrar_evento(f"portafolio-v{version.id}", "PORTAFOLIO_PUBLICADO", resumen,
                                            registrado_por=usuario)
            db.commit()
        logger.info(f"Portafolio: versión {resumen['version']} publicada por {usuario} "
                    f"({resumen['pendientes_de_indexar']} capacidades por indexar).")
        return resumen

    def _vigentes_como_datos(self) -> List[dict]:
        return [{k: c[k] for k in ("id", "tecnologia", "categoria", "descripcion")} for c in self.capacidades()]

    def agregar(self, capacidad: dict, usuario: str) -> dict:
        actuales = self._vigentes_como_datos()
        return self.publicar(actuales + [capacidad], usuario, f"Agrega «{capacidad['tecnologia']}»")

    def editar(self, capacidad_id: int, capacidad: dict, usuario: str) -> dict:
        actuales = self._vigentes_como_datos()
        if not any(c["id"] == capacidad_id for c in actuales):
            raise CapacidadNoEncontradaError("La capacidad no existe en la versión vigente del portafolio.")
        cambiadas = [capacidad if c["id"] == capacidad_id else c for c in actuales]
        return self.publicar(cambiadas, usuario, f"Modifica «{capacidad['tecnologia']}»")

    def retirar(self, capacidad_id: int, usuario: str) -> dict:
        actuales = self._vigentes_como_datos()
        retirada = next((c for c in actuales if c["id"] == capacidad_id), None)
        if retirada is None:
            raise CapacidadNoEncontradaError("La capacidad no existe en la versión vigente del portafolio.")
        return self.publicar([c for c in actuales if c["id"] != capacidad_id], usuario,
                             f"Retira «{retirada['tecnologia']}»")

    # --- Indexación incremental (RF-010) ---

    def indexar(self, version_id: int, modelo: Optional[Embeddings]) -> int:
        """
        Vectoriza las capacidades de la versión que aún no tienen vector. Repetible sin
        efectos: lo ya indexado no se vuelve a enviar al modelo. Devuelve cuántas indexó.
        """
        if modelo is None:
            logger.info(f"Portafolio v{version_id}: sin modelo de embeddings, se usa búsqueda por texto.")
            return 0
        indexadas = 0
        with self._sesiones() as db:
            pendientes = db.execute(select(Portafolio).where(
                Portafolio.version_id == version_id, Portafolio.embedding.is_(None))).scalars().all()
            for p in pendientes:
                try:
                    p.embedding = modelo.embed_query(texto_para_embedding(p.tecnologia, p.descripcion))
                except Exception as e:
                    logger.warning(f"No se pudo indexar la capacidad {p.id} ({type(e).__name__}); "
                                   "queda disponible para la búsqueda por texto.")
                    break
                indexadas += 1
            db.commit()
        logger.info(f"Portafolio v{version_id}: {indexadas} capacidades indexadas.")
        return indexadas

    def asegurar_version_inicial(self) -> Optional[int]:
        """
        Migra los portafolios registrados antes del versionado: si hay capacidades sin
        versión y ninguna versión publicada, las reúne en la versión 1 (vigente).
        """
        with self._sesiones() as db:
            if db.execute(select(PortafolioVersion.id)).first():
                return None
            sueltas = db.execute(select(Portafolio).where(
                Portafolio.version_id.is_(None), Portafolio.activo.is_(True))).scalars().all()
            if not sueltas:
                return None
            version = PortafolioVersion(vigente=True, creada_por="sistema",
                                        descripcion_cambio="Capacidades registradas antes del versionado")
            db.add(version)
            db.flush()
            for p in sueltas:
                p.version_id = version.id
                p.huella = huella_capacidad(p.tecnologia, p.categoria, p.descripcion)
            db.commit()
            logger.info(f"Portafolio: {len(sueltas)} capacidades migradas a la versión {version.id}.")
            return version.id
