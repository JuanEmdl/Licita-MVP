"""
Inicio de sesión con OpenID Connect (RF-005, DA-10, RN-02, ASR-09, RNF-010; Tabla 28).

Sin Entra ID: un proveedor simulado firma los id_token con una clave RSA propia. Se prueba
que la API valida firma, emisor, audiencia, vigencia y nonce; que solo entran los usuarios
registrados y habilitados por el administrador, con el rol que él asignó; y que la sesión
resultante cumple las mismas reglas de vigencia que la local. También el cliente OIDC de la
interfaz (PKCE, state y canje del código) con un transporte HTTP simulado.
"""
import asyncio
import time
import urllib.parse
from dataclasses import replace
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.api.middleware.auth as auth_mod
import src.api.modules.identity.servicio as servicio_mod
from src.api.main import app
from src.api.modules.identity.servicio import OperacionNoPermitidaError, ServicioIdentidad
from src.shared.config import Configuracion
from src.shared.models import Sesion, Usuario
from src.shared.roles import ADMINISTRADOR, ANALISTA, GERENTE, Permiso

AUTORIDAD = "https://login.microsoftonline.com/inquilino/v2.0"
CLIENTE = "11111111-2222-3333-4444-555555555555"
NONCE = "nonce-de-la-solicitud-0123456789"


class AuditoriaNula:
    def registrar_evento(self, *args, **kwargs):
        pass


@pytest.fixture
def config():
    return replace(Configuracion(), auth_mode="oidc", oidc_authority=AUTORIDAD, oidc_client_id=CLIENTE,
                   oidc_client_secret="secreto-del-cliente", sesion_secreto="s" * 48, sesion_inactividad_min=30,
                   sesion_duracion_min=480, webui_url="http://licita.local", admin_email="admin@fabrica.co",
                   admin_password="")


@pytest.fixture
def servicio(config):
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Usuario.__table__.create(motor)
    Sesion.__table__.create(motor)
    s = ServicioIdentidad(config, sessionmaker(bind=motor), auditoria=AuditoriaNula())
    s.asegurar_admin_inicial()  # RN-02: solo con ADMIN_EMAIL, sin contraseña
    s.crear_usuario("Ana", "ana@fabrica.co", ANALISTA)
    s.crear_usuario("Gema", "gema@fabrica.co", GERENTE, activo=False)
    return s


@pytest.fixture
def clave(monkeypatch, config):
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=privada.public_key()))
    monkeypatch.setattr(auth_mod, "_proveedor_oidc", lambda _a: (jwks, AUTORIDAD))
    return privada


@pytest.fixture
def cliente(servicio, config, clave, monkeypatch):
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)
    monkeypatch.setattr("src.api.modules.identity.router.obtener_configuracion", lambda: config)
    monkeypatch.setattr(servicio_mod, "_servicio", servicio)
    app.dependency_overrides[servicio_mod.obtener_servicio_identidad] = lambda: servicio
    yield TestClient(app)
    app.dependency_overrides.clear()


def id_token(clave, **claims):
    ahora = int(time.time())
    base = {"iss": AUTORIDAD, "aud": CLIENTE, "iat": ahora, "exp": ahora + 600, "nonce": NONCE,
            "sub": "sujeto-1", "oid": "objeto-1", "preferred_username": "Ana@Fabrica.co",
            # Un claim de roles en el token no concede nada: el rol lo asigna el administrador (RF-002).
            "roles": [ADMINISTRADOR]}
    base.update(claims)
    return jwt.encode(base, clave, algorithm="RS256")


def _entrar(cliente, token, nonce=NONCE):
    return cliente.post("/auth/oidc", json={"id_token": token, "nonce": nonce})


# --- API (RF-005, DA-10) ---

def test_el_usuario_registrado_entra_con_el_rol_que_asigno_el_administrador(cliente, clave):
    r = _entrar(cliente, id_token(clave))
    assert r.status_code == 200
    sesion = r.json()
    assert sesion["usuario"]["email"] == "ana@fabrica.co" and sesion["usuario"]["rol"] == ANALISTA
    assert Permiso.USUARIOS_GESTIONAR not in sesion["usuario"]["permisos"]  # el claim "roles" se ignora
    h = {"Authorization": f"Bearer {sesion['access_token']}"}
    assert cliente.get("/auth/yo", headers=h).json()["rol"] == ANALISTA
    assert cliente.get("/auth/sesion", headers=h).status_code == 200
    assert cliente.post("/auth/logout", headers=h).status_code == 204  # RF-006
    assert cliente.get("/auth/yo", headers=h).status_code == 401


@pytest.mark.parametrize("cambios, nonce", [
    ({"exp": int(time.time()) - 5}, NONCE),           # vencido
    ({"aud": "otra-aplicacion"}, NONCE),              # para otra aplicación
    ({"iss": "https://emisor-falso/v2.0"}, NONCE),    # de otro emisor
    ({}, "otro-nonce-0123456789abcdef"),              # repetido o de otra solicitud
    ({"nonce": None}, NONCE),                         # sin nonce
])
def test_credenciales_invalidas_se_rechazan(cliente, clave, cambios, nonce):
    assert _entrar(cliente, id_token(clave, **cambios), nonce).status_code == 401


def test_firma_de_otra_clave_se_rechaza(cliente):
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _entrar(cliente, id_token(otra)).status_code == 401


def test_no_registrado_o_deshabilitado_no_entra(cliente, clave):
    r = _entrar(cliente, id_token(clave, preferred_username="intruso@fabrica.co"))
    assert r.status_code == 403 and "no está registrada" in r.json()["detail"]
    r = _entrar(cliente, id_token(clave, preferred_username="gema@fabrica.co"))
    assert r.status_code == 403 and "deshabilitado" in r.json()["detail"]


def test_deshabilitar_corta_la_sesion_federada(cliente, clave, servicio):
    """RF-004: también con OIDC, deshabilitar al usuario cierra su sesión al instante."""
    h = {"Authorization": f"Bearer {_entrar(cliente, id_token(clave)).json()['access_token']}"}
    admin = {"Authorization": f"Bearer {_entrar(cliente, id_token(clave, preferred_username='admin@fabrica.co')).json()['access_token']}"}
    ana = next(u for u in servicio.listar_usuarios() if u["email"] == "ana@fabrica.co")
    assert cliente.patch(f"/usuarios/{ana['id']}", json={"activo": False}, headers=admin).status_code == 200
    r = cliente.get("/auth/yo", headers=h)
    assert r.status_code == 401 and "deshabilitado" in r.json()["detail"]


def test_sin_contrasena_local_con_oidc(cliente, clave, servicio):
    """RN-02: con OIDC no hay contraseñas locales: ni inicio con clave, ni alta con clave, ni cambio."""
    assert cliente.post("/auth/login", json={"email": "ana@fabrica.co", "password": "x"}).status_code == 400
    admin = {"Authorization": f"Bearer {_entrar(cliente, id_token(clave, preferred_username='admin@fabrica.co')).json()['access_token']}"}
    r = cliente.post("/usuarios/", json={"nombre": "Beto", "email": "beto@fabrica.co", "rol": ANALISTA}, headers=admin)
    assert r.status_code == 201
    assert cliente.post(f"/usuarios/{r.json()['id']}/password", json={"password": "Clave1234"},
                        headers=admin).status_code == 422
    with pytest.raises(OperacionNoPermitidaError):
        servicio.cambiar_clave(r.json()["id"], "Clave1234")


def test_el_token_del_proveedor_tambien_sirve_a_clientes_de_la_api(cliente, clave):
    """Un cliente de la API puede presentar el token de Entra; rige el registro de Licita."""
    assert cliente.get("/auth/yo", headers={"Authorization": f"Bearer {id_token(clave)}"}).json()["rol"] == ANALISTA
    otro = id_token(clave, preferred_username="intruso@fabrica.co")
    assert cliente.get("/auth/yo", headers={"Authorization": f"Bearer {otro}"}).status_code == 403


def test_al_pasar_de_local_a_oidc_se_registra_el_administrador_de_admin_email(servicio, config):
    """Con usuarios locales ya creados, ADMIN_EMAIL se registra si falta; uno existente no se toca."""
    otro = ServicioIdentidad(replace(config, admin_email="Nuevo.Admin@Fabrica.co"), servicio._fabrica,
                             auditoria=AuditoriaNula())
    otro.asegurar_admin_inicial()
    nuevo = next(u for u in servicio.listar_usuarios() if u["email"] == "nuevo.admin@fabrica.co")
    assert nuevo["rol"] == ADMINISTRADOR and nuevo["activo"]
    deshabilitada = ServicioIdentidad(replace(config, admin_email="gema@fabrica.co"), servicio._fabrica,
                                      auditoria=AuditoriaNula())
    deshabilitada.asegurar_admin_inicial()
    gema = next(u for u in servicio.listar_usuarios() if u["email"] == "gema@fabrica.co")
    assert (gema["rol"], gema["activo"]) == (GERENTE, False)


def test_en_modo_local_sin_app_registration_no_hay_inicio_federado(cliente, clave, monkeypatch, config):
    local = replace(config, auth_mode="local", oidc_client_secret="")
    monkeypatch.setattr("src.api.modules.identity.router.obtener_configuracion", lambda: local)
    assert _entrar(cliente, id_token(clave)).status_code == 400


def test_modo_local_con_app_registration_ofrece_ambos_inicios(clave, monkeypatch, config):
    """AUTH_MODE=local con OIDC configurado: entran tanto los usuarios con contraseña como los institucionales."""
    local = replace(config, auth_mode="local")
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Usuario.__table__.create(motor)
    Sesion.__table__.create(motor)
    servicio = ServicioIdentidad(local, sessionmaker(bind=motor), auditoria=AuditoriaNula())
    servicio.crear_usuario("Ana", "ana@fabrica.co", ANALISTA)  # sin contraseña: solo institucional
    servicio.crear_usuario("Local", "local@licita.com", GERENTE, "Clave1234")
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: local)
    monkeypatch.setattr("src.api.modules.identity.router.obtener_configuracion", lambda: local)
    monkeypatch.setattr(servicio_mod, "_servicio", servicio)
    app.dependency_overrides[servicio_mod.obtener_servicio_identidad] = lambda: servicio
    try:
        c = TestClient(app)
        institucional = _entrar(c, id_token(clave))
        assert institucional.status_code == 200 and institucional.json()["usuario"]["rol"] == ANALISTA
        h = {"Authorization": f"Bearer {institucional.json()['access_token']}"}
        assert c.get("/auth/yo", headers=h).status_code == 200
        con_clave = c.post("/auth/login", json={"email": "local@licita.com", "password": "Clave1234"})
        assert con_clave.status_code == 200 and con_clave.json()["usuario"]["rol"] == GERENTE
        # Quien no tiene contraseña local no puede entrar con una.
        assert c.post("/auth/login", json={"email": "ana@fabrica.co", "password": "!proveedor-de-identidad"}
                      ).status_code == 401
    finally:
        app.dependency_overrides.clear()


# --- Cliente OIDC de la interfaz (PKCE, state, canje) ---

METADATOS = {"issuer": AUTORIDAD, "authorization_endpoint": f"{AUTORIDAD}/authorize",
             "token_endpoint": f"{AUTORIDAD}/token", "end_session_endpoint": f"{AUTORIDAD}/logout",
             "jwks_uri": f"{AUTORIDAD}/keys"}


@pytest.fixture
def oidc_ui(config, monkeypatch):
    from src.webui import oidc
    monkeypatch.setattr(oidc, "obtener_configuracion", lambda: config)
    oidc._metadatos.clear()
    return oidc


def _cliente_http(manejador):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(manejador))


def test_la_url_de_autorizacion_lleva_pkce_state_y_nonce(oidc_ui):
    solicitud = oidc_ui.nueva_solicitud()
    http = _cliente_http(lambda r: httpx.Response(200, json=METADATOS))
    url = asyncio.run(oidc_ui.url_autorizacion(solicitud, http()))
    destino, consulta = url.split("?", 1)
    p = dict(urllib.parse.parse_qsl(consulta))
    assert destino == f"{AUTORIDAD}/authorize" and p["response_type"] == "code"
    assert p["redirect_uri"] == "http://licita.local/auth/callback" and p["client_id"] == CLIENTE
    assert (p["state"], p["nonce"]) == (solicitud["state"], solicitud["nonce"])
    assert p["code_challenge_method"] == "S256"
    assert p["code_challenge"] == oidc_ui.desafio_pkce(solicitud["verificador"])
    assert solicitud["verificador"] not in url  # el verificador no sale del servidor
    assert oidc_ui.solicitud_vigente(solicitud, solicitud["state"])
    assert not oidc_ui.solicitud_vigente(solicitud, "otro-state")
    assert not oidc_ui.solicitud_vigente({**solicitud, "creada": time.time() - 3600}, solicitud["state"])


def test_el_codigo_se_canjea_desde_el_servidor_con_secreto_y_verificador(oidc_ui):
    solicitud = oidc_ui.nueva_solicitud()
    recibido = {}

    def manejador(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=METADATOS)
        recibido.update(dict(urllib.parse.parse_qsl(request.content.decode())))
        return httpx.Response(200, json={"id_token": "eyJ.token.firmado", "access_token": "a"})

    tokens = asyncio.run(oidc_ui.canjear_codigo("codigo-1", solicitud, _cliente_http(manejador)()))
    assert tokens["id_token"] == "eyJ.token.firmado"
    assert recibido["client_secret"] == "secreto-del-cliente" and recibido["code_verifier"] == solicitud["verificador"]
    assert recibido["grant_type"] == "authorization_code" and recibido["code"] == "codigo-1"


def test_errores_del_proveedor_se_explican(oidc_ui):
    solicitud = oidc_ui.nueva_solicitud()

    def rechaza(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=METADATOS)
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "AADSTS54005: código usado"})

    with pytest.raises(oidc_ui.ErrorOIDC, match="AADSTS54005"):
        asyncio.run(oidc_ui.canjear_codigo("c", solicitud, _cliente_http(rechaza)()))
    oidc_ui._metadatos.clear()
    with pytest.raises(oidc_ui.ErrorOIDC, match="No hay conexión"):
        asyncio.run(oidc_ui.url_autorizacion(solicitud, _cliente_http(lambda r: httpx.Response(503))()))


def test_el_cierre_de_sesion_se_pide_al_proveedor(oidc_ui, config, monkeypatch):
    url = asyncio.run(oidc_ui.url_cierre("id.token", _cliente_http(lambda r: httpx.Response(200, json=METADATOS))()))
    p = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
    assert url.startswith(f"{AUTORIDAD}/logout") and p["post_logout_redirect_uri"] == "http://licita.local/login"
    assert p["id_token_hint"] == "id.token"
    monkeypatch.setattr(oidc_ui, "obtener_configuracion", lambda: replace(config, oidc_cerrar_en_proveedor=False))
    assert asyncio.run(oidc_ui.url_cierre("id.token")) is None
