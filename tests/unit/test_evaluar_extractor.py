"""Calificación del evaluador de prompts (scripts.evaluar_extractor) y coherencia de sus casos. Sin red."""
import pytest

from scripts.evaluar_extractor import (
    calificar_corrida,
    cargar_casos,
    contenido_caso,
    normalizar,
    referencia_correcta,
    resumir,
)
from src.shared.schemas.domain import CategoriaRequisito
from src.worker_analysis.agents.prompts import SISTEMA_EXTRACTOR
from src.worker_analysis.pipeline.guardia import GuardiaDocumental

CASO = {
    "nombre": "Prueba",
    "esperados": [
        {"id": "Contratos", "claves": ["contratos", "1.000 smmlv", "81111500"], "categoria": "experiencia",
         "habilitante": True, "referencia": "3.3"},
        {"id": "ISO", "claves": ["27001"], "categoria": "tecnico", "habilitante": True, "referencia": "3.4"},
    ],
    "prohibidos": [["precio base"]],
}


def r(texto, categoria="experiencia", habilitante=True, referencia="Numeral 3.3"):
    return {"texto": texto, "categoria": categoria, "condicion_habilitante_propuesta": habilitante,
            "referencia_documental": referencia}


def test_normalizar_quita_tildes_y_espacios():
    assert normalizar("  Índice   de LIQUIDEZ ") == "indice de liquidez"


@pytest.mark.parametrize("referencia, numeral, esperado", [
    ("Numeral 3.1", "3.1", True),
    ("3.1 REQUISITOS HABILITANTES", "3.1", True),
    ("Numeral 3.10", "3.1", False),
    ("Numeral 13.1", "3.1", False),
    ("Fragmento 1 de 1", "3.1", False),
])
def test_referencia_exige_el_numeral_completo(referencia, numeral, esperado):
    assert referencia_correcta(referencia, numeral) is esperado


def test_corrida_correcta():
    corrida = calificar_corrida(CASO, [
        r("Dos contratos por 1.000 SMMLV con código UNSPSC 81111500."),
        r("Certificación ISO/IEC 27001 vigente.", "tecnico", referencia="Numeral 3.4"),
    ])
    assert all(e["encontrado"] and e["categoria_ok"] and e["referencia_ok"] for e in corrida["esperados"])
    assert corrida["extras"] == corrida["duplicados"] == corrida["prohibidos"] == []


def test_un_requisito_dividido_no_cuenta_como_encontrado():
    corrida = calificar_corrida(CASO, [
        r("Acreditar dos contratos."),
        r("Por un valor de 1.000 SMMLV."),
        r("Con el código UNSPSC 81111500."),
    ])
    assert corrida["esperados"][0]["encontrado"] is False
    assert len(corrida["extras"]) == 3


def test_duplicado_por_solape_y_prohibido():
    corrida = calificar_corrida(CASO, [
        r("ISO 27001 vigente.", "tecnico"),
        r("Certificación ISO 27001 vigente.", "tecnico"),  # parafraseado en el otro fragmento
        r("El precio base es de 850 millones."),
    ])
    assert len(corrida["duplicados"]) == 1 and len(corrida["prohibidos"]) == 1


def test_estabilidad_y_errores():
    buena = calificar_corrida(CASO, [r("Contratos por 1.000 SMMLV, UNSPSC 81111500."),
                                     r("ISO 27001.", "tecnico", referencia="3.4")])
    otra = calificar_corrida(CASO, [r("Contratos por 1.000 SMMLV, UNSPSC 81111500.", "tecnico"),
                                    r("ISO 27001.", "tecnico", referencia="3.4")])
    resumen = resumir(CASO, [buena, buena, otra, {"error": "RateLimitError"}])
    assert resumen["estabilidad"] == pytest.approx(2 / 3, abs=0.001)
    assert resumen["errores"] == ["RateLimitError"]
    assert resumen["por_esperado"]["Contratos"]["categorias"] == {"experiencia": 2, "tecnico": 1}


# --- Coherencia de los casos versionados ---

CASOS = cargar_casos()


def test_hay_casos():
    assert len(CASOS) >= 3


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c["archivo"])
def test_cada_esperado_aparece_en_su_pliego(caso):
    """Las claves deben estar en el texto fuente; si no, el caso está mal escrito, no el modelo."""
    texto = normalizar(contenido_caso(caso))
    for e in caso["esperados"]:
        assert all(normalizar(c) in texto for c in e["claves"]), e["id"]
        assert e["categoria"] in {c.value for c in CategoriaRequisito}
        assert referencia_correcta(caso["pliego"], e["referencia"]), e["id"]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c["archivo"])
def test_los_casos_pasan_la_guardia(caso):
    GuardiaDocumental().sanear_contenido(contenido_caso(caso))


def test_el_ejemplo_del_prompt_no_se_usa_como_caso():
    """El ejemplo del prompt no debe coincidir con un caso: inflaría los resultados."""
    for caso in CASOS:
        assert "interventoria de sistemas de informacion" not in normalizar(caso["pliego"])
    assert "interventoría" in SISTEMA_EXTRACTOR
