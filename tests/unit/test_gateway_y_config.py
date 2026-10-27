"""Pasarela LLM y configuración: validación de salida y diagnóstico sin secretos."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.shared.config import Configuracion
from src.shared.schemas.domain import ListaRequisitos
from src.worker_analysis.llm_gateway.gateway import LLMGateway


class LLMFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.mensajes = None

    def with_structured_output(self, schema, include_raw=False):
        assert include_raw is True
        return self

    def invoke(self, mensajes):
        self.mensajes = mensajes
        return self.respuesta


class ConsumoFalso:
    def __init__(self, agotada=False):
        self._agotada, self.registros = agotada, []

    def agotada(self):
        return self._agotada

    def estado(self):
        return {"periodo": "2026-10", "consumido": 10, "limite": 10}

    def registrar(self, operacion, entrada, salida, **kwargs):
        self.registros.append((operacion, entrada, salida))


def _gateway(respuesta):
    from src.worker_analysis.llm_gateway.disyuntor import Disyuntor
    gw = LLMGateway(replace(Configuracion(), azure_openai_endpoint="https://x", azure_openai_api_key="k"),
                    consumo=ConsumoFalso(), disyuntor=Disyuntor())
    gw._llm = LLMFalso(respuesta)
    return gw


def test_salida_estructurada_valida_y_mensaje_de_sistema():
    raw = SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 5}, additional_kwargs={})
    gw = _gateway({"raw": raw, "parsed": ListaRequisitos(), "parsing_error": None})
    assert gw.invocar_estructurado("datos", ListaRequisitos, sistema="instrucciones") == ListaRequisitos()
    assert gw._llm.mensajes == [("system", "instrucciones"), ("human", "datos")]


def test_salida_invalida_lanza_error_claro():
    raw = SimpleNamespace(usage_metadata={}, additional_kwargs={"refusal": "No puedo"})
    gw = _gateway({"raw": raw, "parsed": None, "parsing_error": None})
    with pytest.raises(ValueError, match="No puedo"):
        gw.invocar_estructurado("datos", ListaRequisitos)


def test_sin_credenciales_falla_con_variables_nombradas():
    gw = LLMGateway(replace(Configuracion(), azure_openai_endpoint="", azure_openai_api_key=""))
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        gw.llm


@pytest.mark.parametrize("entrada", [
    "https://r.services.ai.azure.com/api/projects/p",
    "https://r.services.ai.azure.com/api/projects/p/",
    "https://r.services.ai.azure.com/",
    "https://r.services.ai.azure.com/openai/v1",
])
def test_endpoint_de_proyecto_se_reduce_a_la_raiz(entrada):
    config = replace(Configuracion(), azure_openai_endpoint=entrada, azure_openai_endpoint_original=entrada)
    assert config.azure_openai_endpoint == "https://r.services.ai.azure.com"


def test_diagnostico_avisa_endpoint_de_proyecto():
    proyecto = "https://r.services.ai.azure.com/api/projects/p"
    config = replace(Configuracion(), azure_openai_endpoint=proyecto, azure_openai_endpoint_original=proyecto)
    assert any("proyecto" in a for a in config.diagnostico("api"))
    raiz = "https://r.openai.azure.com/"
    config = replace(Configuracion(), azure_openai_endpoint=raiz, azure_openai_endpoint_original=raiz)
    assert not any("proyecto" in a for a in config.diagnostico("api"))


@pytest.mark.parametrize("deployment, temperatura, esperada", [
    ("gpt-4o-mini", 0.0, 0.0),
    ("gpt-5-mini", 0.0, None),   # razonamiento: solo la predeterminada
    ("o4-mini", 0.0, None),
    ("gpt-4o-mini", None, None),  # LLM_TEMPERATURA vacía
])
def test_temperatura_solo_si_el_modelo_la_admite(deployment, temperatura, esperada):
    gw = LLMGateway(replace(Configuracion(), azure_openai_endpoint="https://x", azure_openai_api_key="k",
                            azure_openai_deployment=deployment, llm_temperatura=temperatura))
    assert gw.llm.temperature == esperada


def test_version_no_soportada_se_traduce():
    import httpx
    import openai

    from src.worker_analysis.llm_gateway.gateway import ModeloNoDisponibleError, traducir_error_proveedor

    respuesta = httpx.Response(400, request=httpx.Request("POST", "https://x"))
    error = openai.BadRequestError("API version not supported", response=respuesta, body=None)
    traducido = traducir_error_proveedor(error, Configuracion(), "gpt-5-mini")
    assert isinstance(traducido, ModeloNoDisponibleError)
    assert "AZURE_OPENAI_ENDPOINT" in str(traducido)


def test_diagnostico_nombra_variables_sin_exponer_valores():
    config = replace(Configuracion(), auth_mode="desarrollo", api_token_desarrollo="",
                     azure_openai_api_key="", service_bus_connection_string="Endpoint=sb://secreto")
    avisos = " ".join(config.diagnostico("api") + config.diagnostico("worker"))
    assert "API_TOKEN_DESARROLLO" in avisos and "AZURE_OPENAI_API_KEY" in avisos
    assert "secreto" not in avisos
