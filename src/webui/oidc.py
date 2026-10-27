"""
Cliente OpenID Connect de la interfaz (RF-005, DA-10, Tabla 28).

La interfaz es un servidor y actúa como cliente confidencial: hace el flujo de código de
autorización con PKCE, canjea el código con su secreto y nunca entrega los tokens del
proveedor al navegador. El id_token va del servidor de la interfaz a la API, que lo valida
(firma, emisor, audiencia, vigencia y nonce), comprueba que el administrador registró y
habilitó al usuario, y devuelve una sesión propia. El state, el nonce y el verificador PKCE
se guardan del lado del servidor (app.storage.user), ligados a la cookie firmada.
"""
import base64
import hashlib
import secrets
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import Dict, Optional, Tuple

import httpx

from src.shared.config import obtener_configuracion

# Una solicitud de inicio de sesión que no vuelve en este tiempo deja de ser válida.
VIGENCIA_SOLICITUD_S = 600

_metadatos: Dict[str, Tuple[float, dict]] = {}


class ErrorOIDC(Exception):
    """Falla del proveedor o de la solicitud, con un mensaje apto para el usuario."""


@asynccontextmanager
async def _http(cliente: Optional[httpx.AsyncClient], timeout: float):
    """Usa el cliente recibido (pruebas) sin cerrarlo, o abre y cierra uno propio."""
    if cliente is not None:
        yield cliente
        return
    async with httpx.AsyncClient(timeout=timeout) as propio:
        yield propio


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def desafio_pkce(verificador: str) -> str:
    """Desafío S256 del verificador PKCE (RFC 7636)."""
    return _b64url(hashlib.sha256(verificador.encode("ascii")).digest())


def pkce() -> Tuple[str, str]:
    """(verificador, desafío S256)."""
    verificador = _b64url(secrets.token_bytes(48))
    return verificador, desafio_pkce(verificador)


def nueva_solicitud() -> dict:
    verificador, _ = pkce()
    return {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
            "verificador": verificador, "creada": time.time()}


def solicitud_vigente(solicitud: Optional[dict], state: str) -> bool:
    return bool(solicitud) and secrets.compare_digest(solicitud.get("state", ""), state or "") \
        and time.time() - solicitud.get("creada", 0) < VIGENCIA_SOLICITUD_S


async def metadatos(cliente: Optional[httpx.AsyncClient] = None) -> dict:
    """Documento de descubrimiento del proveedor, en caché por una hora."""
    autoridad = obtener_configuracion().oidc_authority
    if not autoridad:
        raise ErrorOIDC("El proveedor de identidad no está configurado (OIDC_AUTHORITY).")
    guardado = _metadatos.get(autoridad)
    if guardado and time.time() - guardado[0] < 3600:
        return guardado[1]
    try:
        async with _http(cliente, 10.0) as http:
            respuesta = await http.get(f"{autoridad}/.well-known/openid-configuration")
            respuesta.raise_for_status()
            datos = respuesta.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ErrorOIDC("No hay conexión con el proveedor de identidad. Intente de nuevo en unos minutos.") from e
    _metadatos[autoridad] = (time.time(), datos)
    return datos


async def url_autorizacion(solicitud: dict, cliente: Optional[httpx.AsyncClient] = None) -> str:
    config = obtener_configuracion()
    destino = (await metadatos(cliente))["authorization_endpoint"]
    desafio = desafio_pkce(solicitud["verificador"])
    parametros = {
        "client_id": config.oidc_client_id, "response_type": "code", "redirect_uri": config.oidc_redirect,
        "scope": config.oidc_scopes, "state": solicitud["state"], "nonce": solicitud["nonce"],
        "code_challenge": desafio, "code_challenge_method": "S256", "response_mode": "query",
    }
    return f"{destino}?{urllib.parse.urlencode(parametros)}"


async def canjear_codigo(codigo: str, solicitud: dict, cliente: Optional[httpx.AsyncClient] = None) -> dict:
    """Canjea el código por los tokens; el secreto del cliente nunca sale del servidor."""
    config = obtener_configuracion()
    destino = (await metadatos(cliente))["token_endpoint"]
    datos = {"grant_type": "authorization_code", "code": codigo, "redirect_uri": config.oidc_redirect,
             "client_id": config.oidc_client_id, "code_verifier": solicitud["verificador"]}
    if config.oidc_client_secret:
        datos["client_secret"] = config.oidc_client_secret
    try:
        async with _http(cliente, 15.0) as http:
            respuesta = await http.post(destino, data=datos)
    except httpx.HTTPError as e:
        raise ErrorOIDC("No hay conexión con el proveedor de identidad.") from e
    if respuesta.status_code != 200:
        try:
            detalle = respuesta.json().get("error_description") or respuesta.json().get("error")
        except ValueError:
            detalle = None
        raise ErrorOIDC(f"El proveedor de identidad rechazó el inicio de sesión{': ' + detalle[:160] if detalle else '.'}")
    tokens = respuesta.json()
    if not tokens.get("id_token"):
        raise ErrorOIDC("El proveedor de identidad no devolvió el id_token (¿falta el alcance openid?).")
    return tokens


async def url_cierre(id_token: Optional[str], cliente: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    """Cierre de sesión en el proveedor, si lo publica y está activado (OIDC_CERRAR_EN_PROVEEDOR)."""
    config = obtener_configuracion()
    if not config.oidc_cerrar_en_proveedor:
        return None
    try:
        destino = (await metadatos(cliente)).get("end_session_endpoint")
    except ErrorOIDC:
        return None
    if not destino:
        return None
    parametros = {"post_logout_redirect_uri": f"{config.webui_url}/login", "client_id": config.oidc_client_id}
    if id_token:
        parametros["id_token_hint"] = id_token
    return f"{destino}?{urllib.parse.urlencode(parametros)}"
