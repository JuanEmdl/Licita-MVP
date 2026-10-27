"""
RNF-001: fragmentos y requisitos en paralelo con el mismo resultado que en serie;
Tabla 49: métrica de longitud de la cola.
"""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.shared import telemetria
from src.shared.longitud_cola import LectorLongitudCola
from src.shared.schemas.domain import CategoriaRequisito as C, ListaRequisitos, RequisitoExtraido
from src.worker_analysis.orchestrator.graph import OrquestadorAnalisis, en_paralelo


def test_en_paralelo_conserva_el_orden_y_corre_a_la_vez():
    barrera = threading.Barrier(3, timeout=5)

    def lenta(n):
        barrera.wait()  # Solo pasa si las tres llamadas están en curso al mismo tiempo.
        return n * 10

    assert en_paralelo(lenta, [1, 2, 3], paralelismo=3) == [10, 20, 30]


def test_en_paralelo_lleva_la_tarea_de_telemetria_a_cada_hilo():
    with telemetria.con_tarea("tarea-xyz"):
        vistas = en_paralelo(lambda _: telemetria.tarea_actual.get(), range(4), paralelismo=4)
    assert vistas == ["tarea-xyz"] * 4


def test_en_paralelo_propaga_la_primera_falla():
    def falla(n):
        if n == 2:
            raise RuntimeError("cuota")
        return n

    with pytest.raises(RuntimeError, match="cuota"):
        en_paralelo(falla, range(5), paralelismo=3)


def test_con_paralelismo_uno_es_en_serie():
    hilos = en_paralelo(lambda _: threading.get_ident(), range(3), paralelismo=1)
    assert set(hilos) == {threading.get_ident()}


def _orquestador(paralelismo):
    extractor = MagicMock()
    # Cada fragmento devuelve un requisito propio y uno repetido entre fragmentos.
    extractor.extraer_requisitos.side_effect = lambda fragmento: ListaRequisitos(requisitos=[
        RequisitoExtraido(identificador="REQ-1", texto=f"Requisito de {fragmento}", categoria=C.TECNICO,
                          condicion_habilitante_propuesta=False, referencia_documental="1"),
        RequisitoExtraido(identificador="REQ-2", texto="RUP vigente", categoria=C.JURIDICO,
                          condicion_habilitante_propuesta=True, referencia_documental="2"),
    ])
    return OrquestadorAnalisis(extractor=extractor, evaluador=MagicMock(), guardia=MagicMock(),
                               segmentador=MagicMock(), motor_puntaje=MagicMock(), recomendador=MagicMock(),
                               informe=MagicMock(), auditoria=MagicMock(), adaptador_secop=MagicMock(),
                               paralelismo=paralelismo)


def test_extraccion_en_paralelo_da_lo_mismo_que_en_serie():
    estado = {"tarea_id": "t", "fragmentos": [f"F{i}" for i in range(8)]}
    serie = _orquestador(1)._extraer_requisitos(estado)["requisitos_extraidos"]
    paralelo = _orquestador(4)._extraer_requisitos(estado)["requisitos_extraidos"]
    assert paralelo == serie
    assert [r["identificador"] for r in paralelo] == [f"REQ-{i:03d}" for i in range(1, 10)]


# --- Longitud de la cola (Tabla 49) ---

def _propiedades(activos, fallidos):
    return SimpleNamespace(active_message_count=activos, dead_letter_message_count=fallidos)


def test_lector_de_cola_usa_cache_y_tolera_fallas():
    cliente = MagicMock()
    cliente.get_queue_runtime_properties.return_value = _propiedades(25, 1)
    reloj = [0.0]
    lector = LectorLongitudCola("conexion", "trabajos", intervalo_s=30, cliente=cliente, reloj=lambda: reloj[0])

    assert lector() == {"en_espera": 25, "fallidos": 1}
    reloj[0] = 10
    assert lector() == {"en_espera": 25, "fallidos": 1}
    assert cliente.get_queue_runtime_properties.call_count == 1  # dentro del intervalo no consulta

    reloj[0] = 40
    cliente.get_queue_runtime_properties.side_effect = PermissionError("sin Manage")
    assert lector() is None


def test_la_metrica_publica_espera_y_fallidos(monkeypatch):
    lectura = InMemoryMetricReader()
    proveedor = MeterProvider(metric_readers=[lectura])
    monkeypatch.setattr(telemetria, "_meter", proveedor.get_meter("prueba"))

    telemetria.observar_longitud_cola(lambda: {"en_espera": 21, "fallidos": 0})

    puntos = {}
    for recurso in lectura.get_metrics_data().resource_metrics:
        for alcance in recurso.scope_metrics:
            for metrica in alcance.metrics:
                if metrica.name == "licita.cola.mensajes":
                    puntos = {p.attributes["estado"]: p.value for p in metrica.data.data_points}
    assert puntos == {"en_espera": 21, "fallidos": 0}
