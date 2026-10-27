import logging
import re
from typing import List, Optional

from src.shared.schemas.domain import DictamenRequisito, EstadoDictamen, RequisitoExtraido
from src.worker_analysis.agents.prompts import SISTEMA_EVALUADOR, mensaje_evaluador
from src.worker_analysis.agents.recuperador import RecuperadorPortafolio
from src.worker_analysis.llm_gateway.gateway import LLMGateway

logger = logging.getLogger(__name__)

_ESTADOS_CON_EVIDENCIA = {EstadoDictamen.CUMPLE, EstadoDictamen.CUMPLE_PARCIALMENTE, EstadoDictamen.NO_CUMPLE}


class AgenteEvaluador:
    """
    Agente Evaluador (RF-006).
    Emite el dictamen de un requisito aprobado usando como única fuente la evidencia
    recuperada del portafolio (RAG).

    Salvaguardas deterministas (RNF-030, cero "Cumple" sin evidencia):
      1. Sin evidencias recuperadas no se llama al modelo: el dictamen es "No verificable".
      2. Un dictamen favorable o "No cumple" que no cite un registro recuperado ([P-n])
         se degrada a "No verificable".
    """

    def __init__(self, gateway: LLMGateway, recuperador: Optional[RecuperadorPortafolio] = None):
        self.gateway = gateway
        self.recuperador = recuperador or RecuperadorPortafolio(
            fabrica_embeddings=gateway.obtener_modelo_embeddings
        )

    @staticmethod
    def formatear_evidencias(evidencias: List[dict]) -> str:
        return "\n".join(
            f"[P-{e['id']}] ({e.get('categoria') or 'sin categoría'} · {e.get('tecnologia') or 'general'}) "
            f"{e.get('descripcion') or ''}"
            for e in evidencias
        )

    def evaluar_requisito(self, requisito: RequisitoExtraido, portafolio_version: Optional[int] = None) -> DictamenRequisito:
        """portafolio_version: la que fijó la tarea; sin ella se usa la versión vigente."""
        if portafolio_version is None:
            evidencias = self.recuperador.buscar_evidencia(requisito.texto)
        else:
            evidencias = self.recuperador.buscar_evidencia(requisito.texto, portafolio_version=portafolio_version)

        if not evidencias:
            return DictamenRequisito(
                identificador_requisito=requisito.identificador,
                estado=EstadoDictamen.NO_VERIFICABLE,
                evidencia=None,
                justificacion="El portafolio no contiene registros relacionados con este requisito.",
            )

        dictamen = self.gateway.invocar_estructurado(
            mensaje_evaluador(
                requisito.identificador,
                requisito.categoria.value,
                requisito.condicion_habilitante_propuesta,
                requisito.texto,
                self.formatear_evidencias(evidencias),
            ),
            schema=DictamenRequisito,
            sistema=SISTEMA_EVALUADOR,
        )
        # El identificador lo fija el sistema, no el modelo.
        dictamen.identificador_requisito = requisito.identificador
        return self._verificar_evidencia(dictamen, evidencias)

    @staticmethod
    def _verificar_evidencia(dictamen: DictamenRequisito, evidencias: List[dict]) -> DictamenRequisito:
        if dictamen.estado not in _ESTADOS_CON_EVIDENCIA:
            return dictamen
        recuperados = {str(e["id"]) for e in evidencias}
        citados = set(re.findall(r"\[P-(\d+)\]", dictamen.evidencia or ""))
        if citados & recuperados:
            return dictamen
        logger.warning(
            f"Dictamen {dictamen.identificador_requisito} degradado a No verificable: "
            "no cita un registro del portafolio recuperado."
        )
        return DictamenRequisito(
            identificador_requisito=dictamen.identificador_requisito,
            estado=EstadoDictamen.NO_VERIFICABLE,
            evidencia=None,
            justificacion=(
                f"Dictamen original '{dictamen.estado.value}' descartado porque no citó un registro "
                f"verificable del portafolio. Razón del modelo: {dictamen.justificacion}"
            ),
        )
