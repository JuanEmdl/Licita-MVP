import logging
import secrets
from functools import lru_cache
from typing import Optional, Tuple

import httpx
import jwt
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.shared.config import Configuracion, obtener_configuracion
from src.shared.roles import ROLES, tiene_permiso

logger = logging.getLogger(__name__)
security = HTTPBearer()

_NO_AUTORIZADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales inválidas o sesión expirada",
    headers={"WWW-Authenticate": "Bearer"},
)


@lru_cache
def _proveedor_oidc(authority: str) -> Tuple[jwt.PyJWKClient, str]:
    """Descubre el emisor y las claves públicas (JWKS) del proveedor de identidad."""
    respuesta = httpx.get(f"{authority}/.well-known/openid-configuration", timeout=10.0)
    respuesta.raise_for_status()
    metadatos = respuesta.json()
    # PyJWKClient guarda en caché las claves y las vuelve a pedir si llega un 'kid' nuevo.
    return jwt.PyJWKClient(metadatos["jwks_uri"], cache_keys=True), metadatos["issuer"]


def validar_token_oidc(token: str, config: Configuracion, nonce: Optional[str] = None) -> dict:
    """
    Claims de un token del proveedor de identidad si la firma (JWKS), el emisor, la audiencia
    y la vigencia son válidos; con nonce, además debe coincidir con el de la solicitud (RF-005).
    """
    if not (config.oidc_authority and config.oidc_client_id):
        logger.error("AUTH_MODE=oidc sin OIDC_AUTHORITY u OIDC_CLIENT_ID: se rechazan todas las solicitudes.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Autenticación no configurada")

    try:
        cliente_jwks, emisor = _proveedor_oidc(config.oidc_authority)
        clave = cliente_jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            clave.key,
            algorithms=["RS256"],
            # Entra ID emite el aud como el client id o como el Application ID URI.
            audience=[config.oidc_client_id, f"api://{config.oidc_client_id}"],
            issuer=emisor,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError, KeyError) as e:
        logger.warning(f"Token rechazado (ASR-09): {e}")
        raise _NO_AUTORIZADO
    if nonce is not None and not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
        logger.warning("Token rechazado (ASR-09): el nonce no corresponde a la solicitud de inicio de sesión.")
        raise _NO_AUTORIZADO
    return claims


def email_federado(claims: dict) -> str:
    """Correo institucional del usuario según el proveedor (RN-01: lo identifica de forma única)."""
    return (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip().lower()


def _usuario_federado(email: str) -> dict:
    """
    DA-10 y ASR-09: el proveedor autentica, pero el rol y el estado los decide el administrador
    en Licita (RF-001 a RF-004). Un correo no registrado o deshabilitado no opera.
    """
    from src.api.modules.identity.servicio import ErrorIdentidad, obtener_servicio_identidad

    try:
        return obtener_servicio_identidad().perfil_federado(email)
    except ErrorIdentidad as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


def _validar_oidc(token: str, config: Configuracion) -> dict:
    """Token del proveedor presentado directamente a la API (clientes de la API, no la interfaz)."""
    return _usuario_federado(email_federado(validar_token_oidc(token, config)))


def es_sesion_propia(token: str) -> bool:
    """True si el token lo emitió la API al iniciar sesión (su firma se valida después)."""
    from src.api.modules.identity.seguridad import EMISOR

    try:
        return jwt.decode(token, options={"verify_signature": False}).get("iss") == EMISOR
    except jwt.PyJWTError:
        return False


def _validar_local(token: str, tocar: bool = True) -> dict:
    from src.api.modules.identity.servicio import SesionInvalidaError, obtener_servicio_identidad

    try:
        return obtener_servicio_identidad().validar(token, tocar=tocar)
    except SesionInvalidaError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


def _validar_desarrollo(token: str, config: Configuracion) -> dict:
    if not config.api_token_desarrollo:
        logger.error("AUTH_MODE=desarrollo sin API_TOKEN_DESARROLLO: se rechazan todas las solicitudes.")
        raise _NO_AUTORIZADO
    if not secrets.compare_digest(token, config.api_token_desarrollo):
        logger.warning("Intento de acceso rechazado por token inválido (ASR-09).")
        raise _NO_AUTORIZADO
    return {
        "user_id": "usuario-desarrollo",
        "email": "desarrollo@localhost",
        "nombre": "Usuario de desarrollo",
        # El token de desarrollo no tiene usuario asociado: suma los tres roles para
        # recorrer el flujo completo en pruebas. Nunca se usa con AUTH_MODE=local u oidc.
        "rol": "Desarrollo (todos los roles)",
        "roles": list(ROLES),
    }


# Cabecera con la que la interfaz marca sus consultas automáticas (refresco de
# tablas, contadores): no cuentan como actividad para la expiración por inactividad.
CABECERA_SIN_ACTIVIDAD = "X-Sin-Actividad"


def verificar_token(request: Request, credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """
    Filtro de Autenticación (DA-10, ASR-09).
    - local: token de sesión emitido por /auth/login; se valida contra la tabla de
      sesiones (cierre, inactividad, vencimiento y usuario deshabilitado).
    - oidc: firma, emisor, audiencia y vigencia del JWT de Entra ID.
    - desarrollo: token fijo de pruebas.
    Todas las rutas protegidas deben depender de esta función (o de requiere_permiso).

    Es síncrona a propósito: la primera validación consulta el JWKS por red y
    FastAPI ejecuta las dependencias síncronas fuera del bucle de eventos.
    """
    config = obtener_configuracion()
    if config.auth_mode == "local":
        tocar = request.headers.get(CABECERA_SIN_ACTIVIDAD, "") != "1"
        return _validar_local(credentials.credentials, tocar=tocar)
    if config.auth_mode == "oidc":
        # La interfaz usa la sesión que la API emitió tras validar al usuario en el proveedor:
        # así rigen la inactividad, el cierre y la deshabilitación inmediata (RNF-010, RF-004).
        if es_sesion_propia(credentials.credentials):
            tocar = request.headers.get(CABECERA_SIN_ACTIVIDAD, "") != "1"
            return _validar_local(credentials.credentials, tocar=tocar)
        return _validar_oidc(credentials.credentials, config)
    if config.auth_mode == "desarrollo":
        return _validar_desarrollo(credentials.credentials, config)

    logger.error(f"AUTH_MODE desconocido: '{config.auth_mode}'.")
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Autenticación no configurada")


def auditar_rechazo(usuario: dict, permiso: str, metodo: str, ruta: str) -> None:
    """
    Apartado 3.31: un rol sin permiso recibe 403 y el intento queda en la bitácora. Si la
    bitácora no responde, el 403 se mantiene: negar el acceso no depende de poder auditarlo.
    """
    try:
        from src.worker_analysis.reports.auditoria import RegistradorAuditoria
        RegistradorAuditoria().registrar_evento(
            f"acceso-{usuario.get('user_id')}", "ACCESO_DENEGADO",
            {"rol": usuario.get("rol"), "permiso": permiso, "metodo": metodo, "ruta": ruta},
            registrado_por=usuario.get("email") or usuario.get("user_id"))
    except Exception as e:
        logger.error(f"No se pudo registrar el acceso denegado en la bitácora: {type(e).__name__}")


def requiere_permiso(permiso: str):
    """
    Dependencia de autorización por rol (RF-002). Uso:
        usuario: dict = Depends(requiere_permiso(Permiso.REQUISITOS_APROBAR))
    """
    def _dependencia(request: Request, usuario: dict = Security(verificar_token)) -> dict:
        if not tiene_permiso(usuario, permiso):
            logger.warning(f"Acceso denegado a {usuario.get('email')} ({usuario.get('rol')}): falta '{permiso}'.")
            # Tabla 49: 403 por rol y por permiso, sin datos personales.
            from src.shared import telemetria
            telemetria.rechazos_autorizacion.add(1, {"rol": usuario.get("rol") or "sin rol", "permiso": permiso})
            auditar_rechazo(usuario, permiso, request.method, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Su rol no tiene permiso para esta operación.",
            )
        return usuario

    # FF-05: la suite rol-operación lee el permiso de cada ruta desde aquí.
    _dependencia.permiso = permiso
    return _dependencia
