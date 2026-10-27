"""
Servicio de identidad (RF-001 a RF-007, RNF-010).

Gestiona usuarios, roles y sesiones del modo AUTH_MODE=local. Una sesión pierde
vigencia por cualquiera de estas causas, y desde ese momento el token deja de
abrir operaciones protegidas:
  1. el usuario cierra sesión (RF-006);
  2. pasa SESION_INACTIVIDAD_MIN sin solicitudes (RF-007);
  3. se cumple SESION_DURACION_MIN desde el inicio de sesión;
  4. un administrador deshabilita al usuario (RF-004).
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.modules.identity import seguridad
from src.shared.config import Configuracion, obtener_configuracion
from src.shared.models import Sesion, Usuario
from src.shared.roles import ADMINISTRADOR, ROLES, permisos_de

logger = logging.getLogger(__name__)

# Evita escribir en la base en cada solicitud: el último uso se actualiza
# como máximo una vez por este intervalo.
_INTERVALO_TOQUE = timedelta(seconds=15)


class ErrorIdentidad(Exception):
    """Error con mensaje apto para mostrar al usuario."""


class CredencialesInvalidasError(ErrorIdentidad):
    pass


class CuentaBloqueadaError(ErrorIdentidad):
    pass


class SesionInvalidaError(ErrorIdentidad):
    pass


class UsuarioNoEncontradoError(ErrorIdentidad):
    pass


class OperacionNoPermitidaError(ErrorIdentidad):
    pass


class _ControlIntentos:
    """Bloqueo temporal tras varios intentos fallidos de inicio de sesión (en memoria del proceso)."""

    def __init__(self):
        self._fallos: Dict[str, Tuple[int, Optional[datetime]]] = {}
        self._candado = threading.Lock()

    def verificar(self, email: str) -> None:
        with self._candado:
            _, bloqueado_hasta = self._fallos.get(email, (0, None))
        if bloqueado_hasta and bloqueado_hasta > seguridad.ahora():
            minutos = max(1, int((bloqueado_hasta - seguridad.ahora()).total_seconds() // 60) + 1)
            raise CuentaBloqueadaError(
                f"Demasiados intentos fallidos. Intente de nuevo en {minutos} minuto(s)."
            )

    def fallo(self, email: str, maximo: int, bloqueo_min: int) -> bool:
        """Cuenta un intento fallido. Devuelve True si con este la cuenta quedó bloqueada."""
        with self._candado:
            intentos, _ = self._fallos.get(email, (0, None))
            intentos += 1
            if intentos >= maximo:
                self._fallos[email] = (0, seguridad.ahora() + timedelta(minutes=bloqueo_min))
                logger.warning(f"Cuenta {email} bloqueada {bloqueo_min} min por intentos fallidos.")
                return True
            self._fallos[email] = (intentos, None)
            return False

    def exito(self, email: str) -> None:
        with self._candado:
            self._fallos.pop(email, None)


_intentos = _ControlIntentos()


def usuario_a_dict(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "email": usuario.email,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
        "activo": usuario.activo,
        "creado_en": usuario.creado_en.isoformat() if usuario.creado_en else None,
        "ultimo_acceso": usuario.ultimo_acceso.isoformat() if usuario.ultimo_acceso else None,
    }


def _normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def _validar_rol(rol: str) -> None:
    if rol not in ROLES:
        raise OperacionNoPermitidaError(f"Rol desconocido: '{rol}'. Roles válidos: {', '.join(ROLES)}.")


class ServicioIdentidad:

    def __init__(
        self,
        configuracion: Optional[Configuracion] = None,
        fabrica_sesiones: Optional[Callable[[], Session]] = None,
        auditoria=None,
    ):
        self.config = configuracion or obtener_configuracion()
        if fabrica_sesiones is None:
            from src.shared.database import SessionLocal
            fabrica_sesiones = SessionLocal
        self._fabrica = fabrica_sesiones
        self._auditoria = auditoria

    @property
    def auditoria(self):
        # RF-042: altas, cambios de rol o de estado, cambios de clave y bloqueos son eventos críticos.
        if self._auditoria is None:
            from src.worker_analysis.reports.auditoria import RegistradorAuditoria
            self._auditoria = RegistradorAuditoria()
        return self._auditoria

    # --- Sesiones ---

    def _secreto(self) -> str:
        if len(self.config.sesion_secreto) < 32:
            logger.error("SESION_SECRETO ausente o corto: no se pueden emitir ni validar sesiones.")
            raise SesionInvalidaError("Autenticación no configurada en el servidor.")
        return self.config.sesion_secreto

    def iniciar_sesion(self, email: str, clave: str) -> dict:
        email = _normalizar_email(email)
        secreto = self._secreto()
        _intentos.verificar(email)

        with self._fabrica() as db:
            usuario = db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
            hash_guardado = usuario.password_hash if usuario else seguridad.hash_senuelo()
            clave_ok = seguridad.verificar_clave(clave, hash_guardado)
            if not usuario or not clave_ok:
                bloqueada = _intentos.fallo(email, self.config.login_max_intentos, self.config.login_bloqueo_min)
                logger.warning(f"Inicio de sesión rechazado para {email}.")
                if bloqueada:
                    self.auditoria.registrar_evento(
                        f"usuario-{email}", "CUENTA_BLOQUEADA",
                        {"email": email, "intentos": self.config.login_max_intentos,
                         "minutos": self.config.login_bloqueo_min}, registrado_por="sistema")
                raise CredencialesInvalidasError("Correo o contraseña incorrectos.")
            if not usuario.activo:
                logger.warning(f"Inicio de sesión de usuario deshabilitado: {email}.")
                raise CredencialesInvalidasError("El usuario está deshabilitado. Contacte al administrador.")

            _intentos.exito(email)
            return self._abrir_sesion(db, usuario, secreto)

    def _abrir_sesion(self, db: Session, usuario: Usuario, secreto: str) -> dict:
        token, jti, expira = seguridad.emitir_token(secreto, usuario.id, self.config.sesion_duracion_min)
        momento = seguridad.ahora()
        db.add(Sesion(id=jti, usuario_id=usuario.id, creada_en=momento, ultimo_uso=momento, expira_en=expira))
        usuario.ultimo_acceso = momento
        db.commit()
        logger.info(f"Sesión iniciada por {usuario.email} ({usuario.rol}).")
        return {
            "access_token": token,
            "token_type": "bearer",
            "expira_en": expira.isoformat() + "Z",
            "inactividad_min": self.config.sesion_inactividad_min,
            "usuario": self._perfil(usuario),
        }

    def _usuario_federado(self, db: Session, email: str) -> Usuario:
        email = _normalizar_email(email)
        usuario = db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none() if email else None
        if usuario is None:
            logger.warning(f"Inicio de sesión federado de un correo no registrado: {email or '(sin correo)'}.")
            raise CredencialesInvalidasError(
                "Su cuenta institucional no está registrada en Licita. Pida al administrador que la cree.")
        if not usuario.activo:
            logger.warning(f"Inicio de sesión federado de un usuario deshabilitado: {email}.")
            raise CredencialesInvalidasError("El usuario está deshabilitado. Contacte al administrador.")
        return usuario

    def iniciar_sesion_federada(self, email: str) -> dict:
        """
        RF-005 con AUTH_MODE=oidc: el proveedor ya autenticó al usuario; la API comprueba que
        el administrador lo registró y lo mantiene habilitado, y abre una sesión propia.
        """
        secreto = self._secreto()
        with self._fabrica() as db:
            return self._abrir_sesion(db, self._usuario_federado(db, email), secreto)

    def perfil_federado(self, email: str) -> dict:
        """Perfil (rol y permisos) del usuario de un token del proveedor presentado a la API."""
        with self._fabrica() as db:
            return self._perfil(self._usuario_federado(db, email))

    @staticmethod
    def _perfil(usuario: Usuario) -> dict:
        return {
            "user_id": str(usuario.id),
            "email": usuario.email,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "roles": [usuario.rol],
            "permisos": sorted(permisos_de([usuario.rol])),
        }

    def validar(self, token: str, tocar: bool = True) -> dict:
        """
        Perfil del usuario dueño de una sesión vigente. Con tocar=True la solicitud
        cuenta como actividad y renueva el plazo de inactividad.
        """
        secreto = self._secreto()
        try:
            claims = seguridad.leer_token(secreto, token)
        except seguridad.TokenExpiradoError:
            raise SesionInvalidaError("La sesión expiró. Inicie sesión de nuevo.")
        if claims is None:
            raise SesionInvalidaError("Credenciales inválidas o sesión expirada.")

        with self._fabrica() as db:
            sesion = db.get(Sesion, claims["jti"])
            if sesion is None or str(sesion.usuario_id) != claims["sub"]:
                raise SesionInvalidaError("Credenciales inválidas o sesión expirada.")
            if sesion.cerrada_en is not None:
                raise SesionInvalidaError(self._mensaje_cierre(sesion.motivo_cierre))

            momento = seguridad.ahora()
            if sesion.expira_en <= momento:
                self._cerrar(db, sesion, "expirada")
                raise SesionInvalidaError("La sesión expiró. Inicie sesión de nuevo.")
            if momento - sesion.ultimo_uso > timedelta(minutes=self.config.sesion_inactividad_min):
                self._cerrar(db, sesion, "inactividad")
                raise SesionInvalidaError(self._mensaje_cierre("inactividad"))

            usuario = db.get(Usuario, sesion.usuario_id)
            if usuario is None or not usuario.activo:
                self._cerrar(db, sesion, "usuario_deshabilitado")
                raise SesionInvalidaError(self._mensaje_cierre("usuario_deshabilitado"))

            if tocar and momento - sesion.ultimo_uso > _INTERVALO_TOQUE:
                sesion.ultimo_uso = momento
                db.commit()

            perfil = self._perfil(usuario)
            perfil["sesion_id"] = sesion.id
            perfil["sesion_expira_en"] = sesion.expira_en.isoformat() + "Z"
            perfil["inactividad_expira_en"] = (
                sesion.ultimo_uso + timedelta(minutes=self.config.sesion_inactividad_min)
            ).isoformat() + "Z"
            return perfil

    @staticmethod
    def _mensaje_cierre(motivo: Optional[str]) -> str:
        return {
            "cierre_usuario": "La sesión fue cerrada. Inicie sesión de nuevo.",
            "inactividad": "La sesión expiró por inactividad. Inicie sesión de nuevo.",
            "expirada": "La sesión expiró. Inicie sesión de nuevo.",
            "usuario_deshabilitado": "El usuario fue deshabilitado. Contacte al administrador.",
            "clave_cambiada": "La contraseña cambió. Inicie sesión de nuevo.",
        }.get(motivo or "", "La sesión ya no es válida. Inicie sesión de nuevo.")

    @staticmethod
    def _cerrar(db: Session, sesion: Sesion, motivo: str) -> None:
        if sesion.cerrada_en is None:
            sesion.cerrada_en = seguridad.ahora()
            sesion.motivo_cierre = motivo
            db.commit()

    def cerrar_sesion(self, sesion_id: str) -> None:
        with self._fabrica() as db:
            sesion = db.get(Sesion, sesion_id)
            if sesion is not None:
                self._cerrar(db, sesion, "cierre_usuario")

    @staticmethod
    def _cerrar_sesiones_de(db: Session, usuario_id: int, motivo: str) -> int:
        abiertas = db.execute(
            select(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.cerrada_en.is_(None))
        ).scalars().all()
        momento = seguridad.ahora()
        for sesion in abiertas:
            sesion.cerrada_en = momento
            sesion.motivo_cierre = motivo
        return len(abiertas)

    # --- Usuarios (RF-001 a RF-004) ---

    def listar_usuarios(self) -> List[dict]:
        with self._fabrica() as db:
            usuarios = db.execute(select(Usuario).order_by(Usuario.id)).scalars().all()
            return [usuario_a_dict(u) for u in usuarios]

    @property
    def federado(self) -> bool:
        """Con OIDC la credencial vive en el proveedor de identidad (RN-02)."""
        return self.config.auth_mode == "oidc"

    @property
    def clave_opcional(self) -> bool:
        """En modo local con OIDC configurado, un usuario puede entrar solo con su cuenta institucional."""
        return self.federado or self.config.oidc_habilitado

    def crear_usuario(self, nombre: str, email: str, rol: str, clave: Optional[str] = None, activo: bool = True,
                      actor: Optional[str] = None) -> dict:
        email = _normalizar_email(email)
        nombre = (nombre or "").strip()
        if not nombre or "@" not in email:
            raise OperacionNoPermitidaError("Indique un nombre y un correo válido.")
        _validar_rol(rol)
        if not (self.federado or (self.clave_opcional and not clave)):
            seguridad.validar_clave(clave or "")
        with self._fabrica() as db:
            if db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none():
                raise OperacionNoPermitidaError(f"Ya existe un usuario con el correo {email}.")
            usuario = Usuario(
                email=email, nombre=nombre, rol=rol, activo=activo,
                # RN-02: con OIDC no hay contraseña local; la marca no corresponde a ningún hash.
                password_hash=seguridad.hash_clave(clave) if clave and not self.federado else seguridad.SIN_CLAVE_LOCAL,
            )
            db.add(usuario)
            db.flush()
            self.auditoria.registrar_evento(
                f"usuario-{usuario.id}", "USUARIO_CREADO",
                {"usuario_id": usuario.id, "email": email, "nombre": nombre, "rol": rol, "activo": activo},
                registrado_por=actor or "sistema")
            db.commit()
            db.refresh(usuario)
            return usuario_a_dict(usuario)

    def _admins_activos(self, db: Session) -> int:
        return db.execute(
            select(func.count()).select_from(Usuario)
            .where(Usuario.rol == ADMINISTRADOR, Usuario.activo.is_(True))
        ).scalar_one()

    def actualizar_usuario(
        self,
        usuario_id: int,
        actor_id: Optional[str],
        nombre: Optional[str] = None,
        rol: Optional[str] = None,
        activo: Optional[bool] = None,
        actor: Optional[str] = None,
    ) -> dict:
        with self._fabrica() as db:
            usuario = db.get(Usuario, usuario_id)
            if usuario is None:
                raise UsuarioNoEncontradoError("Usuario no encontrado.")
            es_el_mismo = actor_id is not None and str(usuario.id) == str(actor_id)
            deja_de_ser_admin = (
                usuario.rol == ADMINISTRADOR and usuario.activo
                and ((rol is not None and rol != ADMINISTRADOR) or activo is False)
            )
            if deja_de_ser_admin and es_el_mismo:
                raise OperacionNoPermitidaError("No puede quitarse a sí mismo el rol de administrador ni deshabilitarse.")
            if deja_de_ser_admin and self._admins_activos(db) <= 1:
                raise OperacionNoPermitidaError("Debe quedar al menos un administrador activo.")

            antes = {"nombre": usuario.nombre, "rol": usuario.rol, "activo": usuario.activo}
            if nombre is not None and nombre.strip():
                usuario.nombre = nombre.strip()
            if rol is not None:
                _validar_rol(rol)
                usuario.rol = rol
            if activo is not None:
                usuario.activo = activo
                if not activo:
                    # RF-004: las operaciones protegidas se cortan de inmediato.
                    cerradas = self._cerrar_sesiones_de(db, usuario.id, "usuario_deshabilitado")
                    logger.info(f"Usuario {usuario.email} deshabilitado; {cerradas} sesión(es) cerradas.")
            despues = {"nombre": usuario.nombre, "rol": usuario.rol, "activo": usuario.activo}
            cambios = {k: {"antes": antes[k], "despues": despues[k]} for k in antes if antes[k] != despues[k]}
            if cambios:
                # Tabla 61: deshabilitar un usuario queda en la bitácora con los valores modificados.
                self.auditoria.registrar_evento(
                    f"usuario-{usuario.id}", "USUARIO_ACTUALIZADO",
                    {"usuario_id": usuario.id, "email": usuario.email, "cambios": cambios},
                    registrado_por=actor or str(actor_id or "sistema"))
            db.commit()
            db.refresh(usuario)
            return usuario_a_dict(usuario)

    def cambiar_clave(self, usuario_id: int, clave: str, actor: Optional[str] = None) -> None:
        if self.federado:
            raise OperacionNoPermitidaError("Con el proveedor de identidad la contraseña se cambia allí (RN-02).")
        seguridad.validar_clave(clave)
        with self._fabrica() as db:
            usuario = db.get(Usuario, usuario_id)
            if usuario is None:
                raise UsuarioNoEncontradoError("Usuario no encontrado.")
            usuario.password_hash = seguridad.hash_clave(clave)
            cerradas = self._cerrar_sesiones_de(db, usuario.id, "clave_cambiada")
            # Nunca la clave ni su hash: solo quién la cambió y cuántas sesiones se cerraron.
            self.auditoria.registrar_evento(
                f"usuario-{usuario.id}", "CLAVE_CAMBIADA",
                {"usuario_id": usuario.id, "email": usuario.email, "sesiones_cerradas": cerradas},
                registrado_por=actor or "sistema")
            db.commit()

    def asegurar_admin_inicial(self) -> None:
        """
        Modo local: crea el administrador de ADMIN_EMAIL/ADMIN_PASSWORD si no hay usuarios.
        Modo oidc: registra ADMIN_EMAIL como administrador si ese correo aún no existe, también
        cuando ya hay usuarios locales (paso de local a oidc: los correos locales no están en el
        proveedor). Un usuario existente no se modifica, ni siquiera si está deshabilitado.
        """
        if self.federado and self.config.admin_email:
            with self._fabrica() as db:
                existe = db.execute(select(Usuario.id).where(
                    Usuario.email == _normalizar_email(self.config.admin_email))).first() is not None
            if not existe:
                # RN-02: el administrador entra con su cuenta institucional, sin contraseña local.
                self.crear_usuario(self.config.admin_nombre, self.config.admin_email, ADMINISTRADOR,
                                   actor="configuración (ADMIN_EMAIL)")
                logger.info(f"Administrador registrado: {self.config.admin_email} (inicia sesión con el proveedor).")
            return
        with self._fabrica() as db:
            hay_usuarios = db.execute(select(func.count()).select_from(Usuario)).scalar_one() > 0
        if hay_usuarios:
            return
        if not (self.config.admin_email and self.config.admin_password):
            logger.warning(
                "No hay usuarios registrados. Defina ADMIN_EMAIL y ADMIN_PASSWORD en el .env para "
                "crear el administrador inicial, o use: python -m scripts.crear_usuario"
            )
            return
        self.crear_usuario(self.config.admin_nombre, self.config.admin_email, ADMINISTRADOR, self.config.admin_password)
        logger.info(f"Administrador inicial creado: {self.config.admin_email}.")


_servicio: Optional[ServicioIdentidad] = None


def obtener_servicio_identidad() -> ServicioIdentidad:
    global _servicio
    if _servicio is None:
        _servicio = ServicioIdentidad()
    return _servicio
