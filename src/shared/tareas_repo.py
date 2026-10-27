"""
Repositorio de tareas de análisis (RF-026).
Guarda el estado visible para el usuario, incluido el motivo de una falla,
para que /estado no dependa solo del log del proceso que ejecutó el grafo.
"""
import hashlib
from typing import Iterable, List, Optional

from sqlalchemy import select

from src.shared.database import get_db
from src.shared.models import Licitacion, TareaAnalisis


class EstadoTarea:
    RECIBIDA = "Recibida"
    EN_PROCESO = "En proceso"
    ESPERANDO_REVISION = "Esperando revisión"
    EVALUANDO = "Evaluando"
    FINALIZADA = "Finalizada"
    SUSPENDIDA = "Suspendida"
    FALLIDA = "Fallida"


def huella_entrada(licitacion_id: str, contenido_pliego: Optional[str], documentos: Iterable[str] = ()) -> str:
    """
    Identifica la entrada de un análisis: el proceso, el pliego aportado y las huellas de
    los documentos vigentes del expediente (RF-036). Cargar una versión nueva de un
    documento cambia la entrada, así que el análisis anterior deja de ser reutilizable.
    Los espacios no cuentan, para que volver a pegar el mismo texto dé la misma huella.
    """
    pliego = " ".join((contenido_pliego or "").split())
    entrada = f"{licitacion_id.strip()}\x1f{pliego}"
    documentos = sorted(documentos)
    if documentos:
        entrada += "\x1f" + ",".join(documentos)
    return hashlib.sha256(entrada.encode("utf-8")).hexdigest()


class RepositorioTareas:

    def crear(self, tarea_id: str, licitacion_id: str, solicitado_por: str,
              reglas_version: Optional[int] = None, portafolio_version: Optional[int] = None,
              huella: Optional[str] = None) -> None:
        with get_db() as db:
            # La tarea referencia la licitación por clave foránea.
            if db.get(Licitacion, licitacion_id) is None:
                db.add(Licitacion(id=licitacion_id))
            db.add(TareaAnalisis(
                id=tarea_id,
                licitacion_id=licitacion_id,
                estado=EstadoTarea.RECIBIDA,
                solicitado_por=solicitado_por,
                reglas_version=reglas_version,
                portafolio_version=portafolio_version,
                huella_entrada=huella,
            ))
            db.commit()

    def buscar_reutilizable(self, huella: str, reglas_version: Optional[int],
                            portafolio_version: Optional[int]) -> Optional[dict]:
        """
        Análisis finalizado con la misma entrada y las mismas versiones de reglas y de
        portafolio (RN-09): su resultado sigue vigente y no hace falta repetirlo.
        """
        with get_db() as db:
            consulta = (
                select(TareaAnalisis)
                .where(
                    TareaAnalisis.huella_entrada == huella,
                    TareaAnalisis.estado == EstadoTarea.FINALIZADA,
                    TareaAnalisis.reglas_version.is_(None) if reglas_version is None
                    else TareaAnalisis.reglas_version == reglas_version,
                    TareaAnalisis.portafolio_version.is_(None) if portafolio_version is None
                    else TareaAnalisis.portafolio_version == portafolio_version,
                )
                .order_by(TareaAnalisis.actualizado_en.desc())
                .limit(1)
            )
            tarea = db.execute(consulta).scalar_one_or_none()
            return self._a_dict(tarea) if tarea else None

    def ultima_aprobada(self, licitacion_id: str, excluir: Optional[str] = None) -> Optional[dict]:
        """Último análisis del proceso con la lista de requisitos aprobada (HU-06 CA-03)."""
        with get_db() as db:
            consulta = (select(TareaAnalisis)
                        .where(TareaAnalisis.licitacion_id == licitacion_id, TareaAnalisis.aprobado_por.is_not(None))
                        .order_by(TareaAnalisis.creado_en.desc()).limit(1))
            if excluir:
                consulta = consulta.where(TareaAnalisis.id != excluir)
            tarea = db.execute(consulta).scalar_one_or_none()
            return self._a_dict(tarea) if tarea else None

    def actualizar(self, tarea_id: str, estado: str, **campos) -> None:
        with get_db() as db:
            tarea = db.get(TareaAnalisis, tarea_id)
            if tarea is None:
                return
            tarea.estado = estado
            for nombre, valor in campos.items():
                setattr(tarea, nombre, valor)
            db.commit()

    def obtener(self, tarea_id: str) -> Optional[dict]:
        with get_db() as db:
            tarea = db.get(TareaAnalisis, tarea_id)
            return self._a_dict(tarea) if tarea else None

    def listar(self, estado: Optional[str] = None, limite: int = 50) -> List[dict]:
        with get_db() as db:
            consulta = select(TareaAnalisis).order_by(TareaAnalisis.creado_en.desc()).limit(limite)
            if estado:
                consulta = consulta.where(TareaAnalisis.estado == estado)
            return [self._a_dict(t) for t in db.execute(consulta).scalars().all()]

    @staticmethod
    def _a_dict(tarea: TareaAnalisis) -> dict:
        return {
            "tarea_id": tarea.id,
            "licitacion_id": tarea.licitacion_id,
            "estado": tarea.estado,
            "detalle_error": tarea.detalle_error,
            "causa_suspension": tarea.causa_suspension,
            "solicitado_por": tarea.solicitado_por,
            "aprobado_por": tarea.aprobado_por,
            "puntaje": tarea.resultado_puntaje,
            "recomendacion": tarea.resultado_recomendacion,
            "reglas_version": tarea.reglas_version,
            "portafolio_version": tarea.portafolio_version,
            "decision": tarea.decision_comercial,
            "decision_por": tarea.decision_por,
            "decision_en": tarea.decision_en.isoformat() if tarea.decision_en else None,
            "creado_en": tarea.creado_en.isoformat() if tarea.creado_en else None,
            "actualizado_en": tarea.actualizado_en.isoformat() if tarea.actualizado_en else None,
        }
