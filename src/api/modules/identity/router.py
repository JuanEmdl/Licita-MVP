"""
Módulo de identidad: inicio y cierre de sesión (RF-005, RF-006) y gestión de
usuarios por el administrador (RF-001 a RF-004).
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.api.middleware.auth import (
    _validar_local,
    email_federado,
    es_sesion_propia,
    requiere_permiso,
    security,
    validar_token_oidc,
    verificar_token,
)
from src.api.modules.identity.seguridad import ClaveDebilError
from src.api.modules.identity.servicio import (
    CredencialesInvalidasError,
    CuentaBloqueadaError,
    OperacionNoPermitidaError,
    ServicioIdentidad,
    SesionInvalidaError,
    UsuarioNoEncontradoError,
    obtener_servicio_identidad,
)
from src.shared.config import obtener_configuracion
from src.shared.roles import ROLES, Permiso, permisos_de

logger = logging.getLogger(__name__)
router_auth = APIRouter(prefix="/auth", tags=["Sesión"])
router_usuarios = APIRouter(prefix="/usuarios", tags=["Usuarios"])


class SolicitudLogin(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)


class SolicitudOIDC(BaseModel):
    id_token: str = Field(..., min_length=20, max_length=20000)
    nonce: str = Field(..., min_length=16, max_length=200)


class NuevoUsuario(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=254)
    rol: str
    # Con AUTH_MODE=oidc no se envía: la credencial vive en el proveedor (RN-02).
    password: Optional[str] = Field(None, max_length=256)
    activo: bool = True


class CambioUsuario(BaseModel):
    nombre: Optional[str] = Field(None, max_length=120)
    rol: Optional[str] = None
    activo: Optional[bool] = None


class CambioClave(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


def _exigir_modo_local() -> None:
    if obtener_configuracion().auth_mode != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El inicio de sesión con usuario y contraseña requiere AUTH_MODE=local.",
        )


def _perfil_publico(usuario: dict) -> dict:
    perfil = {k: v for k, v in usuario.items() if k != "sesion_id"}
    perfil.setdefault("nombre", usuario.get("email") or "Usuario")
    perfil.setdefault("permisos", sorted(permisos_de(usuario.get("roles") or [])))
    return perfil


# --- Sesión ---

@router_auth.post("/login")
def iniciar_sesion(datos: SolicitudLogin, servicio: ServicioIdentidad = Depends(obtener_servicio_identidad)):
    """RF-005: devuelve el token de sesión si las credenciales son válidas."""
    _exigir_modo_local()
    try:
        return servicio.iniciar_sesion(datos.email, datos.password)
    except CuentaBloqueadaError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except (CredencialesInvalidasError, SesionInvalidaError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router_auth.post("/oidc")
def iniciar_sesion_oidc(datos: SolicitudOIDC, servicio: ServicioIdentidad = Depends(obtener_servicio_identidad)):
    """
    RF-005 con el proveedor de identidad (DA-10). La interfaz, como cliente confidencial, canjea
    el código de autorización y entrega aquí el id_token con el nonce que generó. La API valida
    la firma, el emisor, la audiencia, la vigencia y el nonce; luego exige que el usuario esté
    registrado y habilitado en Licita y abre una sesión propia (RNF-010).
    """
    config = obtener_configuracion()
    if not config.oidc_habilitado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El inicio de sesión con la cuenta institucional no está configurado.")
    claims = validar_token_oidc(datos.id_token, config, nonce=datos.nonce)
    try:
        return servicio.iniciar_sesion_federada(email_federado(claims))
    except CredencialesInvalidasError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except SesionInvalidaError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router_auth.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_sesion(
    usuario: dict = Depends(verificar_token),
    servicio: ServicioIdentidad = Depends(obtener_servicio_identidad),
):
    """RF-006: el token deja de ser válido de inmediato."""
    if usuario.get("sesion_id"):
        servicio.cerrar_sesion(usuario["sesion_id"])
        logger.info(f"Sesión cerrada por {usuario.get('email')}.")


@router_auth.get("/yo")
def perfil(usuario: dict = Depends(verificar_token)):
    """Perfil, rol y permisos del usuario de la sesión. Cuenta como actividad."""
    return _perfil_publico(usuario)


@router_auth.get("/sesion")
def estado_sesion(request: Request, credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Comprueba si la sesión sigue vigente SIN contarlo como actividad: la interfaz
    lo consulta periódicamente para detectar la expiración por inactividad.
    """
    modo = obtener_configuracion().auth_mode
    if modo == "local" or (modo == "oidc" and es_sesion_propia(credentials.credentials)):
        return _perfil_publico(_validar_local(credentials.credentials, tocar=False))
    return _perfil_publico(verificar_token(request, credentials))


# --- Usuarios (solo administrador) ---

def _error_usuarios(e: Exception) -> HTTPException:
    if isinstance(e, UsuarioNoEncontradoError):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=422, detail=str(e))


@router_usuarios.get("/roles")
def listar_roles(usuario: dict = Depends(verificar_token)) -> List[dict]:
    return [{"rol": r, "permisos": sorted(permisos_de([r]))} for r in ROLES]


@router_usuarios.get("/")
def listar_usuarios(
    usuario: dict = Depends(requiere_permiso(Permiso.USUARIOS_GESTIONAR)),
    servicio: ServicioIdentidad = Depends(obtener_servicio_identidad),
):
    return servicio.listar_usuarios()


@router_usuarios.post("/", status_code=status.HTTP_201_CREATED)
def crear_usuario(
    datos: NuevoUsuario,
    usuario: dict = Depends(requiere_permiso(Permiso.USUARIOS_GESTIONAR)),
    servicio: ServicioIdentidad = Depends(obtener_servicio_identidad),
):
    """RF-001 / RF-002 / RF-003: crea el usuario con su rol y su estado inicial."""
    if not servicio.clave_opcional and not datos.password:
        raise HTTPException(status_code=422, detail="Indique la contraseña inicial del usuario.")
    try:
        nuevo = servicio.crear_usuario(datos.nombre, datos.email, datos.rol, datos.password, datos.activo,
                                       actor=usuario.get("email"))
    except (OperacionNoPermitidaError, ClaveDebilError) as e:
        raise _error_usuarios(e)
    logger.info(f"Usuario {nuevo['email']} ({nuevo['rol']}) creado por {usuario.get('email')}.")
    return nuevo


@router_usuarios.patch("/{usuario_id}")
def actualizar_usuario(
    usuario_id: int,
    datos: CambioUsuario,
    usuario: dict = Depends(requiere_permiso(Permiso.USUARIOS_GESTIONAR)),
    servicio: ServicioIdentidad = Depends(obtener_servicio_identidad),
):
    """RF-002 a RF-004: cambia rol, habilita o deshabilita (cierra sus sesiones al instante)."""
    try:
        actualizado = servicio.actualizar_usuario(
            usuario_id, usuario.get("user_id"), nombre=datos.nombre, rol=datos.rol, activo=datos.activo,
            actor=usuario.get("email"),
        )
    except (OperacionNoPermitidaError, UsuarioNoEncontradoError) as e:
        raise _error_usuarios(e)
    logger.info(f"Usuario {actualizado['email']} actualizado por {usuario.get('email')}: "
                f"{datos.model_dump(exclude_none=True)}")
    return actualizado


@router_usuarios.post("/{usuario_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_clave(
    usuario_id: int,
    datos: CambioClave,
    usuario: dict = Depends(requiere_permiso(Permiso.USUARIOS_GESTIONAR)),
    servicio: ServicioIdentidad = Depends(obtener_servicio_identidad),
):
    try:
        servicio.cambiar_clave(usuario_id, datos.password, actor=usuario.get("email"))
    except (UsuarioNoEncontradoError, ClaveDebilError, OperacionNoPermitidaError) as e:
        raise _error_usuarios(e)
    logger.info(f"Contraseña del usuario {usuario_id} restablecida por {usuario.get('email')}.")
