"""
Cliente de la API para la interfaz web.

El token de sesión vive en app.storage.user (almacenamiento del servidor de la
interfaz, ligado a una cookie firmada del navegador); nunca se expone al
JavaScript de la página. Si la API responde 401, la sesión se limpia y se vuelve
a la pantalla de inicio de sesión con el motivo.
"""
import logging
import os
from typing import Optional

import httpx
from nicegui import app, ui

logger = logging.getLogger("webui")

API_URL = os.getenv("API_URL", "http://localhost:8000").strip().rstrip("/")
AUTH_MODE = os.getenv("AUTH_MODE", "local").strip().lower()
# Solo en AUTH_MODE=desarrollo: token fijo, sin pantalla de inicio de sesión.
API_TOKEN_DESARROLLO = os.getenv("API_TOKEN", "").strip()

CLAVE_TOKEN = "token"
CLAVE_USUARIO = "usuario"
CLAVE_MOTIVO = "motivo_salida"
# id_token del proveedor, solo para pedirle el cierre de sesión (nunca llega al navegador).
CLAVE_ID_TOKEN = "oidc_id_token"


def modo_desarrollo() -> bool:
    return AUTH_MODE == "desarrollo" and bool(API_TOKEN_DESARROLLO)


def modo_oidc() -> bool:
    """Solo la cuenta institucional (AUTH_MODE=oidc, RN-02)."""
    return AUTH_MODE == "oidc"


def oidc_disponible() -> bool:
    """Botón de la cuenta institucional: en oidc y, en local, si el App Registration está configurado."""
    from src.shared.config import obtener_configuracion
    return obtener_configuracion().oidc_habilitado


def token_actual() -> Optional[str]:
    if modo_desarrollo():
        return API_TOKEN_DESARROLLO
    return app.storage.user.get(CLAVE_TOKEN)


def usuario_actual() -> dict:
    return app.storage.user.get(CLAVE_USUARIO) or {}


def puede(permiso: str) -> bool:
    return permiso in (usuario_actual().get("permisos") or [])


def guardar_sesion(token: str, usuario: dict) -> None:
    app.storage.user[CLAVE_TOKEN] = token
    app.storage.user[CLAVE_USUARIO] = usuario
    app.storage.user.pop(CLAVE_MOTIVO, None)


def limpiar_sesion(motivo: Optional[str] = None) -> None:
    app.storage.user.pop(CLAVE_TOKEN, None)
    app.storage.user.pop(CLAVE_USUARIO, None)
    app.storage.user.pop(CLAVE_ID_TOKEN, None)
    if motivo:
        app.storage.user[CLAVE_MOTIVO] = motivo


def tomar_motivo() -> Optional[str]:
    return app.storage.user.pop(CLAVE_MOTIVO, None)


def detalle_error(response: httpx.Response) -> str:
    try:
        detalle = response.json().get("detail", response.status_code)
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(detalle, list):
        # Errores de validación de FastAPI: se muestran los mensajes, sin la estructura.
        return "; ".join(str(d.get("msg", d)) for d in detalle)
    if isinstance(detalle, dict):
        # Errores con datos adicionales (p. ej. el 409 de un análisis reutilizable).
        return str(detalle.get("mensaje", detalle))
    return str(detalle)


def _salir_por_401(response: httpx.Response) -> None:
    # Si la sesión ya se limpió (p. ej. cierre voluntario) se conserva ese motivo.
    if app.storage.user.get(CLAVE_TOKEN):
        limpiar_sesion(detalle_error(response))
    ui.navigate.to("/login")


async def llamar_api(metodo: str, ruta: str, *, automatica: bool = False, **kwargs) -> httpx.Response:
    """
    Llama a la API con el token de la sesión.
    automatica=True marca las consultas periódicas: no renuevan el plazo de inactividad.
    """
    cabeceras = dict(kwargs.pop("headers", {}) or {})
    token = token_actual()
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    if automatica:
        cabeceras["X-Sin-Actividad"] = "1"
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.request(metodo, ruta, headers=cabeceras, **kwargs)
    if response.status_code == 401 and not ruta.startswith("/auth/login"):
        _salir_por_401(response)
    elif response.status_code == 403:
        ui.notify(detalle_error(response), type="warning")
    return response


async def iniciar_sesion(email: str, clave: str) -> Optional[str]:
    """None si inició sesión; si no, el mensaje de error para mostrar."""
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
            response = await client.post("/auth/login", json={"email": email, "password": clave})
    except httpx.HTTPError:
        return f"No hay conexión con la API en {API_URL}."
    if response.status_code != 200:
        return detalle_error(response)
    datos = response.json()
    guardar_sesion(datos["access_token"], datos["usuario"])
    return None


async def iniciar_sesion_federada(id_token: str, nonce: str) -> Optional[str]:
    """RF-005 con OIDC: la API valida el id_token y abre la sesión. None si entró; si no, el motivo."""
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
            response = await client.post("/auth/oidc", json={"id_token": id_token, "nonce": nonce})
    except httpx.HTTPError:
        return f"No hay conexión con la API en {API_URL}."
    if response.status_code != 200:
        return detalle_error(response)
    datos = response.json()
    guardar_sesion(datos["access_token"], datos["usuario"])
    app.storage.user[CLAVE_ID_TOKEN] = id_token
    return None


async def cerrar_sesion() -> None:
    token = token_actual()
    id_token = app.storage.user.get(CLAVE_ID_TOKEN)
    # Primero se olvida el token localmente: las consultas automáticas en vuelo ya no lo usan.
    limpiar_sesion("Sesión cerrada correctamente.")
    if token:
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=15.0) as client:
                await client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            pass
    if id_token:
        # RF-006: si entró con la cuenta institucional, también se cierra la sesión del proveedor.
        from src.webui import oidc
        destino = await oidc.url_cierre(id_token)
        if destino:
            ui.navigate.to(destino)
            return
    ui.navigate.to("/login")
