"""
Controles de la pasarela del modelo (DA-07): cuota (RF-028, ASR-13), anonimización
(ASR-05), disyuntor (ASR-07) y su efecto en el estado de la tarea. Sin red ni PostgreSQL.
"""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.shared.config import Configuracion
from src.shared.consumo_repo import CuotaInvalidaError, RepositorioConsumo
from src.shared.models import ConsumoTokens, CuotaTokens
from src.shared.schemas.domain import DictamenRequisito, ListaRequisitos
from src.worker_analysis.llm_gateway.anonimizador import Anonimizador
from src.worker_analysis.llm_gateway.disyuntor import ABIERTO, CERRADO, Disyuntor, ProveedorNoDisponibleError
from src.worker_analysis.llm_gateway.gateway import CuotaAgotadaError, LLMGateway

CONFIG = replace(Configuracion(), azure_openai_endpoint="https://x", azure_openai_api_key="k",
                 azure_openai_deployment="gpt-4o-mini")


class AuditoriaFalsa:
    def __init__(self):
        self.eventos = []

    def registrar_evento(self, tarea_id, tipo_evento, detalles, registrado_por=None, **kwargs):
        self.eventos.append((tipo_evento, detalles))


@pytest.fixture
def consumo():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ConsumoTokens.__table__.create(motor)
    CuotaTokens.__table__.create(motor)
    return RepositorioConsumo(sessionmaker(bind=motor), limite_por_defecto=1000, alerta_porcentaje=80,
                              auditoria=AuditoriaFalsa())


class ModeloFalso:
    """Simula el cliente de LangChain: registra lo que recibiría el proveedor."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.enviados = []

    def with_structured_output(self, schema, include_raw=False):
        return self

    def invoke(self, mensajes):
        self.enviados.append(mensajes)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def crudo(entrada=60, salida=40, **extra):
    return SimpleNamespace(usage_metadata={"input_tokens": entrada, "output_tokens": salida},
                           additional_kwargs={}, **extra)


def pasarela(consumo, respuestas, terminos=(), disyuntor=None):
    gw = LLMGateway(replace(CONFIG, anonimizacion_terminos=list(terminos)), consumo=consumo,
                    disyuntor=disyuntor or Disyuntor(umbral_fallas=3, espera_s=60))
    gw._llm = ModeloFalso(respuestas)
    return gw


def error_429():
    return openai.RateLimitError("limite", response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
                                 body=None)


# --- Cuota (RF-028, ASR-13) ---

def test_se_contabilizan_los_tokens_de_cada_invocacion(consumo):
    gw = pasarela(consumo, [{"raw": crudo(60, 40), "parsed": ListaRequisitos()}])
    gw.invocar_estructurado("datos", ListaRequisitos)
    estado = consumo.estado()
    assert estado["consumido"] == 100 and estado["por_operacion"] == {"estructurado:ListaRequisitos": 100}
    assert estado["porcentaje"] == 10.0 and not estado["alerta"]


def test_con_la_cuota_agotada_no_sale_ninguna_llamada(consumo):
    consumo.registrar("texto", 900, 100)
    gw = pasarela(consumo, [{"raw": crudo(), "parsed": ListaRequisitos()}])
    with pytest.raises(CuotaAgotadaError, match="agotada"):
        gw.invocar_estructurado("datos", ListaRequisitos)
    assert gw._llm.enviados == []  # ASR-13: 0 invocaciones tras agotar la cuota


def test_alerta_al_80_por_ciento_y_ampliacion(consumo):
    consumo.registrar("texto", 800, 0)
    assert consumo.estado()["alerta"] and not consumo.estado()["agotada"]
    consumo.registrar("texto", 200, 0)
    assert consumo.agotada()
    with pytest.raises(CuotaInvalidaError, match="solo se amplía"):
        consumo.ampliar(500, "admin@x.co", "Más análisis")
    with pytest.raises(CuotaInvalidaError, match="motivo"):
        consumo.ampliar(2000, "admin@x.co", " ")
    estado = consumo.ampliar(2000, "admin@x.co", "Cierre de trimestre")
    assert estado["limite"] == 2000 and not estado["agotada"] and estado["ampliacion"]["por"] == "admin@x.co"
    assert consumo.auditoria.eventos[0][0] == "CUOTA_AMPLIADA"


def test_limite_cero_desactiva_el_control(consumo):
    consumo.limite_por_defecto = 0
    consumo.registrar("texto", 10**9, 0)
    assert not consumo.agotada()


# --- Anonimización (ASR-05) ---

def test_anonimizador_reemplaza_y_restaura():
    a = Anonimizador(["Grupo Andino S.A.S.", "Laura Gómez"])
    texto = ("Contrato de Grupo Andino S.A.S. con NIT 900.123.456-7; contacto laura@andino.co, "
             "celular 310 555 1234, gerente Laura Gómez. Valor 1.200 SMMLV en 2024. https://andino.co/casos")
    anonimo, mapa = a.anonimizar(texto)
    for dato in ("Andino", "900.123.456-7", "laura@andino.co", "310 555 1234", "Laura Gómez", "https://"):
        assert dato not in anonimo
    assert "1.200 SMMLV" in anonimo and "2024" in anonimo  # las cifras de la evidencia se conservan
    assert a.restaurar(anonimo, mapa) == texto


def test_ningun_dato_protegido_llega_al_proveedor_y_la_respuesta_se_restaura(consumo):
    dictamen = DictamenRequisito(identificador_requisito="REQ-1", estado="Cumple",
                                 evidencia="[P-4] Contrato con [TERMINO_1]", justificacion="[CORREO_1] acredita.")
    gw = pasarela(consumo, [{"raw": crudo(), "parsed": dictamen}], terminos=["Grupo Andino"])
    resultado = gw.invocar_estructurado(
        "<evidencias>[P-4] Contrato con Grupo Andino; soporte a@andino.co</evidencias>", DictamenRequisito,
        sistema="instrucciones")
    enviado = str(gw._llm.enviados[0])
    assert "Grupo Andino" not in enviado and "a@andino.co" not in enviado and "[P-4]" in enviado
    assert resultado.evidencia == "[P-4] Contrato con Grupo Andino"
    assert resultado.justificacion == "a@andino.co acredita."


# --- Disyuntor (ASR-07) ---

def test_disyuntor_abre_tras_fallas_y_se_recupera():
    reloj = {"t": 0.0}
    d = Disyuntor(umbral_fallas=2, espera_s=30, reloj=lambda: reloj["t"])
    d.permitir(); d.registrar_falla()
    d.permitir(); d.registrar_falla()
    assert d.estado == ABIERTO
    with pytest.raises(ProveedorNoDisponibleError):
        d.permitir()
    reloj["t"] = 31
    d.permitir()  # semiabierto: deja pasar una prueba
    with pytest.raises(ProveedorNoDisponibleError):
        d.permitir()  # solo una a la vez
    d.registrar_exito()
    assert d.estado == CERRADO


def test_el_reintento_espera_a_que_el_disyuntor_deje_pasar_la_prueba():
    # DEF-02: Service Bus reentrega al instante; el trabajador espera antes de devolver el mensaje.
    from src.worker_analysis.servicio import espera_antes_de_reintentar
    reloj = {"t": 0.0}
    d = Disyuntor(umbral_fallas=1, espera_s=60, reloj=lambda: reloj["t"])
    assert d.segundos_para_reintentar() == 0
    assert espera_antes_de_reintentar(1, d) == 2 and espera_antes_de_reintentar(4, d) == 16
    assert espera_antes_de_reintentar(9, d) == 60  # el mínimo creciente tiene tope
    d.permitir(); d.registrar_falla()
    reloj["t"] = 15
    assert d.segundos_para_reintentar() == 45
    assert espera_antes_de_reintentar(1, d) == 45


def test_la_pasarela_deja_de_insistir_con_el_disyuntor_abierto(consumo, monkeypatch):
    # Sin esperas reales entre reintentos: tenacity fija la función de espera al decorar.
    monkeypatch.setattr(LLMGateway.invocar_texto.retry, "sleep", lambda s: None)
    disyuntor = Disyuntor(umbral_fallas=3, espera_s=60)
    gw = pasarela(consumo, [error_429() for _ in range(5)], disyuntor=disyuntor)
    with pytest.raises(ProveedorNoDisponibleError):
        gw.invocar_texto("hola")
    assert len(gw._llm.enviados) == 3 and disyuntor.estado == ABIERTO  # no hubo un cuarto intento


def test_un_error_de_configuracion_no_abre_el_disyuntor(consumo):
    error = openai.NotFoundError("no existe", response=httpx.Response(404, request=httpx.Request("POST", "https://x")),
                                 body=None)
    disyuntor = Disyuntor(umbral_fallas=1)
    gw = pasarela(consumo, [error], disyuntor=disyuntor)
    with pytest.raises(Exception, match="no existe"):
        gw.invocar_texto("hola")
    assert disyuntor.estado == CERRADO


# --- Efecto en la tarea (servicio de análisis) ---

class RepoTareas:
    def __init__(self, estado="Esperando revisión", causa=None):
        self.tarea = {"estado": estado, "causa_suspension": causa}
        self.cambios = []

    def actualizar(self, tarea_id, estado, **campos):
        self.tarea.update(estado=estado, **campos)
        self.cambios.append((estado, campos))

    def obtener(self, tarea_id):
        return dict(self.tarea)


def _servicio(grafo, repo):
    from src.worker_analysis.servicio import ServicioAnalisis
    orquestador = MagicMock()
    orquestador.graph = grafo
    return ServicioAnalisis(checkpointer=MagicMock(), repositorio=repo, orquestador=orquestador)


def _grafo(error, valores=None, siguiente=("evaluando",)):
    grafo = MagicMock()
    grafo.stream.side_effect = error
    grafo.get_state.return_value = SimpleNamespace(values=valores or {"aprobado_por": "ana"}, next=siguiente)
    return grafo


def test_cuota_agotada_suspende_la_tarea_y_se_puede_continuar():
    from src.worker_analysis.servicio import TransicionInvalidaError

    repo = RepoTareas()
    servicio = _servicio(_grafo(CuotaAgotadaError("Cuota agotada")), repo)
    servicio.reanudar_analisis("t1")
    assert repo.tarea["estado"] == "Suspendida" and repo.tarea["causa_suspension"] == "cuota"
    servicio.grafo.stream.side_effect = None
    servicio.grafo.stream.return_value = iter([])
    servicio.continuar_suspendida("t1")
    servicio.grafo.stream.assert_called_with(None, {"configurable": {"thread_id": "t1"}})
    repo.tarea.update(estado="Suspendida", causa_suspension="inyeccion")
    with pytest.raises(TransicionInvalidaError):
        servicio.continuar_suspendida("t1")  # Tabla 18: la inyección no se reanuda


def test_falla_del_proveedor_bajo_la_cola_devuelve_el_trabajo():
    from src.worker_analysis.servicio import ReintentoPendienteError

    repo = RepoTareas(estado="Evaluando")
    servicio = _servicio(_grafo(ProveedorNoDisponibleError("abierto")), repo)
    with pytest.raises(ReintentoPendienteError):
        servicio.procesar_mensaje({"tipo_tarea": "analisis.reanudar", "tarea_id": "t1"})
    assert repo.tarea["estado"] == "Evaluando" and "se reintentará" in repo.tarea["detalle_error"]
    # Sin cola (desarrollo) la tarea queda Fallida con el motivo.
    servicio.reanudar_analisis("t1")
    assert repo.tarea["estado"] == "Fallida" and "no respondió" in repo.tarea["detalle_error"]


def test_un_mensaje_repetido_continua_desde_el_checkpoint():
    grafo = _grafo(None, valores={"tarea_id": "t1"}, siguiente=("extrayendo",))
    grafo.stream.side_effect = None
    grafo.stream.return_value = iter([])
    servicio = _servicio(grafo, RepoTareas(estado="En proceso"))
    servicio.iniciar_analisis("t1", "CO1.1", "pliego")
    grafo.stream.assert_called_once_with(None, {"configurable": {"thread_id": "t1"}})  # no reinicia


def test_no_se_aprueba_dos_veces_aunque_la_evaluacion_haya_fallado():
    from src.shared.schemas.domain import CategoriaRequisito, RequisitoExtraido
    from src.worker_analysis.servicio import TransicionInvalidaError

    grafo = _grafo(None, valores={"aprobado_por": "ana", "requisitos_extraidos": []})
    servicio = _servicio(grafo, RepoTareas())
    req = RequisitoExtraido(identificador="R1", texto="t", categoria=CategoriaRequisito.TECNICO,
                            condicion_habilitante_propuesta=True, referencia_documental="1")
    with pytest.raises(TransicionInvalidaError, match="ya fue aprobada"):
        servicio.registrar_aprobacion("t1", [req], "ana")
