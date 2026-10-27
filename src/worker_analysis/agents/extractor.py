from src.shared.schemas.domain import ListaRequisitos
from src.worker_analysis.agents.prompts import SISTEMA_EXTRACTOR, mensaje_extractor
from src.worker_analysis.llm_gateway.gateway import LLMGateway


class AgenteExtractor:
    """
    Agente Extractor (RF-018).
    Produce la lista estructurada de requisitos validada contra un esquema.
    Agente LLM sin herramientas con efectos directos (DA-08).
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    def extraer_requisitos(self, fragmento: str) -> ListaRequisitos:
        """
        Extrae los requisitos técnicos, financieros, jurídicos, de experiencia y de
        personal de un fragmento del expediente. Un fragmento sin texto no se envía al modelo.
        """
        if not (fragmento or "").strip():
            return ListaRequisitos(requisitos=[])
        return self.gateway.invocar_estructurado(
            mensaje_extractor(fragmento), schema=ListaRequisitos, sistema=SISTEMA_EXTRACTOR
        )
