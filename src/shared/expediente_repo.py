"""
Expediente documental de cada proceso (RF-011, RF-021, RF-022).

Cada documento conserva su nombre, su versión, su procedencia (SECOP II o carga manual),
su fecha de obtención y su huella SHA-256. El expediente identifica de forma explícita
los documentos faltantes (publicados en la fuente pero no obtenidos) y los ilegibles
(obtenidos sin texto utilizable), para que el analista continúe o los cargue a mano.

Cargar de nuevo un documento crea una versión nueva y deja la anterior como histórico:
el análisis usa siempre la versión vigente y el informe declara cuál fue.
"""
import hashlib
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.shared.lectura_documentos import FORMATOS_ADMITIDOS, extension_de, leer_documento, resumen_paginas
from src.shared.models import DocumentoExpediente, Oportunidad

logger = logging.getLogger(__name__)


class EstadoDocumento:
    DISPONIBLE = "Disponible"
    FALTANTE = "Faltante"
    ILEGIBLE = "Ilegible"


PROCEDENCIA_MANUAL = "Carga manual"
# Tras estos rechazos seguidos de la fuente, no se insiste con el resto de archivos del proceso.
RECHAZOS_PARA_DESISTIR = 3


class DocumentoNoAdmitidoError(ValueError):
    """El archivo no cumple las restricciones de la carga manual (formato o tamaño)."""


class DocumentoNoEncontradoError(Exception):
    pass


def _iso(valor: Optional[datetime]) -> Optional[str]:
    return valor.isoformat() if valor else None


def _nombre_seguro(nombre: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", nombre)[-120:] or "documento"


def _clave_nombre(nombre: str) -> str:
    return " ".join((nombre or "").lower().split())


class RepositorioExpediente:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None,
                 directorio: Optional[str] = None, max_mb: Optional[int] = None):
        from src.shared.config import obtener_configuracion

        config = obtener_configuracion()
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._sesiones = fabrica_sesiones
        self.directorio = directorio or config.expedientes_dir
        self.max_bytes = (max_mb or config.expediente_max_mb) * 1024 * 1024

    # --- Almacenamiento ---

    def _guardar_archivo(self, id_proceso: str, documento_id: int, version: int, nombre: str,
                         contenido: bytes) -> str:
        carpeta = os.path.join(self.directorio, _nombre_seguro(id_proceso))
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, f"{documento_id:06d}_v{version}_{_nombre_seguro(nombre)}")
        with open(ruta, "wb") as f:
            f.write(contenido)
        return ruta

    def _completar_con_archivo(self, db: Session, documento: DocumentoExpediente, contenido: bytes) -> None:
        lectura = leer_documento(documento.nombre, contenido)
        documento.estado = EstadoDocumento.ILEGIBLE if lectura.ilegible else EstadoDocumento.DISPONIBLE
        documento.motivo = lectura.motivo
        documento.paginas = lectura.paginas
        documento.huella_sha256 = hashlib.sha256(contenido).hexdigest()
        documento.tamano_bytes = len(contenido)
        documento.obtenido_en = datetime.utcnow()
        db.flush()  # asigna el id antes de nombrar el archivo
        documento.ruta_archivo = self._guardar_archivo(
            documento.id_proceso, documento.id, documento.version, documento.nombre, contenido)

    # --- Documentos publicados en la fuente (RF-011) ---

    def registrar_publicados(self, id_proceso: str, publicados: Iterable[Dict[str, Any]], procedencia: str,
                             descargar: Optional[Callable[[Optional[str], int], bytes]] = None) -> Dict[str, int]:
        """
        Agrega al expediente los documentos que la fuente publica y aún no están en él.
        descargar(url, max_bytes) devuelve el archivo o lanza una excepción con el motivo;
        sin descargador (o si la fuente lo rechaza) el documento queda como faltante.
        """
        resumen = {"nuevos": 0, EstadoDocumento.DISPONIBLE: 0, EstadoDocumento.FALTANTE: 0,
                   EstadoDocumento.ILEGIBLE: 0}
        rechazos, ultimo_motivo = 0, None
        with self._sesiones() as db:
            conocidos = set(db.execute(select(DocumentoExpediente.id_documento_fuente).where(
                DocumentoExpediente.id_proceso == id_proceso,
                DocumentoExpediente.id_documento_fuente.is_not(None))).scalars())
            for publicado in publicados:
                clave = publicado.get("id_documento_fuente")
                if clave and clave in conocidos:
                    continue
                documento = DocumentoExpediente(
                    id_proceso=id_proceso, nombre=publicado["nombre"], version=1, procedencia=procedencia,
                    id_documento_fuente=clave, url_fuente=publicado.get("url_fuente"),
                    extension=publicado.get("extension") or extension_de(publicado["nombre"]) or None,
                    tamano_bytes=publicado.get("tamano_bytes"), publicado_en=publicado.get("publicado_en"),
                    estado=EstadoDocumento.FALTANTE, vigente=True)
                db.add(documento)
                resumen["nuevos"] += 1
                if descargar is None:
                    documento.motivo = "La descarga automática está desactivada (SECOP_DESCARGAR_DOCUMENTOS)."
                elif rechazos >= RECHAZOS_PARA_DESISTIR:
                    documento.motivo = ultimo_motivo
                else:
                    try:
                        self._completar_con_archivo(db, documento, descargar(documento.url_fuente, self.max_bytes))
                        rechazos = 0
                    except Exception as e:
                        rechazos += 1
                        ultimo_motivo = str(e) or type(e).__name__
                        documento.motivo = ultimo_motivo
                if documento.estado == EstadoDocumento.FALTANTE:
                    documento.motivo = f"{documento.motivo} Cárguelo manualmente desde SECOP II."
                resumen[documento.estado] += 1
                if clave:
                    conocidos.add(clave)
            db.commit()
        return resumen

    def conocidos_de_fuente(self, id_proceso: str) -> List[dict]:
        with self._sesiones() as db:
            return [{"id_documento_fuente": d.id_documento_fuente, "nombre": d.nombre}
                    for d in db.execute(select(DocumentoExpediente).where(
                        DocumentoExpediente.id_proceso == id_proceso,
                        DocumentoExpediente.id_documento_fuente.is_not(None))).scalars()]

    # --- Carga manual (RF-022) ---

    def cargar_manual(self, id_proceso: str, nombre: str, contenido: bytes, usuario: str,
                      reemplaza_id: Optional[int] = None, nota: Optional[str] = None) -> dict:
        """
        Incorpora un archivo autorizado del proceso con su procedencia y su versión. Si
        reemplaza a otro documento (o hay uno vigente con el mismo nombre), el anterior
        queda como histórico y el nuevo toma la versión siguiente.
        """
        nombre = os.path.basename((nombre or "").replace("\\", "/")).strip()
        extension = extension_de(nombre)
        if extension not in FORMATOS_ADMITIDOS:
            raise DocumentoNoAdmitidoError(
                f"El formato .{extension or '?'} no está admitido: cargue PDF, DOCX, XLSX o TXT.")
        if not contenido:
            raise DocumentoNoAdmitidoError("El archivo está vacío.")
        if len(contenido) > self.max_bytes:
            raise DocumentoNoAdmitidoError(
                f"El archivo supera el máximo de {self.max_bytes // (1024 * 1024)} MB.")
        with self._sesiones() as db:
            if db.get(Oportunidad, id_proceso) is None:
                raise DocumentoNoEncontradoError(f"El proceso {id_proceso} no está registrado.")
            anterior = None
            if reemplaza_id is not None:
                anterior = db.get(DocumentoExpediente, reemplaza_id)
                if anterior is None or anterior.id_proceso != id_proceso:
                    raise DocumentoNoEncontradoError(f"El documento {reemplaza_id} no pertenece a {id_proceso}.")
            else:
                anterior = next((d for d in db.execute(select(DocumentoExpediente).where(
                    DocumentoExpediente.id_proceso == id_proceso, DocumentoExpediente.vigente)).scalars()
                    if _clave_nombre(d.nombre) == _clave_nombre(nombre)), None)
            version = 1
            if anterior is not None:
                anterior.vigente = False
                # Un faltante nunca se obtuvo: la carga manual es su primera versión.
                version = anterior.version + (0 if anterior.estado == EstadoDocumento.FALTANTE else 1)
            documento = DocumentoExpediente(
                id_proceso=id_proceso, nombre=nombre, version=version,
                procedencia=f"{PROCEDENCIA_MANUAL} por {usuario}" + (f" ({nota.strip()})" if nota and nota.strip() else ""),
                id_documento_fuente=None, extension=extension, cargado_por=usuario,
                publicado_en=anterior.publicado_en if anterior is not None else None,
                estado=EstadoDocumento.FALTANTE, vigente=True)
            db.add(documento)
            self._completar_con_archivo(db, documento, contenido)
            db.commit()
            return self._a_dict(documento)

    # --- Consulta (RF-021) ---

    def expediente(self, id_proceso: str) -> dict:
        with self._sesiones() as db:
            todos = db.execute(select(DocumentoExpediente).where(DocumentoExpediente.id_proceso == id_proceso)
                               .order_by(DocumentoExpediente.publicado_en.nullslast(), DocumentoExpediente.id)
                               ).scalars().all()
        vigentes = [self._a_dict(d) for d in todos if d.vigente]
        return {
            "id_proceso": id_proceso,
            "documentos": vigentes,
            "historico": [self._a_dict(d) for d in todos if not d.vigente],
            "faltantes": [d["nombre"] for d in vigentes if d["estado"] == EstadoDocumento.FALTANTE],
            "ilegibles": [d["nombre"] for d in vigentes if d["estado"] == EstadoDocumento.ILEGIBLE],
            "disponibles": sum(1 for d in vigentes if d["estado"] == EstadoDocumento.DISPONIBLE),
            "completo": bool(vigentes) and all(d["estado"] == EstadoDocumento.DISPONIBLE for d in vigentes),
        }

    def documento(self, documento_id: int) -> Optional[dict]:
        with self._sesiones() as db:
            d = db.get(DocumentoExpediente, documento_id)
            return {**self._a_dict(d), "ruta_archivo": d.ruta_archivo} if d else None

    def contenido_para_analisis(self, id_proceso: str) -> dict:
        """Texto por página de los documentos vigentes legibles y la lista de los que no lo son."""
        with self._sesiones() as db:
            vigentes = db.execute(select(DocumentoExpediente).where(
                DocumentoExpediente.id_proceso == id_proceso, DocumentoExpediente.vigente)
                .order_by(DocumentoExpediente.publicado_en.nullslast(), DocumentoExpediente.id)).scalars().all()
            return {
                "documentos": [{"id": d.id, "nombre": d.nombre, "version": d.version, "procedencia": d.procedencia,
                                "huella_sha256": d.huella_sha256, "obtenido_en": _iso(d.obtenido_en),
                                "paginas": d.paginas or []}
                               for d in vigentes if d.estado == EstadoDocumento.DISPONIBLE],
                "no_analizados": [{"nombre": d.nombre, "estado": d.estado, "motivo": d.motivo}
                                  for d in vigentes if d.estado != EstadoDocumento.DISPONIBLE],
            }

    def huellas_vigentes(self, id_proceso: str) -> List[str]:
        """Huellas de los documentos que entrarían al análisis: cambian si cambia el expediente (RF-036)."""
        with self._sesiones() as db:
            return sorted(h for h in db.execute(select(DocumentoExpediente.huella_sha256).where(
                DocumentoExpediente.id_proceso == id_proceso, DocumentoExpediente.vigente,
                DocumentoExpediente.estado == EstadoDocumento.DISPONIBLE)).scalars() if h)

    @staticmethod
    def _a_dict(d: DocumentoExpediente) -> dict:
        return {
            "id": d.id, "id_proceso": d.id_proceso, "nombre": d.nombre, "version": d.version,
            "procedencia": d.procedencia, "estado": d.estado, "motivo": d.motivo,
            "extension": d.extension, "tamano_bytes": d.tamano_bytes,
            "publicado_en": _iso(d.publicado_en), "obtenido_en": _iso(d.obtenido_en),
            "huella_sha256": d.huella_sha256, "cargado_por": d.cargado_por, "vigente": d.vigente,
            "paginas": resumen_paginas(d.paginas) if d.paginas else None,
            "url_fuente": d.url_fuente, "tiene_archivo": bool(d.ruta_archivo),
        }
