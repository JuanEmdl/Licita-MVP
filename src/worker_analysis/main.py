"""
Trabajador de análisis multi-agente (ASR-11).
Consume la cola de Azure Service Bus y ejecuta o reanuda el grafo de LangGraph.
Los checkpoints viven en PostgreSQL, así que una tarea pausada en la compuerta
humana puede reanudarla cualquier réplica del worker.
"""
import json
import logging
import sys
import time

from azure.servicebus import AutoLockRenewer, ServiceBusClient

from opentelemetry import context as contexto_otel

from src.shared import telemetria
from src.shared.config import obtener_configuracion
from src.shared.database import init_db
from src.shared.longitud_cola import LectorLongitudCola
from src.worker_analysis.servicio import ReintentoPendienteError, espera_antes_de_reintentar, obtener_servicio

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("worker_analysis")

# Un análisis completo puede tardar varios minutos: el bloqueo del mensaje se
# renueva mientras dura para que Service Bus no lo entregue a otra réplica.
DURACION_MAXIMA_BLOQUEO_S = 60 * 60


def escuchar_cola() -> None:
    config = obtener_configuracion()
    config.registrar_diagnostico("worker")
    telemetria.configurar("worker-analisis")
    if not config.usa_service_bus:
        logger.warning(
            "SERVICE_BUS_CONNECTION_STRING no está definida: la API ejecuta los análisis en su "
            "propio proceso y este worker no tiene cola que consumir. Saliendo."
        )
        return

    init_db()
    # Tabla 49: mensajes en espera y en la cola de fallidos, exportados con las demás métricas.
    telemetria.observar_longitud_cola(
        LectorLongitudCola(config.service_bus_connection_string, config.service_bus_queue_name))
    servicio = obtener_servicio()
    logger.info(f"Escuchando la cola '{config.service_bus_queue_name}'...")

    with ServiceBusClient.from_connection_string(config.service_bus_connection_string) as cliente, \
            AutoLockRenewer(max_lock_renewal_duration=DURACION_MAXIMA_BLOQUEO_S) as renovador:
        with cliente.get_queue_receiver(queue_name=config.service_bus_queue_name) as receptor:
            for mensaje in receptor:
                renovador.register(receptor, mensaje)
                cuerpo = {}
                ficha = None
                try:
                    cuerpo = json.loads(str(mensaje))
                    # Continúa la traza que empezó la API al aceptar la solicitud.
                    ficha = contexto_otel.attach(telemetria.extraer_contexto(cuerpo.get("traza")))
                    with telemetria.medir("procesar mensaje", tipo=cuerpo.get("tipo_tarea"),
                                          tarea_id=cuerpo.get("tarea_id"), entrega=mensaje.delivery_count):
                        servicio.procesar_mensaje(cuerpo)
                except ReintentoPendienteError:
                    # ASR-07: el proveedor no respondió. Las etapas cerradas están en el checkpoint;
                    # el mensaje vuelve a la cola y, agotadas las entregas, pasa a mensajes fallidos.
                    entregas = (mensaje.delivery_count or 0) + 1
                    if entregas >= config.service_bus_max_entregas:
                        servicio.marcar_fallida_por_reintentos(cuerpo["tarea_id"], entregas)
                        receptor.dead_letter_message(mensaje, reason="proveedor_no_disponible",
                                                     error_description=f"{entregas} entregas sin respuesta")
                    else:
                        # El renovador mantiene el bloqueo mientras se espera (DEF-02).
                        time.sleep(espera_antes_de_reintentar(entregas))
                        receptor.abandon_message(mensaje)
                    continue
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    # Mensaje mal formado: reintentarlo no lo arregla.
                    logger.error(f"Mensaje inválido enviado a dead-letter: {e}")
                    receptor.dead_letter_message(mensaje, reason="mensaje_invalido", error_description=str(e))
                    continue
                except Exception:
                    # Falla de infraestructura (p. ej. base de datos caída) antes de que el
                    # servicio pudiera registrar el estado: se devuelve el mensaje a la cola
                    # para reintentarlo; Service Bus lo envía a dead-letter tras MaxDeliveryCount.
                    logger.exception("Error inesperado procesando el mensaje; se devuelve a la cola.")
                    receptor.abandon_message(mensaje)
                    continue
                finally:
                    if ficha is not None:
                        contexto_otel.detach(ficha)
                # Las fallas del análisis ya quedaron registradas en la tarea por el
                # servicio; se completa el mensaje para no repetir llamadas costosas al modelo.
                receptor.complete_message(mensaje)


if __name__ == "__main__":
    logger.info("Iniciando trabajador de análisis multi-agente...")
    try:
        escuchar_cola()
    except KeyboardInterrupt:
        sys.exit(0)
