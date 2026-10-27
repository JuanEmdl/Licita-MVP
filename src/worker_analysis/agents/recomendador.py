import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from src.shared.config import obtener_configuracion
from src.shared.schemas.domain import RequisitoExtraido, DictamenRequisito, EstadoDictamen
from src.worker_analysis.agents.prompts import SISTEMA_RECOMENDADOR, mensaje_recomendador
from src.worker_analysis.llm_gateway.gateway import LLMGateway

logger = logging.getLogger(__name__)

class RecomendacionFinal(BaseModel):
    categoria: str = Field(..., description="Categoría de recomendación: 'Ofertar', 'No ofertar', o 'Solicitar revisión'")
    justificacion: str = Field(..., description="Justificación detallada redactada para la decisión tomada.")

class GeneradorRecomendacion:
    """
    Generador de Recomendación (RF-035).
    Combina reglas deterministas para definir la categoría (Ofertar, No ofertar, Solicitar revisión)
    con un Agente LLM que redacta la justificación ejecutiva basándose en los dictámenes.
    """

    def __init__(
        self,
        gateway: LLMGateway,
        umbral_ofertar: Optional[float] = None,
        umbral_revision: Optional[float] = None,
    ):
        self.gateway = gateway
        # Valores por defecto. En el flujo real generar() recibe los umbrales de la versión
        # de reglas que fijó la tarea (RF-032, RF-033).
        config = obtener_configuracion()
        self.umbral_ofertar = config.umbral_ofertar if umbral_ofertar is None else umbral_ofertar
        self.umbral_revision = config.umbral_revision if umbral_revision is None else umbral_revision

    def generar(
        self, 
        puntaje_global: float, 
        requisitos: List[RequisitoExtraido], 
        dictamenes: List[DictamenRequisito],
        umbral_ofertar: Optional[float] = None,
        umbral_revision: Optional[float] = None,
    ) -> RecomendacionFinal:
        """
        Asigna la categoría por umbrales y redacta la justificación a partir de los dictámenes.
        Los umbrales recibidos (los de la versión de reglas de la tarea) prevalecen sobre los
        del constructor.
        """
        ofertar = self.umbral_ofertar if umbral_ofertar is None else umbral_ofertar
        revision = self.umbral_revision if umbral_revision is None else umbral_revision
        logger.info(f"Generando recomendación comercial para puntaje global: {puntaje_global}")

        # 1. Determinación de categoría basada en reglas (DA-09)
        categoria = self._determinar_categoria(puntaje_global, requisitos, dictamenes, ofertar, revision)

        # 2. Redacción de justificación mediante LLM
        if not dictamenes:
            # No hay nada que justificar: se evita una llamada al modelo que solo podría inventar.
            justificacion = (
                "No se emitieron dictámenes sobre los requisitos aprobados, por lo que el "
                "puntaje no tiene evidencia que lo respalde. Se requiere revisión humana."
            )
        else:
            justificacion = self._redactar_justificacion(
                categoria, puntaje_global, requisitos, dictamenes, ofertar, revision)

        logger.info(f"Recomendación generada: {categoria}")
        return RecomendacionFinal(categoria=categoria, justificacion=justificacion)

    def _determinar_categoria(
        self, 
        puntaje_global: float, 
        requisitos: List[RequisitoExtraido], 
        dictamenes: List[DictamenRequisito],
        umbral_ofertar: Optional[float] = None,
        umbral_revision: Optional[float] = None,
    ) -> str:
        ofertar = self.umbral_ofertar if umbral_ofertar is None else umbral_ofertar
        revision = self.umbral_revision if umbral_revision is None else umbral_revision

        # Sin dictámenes el puntaje no tiene respaldo: no se puede recomendar ofertar.
        if not dictamenes:
            return "Solicitar revisión"

        mapa_requisitos = {req.identificador: req for req in requisitos}
        estados_habilitantes = []
        for dictamen in dictamenes:
            req = mapa_requisitos.get(dictamen.identificador_requisito)
            if req and req.condicion_habilitante_propuesta:
                estados_habilitantes.append(dictamen.estado)

        # Validación de reglas de negocio específicas (HU-03 CA-02 y CA-03).
        # Todos los "No cumple" se revisan antes que los "No verificable": el
        # resultado no debe depender del orden en que llegan los dictámenes.
        if EstadoDictamen.NO_CUMPLE in estados_habilitantes:
            # HU-03 CA-02: Si un requisito habilitante no cumple, la recomendación no es ofertar
            return "No ofertar"
        if EstadoDictamen.NO_VERIFICABLE in estados_habilitantes:
            # HU-03 CA-03: Si un habilitante es No verificable, se solicita revisión humana
            return "Solicitar revisión"
        if EstadoDictamen.CUMPLE_PARCIALMENTE in estados_habilitantes:
            # RF-030: un habilitante se acredita o no; uno parcial no permite recomendar
            # ofertar sin que una persona confirme que el faltante es subsanable.
            return "Solicitar revisión"

        # Aplicación de umbrales
        if puntaje_global >= ofertar:
            return "Ofertar"
        elif puntaje_global >= revision:
            return "Solicitar revisión"
        else:
            return "No ofertar"

    def _redactar_justificacion(
        self,
        categoria: str,
        puntaje_global: float,
        requisitos: List[RequisitoExtraido],
        dictamenes: List[DictamenRequisito],
        umbral_ofertar: float,
        umbral_revision: float,
    ) -> str:
        mapa_requisitos = {req.identificador: req for req in requisitos}
        lineas = []
        for d in dictamenes:
            req = mapa_requisitos.get(d.identificador_requisito)
            cat_req = req.categoria.value if req else "desconocida"
            hab_req = "habilitante" if req and req.condicion_habilitante_propuesta else "puntuable"
            texto_req = req.texto if req else "(requisito no encontrado)"
            lineas.append(
                f"- {d.identificador_requisito} [{cat_req}] [{hab_req}] Requisito: {texto_req} | "
                f"Estado: {d.estado.value} | Razón: {d.justificacion}"
            )

        respuesta = self.gateway.invocar_texto(
            mensaje_recomendador(categoria, puntaje_global, umbral_ofertar,
                                 umbral_revision,"\n".join(lineas)),
            sistema=SISTEMA_RECOMENDADOR,
        )
        return respuesta.strip()
