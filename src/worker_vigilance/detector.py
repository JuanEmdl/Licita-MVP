"""
Detector de cambios (RF-019): compara la versión recuperada de un proceso seguido con
la última conocida y produce sus novedades.

Los cambios son de cuatro tipos, los que nombra el requisito:
- Estado: estado del procedimiento o fase.
- Fechas: publicación y cierre (recepción de ofertas).
- Documentos: archivos publicados o retirados del expediente en SECOP II.
- Requisitos: un documento nuevo que por su nombre puede cambiar las exigencias (adenda,
  pliego, anexo técnico...). Datos Abiertos no publica los requisitos como datos, así que
  esta novedad avisa que la lista aprobada puede haber quedado desactualizada (HU-06 CA-03).
"""
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from src.worker_vigilance.afinidad import normalizar


class TipoNovedad:
    ESTADO = "Estado"
    FECHAS = "Fechas"
    DOCUMENTOS = "Documentos"
    REQUISITOS = "Requisitos"


# Campo del proceso -> (tipo de novedad, nombre visible)
CAMPOS_VIGILADOS = {
    "estado": (TipoNovedad.ESTADO, "Estado del procedimiento"),
    "fase": (TipoNovedad.ESTADO, "Fase"),
    "fecha_publicacion": (TipoNovedad.FECHAS, "Fecha de publicación"),
    "fecha_cierre": (TipoNovedad.FECHAS, "Fecha de cierre"),
}

# Nombres de archivo que suelen modificar las exigencias del pliego.
_DOCUMENTOS_DE_REQUISITOS = re.compile(
    r"adenda|modificaci|pliego|anexo tecnico|especificaciones|requisitos|estudios? previos?|"
    r"condiciones|terminos de referencia|invitacion")


def _valor(valor: Any) -> Optional[str]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ", timespec="minutes")
    return str(valor)


def huella_proceso(proceso: Dict[str, Any]) -> str:
    """Huella de los campos vigilados: si no cambia, no hay novedad que buscar."""
    datos = {campo: _valor(proceso.get(campo)) for campo in CAMPOS_VIGILADOS}
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode("utf-8")).hexdigest()


def cambios_proceso(anterior: Dict[str, Any], nuevo: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    novedades = []
    for campo, (tipo, nombre) in CAMPOS_VIGILADOS.items():
        antes, despues = _valor(anterior.get(campo)), _valor(nuevo.get(campo))
        # Que la fuente deje de publicar un valor no es un cambio del proceso, y completar un dato
        # que el sistema no tenía tampoco, salvo la fecha de cierre: publicarla sí es una novedad.
        if despues is None or antes == despues or (antes is None and campo != "fecha_cierre"):
            continue
        novedades.append({"tipo": tipo, "campo": nombre, "antes": antes, "despues": despues})
    return novedades


def puede_cambiar_requisitos(nombre_documento: str) -> bool:
    return bool(_DOCUMENTOS_DE_REQUISITOS.search(normalizar(nombre_documento)))


def cambios_documentos(conocidos: Iterable[Dict[str, Any]],
                       publicados: Iterable[Dict[str, Any]]) -> List[Dict[str, Optional[str]]]:
    """
    conocidos: documentos del expediente que vinieron de la fuente (id_documento_fuente, nombre).
    publicados: lista actual de Datos Abiertos. Los cargados a mano no cuentan: no están en la fuente.
    """
    previos = {d["id_documento_fuente"]: d for d in conocidos if d.get("id_documento_fuente")}
    actuales = {d["id_documento_fuente"]: d for d in publicados if d.get("id_documento_fuente")}
    # Una lista vacía es una respuesta incompleta de la fuente, no el retiro de todo el expediente.
    if not actuales:
        return []
    novedades = []
    for clave, documento in actuales.items():
        if clave in previos:
            continue
        novedades.append({"tipo": TipoNovedad.DOCUMENTOS, "campo": "Documento publicado",
                          "antes": None, "despues": documento["nombre"]})
        if puede_cambiar_requisitos(documento["nombre"]):
            novedades.append({"tipo": TipoNovedad.REQUISITOS, "campo": "Posible cambio de requisitos",
                              "antes": None, "despues": documento["nombre"]})
    for clave, documento in previos.items():
        if clave not in actuales:
            novedades.append({"tipo": TipoNovedad.DOCUMENTOS, "campo": "Documento retirado de la fuente",
                              "antes": documento["nombre"], "despues": None})
    return novedades
