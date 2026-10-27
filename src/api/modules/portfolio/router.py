"""
Módulo de portafolio (RF-008, RF-009, RF-010, RN-03).

Cada cambio publica una versión nueva y completa del portafolio y deja la anterior
como histórico consultable; los análisis conservan la versión con que se evaluaron.
Las capacidades nuevas o modificadas se indexan en segundo plano: lo hace el
trabajador al recibir portafolio.indexar, o la API cuando no hay Service Bus.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.adapters.queue import PublicadorTrabajos
from src.api.middleware.auth import requiere_permiso
from src.api.modules.analysis.router import obtener_publicador
from src.shared.portfolio_repo import CapacidadNoEncontradaError, RepositorioVersionesPortafolio
from src.shared.roles import Permiso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portafolio", tags=["Portafolio"])


class NuevaCapacidad(BaseModel):
    tecnologia: str = Field(..., min_length=1, max_length=200)
    categoria: str = Field(..., min_length=1, max_length=100)
    descripcion: str = Field(..., min_length=10, max_length=4000,
                             description="Evidencia verificable: cifras, años, certificaciones y vigencia.")


class NuevaVersion(BaseModel):
    capacidades: List[NuevaCapacidad] = Field(..., description="Contenido completo de la versión.")
    descripcion_cambio: Optional[str] = Field(None, max_length=500)


def obtener_repositorio_portafolio() -> RepositorioVersionesPortafolio:
    return RepositorioVersionesPortafolio()


def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


def _indexar(resumen: dict, background_tasks: BackgroundTasks, publicador: Optional[PublicadorTrabajos]) -> None:
    """Solo se indexa lo nuevo o modificado (RF-010); sin pendientes no se encola nada."""
    if not resumen["pendientes_de_indexar"]:
        return
    if publicador:
        publicador.encolar_indexacion(resumen["version"])
    else:
        from src.worker_analysis.servicio import indexar_portafolio
        background_tasks.add_task(indexar_portafolio, resumen["version"])


@router.get("/")
def listar_capacidades(
    version: Optional[int] = None,
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_VER)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
) -> List[dict]:
    """Capacidades de la versión vigente, o de la versión indicada (histórico)."""
    return repositorio.capacidades(version)


@router.get("/versiones")
def listar_versiones(
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_VER)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
) -> List[dict]:
    return repositorio.versiones()


@router.post("/versiones", status_code=status.HTTP_201_CREATED)
def publicar_version(
    version: NuevaVersion,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_GESTIONAR)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
) -> dict:
    """Tabla 45: publica una versión completa; la anterior queda como histórico."""
    resumen = repositorio.publicar([c.model_dump() for c in version.capacidades], _usuario(usuario),
                                   version.descripcion_cambio)
    _indexar(resumen, background_tasks, publicador)
    return resumen


@router.post("/", status_code=status.HTTP_201_CREATED)
def registrar_capacidad(
    capacidad: NuevaCapacidad,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_GESTIONAR)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
) -> dict:
    """Agrega una capacidad publicando una versión nueva (RF-009)."""
    resumen = repositorio.agregar(capacidad.model_dump(), _usuario(usuario))
    _indexar(resumen, background_tasks, publicador)
    return resumen


@router.put("/{capacidad_id}")
def editar_capacidad(
    capacidad_id: int,
    capacidad: NuevaCapacidad,
    background_tasks: BackgroundTasks,
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_EDITAR)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
    publicador: Optional[PublicadorTrabajos] = Depends(obtener_publicador),
) -> dict:
    try:
        resumen = repositorio.editar(capacidad_id, capacidad.model_dump(), _usuario(usuario))
    except CapacidadNoEncontradaError as e:
        raise HTTPException(status_code=404, detail=str(e))
    _indexar(resumen, background_tasks, publicador)
    return resumen


@router.delete("/{capacidad_id}")
def retirar_capacidad(
    capacidad_id: int,
    usuario: dict = Depends(requiere_permiso(Permiso.PORTAFOLIO_GESTIONAR)),
    repositorio: RepositorioVersionesPortafolio = Depends(obtener_repositorio_portafolio),
) -> dict:
    """La capacidad sale de la versión nueva; sigue en las anteriores (histórico)."""
    try:
        return repositorio.retirar(capacidad_id, _usuario(usuario))
    except CapacidadNoEncontradaError as e:
        raise HTTPException(status_code=404, detail=str(e))
