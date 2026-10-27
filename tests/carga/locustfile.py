"""
FF-01 (ASR-01, ASR-02, Tabla 33): prueba de carga con Locust en el ambiente de pruebas.

Cada usuario simulado es un analista que solicita un análisis, espera la compuerta humana,
aprueba la lista extraída y espera el resultado. El tiempo de punta a punta se registra
como la solicitud «analisis completo»; al terminar, la ejecución falla si su percentil 90
supera los 10 minutos (RNF-001) o si alguna tarea no termina.

No corre en cada integración: consume cuota de inferencia y crédito de la suscripción, así
que se ejecuta al cierre de cada sprint (azure-pipelines-carga.yml) o a mano:

    LICITA_TOKEN=<token de un analista> locust -f tests/carga/locustfile.py --headless \\
        -u 10 -r 10 --run-time 30m --host https://<api del ambiente de pruebas>

El tiempo de espera humana en la compuerta no cuenta: se mide desde la solicitud hasta la
revisión y desde la aprobación hasta el resultado, como define ASR-01.
"""
import itertools
import os
import time
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

UMBRAL_P90_S = 600  # ASR-01: 10 minutos en el percentil 90
ESPERA_MAXIMA_S = 30 * 60
SONDEO_S = 5
RAIZ = Path(__file__).resolve().parents[2]
# ASR-01 pide pliegos de 60 páginas en promedio: se rotan cinco pliegos reales del corpus (46, 66, 84,
# 79 y 20 páginas; 59 en promedio). LICITA_PLIEGO=ejemplo usa el pliego corto de data/ejemplos.
PLIEGOS_CARGA = [
    "08_norte_santander/PLIEGO DEFINITIVO.pdf",
    "04_corpocesar/6-Pliego de Condiciones Definitivos.pdf",
    "01_contraloria_cundinamarca/3.CDC-LP-001-2026-(Pliego de Condiciones Definitivo).pdf",
    "05_cali_rcd/PLIEGO DE CONDICIONES DEFINITIVO PLATAFORMA RCD.docx.pdf",
    "02_sdp_fabrica_software/IF_PR_600_fab_software - pliego def.pdf",
]


def _pliegos() -> list:
    if os.getenv("LICITA_PLIEGO") == "ejemplo":
        return [(RAIZ / "data" / "ejemplos" / "pliego_ejemplo.txt").read_text(encoding="utf-8")]
    from src.shared.lectura_documentos import leer_documento
    textos = []
    for relativa in PLIEGOS_CARGA:
        ruta = RAIZ / "data" / "evaluacion" / "pliegos_secop" / relativa
        textos.append("\n".join(leer_documento(ruta.name, ruta.read_bytes()).paginas))
    return textos


PLIEGOS = _pliegos()
NOMBRE = "analisis completo"
_turno = itertools.cycle(PLIEGOS)


class Analista(HttpUser):
    # Cada usuario hace un análisis por iteración; 10 usuarios = 10 solicitudes concurrentes (ASR-02).
    wait_time = between(1, 3)

    def on_start(self):
        self.client.headers["Authorization"] = f"Bearer {os.environ['LICITA_TOKEN']}"

    def _esperar(self, tarea_id: str, estados: set) -> dict:
        limite = time.monotonic() + ESPERA_MAXIMA_S
        while time.monotonic() < limite:
            estado = self.client.get(f"/analisis/{tarea_id}/estado", name="/analisis/{id}/estado").json()
            if estado["estado"] in estados or estado["estado"] in ("Fallida", "Suspendida"):
                return estado
            time.sleep(SONDEO_S)
        return {"estado": "Sin terminar"}

    def _registrar(self, inicio: float, medido_s: float, error: str = None):
        events.request.fire(request_type="FLUJO", name=NOMBRE, response_time=medido_s * 1000,
                            response_length=0, exception=RuntimeError(error) if error else None,
                            context={}, start_time=inicio)

    @task
    def analizar(self):
        inicio = time.time()
        # Cada solicitud es un proceso distinto para que RF-036 no la responda con un análisis previo.
        proceso = f"CO1.CARGA.{uuid.uuid4().hex[:10]}"
        t0 = time.monotonic()
        r = self.client.post("/analisis/", name="/analisis/", json={
            "licitacion_url": proceso, "contenido_pliego": next(_turno), "forzar_nuevo": True})
        if r.status_code != 202:
            return self._registrar(inicio, time.monotonic() - t0, f"solicitud rechazada: {r.status_code}")
        tarea = r.json()["tarea_id"]

        estado = self._esperar(tarea, {"Esperando revisión"})
        hasta_revision = time.monotonic() - t0
        if estado["estado"] != "Esperando revisión":
            return self._registrar(inicio, hasta_revision, f"no llegó a revisión: {estado['estado']}")

        requisitos = self.client.get(f"/analisis/{tarea}/requisitos", name="/analisis/{id}/requisitos").json()
        t1 = time.monotonic()
        r = self.client.put(f"/analisis/{tarea}/requisitos", name="/analisis/{id}/requisitos",
                            json={"requisitos": requisitos["requisitos"], "aprobar": True})
        if r.status_code != 202:
            return self._registrar(inicio, hasta_revision, f"aprobación rechazada: {r.status_code}")

        estado = self._esperar(tarea, {"Finalizada"})
        total = hasta_revision + (time.monotonic() - t1)
        self._registrar(inicio, total, None if estado["estado"] == "Finalizada" else f"terminó {estado['estado']}")


@events.quitting.add_listener
def _verificar_umbral(environment, **_):
    """FF-01: la canalización marca la ejecución como fallida si no se cumple ASR-01."""
    entrada = environment.stats.get(NOMBRE, "FLUJO")
    p90 = entrada.get_response_time_percentile(0.9) / 1000 if entrada.num_requests else None
    if not entrada.num_requests or entrada.num_failures or p90 > UMBRAL_P90_S:
        print(f"FF-01 falló: {entrada.num_requests} análisis, {entrada.num_failures} fallidos, p90={p90} s "
              f"(umbral {UMBRAL_P90_S} s).")
        environment.process_exit_code = 1
    else:
        print(f"FF-01 cumplido: {entrada.num_requests} análisis, p90={p90:.0f} s (umbral {UMBRAL_P90_S} s).")
