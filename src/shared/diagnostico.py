"""
Diagnóstico de los servicios externos: base de datos, SECOP II, Azure OpenAI y
Service Bus. Hace una llamada mínima a cada uno y nunca devuelve secretos.

Se usa desde la API (/diagnostico, solo administrador) y desde la consola:
    python -m scripts.verificar_servicios
"""
import logging
from typing import Dict, List

import httpx

from src.shared.config import Configuracion, obtener_configuracion

logger = logging.getLogger(__name__)


def _resultado(servicio: str, ok: bool, detalle: str, accion: str = "") -> Dict[str, object]:
    return {"servicio": servicio, "ok": ok, "detalle": detalle, "accion": accion}


def _base_de_datos() -> Dict[str, object]:
    from src.shared.database import verificar_conexion
    if verificar_conexion():
        return _resultado("Base de datos", True, "PostgreSQL responde.")
    return _resultado("Base de datos", False, "PostgreSQL no responde.",
                      "Revise DB_CONNECTION_STRING y que el servidor esté encendido.")


def _secop(config: Configuracion) -> Dict[str, object]:
    cabeceras = {"X-App-Token": config.socrata_app_token} if config.socrata_app_token else {}
    try:
        r = httpx.get(config.secop_base_url, params={"$limit": 1}, headers=cabeceras, timeout=20)
    except httpx.HTTPError as e:
        return _resultado("SECOP II (Datos Abiertos)", False, f"Sin conexión: {type(e).__name__}.",
                          "Revise la salida a internet.")
    if r.status_code == 403:
        return _resultado("SECOP II (Datos Abiertos)", False, "El token de aplicación fue rechazado.",
                          "Revise SOCRATA_APP_TOKEN.")
    if r.status_code != 200:
        return _resultado("SECOP II (Datos Abiertos)", False, f"Respuesta HTTP {r.status_code}.")
    token = "con token de aplicación" if cabeceras else "SIN token de aplicación (cuota reducida)"
    return _resultado("SECOP II (Datos Abiertos)", True, f"Responde {token}.",
                      "" if cabeceras else "Agregue SOCRATA_APP_TOKEN al .env.")


def _azure(config: Configuracion, deployment: str, nombre: str, embeddings: bool) -> Dict[str, object]:
    if not config.llm_configurado:
        return _resultado(nombre, False, "AZURE_OPENAI_ENDPOINT o AZURE_OPENAI_API_KEY vacías.",
                          "Complete las variables de Azure OpenAI en el .env.")
    base = config.azure_openai_endpoint.rstrip("/")
    ruta = "embeddings" if embeddings else "chat/completions"
    cuerpo = {"input": "prueba"} if embeddings else {
        # max_completion_tokens y no max_tokens: los modelos de razonamiento (gpt-5*, o*) rechazan max_tokens.
        "messages": [{"role": "user", "content": "Responde solo: ok"}], "max_completion_tokens": 16,
    }
    try:
        r = httpx.post(
            f"{base}/openai/deployments/{deployment}/{ruta}",
            params={"api-version": config.azure_openai_api_version},
            headers={"api-key": config.azure_openai_api_key},
            json=cuerpo, timeout=30,
        )
    except httpx.HTTPError as e:
        return _resultado(nombre, False, f"Sin conexión con {base}: {type(e).__name__}.",
                          "Revise AZURE_OPENAI_ENDPOINT y la salida a internet.")
    if r.status_code == 200:
        return _resultado(nombre, True, f"Deployment '{deployment}' responde.")
    try:
        error = r.json().get("error", {})
        codigo, mensaje = error.get("code", ""), error.get("message", "")
    except ValueError:
        codigo, mensaje = "", ""
    if r.status_code == 400 and "API version not supported" in mensaje:
        return _resultado(
            nombre, False,
            f"Azure no acepta la versión de API '{config.azure_openai_api_version}' en {base}.",
            "Use la raíz del recurso en AZURE_OPENAI_ENDPOINT (no el endpoint del proyecto de Foundry) "
            "o corrija AZURE_OPENAI_API_VERSION.",
        )
    if r.status_code in (401, 403):
        return _resultado(nombre, False, "La llave fue rechazada (401/403).",
                          "Copie de nuevo AZURE_OPENAI_API_KEY desde el portal (Claves y punto de conexión).")
    if r.status_code == 404 and codigo == "DeploymentNotFound":
        return _resultado(
            nombre, False,
            f"La llave es válida, pero el recurso no tiene un deployment llamado '{deployment}'.",
            "En Azure AI Foundry > Implementaciones, cree el deployment con ese nombre "
            "o ajuste la variable del .env al nombre que ya exista.",
        )
    return _resultado(nombre, False, f"HTTP {r.status_code} {codigo}: {mensaje[:160]}".strip(" :"))


def _service_bus(config: Configuracion) -> Dict[str, object]:
    if not config.usa_service_bus:
        return _resultado("Service Bus", True, "No configurado: la API ejecuta el análisis en su propio proceso.")
    try:
        from azure.servicebus import ServiceBusClient
        with ServiceBusClient.from_connection_string(config.service_bus_connection_string) as cliente:
            with cliente.get_queue_receiver(config.service_bus_queue_name, max_wait_time=3) as receptor:
                pendientes = len(receptor.peek_messages(max_message_count=50))
        return _resultado("Service Bus", True,
                          f"Cola '{config.service_bus_queue_name}' accesible ({pendientes} mensaje(s) en espera).",
                          "El worker de análisis debe estar corriendo para procesar la cola.")
    except Exception as e:
        return _resultado("Service Bus", False, f"{type(e).__name__}: {str(e)[:160]}",
                          "Revise SERVICE_BUS_CONNECTION_STRING y SERVICE_BUS_QUEUE_NAME.")


def diagnosticar(config: Configuracion = None) -> List[Dict[str, object]]:
    config = config or obtener_configuracion()
    return [
        _base_de_datos(),
        _secop(config),
        _azure(config, config.azure_openai_deployment, "Azure OpenAI (chat)", embeddings=False),
        _azure(config, config.azure_openai_embedding_deployment, "Azure OpenAI (embeddings)", embeddings=True),
        _service_bus(config),
    ]
