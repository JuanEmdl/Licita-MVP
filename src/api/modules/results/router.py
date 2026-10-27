from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.middleware.auth import requiere_permiso
from src.api.modules.results.servicio import (
    DECISIONES,
    DecisionNoPermitidaError,
    ServicioDecisiones,
    TareaNoDecidibleError,
    TareaNoEncontradaError,
    obtener_servicio_decisiones,
)
from src.shared.roles import Permiso

router = APIRouter(prefix="/resultados", tags=["Resultados y decisiones"])


class SolicitudDecision(BaseModel):
    decision: str = Field(..., description=f"Una de: {', '.join(DECISIONES)}")
    justificacion: str = Field(..., min_length=1, max_length=2000)


def _usuario(usuario: dict) -> str:
    return usuario.get("email") or usuario.get("user_id") or "desconocido"


@router.get("/")
def tablero(
    recomendacion: Optional[str] = None,
    decision: Optional[str] = None,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioDecisiones = Depends(obtener_servicio_decisiones),
):
    """RF-038: análisis finalizados con recomendación automática y decisión humana (o «Pendiente»)."""
    return servicio.tablero(recomendacion=recomendacion, decision=decision)


@router.get("/opciones")
def opciones_decision(usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER))):
    return {"decisiones": DECISIONES}


@router.post("/{tarea_id}/decision", status_code=status.HTTP_201_CREATED)
def registrar_decision(
    tarea_id: str,
    solicitud: SolicitudDecision,
    usuario: dict = Depends(requiere_permiso(Permiso.DECISION_REGISTRAR)),
    servicio: ServicioDecisiones = Depends(obtener_servicio_decisiones),
):
    """RF-039: registra la decisión comercial con su fecha, autor y justificación."""
    try:
        return servicio.registrar(tarea_id, solicitud.decision, solicitud.justificacion, _usuario(usuario))
    except TareaNoEncontradaError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TareaNoDecidibleError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DecisionNoPermitidaError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{tarea_id}/decisiones")
def historial_decisiones(
    tarea_id: str,
    usuario: dict = Depends(requiere_permiso(Permiso.RESULTADOS_VER)),
    servicio: ServicioDecisiones = Depends(obtener_servicio_decisiones),
):
    """Historial de decisiones de la tarea, la más reciente primero."""
    try:
        return servicio.historial(tarea_id)
    except TareaNoEncontradaError as e:
        raise HTTPException(status_code=404, detail=str(e))
