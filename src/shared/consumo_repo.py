"""
Consumo de inferencia y cuota del periodo (RF-028, RN-10, ASR-13).

La pasarela registra los tokens de cada invocación y consulta la cuota antes de la
siguiente: alcanzado el límite del periodo (mes calendario, UTC) no sale ninguna
llamada más al proveedor. Las solicitudes nuevas se rechazan y las tareas que
necesitan más inferencia quedan suspendidas hasta que el responsable autorizado
amplía la cuota o empieza el periodo siguiente.

Límite: dos llamadas simultáneas pueden pasar la verificación con la cuota casi
agotada; el exceso queda acotado a las invocaciones en curso en ese momento.
"""
import logging
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.shared.models import ConsumoTokens, CuotaTokens

logger = logging.getLogger(__name__)


class CuotaInvalidaError(Exception):
    """Error con mensaje apto para mostrar al usuario."""


def periodo_actual(ahora: Optional[datetime] = None) -> str:
    return (ahora or datetime.utcnow()).strftime("%Y-%m")


class RepositorioConsumo:

    def __init__(self, fabrica_sesiones: Optional[Callable[[], Session]] = None,
                 limite_por_defecto: Optional[int] = None, alerta_porcentaje: Optional[float] = None,
                 auditoria=None):
        from src.shared.config import obtener_configuracion
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        config = obtener_configuracion()
        self._sesiones = fabrica_sesiones
        self.limite_por_defecto = config.cuota_tokens_periodo if limite_por_defecto is None else limite_por_defecto
        self.alerta_porcentaje = config.cuota_alerta_porcentaje if alerta_porcentaje is None else alerta_porcentaje
        self._auditoria = auditoria
        self._alertado: set = set()

    @property
    def auditoria(self):
        if self._auditoria is None:
            from src.worker_analysis.reports.auditoria import RegistradorAuditoria
            self._auditoria = RegistradorAuditoria()
        return self._auditoria

    # --- Consulta ---

    def limite(self, periodo: Optional[str] = None) -> int:
        periodo = periodo or periodo_actual()
        with self._sesiones() as db:
            cuota = db.get(CuotaTokens, periodo)
            return cuota.limite if cuota else self.limite_por_defecto

    def consumido(self, periodo: Optional[str] = None) -> int:
        periodo = periodo or periodo_actual()
        with self._sesiones() as db:
            total = db.execute(
                select(func.coalesce(func.sum(ConsumoTokens.tokens_entrada + ConsumoTokens.tokens_salida), 0))
                .where(ConsumoTokens.periodo == periodo)
            ).scalar_one()
            return int(total)

    def agotada(self) -> bool:
        """True si ya no se permite ninguna invocación más en el periodo. Límite 0 = sin control."""
        limite = self.limite()
        return limite > 0 and self.consumido() >= limite

    def estado(self) -> dict:
        periodo = periodo_actual()
        limite, consumido = self.limite(periodo), self.consumido(periodo)
        with self._sesiones() as db:
            por_operacion = {
                operacion: int(total) for operacion, total in db.execute(
                    select(ConsumoTokens.operacion,
                           func.sum(ConsumoTokens.tokens_entrada + ConsumoTokens.tokens_salida))
                    .where(ConsumoTokens.periodo == periodo).group_by(ConsumoTokens.operacion)
                ).all()
            }
            cuota = db.get(CuotaTokens, periodo)
            ampliacion = None if cuota is None else {
                "por": cuota.ampliado_por, "en": cuota.ampliado_en.isoformat(), "motivo": cuota.motivo}
        porcentaje = round(consumido / limite * 100, 1) if limite else 0.0
        return {
            "periodo": periodo,
            "limite": limite,
            "consumido": consumido,
            "disponible": max(limite - consumido, 0) if limite else None,
            "porcentaje": porcentaje,
            "alerta": bool(limite) and porcentaje >= self.alerta_porcentaje,
            "agotada": bool(limite) and consumido >= limite,
            "umbral_alerta": self.alerta_porcentaje,
            "por_operacion": por_operacion,
            "ampliacion": ampliacion,
        }

    # --- Registro ---

    def registrar(self, operacion: str, tokens_entrada: int, tokens_salida: int, modelo: Optional[str] = None,
                  tarea_id: Optional[str] = None, estimado: bool = False) -> None:
        periodo = periodo_actual()
        with self._sesiones() as db:
            db.add(ConsumoTokens(periodo=periodo, tarea_id=tarea_id, operacion=operacion, modelo=modelo,
                                 tokens_entrada=int(tokens_entrada or 0), tokens_salida=int(tokens_salida or 0),
                                 estimado=estimado))
            db.commit()
        self._avisar_si_alcanza_alerta(periodo)

    def _avisar_si_alcanza_alerta(self, periodo: str) -> None:
        if periodo in self._alertado:
            return
        limite = self.limite(periodo)
        if limite and self.consumido(periodo) >= limite * self.alerta_porcentaje / 100:
            self._alertado.add(periodo)
            logger.warning(f"Consumo de tokens del periodo {periodo} en el {self.alerta_porcentaje:g} % "
                           f"de la cuota ({limite} tokens). Avise a la gerencia financiera.")

    # --- Ampliación (RN-10: la amplía el responsable autorizado) ---

    def ampliar(self, nuevo_limite: int, usuario: str, motivo: str) -> dict:
        periodo = periodo_actual()
        motivo = (motivo or "").strip()
        if not motivo:
            raise CuotaInvalidaError("Indique el motivo de la ampliación.")
        actual = self.limite(periodo)
        if actual and nuevo_limite <= actual:
            raise CuotaInvalidaError(f"La cuota solo se amplía: el límite actual es {actual} tokens.")
        with self._sesiones() as db:
            cuota = db.get(CuotaTokens, periodo)
            if cuota is None:
                cuota = CuotaTokens(periodo=periodo, limite=nuevo_limite, motivo=motivo, ampliado_por=usuario)
                db.add(cuota)
            else:
                cuota.limite, cuota.motivo = nuevo_limite, motivo
                cuota.ampliado_por, cuota.ampliado_en = usuario, datetime.utcnow()
            self.auditoria.registrar_evento(
                f"cuota-{periodo}", "CUOTA_AMPLIADA",
                {"periodo": periodo, "limite_anterior": actual, "limite_nuevo": nuevo_limite, "motivo": motivo},
                registrado_por=usuario)
            db.commit()
        self._alertado.discard(periodo)
        return self.estado()
