"""
Longitud de la cola de trabajos (Tabla 49; ASR-02 y ASR-07).

Lee de Service Bus los mensajes en espera y los que están en la cola de mensajes
fallidos. La consulta de propiedades de la cola es una operación de administración: la
cadena de conexión del trabajador necesita el permiso Manage (o una identidad con el rol
«Azure Service Bus Data Owner»). Sin él la métrica no se publica y el trabajador sigue.
"""
import logging
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class LectorLongitudCola:
    """Callable para telemetria.observar_longitud_cola, con caché para no consultar en cada lectura."""

    def __init__(self, conexion: str, cola: str, intervalo_s: float = 30.0, cliente=None,
                 reloj: Callable[[], float] = time.monotonic):
        self.conexion = conexion
        self.cola = cola
        self.intervalo_s = intervalo_s
        self._cliente_admin = cliente
        self._reloj = reloj
        self._ultimo: Optional[Dict[str, int]] = None
        self._leido_en: Optional[float] = None
        self._aviso_dado = False

    def _cliente(self):
        if self._cliente_admin is None:
            from azure.servicebus.management import ServiceBusAdministrationClient
            self._cliente_admin = ServiceBusAdministrationClient.from_connection_string(self.conexion)
        return self._cliente_admin

    def __call__(self) -> Optional[Dict[str, int]]:
        ahora = self._reloj()
        if self._leido_en is not None and ahora - self._leido_en < self.intervalo_s:
            return self._ultimo
        self._leido_en = ahora
        try:
            propiedades = self._cliente().get_queue_runtime_properties(self.cola)
        except Exception as e:
            if not self._aviso_dado:
                self._aviso_dado = True
                logger.warning(f"No se pudo leer la longitud de la cola '{self.cola}' ({type(e).__name__}). "
                               "La métrica requiere el permiso Manage en Service Bus.")
            return None
        self._ultimo = {"en_espera": int(propiedades.active_message_count or 0),
                        "fallidos": int(propiedades.dead_letter_message_count or 0)}
        return self._ultimo
