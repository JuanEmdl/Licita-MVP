"""
Disyuntor hacia el proveedor del modelo (ASR-07, DA-07).

El reintento insiste; el disyuntor decide cuándo dejar de insistir. Tras
DISYUNTOR_FALLAS fallas transitorias seguidas (429, 5xx, red, tiempo de espera) se
abre y durante DISYUNTOR_ESPERA_S las llamadas fallan de inmediato sin tocar al
proveedor. Pasado ese tiempo deja pasar una llamada de prueba (semiabierto): si
responde, se cierra; si falla, vuelve a abrirse.

Hay un disyuntor por proceso, compartido por todas las tareas que ese proceso ejecuta.
"""
import logging
import threading
import time
from typing import Callable, Optional

from src.shared import telemetria

logger = logging.getLogger(__name__)

CERRADO = "cerrado"
ABIERTO = "abierto"
SEMIABIERTO = "semiabierto"


class ProveedorNoDisponibleError(RuntimeError):
    """El disyuntor está abierto: no se invoca al proveedor."""


class Disyuntor:

    def __init__(self, umbral_fallas: int = 5, espera_s: float = 60.0, reloj: Callable[[], float] = time.monotonic):
        self.umbral_fallas = max(1, umbral_fallas)
        self.espera_s = espera_s
        self._reloj = reloj
        self._candado = threading.Lock()
        self._estado = CERRADO
        self._fallas = 0
        self._abierto_desde: Optional[float] = None
        self._prueba_en_curso = False

    @property
    def estado(self) -> str:
        with self._candado:
            return self._estado

    def segundos_para_reintentar(self) -> float:
        """Lo que falta para que el disyuntor abierto deje pasar la llamada de prueba (0 si no está abierto)."""
        with self._candado:
            if self._estado != ABIERTO:
                return 0.0
            return max(0.0, self.espera_s - (self._reloj() - self._abierto_desde))

    def permitir(self) -> None:
        """Lanza ProveedorNoDisponibleError si la llamada no debe salir."""
        with self._candado:
            if self._estado == ABIERTO:
                restante = self.espera_s - (self._reloj() - self._abierto_desde)
                if restante > 0:
                    raise ProveedorNoDisponibleError(
                        f"El proveedor del modelo falló {self.umbral_fallas} veces seguidas; el disyuntor "
                        f"está abierto y se volverá a intentar en {restante:.0f} s.")
                self._estado = SEMIABIERTO
            if self._estado == SEMIABIERTO:
                if self._prueba_en_curso:
                    raise ProveedorNoDisponibleError("El disyuntor está probando al proveedor; reintente en breve.")
                self._prueba_en_curso = True

    def registrar_exito(self) -> None:
        with self._candado:
            if self._estado != CERRADO:
                logger.info("Disyuntor cerrado: el proveedor del modelo volvió a responder.")
            self._estado, self._fallas, self._prueba_en_curso = CERRADO, 0, False

    def registrar_falla(self) -> None:
        with self._candado:
            self._fallas += 1
            self._prueba_en_curso = False
            if self._estado == SEMIABIERTO or self._fallas >= self.umbral_fallas:
                if self._estado != ABIERTO:
                    telemetria.aperturas_disyuntor.add(1)
                    logger.warning(f"Disyuntor abierto tras {self._fallas} fallas del proveedor del modelo.")
                self._estado, self._abierto_desde = ABIERTO, self._reloj()

    def liberar_prueba(self) -> None:
        """La llamada de prueba terminó con un error que no es del proveedor (p. ej. cuota)."""
        with self._candado:
            self._prueba_en_curso = False


_compartido: Optional[Disyuntor] = None
_candado_global = threading.Lock()


def disyuntor_compartido() -> Disyuntor:
    global _compartido
    with _candado_global:
        if _compartido is None:
            from src.shared.config import obtener_configuracion
            config = obtener_configuracion()
            _compartido = Disyuntor(config.disyuntor_fallas, config.disyuntor_espera_s)
        return _compartido
