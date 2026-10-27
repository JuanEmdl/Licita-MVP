"""
Servicio de resultados y decisiones (RF-038, RF-039).

El sistema sugiere; la decisión comercial la registra una persona autorizada:
continuar, descartar o solicitar información, siempre con fecha y justificación.
Cada decisión se agrega al historial (no se sobrescribe) y la tarea guarda la
más reciente para el tablero. Antes de confirmarla se anexa a la bitácora
encadenada: si la bitácora no la acepta, la decisión no queda registrada (RF-042).
"""
import logging
from datetime import datetime
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.shared.models import DecisionComercial, TareaAnalisis
from src.shared.tareas_repo import EstadoTarea, RepositorioTareas

logger = logging.getLogger(__name__)

CONTINUAR = "Continuar"
DESCARTAR = "Descartar"
SOLICITAR_INFORMACION = "Solicitar información"
DECISIONES: List[str] = [CONTINUAR, DESCARTAR, SOLICITAR_INFORMACION]

# Valor de "decision" en el tablero para las tareas que aún no tienen una.
PENDIENTE = "Pendiente"

# Decisión humana equivalente a cada recomendación del motor de puntaje.
_EQUIVALENTE = {
    "Ofertar": CONTINUAR,
    "No ofertar": DESCARTAR,
    "Solicitar revisión": SOLICITAR_INFORMACION,
}


class ErrorDecision(Exception):
    """Error con mensaje apto para mostrar al usuario."""


class TareaNoEncontradaError(ErrorDecision):
    pass


class DecisionNoPermitidaError(ErrorDecision):
    """Decisión o justificación inválidas."""


class TareaNoDecidibleError(ErrorDecision):
    """La tarea todavía no tiene un resultado sobre el cual decidir."""


def coincide_con_sugerencia(decision: str, recomendacion: Optional[str]) -> Optional[bool]:
    """None si el sistema no emitió una recomendación reconocible."""
    equivalente = _EQUIVALENTE.get(recomendacion or "")
    return None if equivalente is None else equivalente == decision


class ServicioDecisiones:

    def __init__(
        self,
        fabrica_sesiones: Optional[Callable[[], Session]] = None,
        auditoria=None,
    ):
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        if auditoria is None:
            from src.worker_analysis.reports.auditoria import RegistradorAuditoria
            auditoria = RegistradorAuditoria()
        self._sesiones = fabrica_sesiones
        self.auditoria = auditoria

    # --- Tablero (RF-038) ---

    def tablero(
        self,
        recomendacion: Optional[str] = None,
        decision: Optional[str] = None,
        limite: int = 100,
    ) -> List[dict]:
        """Análisis finalizados con su recomendación y la última decisión humana."""
        consulta = (
            select(TareaAnalisis)
            .where(TareaAnalisis.estado == EstadoTarea.FINALIZADA)
            .order_by(TareaAnalisis.actualizado_en.desc())
            .limit(limite)
        )
        if recomendacion:
            consulta = consulta.where(TareaAnalisis.resultado_recomendacion == recomendacion)
        if decision == PENDIENTE:
            consulta = consulta.where(TareaAnalisis.decision_comercial.is_(None))
        elif decision:
            consulta = consulta.where(TareaAnalisis.decision_comercial == decision)
        with self._sesiones() as db:
            filas = []
            for tarea in db.execute(consulta).scalars().all():
                fila = RepositorioTareas._a_dict(tarea)
                fila["decision"] = fila["decision"] or PENDIENTE
                filas.append(fila)
            return filas

    # --- Decisión comercial (RF-039) ---

    def registrar(self, tarea_id: str, decision: str, justificacion: str, usuario: str) -> dict:
        if decision not in DECISIONES:
            raise DecisionNoPermitidaError(
                f"Decisión no reconocida. Opciones: {', '.join(DECISIONES)}."
            )
        justificacion = (justificacion or "").strip()
        if not justificacion:
            raise DecisionNoPermitidaError("La justificación es obligatoria.")

        with self._sesiones() as db:
            tarea = db.get(TareaAnalisis, tarea_id)
            if tarea is None:
                raise TareaNoEncontradaError("Tarea no encontrada")
            if tarea.estado != EstadoTarea.FINALIZADA:
                raise TareaNoDecidibleError(
                    f"Solo se decide sobre análisis finalizados; esta tarea está en «{tarea.estado}»."
                )

            ahora = datetime.utcnow()
            coincide = coincide_con_sugerencia(decision, tarea.resultado_recomendacion)
            # Evento crítico: primero la bitácora. Si falla, se propaga y no se guarda nada.
            self.auditoria.registrar_evento(
                tarea_id,
                "DECISION_COMERCIAL",
                {
                    "decision": decision,
                    "justificacion": justificacion,
                    "recomendacion_sistema": tarea.resultado_recomendacion,
                    "puntaje": tarea.resultado_puntaje,
                    "coincide_con_sugerencia": coincide,
                    "decision_anterior": tarea.decision_comercial,
                },
                registrado_por=usuario,
                licitacion_id=tarea.licitacion_id,
            )
            registro = DecisionComercial(
                tarea_id=tarea_id,
                decision=decision,
                justificacion=justificacion,
                recomendacion_sistema=tarea.resultado_recomendacion,
                puntaje=tarea.resultado_puntaje,
                coincide_con_sugerencia=coincide,
                registrado_por=usuario,
                registrado_en=ahora,
            )
            db.add(registro)
            tarea.decision_comercial = decision
            tarea.decision_por = usuario
            tarea.decision_en = ahora
            db.commit()
            logger.info(f"Decisión comercial «{decision}» registrada para la tarea {tarea_id} por {usuario}.")
            return self._a_dict(registro)

    def historial(self, tarea_id: str) -> List[dict]:
        """Decisiones registradas sobre la tarea, de la más reciente a la más antigua."""
        with self._sesiones() as db:
            if db.get(TareaAnalisis, tarea_id) is None:
                raise TareaNoEncontradaError("Tarea no encontrada")
            consulta = (
                select(DecisionComercial)
                .where(DecisionComercial.tarea_id == tarea_id)
                .order_by(DecisionComercial.registrado_en.desc(), DecisionComercial.id.desc())
            )
            return [self._a_dict(d) for d in db.execute(consulta).scalars().all()]

    @staticmethod
    def _a_dict(d: DecisionComercial) -> dict:
        return {
            "id": d.id,
            "tarea_id": d.tarea_id,
            "decision": d.decision,
            "justificacion": d.justificacion,
            "recomendacion_sistema": d.recomendacion_sistema,
            "puntaje": d.puntaje,
            "coincide_con_sugerencia": d.coincide_con_sugerencia,
            "registrado_por": d.registrado_por,
            "registrado_en": d.registrado_en.isoformat() if d.registrado_en else None,
        }


_servicio: Optional[ServicioDecisiones] = None


def obtener_servicio_decisiones() -> ServicioDecisiones:
    global _servicio
    if _servicio is None:
        _servicio = ServicioDecisiones()
    return _servicio
