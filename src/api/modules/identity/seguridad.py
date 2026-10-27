"""
Primitivas de seguridad del módulo de identidad: hash de contraseñas y tokens de sesión.

- Contraseñas: PBKDF2-HMAC-SHA256 de la biblioteca estándar (sin dependencias
  nuevas), con sal aleatoria por usuario y comparación en tiempo constante.
- Tokens: JWT HS256 firmado por la API. El token solo identifica la sesión (jti);
  la vigencia real se decide contra la tabla `sesiones`, de modo que cerrar sesión,
  la inactividad o deshabilitar al usuario invalidan el token de inmediato.
"""
import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional, Tuple

import jwt

ALGORITMO_HASH = "pbkdf2_sha256"
ITERACIONES = 600_000
EMISOR = "licitaciones-api"
LONGITUD_MINIMA_CLAVE = 8
# Usuario sin contraseña local (AUTH_MODE=oidc, RN-02): verificar_clave siempre la rechaza.
SIN_CLAVE_LOCAL = "!proveedor-de-identidad"


class ClaveDebilError(ValueError):
    pass


def validar_clave(clave: str) -> None:
    """Política mínima: 8 caracteres, con letras y números."""
    if len(clave or "") < LONGITUD_MINIMA_CLAVE:
        raise ClaveDebilError(f"La contraseña debe tener al menos {LONGITUD_MINIMA_CLAVE} caracteres.")
    if not any(c.isalpha() for c in clave) or not any(c.isdigit() for c in clave):
        raise ClaveDebilError("La contraseña debe combinar letras y números.")


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def hash_clave(clave: str, iteraciones: int = ITERACIONES) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones)
    return f"{ALGORITMO_HASH}${iteraciones}${_b64(sal)}${_b64(derivada)}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        algoritmo, iteraciones, sal, esperado = almacenado.split("$")
        if algoritmo != ALGORITMO_HASH:
            return False
        derivada = hashlib.pbkdf2_hmac(
            "sha256", (clave or "").encode("utf-8"), base64.b64decode(sal), int(iteraciones)
        )
        return hmac.compare_digest(derivada, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


@lru_cache
def hash_senuelo() -> str:
    """
    Hash de referencia para gastar el mismo tiempo cuando el correo no existe:
    así el tiempo de respuesta no revela qué correos están registrados.
    """
    return hash_clave(secrets.token_urlsafe(16))


def ahora() -> datetime:
    """UTC sin zona: es como se guardan las fechas en la base."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def emitir_token(secreto: str, usuario_id: int, duracion_min: int) -> Tuple[str, str, datetime]:
    """Devuelve (token, jti, expira_en)."""
    jti = str(uuid.uuid4())
    emitido = ahora()
    expira = emitido + timedelta(minutes=duracion_min)
    token = jwt.encode(
        {
            "iss": EMISOR,
            "sub": str(usuario_id),
            "jti": jti,
            "iat": int(emitido.replace(tzinfo=timezone.utc).timestamp()),
            "exp": int(expira.replace(tzinfo=timezone.utc).timestamp()),
        },
        secreto,
        algorithm="HS256",
    )
    return token, jti, expira


class TokenExpiradoError(Exception):
    pass


def leer_token(secreto: str, token: str) -> Optional[dict]:
    """
    Claims del token si la firma, el emisor y la vigencia son válidos; None si el
    token es inválido. Lanza TokenExpiradoError si la firma es válida pero venció.
    """
    try:
        return jwt.decode(
            token,
            secreto,
            algorithms=["HS256"],
            issuer=EMISOR,
            options={"require": ["exp", "iat", "sub", "jti", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiradoError()
    except jwt.PyJWTError:
        return None
