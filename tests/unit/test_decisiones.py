"""
Decisión comercial humana (RF-038, RF-039).

Usa SQLite en memoria con las tablas de tareas y decisiones, y un registrador de
auditoría falso, así que no requiere PostgreSQL.
"""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.api.modules.results.servicio import (
    CONTINUAR,
    DESCARTAR,
    PENDIENTE,
    SOLICITAR_INFORMACION,
    DecisionNoPermitidaError,
    ServicioDecisiones,
    TareaNoDecidibleError,
    TareaNoEncontradaError,
    coincide_con_sugerencia,
    obtener_servicio_decisiones,
)
from src.shared.config import Configuracion
from src.shared.models import DecisionComercial, Licitacion, TareaAnalisis
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE


class AuditoriaFalsa:
    def __init__(self, falla: bool = False):
        self.eventos = []
        self.falla = falla

    def registrar_evento(self, tarea_id, tipo_evento, detalles, registrado_por=None, **kwargs):
        if self.falla:
            raise RuntimeError("La bitácora no acepta el registro")
        self.eventos.append((tarea_id, tipo_evento, detalles, registrado_por))


@pytest.fixture
def fabrica():
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for modelo in (Licitacion, TareaAnalisis, DecisionComercial):
        modelo.__table__.create(motor)
    fabrica = sessionmaker(bind=motor, expire_on_commit=False)
    with fabrica() as db:
        db.add(Licitacion(id="CO1.REQ.1"))
        db.add_all([
            TareaAnalisis(id="fin-ofertar", licitacion_id="CO1.REQ.1", estado="Finalizada",
                          resultado_puntaje=82.0, resultado_recomendacion="Ofertar"),
            TareaAnalisis(id="fin-no", licitacion_id="CO1.REQ.1", estado="Finalizada",
                          resultado_puntaje=31.0, resultado_recomendacion="No ofertar"),
            TareaAnalisis(id="en-revision", licitacion_id="CO1.REQ.1", estado="Esperando revisión"),
        ])
        db.commit()
    return fabrica


@pytest.fixture
def auditoria():
    return AuditoriaFalsa()


@pytest.fixture
def servicio(fabrica, auditoria):
    return ServicioDecisiones(fabrica, auditoria)


# --- Servicio ---

def test_registrar_guarda_decision_autor_y_fecha(servicio, fabrica, auditoria):
    d = servicio.registrar("fin-ofertar", CONTINUAR, "  Cumple todo el pliego.  ", "gema@x.co")
    assert d["decision"] == CONTINUAR
    assert d["justificacion"] == "Cumple todo el pliego."
    assert d["registrado_por"] == "gema@x.co"
    assert d["registrado_en"]
    assert d["coincide_con_sugerencia"] is True
    with fabrica() as db:
        tarea = db.get(TareaAnalisis, "fin-ofertar")
        assert tarea.decision_comercial == CONTINUAR
        assert tarea.decision_por == "gema@x.co"
        assert tarea.decision_en is not None
    tarea_id, tipo, detalles, autor = auditoria.eventos[0]
    assert (tarea_id, tipo, autor) == ("fin-ofertar", "DECISION_COMERCIAL", "gema@x.co")
    assert detalles["recomendacion_sistema"] == "Ofertar"


def test_apartarse_de_la_sugerencia_queda_marcado(servicio):
    d = servicio.registrar("fin-no", CONTINUAR, "Cliente estratégico; se subsana la experiencia.", "gema@x.co")
    assert d["coincide_con_sugerencia"] is False


def test_justificacion_obligatoria(servicio, auditoria):
    with pytest.raises(DecisionNoPermitidaError):
        servicio.registrar("fin-ofertar", CONTINUAR, "   ", "gema@x.co")
    assert auditoria.eventos == []


def test_decision_desconocida(servicio):
    with pytest.raises(DecisionNoPermitidaError):
        servicio.registrar("fin-ofertar", "Ofertar", "Sí", "gema@x.co")


def test_solo_sobre_analisis_finalizados(servicio):
    with pytest.raises(TareaNoDecidibleError):
        servicio.registrar("en-revision", CONTINUAR, "Aún no", "gema@x.co")
    with pytest.raises(TareaNoEncontradaError):
        servicio.registrar("no-existe", CONTINUAR, "x", "gema@x.co")


def test_sin_auditoria_no_se_registra(fabrica):
    servicio = ServicioDecisiones(fabrica, AuditoriaFalsa(falla=True))
    with pytest.raises(RuntimeError):
        servicio.registrar("fin-ofertar", CONTINUAR, "Cumple", "gema@x.co")
    with fabrica() as db:
        assert db.get(TareaAnalisis, "fin-ofertar").decision_comercial is None
        assert db.query(DecisionComercial).count() == 0


def test_historial_conserva_las_decisiones_anteriores(servicio, auditoria):
    servicio.registrar("fin-ofertar", SOLICITAR_INFORMACION, "Falta el certificado ISO.", "gema@x.co")
    servicio.registrar("fin-ofertar", CONTINUAR, "Llegó el certificado.", "gema@x.co")
    historial = servicio.historial("fin-ofertar")
    assert [d["decision"] for d in historial] == [CONTINUAR, SOLICITAR_INFORMACION]
    assert auditoria.eventos[1][2]["decision_anterior"] == SOLICITAR_INFORMACION


def test_tablero_filtra_por_recomendacion_y_decision(servicio):
    servicio.registrar("fin-no", DESCARTAR, "No hay experiencia.", "gema@x.co")
    todas = servicio.tablero()
    assert {t["tarea_id"] for t in todas} == {"fin-ofertar", "fin-no"}  # solo finalizadas
    assert {t["tarea_id"]: t["decision"] for t in todas} == {"fin-ofertar": PENDIENTE, "fin-no": DESCARTAR}
    assert [t["tarea_id"] for t in servicio.tablero(decision=PENDIENTE)] == ["fin-ofertar"]
    assert [t["tarea_id"] for t in servicio.tablero(decision=DESCARTAR)] == ["fin-no"]
    assert [t["tarea_id"] for t in servicio.tablero(recomendacion="Ofertar")] == ["fin-ofertar"]


def test_equivalencia_con_la_recomendacion():
    assert coincide_con_sugerencia(DESCARTAR, "No ofertar") is True
    assert coincide_con_sugerencia(SOLICITAR_INFORMACION, "Solicitar revisión") is True
    assert coincide_con_sugerencia(CONTINUAR, None) is None


# --- API y matriz de roles ---

USUARIOS = {
    "tok-gerente": {"email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-analista": {"email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-admin": {"email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


@pytest.fixture
def cliente(servicio, monkeypatch):
    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    app.dependency_overrides[obtener_servicio_decisiones] = lambda: servicio
    yield TestClient(app)
    app.dependency_overrides.clear()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_gerente_registra_y_consulta(cliente):
    r = cliente.post("/resultados/fin-ofertar/decision", headers=_h("tok-gerente"),
                     json={"decision": CONTINUAR, "justificacion": "Cumple."})
    assert r.status_code == 201, r.text
    tablero = cliente.get("/resultados/", headers=_h("tok-gerente")).json()
    assert next(t for t in tablero if t["tarea_id"] == "fin-ofertar")["decision"] == CONTINUAR
    historial = cliente.get("/resultados/fin-ofertar/decisiones", headers=_h("tok-analista"))
    assert historial.status_code == 200 and len(historial.json()) == 1


@pytest.mark.parametrize("token", ["tok-analista", "tok-admin"])
def test_api_solo_el_gerente_decide(cliente, token):
    """Tabla 61: solo el gerente registra la decisión; el analista y el administrador la consultan."""
    r = cliente.post("/resultados/fin-ofertar/decision", headers=_h(token),
                     json={"decision": CONTINUAR, "justificacion": "Cumple."})
    assert r.status_code == 403
    assert cliente.get("/resultados/", headers=_h(token)).status_code == 200


def test_api_codigos_de_error(cliente):
    gerente = _h("tok-gerente")
    cuerpo = {"decision": CONTINUAR, "justificacion": "Cumple."}
    assert cliente.post("/resultados/no-existe/decision", headers=gerente, json=cuerpo).status_code == 404
    assert cliente.post("/resultados/en-revision/decision", headers=gerente, json=cuerpo).status_code == 409
    assert cliente.post("/resultados/fin-ofertar/decision", headers=gerente,
                        json={"decision": "Ofertar", "justificacion": "x"}).status_code == 422
    assert cliente.post("/resultados/fin-ofertar/decision", headers=gerente,
                        json={"decision": CONTINUAR, "justificacion": ""}).status_code == 422
