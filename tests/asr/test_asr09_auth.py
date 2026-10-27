"""ASR-09: ninguna ruta protegida responde sin un token válido."""
import time
from dataclasses import replace
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import src.api.middleware.auth as auth_mod
from src.api.main import app
from src.api.modules.analysis import router as modulo_router
from src.shared.config import Configuracion

TOKEN_DEV = "token-de-prueba-largo"
AUTORIDAD = "https://login.example.com/tenant/v2.0"
CLIENT_ID = "api-licitaciones"


class RepositorioFalso:
    def obtener(self, tarea_id):
        return {"tarea_id": tarea_id, "estado": "Recibida"}


@pytest.fixture
def cliente():
    app.dependency_overrides[modulo_router.obtener_repositorio] = RepositorioFalso
    yield TestClient(app)
    app.dependency_overrides.clear()


def usar_config(monkeypatch, **campos):
    config = replace(Configuracion(), **campos)
    monkeypatch.setattr(auth_mod, "obtener_configuracion", lambda: config)


def estado(cliente, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return cliente.get("/analisis/t1/estado", headers=headers)


# --- Modo desarrollo ---

def test_sin_token_rechaza(cliente, monkeypatch):
    usar_config(monkeypatch, auth_mode="desarrollo", api_token_desarrollo=TOKEN_DEV)
    assert estado(cliente).status_code in (401, 403)


@pytest.mark.parametrize("token", ["token_valido", "token_invalido", "cualquier-cosa"])
def test_token_distinto_rechaza(cliente, monkeypatch, token):
    """Antes se aceptaba cualquier token salvo 'token_invalido'."""
    usar_config(monkeypatch, auth_mode="desarrollo", api_token_desarrollo=TOKEN_DEV)
    assert estado(cliente, token).status_code == 401


def test_token_de_desarrollo_correcto(cliente, monkeypatch):
    usar_config(monkeypatch, auth_mode="desarrollo", api_token_desarrollo=TOKEN_DEV)
    assert estado(cliente, TOKEN_DEV).status_code == 200


def test_modo_desarrollo_sin_token_configurado_rechaza_todo(cliente, monkeypatch):
    usar_config(monkeypatch, auth_mode="desarrollo", api_token_desarrollo="")
    assert estado(cliente, "").status_code in (401, 403)
    assert estado(cliente, "x").status_code == 401


# --- Modo OIDC ---

REGISTRADOS = {"analista@ejemplo.com": {"user_id": "7", "email": "analista@ejemplo.com",
                                       "rol": "Analista Comercial", "roles": ["Analista Comercial"]}}


@pytest.fixture
def clave_rsa(monkeypatch):
    from fastapi import HTTPException

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=clave.public_key()))
    monkeypatch.setattr(auth_mod, "_proveedor_oidc", lambda _a: (jwks, AUTORIDAD))
    usar_config(monkeypatch, auth_mode="oidc", oidc_authority=AUTORIDAD, oidc_client_id=CLIENT_ID)

    def usuario_federado(email):
        # DA-10: el rol y el estado vienen del registro del administrador, no del token.
        if email not in REGISTRADOS:
            raise HTTPException(status_code=403, detail="no registrado")
        return REGISTRADOS[email]
    monkeypatch.setattr(auth_mod, "_usuario_federado", usuario_federado)
    return clave


def firmar(clave, **claims):
    ahora = int(time.time())
    base = {"iss": AUTORIDAD, "aud": CLIENT_ID, "iat": ahora, "exp": ahora + 600,
            "oid": "u1", "preferred_username": "analista@ejemplo.com", "roles": ["Analista Comercial"]}
    base.update(claims)
    return jwt.encode(base, clave, algorithm="RS256")


def test_oidc_token_valido(cliente, clave_rsa):
    assert estado(cliente, firmar(clave_rsa)).status_code == 200


def test_oidc_token_valido_de_un_usuario_no_registrado_no_opera(cliente, clave_rsa):
    """ASR-09: autenticarse en el proveedor no basta; el administrador debe haberlo registrado."""
    assert estado(cliente, firmar(clave_rsa, preferred_username="intruso@ejemplo.com")).status_code == 403


@pytest.mark.parametrize("claims", [
    {"exp": int(time.time()) - 10},
    {"aud": "otra-api"},
    {"iss": "https://emisor-falso"},
])
def test_oidc_token_invalido(cliente, clave_rsa, claims):
    assert estado(cliente, firmar(clave_rsa, **claims)).status_code == 401


def test_oidc_firma_de_otra_clave(cliente, clave_rsa):
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert estado(cliente, firmar(otra)).status_code == 401


def test_oidc_sin_configurar_no_abre_la_api(cliente, monkeypatch):
    usar_config(monkeypatch, auth_mode="oidc", oidc_authority="", oidc_client_id="")
    assert estado(cliente, "x").status_code == 503
