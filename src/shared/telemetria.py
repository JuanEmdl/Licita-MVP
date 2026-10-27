"""
Telemetría con OpenTelemetry (RF-043, Tabla 49).

Cada unidad (api, worker-analisis, worker-vigilancia, webui) llama a configurar()
al arrancar. Con APPLICATIONINSIGHTS_CONNECTION_STRING las trazas y métricas se
exportan a Azure Monitor; sin ella, los instrumentos existen pero no exportan nada,
así que el código no depende de que la telemetría esté disponible.

Todo se correlaciona por el identificador de tarea, que viaja de la API al
trabajador dentro del mensaje junto con el contexto de traza W3C. Por ASR-05 la
telemetría nunca lleva contenido de pliegos ni del portafolio: solo
identificadores, tiempos, contadores y códigos de resultado.
"""
import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Dict, Iterable, Iterator, Optional

from opentelemetry import metrics, propagate, trace

logger = logging.getLogger(__name__)

# Tarea en curso en este hilo o tarea asíncrona: la usan la pasarela y las métricas.
tarea_actual: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("tarea_actual", default=None)

_configurada = False
_candado = threading.Lock()

tracer = trace.get_tracer("licita")
_meter = metrics.get_meter("licita")

# Instrumentos de la Tabla 49. Se crean sobre el proveedor global: si configurar()
# se llama después, el API de OpenTelemetry los enlaza al proveedor real.
duracion_tarea = _meter.create_histogram(
    "licita.analisis.duracion", unit="s", description="Duración de cada ejecución de una tarea de análisis.")
duracion_etapa = _meter.create_histogram(
    "licita.analisis.etapa.duracion", unit="s", description="Duración de cada etapa del grafo por tarea.")
tokens_consumidos = _meter.create_counter(
    "licita.llm.tokens", unit="{token}", description="Tokens de entrada y salida enviados al proveedor.")
llamadas_llm = _meter.create_counter(
    "licita.llm.llamadas", description="Invocaciones al proveedor por operación y resultado.")
errores_proveedor = _meter.create_counter(
    "licita.llm.errores", description="Respuestas 429, 5xx y tiempos de espera del proveedor.")
aperturas_disyuntor = _meter.create_counter(
    "licita.llm.disyuntor.aperturas", description="Veces que el disyuntor se abrió.")
tareas_suspendidas = _meter.create_counter(
    "licita.analisis.suspendidas", description="Tareas suspendidas por inyección o por cuota.")
rechazos_autorizacion = _meter.create_counter(
    "licita.api.rechazos", description="Respuestas 403 por rol y por permiso.")
solicitudes_api = _meter.create_histogram(
    "licita.api.solicitudes.duracion", unit="s", description="Duración de las solicitudes HTTP por ruta y código.")


def configurar(servicio: str) -> bool:
    """Inicializa los proveedores de trazas y métricas. Devuelve True si exporta a Azure Monitor."""
    global _configurada
    from src.shared.config import obtener_configuracion

    with _candado:
        if _configurada:
            return False
        _configurada = True
        conexion = obtener_configuracion().applicationinsights_connection_string
        if not conexion:
            logger.info(f"Telemetría [{servicio}]: sin APPLICATIONINSIGHTS_CONNECTION_STRING, no se exporta.")
            return False
        try:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorMetricExporter,
                AzureMonitorTraceExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            recurso = Resource.create({"service.name": f"licita-{servicio}", "service.namespace": "licita"})
            proveedor_trazas = TracerProvider(resource=recurso)
            proveedor_trazas.add_span_processor(
                BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=conexion)))
            trace.set_tracer_provider(proveedor_trazas)
            lector = PeriodicExportingMetricReader(
                AzureMonitorMetricExporter(connection_string=conexion), export_interval_millis=60_000)
            metrics.set_meter_provider(MeterProvider(resource=recurso, metric_readers=[lector]))
        except Exception as e:
            # La telemetría nunca debe impedir que el sistema arranque.
            logger.warning(f"Telemetría [{servicio}] no disponible: {type(e).__name__}: {e}")
            return False
        logger.info(f"Telemetría [{servicio}]: exportando a Azure Monitor.")
        return True


def observar_longitud_cola(lector: Callable[[], Optional[Dict[str, int]]]) -> None:
    """
    Tabla 49, longitud de la cola (ASR-02, ASR-07): mensajes en espera y en la cola de
    fallidos. `lector` devuelve {"en_espera": n, "fallidos": m}, o None si no pudo leerla;
    el exportador la consulta en cada periodo. La alerta (más de 20 en espera o cualquier
    fallido) se define en Azure Monitor (infra/terraform/monitoreo.tf).
    """
    def observar(_opciones) -> Iterable[metrics.Observation]:
        try:
            valores = lector()
        except Exception as e:
            logger.warning(f"No se pudo leer la longitud de la cola: {type(e).__name__}")
            return []
        return [metrics.Observation(n, {"estado": estado}) for estado, n in (valores or {}).items()]

    _meter.create_observable_gauge("licita.cola.mensajes", callbacks=[observar], unit="{mensaje}",
                                   description="Mensajes en espera y en la cola de mensajes fallidos.")


def atributos(**valores) -> Dict[str, object]:
    """Atributos sin valores vacíos; añade la tarea en curso si hay una."""
    tarea = tarea_actual.get()
    if tarea and "tarea_id" not in valores:
        valores["tarea_id"] = tarea
    return {k: v for k, v in valores.items() if v is not None}


@contextmanager
def con_tarea(tarea_id: Optional[str]) -> Iterator[None]:
    """Marca la tarea en curso para la pasarela, los registros de consumo y las métricas."""
    ficha = tarea_actual.set(tarea_id)
    try:
        yield
    finally:
        tarea_actual.reset(ficha)


@contextmanager
def medir(nombre_span: str, histograma=None, **atributos_span) -> Iterator[trace.Span]:
    """Span con duración y estado; si se da un histograma, registra también la duración."""
    inicio = time.monotonic()
    attrs = atributos(**atributos_span)
    with tracer.start_as_current_span(nombre_span, attributes=attrs) as span:
        resultado = "ok"
        try:
            yield span
        except Exception as e:
            resultado = type(e).__name__
            span.set_attribute("resultado", resultado)
            raise
        finally:
            if histograma is not None:
                histograma.record(time.monotonic() - inicio, {**attrs, "resultado": resultado})


def inyectar_contexto() -> Dict[str, str]:
    """Contexto de traza W3C para viajar dentro de un mensaje de la cola."""
    portador: Dict[str, str] = {}
    propagate.inject(portador)
    return portador


def extraer_contexto(portador: Optional[Dict[str, str]]):
    return propagate.extract(portador or {})
