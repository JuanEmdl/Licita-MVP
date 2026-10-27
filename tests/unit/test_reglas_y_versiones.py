"""
Bloque de versionado: reglas del puntaje (RF-032, RF-033), portafolio (RF-009, RF-010)
y reutilización de análisis vigentes (RF-036). SQLite en memoria y bitácora falsa.
"""
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.api.modules.analysis import router as modulo_analisis
from src.api.modules.portfolio import router as modulo_portafolio
from src.api.modules.scoring_rules import router as modulo_reglas
from src.shared.config import Configuracion
from src.shared.models import Portafolio, PortafolioVersion, ReglaPuntaje
from src.shared.portfolio_repo import RepositorioVersionesPortafolio
from src.shared.reglas_repo import (
    HISTORICA,
    OperacionReglasNoPermitidaError,
    PESOS_INICIALES,
    ReglasInvalidasError,
    RepositorioReglas,
    VIGENTE,
)
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE
from src.shared.schemas.domain import CategoriaRequisito as C, EstadoDictamen as E
from src.shared.tareas_repo import huella_entrada
from src.worker_analysis.scoring.motor import MotorPuntaje, ReglasPuntaje
from tests.conftest import dic, req


class AuditoriaFalsa:
    def __init__(self):
        self.eventos = []

    def registrar_evento(self, tarea_id, tipo_evento, detalles, registrado_por=None, **kwargs):
        self.eventos.append((tipo_evento, detalles, registrado_por))


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for modelo in (ReglaPuntaje, PortafolioVersion, Portafolio):
        modelo.__table__.create(motor)
    return sessionmaker(bind=motor, expire_on_commit=False)


@pytest.fixture
def auditoria():
    return AuditoriaFalsa()


@pytest.fixture
def reglas(fabrica, auditoria):
    repo = RepositorioReglas(fabrica, auditoria)
    repo.asegurar_version_inicial(80, 50)
    return repo


@pytest.fixture
def portafolio(fabrica, auditoria):
    return RepositorioVersionesPortafolio(fabrica, auditoria)


PESOS = {"tecnico": 50, "experiencia": 20, "financiero": 10, "juridico": 10, "personal": 10}


# --- Reglas del puntaje ---

def test_version_inicial_provisional_y_vigente(reglas):
    vigente = reglas.vigente()
    assert vigente["version"] == 1 and vigente["estado"] == VIGENTE
    assert vigente["pesos"] == {c: float(p) for c, p in PESOS_INICIALES.items()}
    reglas.asegurar_version_inicial(70, 40)  # idempotente: no crea otra
    assert len(reglas.historial()) == 1


@pytest.mark.parametrize("pesos, ofertar, revision, mensaje", [
    ({**PESOS, "tecnico": 60}, 80, 50, "sumar 100"),
    ({k: v for k, v in PESOS.items() if k != "personal"}, 80, 50, "faltan personal"),
    ({**PESOS, "otra": 0}, 80, 50, "no existen otra"),
    ({**PESOS, "tecnico": 70, "experiencia": -10}, 80, 50, "negativos"),
    (PESOS, 50, 80, "umbral"),
])
def test_validacion_de_la_propuesta(reglas, pesos, ofertar, revision, mensaje):
    with pytest.raises(ReglasInvalidasError, match=mensaje):
        reglas.proponer(pesos, ofertar, revision, "admin@x.co")


def test_doble_control_propone_admin_confirma_gerente(reglas, auditoria):
    propuesta = reglas.proponer(PESOS, 75, 45, "admin@x.co", "Pesos aprobados por el comité")
    assert propuesta["estado"] == "Propuesta"
    assert reglas.vigente()["version"] == 1  # todavía no rige
    with pytest.raises(OperacionReglasNoPermitidaError, match="Doble control"):
        reglas.confirmar(propuesta["version"], "admin@x.co")
    publicada = reglas.confirmar(propuesta["version"], "gema@x.co")
    assert publicada["estado"] == VIGENTE and publicada["confirmado_por"] == "gema@x.co"
    assert reglas.obtener(1)["estado"] == HISTORICA  # la anterior queda como histórico
    assert [e[0] for e in auditoria.eventos] == ["REGLAS_PROPUESTAS", "REGLAS_PUBLICADAS"]


def test_una_sola_propuesta_pendiente_y_rechazo(reglas):
    p = reglas.proponer(PESOS, 80, 50, "admin@x.co")
    with pytest.raises(OperacionReglasNoPermitidaError, match="pendiente"):
        reglas.proponer(PESOS, 80, 50, "admin@x.co")
    with pytest.raises(ReglasInvalidasError):
        reglas.rechazar(p["version"], "gema@x.co", "  ")
    assert reglas.rechazar(p["version"], "gema@x.co", "Falta aval del comité")["estado"] == "Rechazada"
    with pytest.raises(OperacionReglasNoPermitidaError):
        reglas.confirmar(p["version"], "gema@x.co")  # una rechazada ya no se publica
    reglas.proponer(PESOS, 80, 50, "admin@x.co")  # ya se puede proponer otra


def test_el_motor_usa_los_pesos_de_la_version():
    requisitos = [req("T1", C.TECNICO), req("P1", C.PERSONAL)]
    dictamenes = [dic("T1", E.CUMPLE), dic("P1", E.NO_CUMPLE)]
    regla = {"version": 7, "pesos": {**PESOS_INICIALES, "tecnico": 10.0, "personal": 35.0}}
    provisional = MotorPuntaje().calcular(requisitos, dictamenes)
    versionado = MotorPuntaje().calcular(requisitos, dictamenes, ReglasPuntaje.desde_version(regla))
    assert provisional.puntaje_total == pytest.approx(40 / 45 * 100, abs=0.01)
    assert versionado.puntaje_total == pytest.approx(10 / 45 * 100, abs=0.01)
    assert versionado.version_reglas == "7"


def test_el_grafo_aplica_la_version_fijada_por_la_tarea():
    from src.worker_analysis.orchestrator.graph import OrquestadorAnalisis

    regla = {"version": 3, "pesos": PESOS_INICIALES, "umbral_ofertar": 95.0, "umbral_revision": 10.0}
    recomendador = MagicMock()
    recomendador.generar.return_value = MagicMock(categoria="Solicitar revisión", justificacion="j")
    orquestador = OrquestadorAnalisis(
        extractor=MagicMock(), evaluador=MagicMock(), guardia=MagicMock(), segmentador=MagicMock(),
        motor_puntaje=MotorPuntaje(), recomendador=recomendador, informe=MagicMock(), auditoria=MagicMock(),
        adaptador_secop=MagicMock(), proveedor_reglas=lambda v: regla if v == 3 else None,
    )
    estado = {"reglas_version": 3, "requisitos_aprobados": [req("T1", C.TECNICO).model_dump(mode="json")],
              "dictamenes": [dic("T1", E.CUMPLE).model_dump(mode="json")]}
    estado.update(orquestador._calcular_puntaje(estado))
    assert estado["desglose_puntaje"]["version_reglas"] == "3"
    assert estado["reglas_aplicadas"]["umbral_ofertar"] == 95.0
    orquestador._generar_recomendacion(estado)
    assert recomendador.generar.call_args.kwargs == {"umbral_ofertar": 95.0, "umbral_revision": 10.0}


# --- Portafolio versionado ---

CAPS = [
    {"tecnologia": "ISO 27001", "categoria": "Certificación", "descripcion": "Certificación vigente hasta 2027."},
    {"tecnologia": "Python", "categoria": "Desarrollo", "descripcion": "Cuatro proyectos con FastAPI."},
]


class ModeloFalso:
    def __init__(self):
        self.textos = []

    def embed_query(self, texto):
        self.textos.append(texto)
        return [0.1] * 1536


def test_publicar_crea_version_vigente_y_conserva_la_anterior(portafolio, auditoria):
    v1 = portafolio.publicar(CAPS, "ana@x.co", "Carga inicial")
    v2 = portafolio.agregar({"tecnologia": "Java", "categoria": "Desarrollo",
                             "descripcion": "Dos proyectos con Spring Boot."}, "ana@x.co")
    assert (v1["version"], v2["version"]) == (1, 2) and portafolio.vigente() == 2
    assert len(portafolio.capacidades()) == 3
    assert len(portafolio.capacidades(1)) == 2  # histórico consultable (RN-03)
    versiones = portafolio.versiones()
    assert [(v["version"], v["vigente"]) for v in versiones] == [(2, True), (1, False)]
    assert auditoria.eventos[-1][0] == "PORTAFOLIO_PUBLICADO"


def test_solo_se_indexa_lo_nuevo_o_modificado(portafolio):
    modelo = ModeloFalso()
    v1 = portafolio.publicar(CAPS, "ana@x.co")
    assert v1["pendientes_de_indexar"] == 2
    assert portafolio.indexar(1, modelo) == 2
    assert portafolio.indexar(1, modelo) == 0  # repetible sin efectos

    iso = next(c for c in portafolio.capacidades() if c["tecnologia"] == "ISO 27001")
    v2 = portafolio.editar(iso["id"], {**CAPS[0], "descripcion": "Certificación vigente hasta 2028."}, "ana@x.co")
    assert v2["pendientes_de_indexar"] == 1  # Python conserva su vector
    modelo.textos.clear()
    assert portafolio.indexar(2, modelo) == 1 and "2028" in modelo.textos[0]


def test_retirar_y_capacidad_inexistente(portafolio):
    from src.shared.portfolio_repo import CapacidadNoEncontradaError

    portafolio.publicar(CAPS, "ana@x.co")
    viejo_id = portafolio.capacidades()[0]["id"]
    v2 = portafolio.retirar(viejo_id, "ana@x.co")
    assert v2["retiradas"] == 1 and len(portafolio.capacidades()) == 1
    with pytest.raises(CapacidadNoEncontradaError):
        portafolio.retirar(viejo_id, "ana@x.co")  # ya no está en la vigente


def test_migracion_del_portafolio_sin_versiones(portafolio, fabrica):
    with fabrica() as db:
        db.add_all([Portafolio(activo=True, **c) for c in CAPS])
        db.commit()
    assert portafolio.asegurar_version_inicial() == 1
    assert portafolio.vigente() == 1 and len(portafolio.capacidades()) == 2
    assert portafolio.asegurar_version_inicial() is None  # idempotente


def test_huella_de_entrada_ignora_espacios():
    assert huella_entrada("CO1.1", "Pliego  con\n espacios") == huella_entrada(" CO1.1 ", "Pliego con espacios")
    assert huella_entrada("CO1.1", "Pliego A") != huella_entrada("CO1.1", "Pliego B")
    assert huella_entrada("CO1.1", None) != huella_entrada("CO1.2", None)


# --- API: roles, 422 y reutilización ---

USUARIOS = {
    "tok-analista": {"email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-gerente": {"email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-admin": {"email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


class TareasFalsas:
    def __init__(self, previa=None):
        self.previa, self.creadas = previa, []

    def buscar_reutilizable(self, huella, reglas_version, portafolio_version):
        return self.previa

    def crear(self, tarea_id, licitacion_id, solicitado_por, **versiones):
        self.creadas.append(versiones)


class PublicadorFalso:
    def __init__(self):
        self.mensajes = []

    def encolar_analisis(self, *args, **kwargs):
        self.mensajes.append(kwargs)

    def encolar_indexacion(self, version):
        self.mensajes.append({"indexar": version})


@pytest.fixture
def entorno_api(reglas, portafolio, monkeypatch):
    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    tareas, publicador = TareasFalsas(), PublicadorFalso()
    app.dependency_overrides[modulo_reglas.obtener_repositorio_reglas] = lambda: reglas
    app.dependency_overrides[modulo_portafolio.obtener_repositorio_portafolio] = lambda: portafolio
    app.dependency_overrides[modulo_analisis.obtener_repositorio] = lambda: tareas
    app.dependency_overrides[modulo_analisis.obtener_publicador] = lambda: publicador
    app.dependency_overrides[modulo_analisis.obtener_versiones_vigentes] = lambda: (1, 4)
    app.dependency_overrides[modulo_analisis.verificar_cuota_disponible] = lambda: None
    app.dependency_overrides[modulo_analisis.obtener_expediente] = lambda: None
    yield TestClient(app), tareas, publicador
    app.dependency_overrides.clear()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_reglas_doble_control_por_rol(entorno_api):
    cliente, *_ = entorno_api
    cuerpo = {"ponderaciones": PESOS, "umbral_ofertar": 75, "umbral_revision": 45}
    assert cliente.put("/reglas-puntaje/", headers=_h("tok-gerente"), json=cuerpo).status_code == 403
    assert cliente.put("/reglas-puntaje/", headers=_h("tok-admin"),
                       json={**cuerpo, "ponderaciones": {**PESOS, "tecnico": 1}}).status_code == 422
    r = cliente.put("/reglas-puntaje/", headers=_h("tok-admin"), json=cuerpo)
    assert r.status_code == 201
    version = r.json()["version"]
    assert cliente.post(f"/reglas-puntaje/{version}/confirmar", headers=_h("tok-admin")).status_code == 403
    assert cliente.post(f"/reglas-puntaje/{version}/confirmar", headers=_h("tok-gerente")).status_code == 200
    estado = cliente.get("/reglas-puntaje/", headers=_h("tok-analista")).json()
    assert estado["vigente"]["version"] == version and estado["propuesta"] is None


def test_api_portafolio_publica_e_indexa(entorno_api):
    cliente, _, publicador = entorno_api
    r = cliente.post("/portafolio/versiones", headers=_h("tok-analista"),
                     json={"capacidades": CAPS, "descripcion_cambio": "Carga"})
    assert r.status_code == 201 and r.json()["version"] == 1
    assert publicador.mensajes == [{"indexar": 1}]  # portafolio.indexar (Tabla 46)
    assert cliente.post("/portafolio/versiones", headers=_h("tok-gerente"),
                        json={"capacidades": CAPS}).status_code == 403
    cap = cliente.get("/portafolio/", headers=_h("tok-admin")).json()[0]
    editada = {**CAPS[0], "descripcion": "Certificación vigente hasta 2029."}
    assert cliente.put(f"/portafolio/{cap['id']}", headers=_h("tok-admin"), json=editada).status_code == 200
    assert cliente.delete(f"/portafolio/{cap['id']}", headers=_h("tok-admin")).status_code == 403  # solo edita
    assert len(cliente.get("/portafolio/versiones", headers=_h("tok-gerente")).json()) == 2


def test_api_reutiliza_un_analisis_vigente(entorno_api):
    cliente, tareas, publicador = entorno_api
    tareas.previa = {"tarea_id": "t-previa", "actualizado_en": "2026-10-20T10:30:00",
                     "recomendacion": "Ofertar", "puntaje": 88.0}
    solicitud = {"licitacion_url": "CO1.REQ.1", "contenido_pliego": "Pliego"}
    r = cliente.post("/analisis/", headers=_h("tok-analista"), json=solicitud)
    assert r.status_code == 409
    assert r.json()["detail"]["tarea_id"] == "t-previa" and "2026-10-20 05:30" in r.json()["detail"]["mensaje"]  # 10:30 UTC en hora de Colombia
    assert tareas.creadas == []
    r = cliente.post("/analisis/", headers=_h("tok-analista"), json={**solicitud, "forzar_nuevo": True})
    assert r.status_code == 202
    # La tarea nueva fija las versiones vigentes y el mensaje las lleva (RN-06, Tabla 46).
    assert tareas.creadas[0]["reglas_version"] == 1 and tareas.creadas[0]["portafolio_version"] == 4
    assert publicador.mensajes[0] == {"reglas_version": 1, "portafolio_version": 4}
