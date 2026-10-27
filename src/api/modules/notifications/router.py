"""
Notificaciones (RF-016, RF-017, RF-020).

Cada usuario consulta y marca como leídas solo las suyas, y configura el canal (solo
aplicación, o correo y aplicación) y la frecuencia (inmediata o resumen diario). Tabla 61,
fila "Perfiles de búsqueda y notificaciones": el gerente consulta; el analista y el
administrador además configuran. El alcance por destinatario se resuelve aquí.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.api.middleware.auth import requiere_permiso
from src.shared.config import obtener_configuracion
from src.shared.roles import Permiso

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


def obtener_notificaciones():
    from src.shared.notificaciones_repo import RepositorioNotificaciones
    return RepositorioNotificaciones()


def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


class Preferencias(BaseModel):
    canal: str
    frecuencia: str


@router.get("/")
def listar_notificaciones(
    no_leidas: bool = False,
    limite: int = 50,
    usuario: dict = Depends(requiere_permiso(Permiso.NOTIFICACIONES_VER)),
    repositorio=Depends(obtener_notificaciones),
):
    return repositorio.listar(_usuario(usuario), solo_no_leidas=no_leidas, limite=limite)


@router.post("/leidas", status_code=status.HTTP_200_OK)
def marcar_todas_leidas(
    usuario: dict = Depends(requiere_permiso(Permiso.NOTIFICACIONES_VER)),
    repositorio=Depends(obtener_notificaciones),
):
    return {"marcadas": repositorio.marcar_todas_leidas(_usuario(usuario))}


@router.post("/{notificacion_id}/leida", status_code=status.HTTP_204_NO_CONTENT)
def marcar_leida(
    notificacion_id: int,
    usuario: dict = Depends(requiere_permiso(Permiso.NOTIFICACIONES_VER)),
    repositorio=Depends(obtener_notificaciones),
):
    # Una notificación ajena se trata como inexistente.
    if not repositorio.marcar_leida(notificacion_id, _usuario(usuario)):
        raise HTTPException(status_code=404, detail="Notificación no encontrada")


@router.get("/preferencias")
def consultar_preferencias(
    usuario: dict = Depends(requiere_permiso(Permiso.NOTIFICACIONES_VER)),
    repositorio=Depends(obtener_notificaciones),
):
    from src.shared.notificaciones_repo import Canal, Frecuencia
    return {**repositorio.preferencias(_usuario(usuario)), "canales": list(Canal.TODOS),
            "frecuencias": list(Frecuencia.TODAS), "correo_configurado": obtener_configuracion().correo_configurado,
            "hora_resumen": obtener_configuracion().notificaciones_hora_resumen}


@router.put("/preferencias")
def guardar_preferencias(
    preferencias: Preferencias,
    usuario: dict = Depends(requiere_permiso(Permiso.NOTIFICACIONES_CONFIGURAR)),
    repositorio=Depends(obtener_notificaciones),
):
    """RF-016: canal y frecuencia de los avisos de perfiles y de procesos seguidos."""
    try:
        return repositorio.guardar_preferencias(_usuario(usuario), preferencias.canal, preferencias.frecuencia)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
