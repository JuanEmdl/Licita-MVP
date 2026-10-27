"""
Consulta de la bitácora de auditoría (RF-042, Tabla 61).

El Gerente Comercial y el Administrador la consultan; nadie la edita ni la borra
(solo anexado, también en la base). La verificación recorre la cadena de huellas
y señala dónde se rompe si un registro fue alterado o eliminado.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.middleware.auth import requiere_permiso
from src.shared.roles import Permiso

router = APIRouter(prefix="/auditoria", tags=["Auditoría"])


def obtener_registrador():
    from src.worker_analysis.reports.auditoria import RegistradorAuditoria
    return RegistradorAuditoria()


@router.get("/")
def consultar_bitacora(
    accion: Optional[str] = None,
    tarea_id: Optional[str] = None,
    usuario: Optional[str] = Query(None, description="Parte del correo de quien registró el evento."),
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    limite: int = Query(100, ge=1, le=500),
    desplazamiento: int = Query(0, ge=0),
    autor: dict = Depends(requiere_permiso(Permiso.BITACORA_VER)),
    registrador=Depends(obtener_registrador),
):
    """Eventos críticos con autor, fecha, tarea y valores modificados, del más reciente al más antiguo."""
    return registrador.consultar(accion=accion, tarea_id=tarea_id, usuario=usuario, desde=desde, hasta=hasta,
                                 limite=limite, desplazamiento=desplazamiento)


@router.get("/verificacion")
def verificar_bitacora(
    autor: dict = Depends(requiere_permiso(Permiso.BITACORA_VER)),
    registrador=Depends(obtener_registrador),
):
    """ASR-06: comprueba que ningún registro fue alterado ni borrado."""
    return registrador.verificar()
