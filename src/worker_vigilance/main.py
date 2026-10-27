"""
Trabajador de vigilancia de SECOP II (lectura automática).

Ejecuta un barrido real contra Datos Abiertos y registra las oportunidades
afines al portafolio en la tabla alertas_oportunidad, que la interfaz muestra en
la pestaña Vigilancia. Con VIGILANCIA_INTERVALO_MIN > 0 repite el barrido de
forma continua; con 0 (por defecto) hace uno y termina, para programarlo como
tarea (cron de Container Apps, Programador de tareas de Windows, etc.).
"""
import logging
import sys
import time

from src.shared import telemetria
from src.shared.config import obtener_configuracion
from src.shared.database import init_db
from src.worker_vigilance.servicio import ServicioVigilancia

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Vigilancia")


def iniciar() -> None:
    config = obtener_configuracion()
    telemetria.configurar("worker-vigilancia")
    init_db()
    servicio = ServicioVigilancia()
    while True:
        resultado = servicio.barrer()
        if resultado["estado"] == "fallido":
            logger.error(f"Barrido fallido: {resultado.get('mensaje')}")
        if config.vigilancia_intervalo_min <= 0:
            return
        logger.info(f"Próximo barrido en {config.vigilancia_intervalo_min} minutos.")
        time.sleep(config.vigilancia_intervalo_min * 60)


if __name__ == "__main__":
    try:
        iniciar()
    except KeyboardInterrupt:
        sys.exit(0)
