"""
Informe en PDF (RF-037, HU-09, HU-10, ASR-06) y bitácora completa (RF-042, Tabla 61).
Sin PostgreSQL: la bitácora se reemplaza por una lista.
"""
import hashlib
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.api.modules.audit import router as modulo_auditoria
from src.shared.config import Configuracion
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE
from src.worker_analysis.reports.informe import GeneradorInforme
from src.worker_analysis.reports.pdf import extraer_texto

ESTADO = {
    "tarea_id": "t-123",
    "licitacion_url": "CO1.REQ.999",
    "contenido_crudo": "NOMBRE DEL PROCEDIMIENTO: Plataforma\n\nPLIEGO DE CONDICIONES:\n...",
    "contenido_pliego": "",
    "recomendacion": "Solicitar revisión",
    "puntaje_global": 62.5,
    "justificacion_recomendacion": "Falta acreditar la capacidad financiera.",
    "desglose_puntaje": {"version_reglas": "3", "aporte_por_categoria": {"tecnico": 40.0, "financiero": 0.0},
                         "peso_efectivo_por_categoria": {"tecnico": 64.0, "financiero": 36.0},
                         "categorias_no_aplicables": ["personal"]},
    "reglas_aplicadas": {"version": 3, "pesos": {"tecnico": 40, "financiero": 15}, "umbral_ofertar": 80,
                         "umbral_revision": 50},
    "portafolio_version": 4,
    "version_prompts": "2.2.0",
    "aprobado_por": "ana@x.co",
    "requisitos_extraidos": [
        {"identificador": "REQ-001", "texto": "ISO 27001 vigente"},
        {"identificador": "REQ-002", "texto": "Liquidez >= 1,5"},
        {"identificador": "REQ-003", "texto": "Experiencia en Java"},
    ],
    "requisitos_aprobados": [
        {"identificador": "REQ-001", "texto": "ISO/IEC 27001 vigente", "categoria": "tecnico",
         "condicion_habilitante_propuesta": True, "referencia_documental": "Numeral 3.4"},
        {"identificador": "REQ-002", "texto": "Liquidez >= 1,5", "categoria": "financiero",
         "condicion_habilitante_propuesta": True, "referencia_documental": "Numeral 3.2"},
        {"identificador": "REQ-010", "texto": "Endeudamiento <= 60 %", "categoria": "financiero",
         "condicion_habilitante_propuesta": True, "referencia_documental": "Numeral 3.2"},
    ],
    "dictamenes": [
        {"identificador_requisito": "REQ-001", "estado": "Cumple", "evidencia": "[P-3] ISO 27001 hasta 2027",
         "justificacion": "Certificación vigente."},
        {"identificador_requisito": "REQ-002", "estado": "No verificable", "evidencia": None,
         "justificacion": "El portafolio no trae estados financieros."},
    ],
}
MOMENTO = datetime(2026, 10, 24, 15, 30)


def test_el_informe_es_un_pdf_con_todo_lo_que_exige_rf_037(tmp_path):
    resultado = GeneradorInforme(str(tmp_path)).generar_y_sellar(ESTADO, MOMENTO)
    pdf = open(resultado["informe_path"], "rb").read()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert resultado["huella_sha256"] == hashlib.sha256(pdf).hexdigest()
    texto = extraer_texto(pdf)
    for esperado in (
        "Recomendación del sistema: Solicitar revisión", "Puntaje de cumplimiento: 62.5",
        "Reglas del puntaje: versión 3", "Portafolio usado como evidencia: versión 4",
        "Instrucciones de los agentes: versión 2.2.0",
        "Documento faltante: no se aportó el pliego",          # HU-10: documentos faltantes
        "Agregados por el analista: REQ-010",                  # HU-10: intervenciones humanas
        "Eliminados por el analista: REQ-003",
        "Modificados por el analista: REQ-001",
        "REQ-002: No verificable",                             # HU-10: incertidumbres
        "Evidencia: [P-3] ISO 27001 hasta 2027",               # RF-037: evidencia del dictamen
        "aprobada por: ana@x.co",
    ):
        assert esperado in texto, esperado


def test_mismo_contenido_misma_huella_y_vista_en_texto(tmp_path):
    a = GeneradorInforme(str(tmp_path / "a")).generar_y_sellar(ESTADO, MOMENTO)
    b = GeneradorInforme(str(tmp_path / "b")).generar_y_sellar(ESTADO, MOMENTO)
    assert a["huella_sha256"] == b["huella_sha256"]  # la huella identifica el contenido
    vista = open(a["texto_path"], encoding="utf-8").read()
    assert "INCERTIDUMBRES" in vista and "REQ-002: No verificable" in vista


def test_la_huella_detecta_cualquier_alteracion(tmp_path):
    resultado = GeneradorInforme(str(tmp_path)).generar_y_sellar(ESTADO, MOMENTO)
    with open(resultado["informe_path"], "r+b") as f:
        f.seek(400)
        f.write(b"X")
    assert GeneradorInforme.huella_archivo(resultado["informe_path"]) != resultado["huella_sha256"]


# --- Eventos de identidad (RF-042, Tabla 61) ---

class AuditoriaFalsa:
    def __init__(self):
        self.eventos = []

    def registrar_evento(self, tarea_id, tipo_evento, detalles, registrado_por=None, **kwargs):
        self.eventos.append((tipo_evento, detalles, registrado_por))


@pytest.fixture
def identidad():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import src.api.modules.identity.servicio as servicio_mod
    from src.api.modules.identity.servicio import ServicioIdentidad
    from src.shared.models import Sesion, Usuario

    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Usuario.__table__.create(motor)
    Sesion.__table__.create(motor)
    servicio_mod._intentos._fallos.clear()
    config = replace(Configuracion(), auth_mode="local", sesion_secreto="s" * 48, login_max_intentos=2)
    auditoria = AuditoriaFalsa()
    return ServicioIdentidad(config, sessionmaker(bind=motor, expire_on_commit=False), auditoria), auditoria


def test_altas_cambios_y_claves_quedan_en_la_bitacora(identidad):
    servicio, auditoria = identidad
    servicio.crear_usuario("Admin", "admin@x.co", ADMINISTRADOR, "Prueba1234")
    ana = servicio.crear_usuario("Ana", "ana@x.co", ANALISTA, "Prueba1234", actor="admin@x.co")
    servicio.actualizar_usuario(ana["id"], actor_id="1", rol=GERENTE, activo=False, actor="admin@x.co")
    servicio.cambiar_clave(ana["id"], "Otra12345", actor="admin@x.co")
    tipos = [e[0] for e in auditoria.eventos]
    assert tipos == ["USUARIO_CREADO", "USUARIO_CREADO", "USUARIO_ACTUALIZADO", "CLAVE_CAMBIADA"]
    _, cambio, autor = auditoria.eventos[2]
    assert autor == "admin@x.co"
    assert cambio["cambios"] == {"rol": {"antes": ANALISTA, "despues": GERENTE},
                                 "activo": {"antes": True, "despues": False}}
    assert "Otra12345" not in str(auditoria.eventos) and "hash" not in str(auditoria.eventos[3][1])


def test_el_bloqueo_por_intentos_queda_en_la_bitacora(identidad):
    from src.api.modules.identity.servicio import CredencialesInvalidasError

    servicio, auditoria = identidad
    servicio.crear_usuario("Ana", "ana@x.co", ANALISTA, "Prueba1234")
    for _ in range(2):
        with pytest.raises(CredencialesInvalidasError):
            servicio.iniciar_sesion("ana@x.co", "Mala12345")
    assert auditoria.eventos[-1][0] == "CUENTA_BLOQUEADA"


# --- 403 auditado y consulta de la bitácora ---

USUARIOS = {
    "tok-analista": {"user_id": "2", "email": "ana@x.co", "rol": ANALISTA, "roles": [ANALISTA]},
    "tok-gerente": {"user_id": "3", "email": "gema@x.co", "rol": GERENTE, "roles": [GERENTE]},
    "tok-admin": {"user_id": "1", "email": "admin@x.co", "rol": ADMINISTRADOR, "roles": [ADMINISTRADOR]},
}


class RegistradorFalso:
    def consultar(self, **filtros):
        return {"total": 1, "acciones": ["DECISION_COMERCIAL"], "eventos": [{"id": 1, "accion": "DECISION_COMERCIAL"}],
                "filtros": filtros}

    def verificar(self):
        return {"integra": True, "registros": 1, "ruptura_en": None, "detalle": None}


@pytest.fixture
def cliente(monkeypatch):
    config = replace(Configuracion(), auth_mode="local")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr(auth_mod, "_validar_local", lambda token, tocar=True: USUARIOS[token])
    rechazos = []
    monkeypatch.setattr(auth_mod, "auditar_rechazo", lambda *args: rechazos.append(args))
    app.dependency_overrides[modulo_auditoria.obtener_registrador] = RegistradorFalso
    yield TestClient(app), rechazos
    app.dependency_overrides.clear()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_la_bitacora_la_consultan_gerente_y_administrador(cliente):
    c, rechazos = cliente
    assert c.get("/auditoria/", headers=_h("tok-gerente")).status_code == 200
    r = c.get("/auditoria/", headers=_h("tok-admin"), params={"accion": "DECISION_COMERCIAL", "usuario": "gema"})
    assert r.json()["filtros"]["accion"] == "DECISION_COMERCIAL" and r.json()["filtros"]["usuario"] == "gema"
    assert c.get("/auditoria/verificacion", headers=_h("tok-gerente")).json()["integra"] is True
    assert c.get("/auditoria/", headers=_h("tok-analista")).status_code == 403
    # Apartado 3.31: el intento sin permiso queda en la bitácora.
    usuario, permiso, metodo, ruta = rechazos[-1]
    assert (usuario["email"], permiso, metodo, ruta) == ("ana@x.co", "bitacora:ver", "GET", "/auditoria/")
