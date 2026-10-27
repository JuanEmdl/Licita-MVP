import json
import logging
from typing import Optional

from azure.servicebus import ServiceBusClient, ServiceBusMessage

from src.shared import telemetria
from src.shared.config import obtener_configuracion
from src.worker_analysis.servicio import (
    TIPO_ANALISIS,
    TIPO_CONTINUAR,
    TIPO_INDEXAR_PORTAFOLIO,
    TIPO_REANUDACION,
)

logger = logging.getLogger(__name__)

class PublicadorTrabajos:
    """
    Adaptador del puerto de mensajería (Azure Service Bus).
    Publica trabajos de análisis y reanudación hacia la cola,
    permitiendo la respuesta inmediata (202) al usuario (ASR-11).
    """
    def __init__(self, connection_string: Optional[str] = None, queue_name: Optional[str] = None):
        config = obtener_configuracion()
        self.connection_string = connection_string or config.service_bus_connection_string
        self.queue_name = queue_name or config.service_bus_queue_name

    def _publicar(self, mensaje: dict) -> None:
        # Contexto W3C: el trabajador continúa la misma traza (RF-043).
        mensaje = {**mensaje, "traza": telemetria.inyectar_contexto()}
        with ServiceBusClient.from_connection_string(self.connection_string) as cliente:
            with cliente.get_queue_sender(queue_name=self.queue_name) as emisor:
                emisor.send_messages(ServiceBusMessage(
                    json.dumps(mensaje, ensure_ascii=False),
                    content_type="application/json",
                    # Correlaciona el mensaje con la tarea en la telemetría (RF-043)
                    correlation_id=mensaje.get("tarea_id") or f"portafolio-{mensaje.get('portafolio_version')}",
                ))

    def encolar_analisis(self, tarea_id: str, licitacion_url: str, contenido_pliego: Optional[str] = None,
                         reglas_version: Optional[int] = None, portafolio_version: Optional[int] = None) -> None:
        """Encola un trabajo de análisis (mensaje analisis.solicitado de la Tabla 46)."""
        self._publicar({
            "tipo_tarea": TIPO_ANALISIS,
            "tarea_id": tarea_id,
            "licitacion_url": licitacion_url,
            "contenido_pliego": contenido_pliego,
            "reglas_version": reglas_version,
            "portafolio_version": portafolio_version,
        })
        logger.info(f"Trabajo de análisis encolado. ID: {tarea_id}, Licitación: {licitacion_url}")

    def encolar_reanudacion(self, tarea_id: str) -> None:
        """Encola la reanudación del grafo tras la aprobación humana (ASR-12)."""
        self._publicar({"tipo_tarea": TIPO_REANUDACION, "tarea_id": tarea_id})
        logger.info(f"Reanudación encolada. ID: {tarea_id}")

    def encolar_continuacion(self, tarea_id: str) -> None:
        """Continúa una tarea suspendida por cuota agotada (RN-10)."""
        self._publicar({"tipo_tarea": TIPO_CONTINUAR, "tarea_id": tarea_id})
        logger.info(f"Continuación encolada. ID: {tarea_id}")

    def encolar_indexacion(self, portafolio_version: int) -> None:
        """Pide al trabajador indexar una versión nueva del portafolio (portafolio.indexar, RF-010)."""
        self._publicar({"tipo_tarea": TIPO_INDEXAR_PORTAFOLIO, "portafolio_version": portafolio_version})
        logger.info(f"Indexación encolada. Portafolio v{portafolio_version}")
