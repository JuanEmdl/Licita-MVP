"""
Consumo de inferencia y cuota del periodo (RF-028, RN-10, ASR-13).

El administrador consulta el consumo junto con la telemetría (Tabla 61) y es el
responsable autorizado de ampliar la cuota; la ampliación queda en la bitácora.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.middleware.auth import requiere_permiso
from src.shared.consumo_repo import CuotaInvalidaError, RepositorioConsumo
from src.shared.roles import Permiso

router = APIRouter(prefix="/consumo", tags=["Consumo de inferencia"])


class Ampliacion(BaseModel):
    limite: int = Field(..., gt=0, description="Nuevo límite de tokens para el periodo en curso.")
    motivo: str = Field(..., min_length=1, max_length=1000)


def obtener_repositorio_consumo() -> RepositorioConsumo:
    return RepositorioConsumo()


@router.get("/")
def estado_consumo(
    usuario: dict = Depends(requiere_permiso(Permiso.DIAGNOSTICO_VER)),
    repositorio: RepositorioConsumo = Depends(obtener_repositorio_consumo),
):
    """Tokens consumidos en el periodo, límite, porcentaje y si se alcanzó la alerta o la cuota."""
    return repositorio.estado()


@router.post("/ampliar")
def ampliar_cuota(
    ampliacion: Ampliacion,
    usuario: dict = Depends(requiere_permiso(Permiso.CUOTA_AMPLIAR)),
    repositorio: RepositorioConsumo = Depends(obtener_repositorio_consumo),
):
    try:
        return repositorio.ampliar(ampliacion.limite, usuario.get("email") or usuario.get("user_id"),
                                   ampliacion.motivo)
    except CuotaInvalidaError as e:
        raise HTTPException(status_code=422, detail=str(e))
