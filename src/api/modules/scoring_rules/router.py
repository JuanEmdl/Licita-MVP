"""
Reglas del puntaje (RF-032, RF-033, DA-14).

Todos los roles consultan las reglas; el Administrador propone una versión nueva y
el Gerente Comercial la confirma o la rechaza (doble control, Tabla 61). Una versión
publicada no se edita: el cambio es otra versión.
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.middleware.auth import requiere_permiso
from src.shared.reglas_repo import (
    OperacionReglasNoPermitidaError,
    ReglasInvalidasError,
    RepositorioReglas,
    VersionNoEncontradaError,
)
from src.shared.roles import Permiso

router = APIRouter(prefix="/reglas-puntaje", tags=["Reglas del puntaje"])


class PropuestaReglas(BaseModel):
    ponderaciones: Dict[str, float] = Field(..., description="Peso de cada categoría de requisitos; suman 100.")
    umbral_ofertar: float = Field(..., ge=0, le=100)
    umbral_revision: float = Field(..., ge=0, le=100)
    nota: Optional[str] = Field(None, max_length=1000, description="Motivo del cambio.")


class Rechazo(BaseModel):
    motivo: str = Field(..., min_length=1, max_length=1000)


def obtener_repositorio_reglas() -> RepositorioReglas:
    return RepositorioReglas()


def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


def _http(e: Exception) -> HTTPException:
    if isinstance(e, VersionNoEncontradaError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ReglasInvalidasError):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=409, detail=str(e))


@router.get("/")
def consultar_reglas(
    usuario: dict = Depends(requiere_permiso(Permiso.REGLAS_VER)),
    repositorio: RepositorioReglas = Depends(obtener_repositorio_reglas),
):
    """Versión vigente, propuesta pendiente (si hay) e historial completo."""
    historial = repositorio.historial()
    return {
        "vigente": next((r for r in historial if r["estado"] == "Vigente"), None),
        "propuesta": next((r for r in historial if r["estado"] == "Propuesta"), None),
        "historial": historial,
    }


@router.get("/{version}")
def consultar_version(
    version: int,
    usuario: dict = Depends(requiere_permiso(Permiso.REGLAS_VER)),
    repositorio: RepositorioReglas = Depends(obtener_repositorio_reglas),
):
    try:
        return repositorio.obtener(version)
    except VersionNoEncontradaError as e:
        raise _http(e)


@router.put("/", status_code=status.HTTP_201_CREATED)
def proponer_reglas(
    propuesta: PropuestaReglas,
    usuario: dict = Depends(requiere_permiso(Permiso.REGLAS_PROPONER)),
    repositorio: RepositorioReglas = Depends(obtener_repositorio_reglas),
):
    """Tabla 45: el Administrador propone una versión; 422 si las ponderaciones no suman 100."""
    try:
        return repositorio.proponer(propuesta.ponderaciones, propuesta.umbral_ofertar,
                                    propuesta.umbral_revision, _usuario(usuario), propuesta.nota)
    except (ReglasInvalidasError, OperacionReglasNoPermitidaError) as e:
        raise _http(e)


@router.post("/{version}/confirmar")
def confirmar_reglas(
    version: int,
    usuario: dict = Depends(requiere_permiso(Permiso.REGLAS_CONFIRMAR)),
    repositorio: RepositorioReglas = Depends(obtener_repositorio_reglas),
):
    """La gerencia comercial publica la propuesta: rige para los análisis que se soliciten después."""
    try:
        return repositorio.confirmar(version, _usuario(usuario))
    except (VersionNoEncontradaError, OperacionReglasNoPermitidaError) as e:
        raise _http(e)


@router.post("/{version}/rechazar")
def rechazar_reglas(
    version: int,
    rechazo: Rechazo,
    usuario: dict = Depends(requiere_permiso(Permiso.REGLAS_CONFIRMAR)),
    repositorio: RepositorioReglas = Depends(obtener_repositorio_reglas),
):
    try:
        return repositorio.rechazar(version, _usuario(usuario), rechazo.motivo)
    except (VersionNoEncontradaError, OperacionReglasNoPermitidaError, ReglasInvalidasError) as e:
        raise _http(e)
