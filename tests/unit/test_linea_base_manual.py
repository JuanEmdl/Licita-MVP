"""PB-01: el modelo de la línea base manual es reproducible y aplica el criterio fijado de antemano."""
from scripts.linea_base_manual import ESCENARIOS, UMBRAL_REDUCCION, estimar, minutos_con_sistema, minutos_manual


def test_minutos_manual_suma_lectura_registro_cotejo_y_concepto():
    p = {"palabras_min": 200, "registro_min": 2, "cotejo_min": 4, "concepto_min": 45}
    # 12.000 palabras a 200/min = 60 min; 20 requisitos × 6 min = 120 min; más 45 min.
    assert minutos_manual(12000, 20, p) == 225


def test_minutos_con_sistema_son_revision_de_lista_e_informe():
    assert minutos_con_sistema(20, {"revision_min": 0.75, "revision_informe_min": 15}) == 30


def test_los_escenarios_ordenan_el_tiempo_manual():
    rapido, central, lento = (minutos_manual(30000, 100, ESCENARIOS[n]) for n in ("manual rápido", "central", "manual lento"))
    assert rapido < central < lento


def test_estimar_aplica_el_criterio_en_el_escenario_que_favorece_al_manual():
    casos = [{"caso": "x", "palabras": 30000, "requisitos": 100, "segundos_sistema": 600}]
    r = estimar(casos)
    assert r["umbral_reduccion"] == UMBRAL_REDUCCION
    assert r["cumple"] == (r["escenarios"]["manual rápido"]["reduccion"] >= UMBRAL_REDUCCION)
    # Mismas entradas, mismo resultado.
    assert estimar(casos) == r
