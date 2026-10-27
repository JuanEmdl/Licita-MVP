from unittest.mock import MagicMock

import pytest

from src.shared.schemas.domain import CategoriaRequisito as C, EstadoDictamen as E
from src.worker_analysis.agents.recomendador import GeneradorRecomendacion
from tests.conftest import dic, req


@pytest.fixture
def recomendador():
    gateway = MagicMock()
    gateway.invocar_texto.return_value = "Justificación."
    return GeneradorRecomendacion(gateway, umbral_ofertar=80, umbral_revision=50)


def test_no_cumple_prevalece_sobre_no_verificable_sin_importar_el_orden(recomendador):
    """Antes devolvía 'Solicitar revisión' si el 'No verificable' llegaba primero."""
    requisitos = [req("H1", C.JURIDICO, habilitante=True), req("H2", C.FINANCIERO, habilitante=True)]
    dictamenes = [dic("H1", E.NO_VERIFICABLE), dic("H2", E.NO_CUMPLE)]

    assert recomendador.generar(100, requisitos, dictamenes).categoria == "No ofertar"
    assert recomendador.generar(100, requisitos, list(reversed(dictamenes))).categoria == "No ofertar"


def test_habilitante_no_verificable_pide_revision(recomendador):
    requisitos = [req("H1", C.JURIDICO, habilitante=True), req("T1", C.TECNICO)]
    dictamenes = [dic("H1", E.NO_VERIFICABLE), dic("T1", E.CUMPLE)]

    assert recomendador.generar(95, requisitos, dictamenes).categoria == "Solicitar revisión"


def test_sin_dictamenes_no_recomienda_ofertar_ni_llama_al_modelo(recomendador):
    resultado = recomendador.generar(100, [], [])

    assert resultado.categoria == "Solicitar revisión"
    recomendador.gateway.invocar_texto.assert_not_called()


@pytest.mark.parametrize("puntaje, esperado", [(80, "Ofertar"), (79.9, "Solicitar revisión"),
                                               (50, "Solicitar revisión"), (49.9, "No ofertar")])
def test_umbrales(recomendador, puntaje, esperado):
    requisitos = [req("T1", C.TECNICO)]
    assert recomendador.generar(puntaje, requisitos, [dic("T1", E.CUMPLE)]).categoria == esperado


def test_umbrales_por_defecto_desde_configuracion():
    recomendador = GeneradorRecomendacion(MagicMock())
    assert (recomendador.umbral_ofertar, recomendador.umbral_revision) == (80.0, 50.0)
