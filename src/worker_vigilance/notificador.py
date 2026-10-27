"""
Notificador (Figura 11): compone y envía las alertas por el canal y la frecuencia que
cada usuario configuró (RF-016, RF-017, RF-020).

- El aviso ya está en la aplicación cuando el notificador corre; el correo es el canal
  adicional. Una falla del servicio de correo se reintenta en las siguientes ejecuciones
  hasta NOTIFICACIONES_MAX_INTENTOS; después el aviso queda solo en la aplicación
  (Tabla 16). Nada de esto detiene un barrido ni un análisis.
- Frecuencia inmediata: un correo por aviso. Resumen diario: un único correo con todos los
  avisos pendientes, a partir de NOTIFICACIONES_HORA_RESUMEN (hora local), una vez al día
  (HU-04 CA-03).
- El correo sale por SMTP con TLS (STARTTLS o SSL), como indica el documento.
"""
import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Dict, List, Optional

from src.shared.config import Configuracion, obtener_configuracion
from src.shared.notificaciones_repo import Frecuencia, RepositorioNotificaciones, TipoNotificacion

logger = logging.getLogger(__name__)

PIE = ("Recibes este aviso por tus preferencias de notificación en Licita (pantalla «Perfiles de búsqueda»). "
       "Las notificaciones también están disponibles en la aplicación.")


class EnviadorCorreo:
    """Envía un correo por SMTP. Sin SMTP_HOST ni SMTP_REMITENTE no está configurado."""

    def __init__(self, config: Optional[Configuracion] = None):
        self.config = config or obtener_configuracion()

    @property
    def configurado(self) -> bool:
        return self.config.correo_configurado

    def enviar(self, destinatario: str, asunto: str, texto: str) -> None:
        c = self.config
        mensaje = EmailMessage()
        mensaje["From"] = c.smtp_remitente
        mensaje["To"] = destinatario
        mensaje["Subject"] = asunto
        mensaje.set_content(texto)
        contexto = ssl.create_default_context()
        if c.smtp_seguridad == "ssl":
            servidor = smtplib.SMTP_SSL(c.smtp_host, c.smtp_puerto, timeout=20, context=contexto)
        else:
            servidor = smtplib.SMTP(c.smtp_host, c.smtp_puerto, timeout=20)
        with servidor:
            if c.smtp_seguridad == "starttls":
                servidor.starttls(context=contexto)
            if c.smtp_usuario:
                servidor.login(c.smtp_usuario, c.smtp_clave)
            servidor.send_message(mensaje)


def texto_aviso(n: dict, webui_url: str) -> str:
    lineas = [n["titulo"], "", n["cuerpo"]]
    if n.get("enlace"):
        lineas += ["", f"Ver en SECOP II: {n['enlace']}"]
    lineas += [f"Abrir Licita: {webui_url}", "", PIE]
    return "\n".join(lineas)


def texto_resumen(notificaciones: List[dict], webui_url: str) -> str:
    """Un único envío consolidado, agrupado por tipo de aviso (HU-04 CA-03)."""
    grupos: Dict[str, List[dict]] = {}
    for n in notificaciones:
        grupos.setdefault(n["tipo"], []).append(n)
    lineas = [f"Resumen diario de Licita: {len(notificaciones)} avisos.", ""]
    orden = [TipoNotificacion.OPORTUNIDAD, TipoNotificacion.NOVEDAD, TipoNotificacion.REVISION,
             TipoNotificacion.SUSPENSION]
    for tipo in sorted(grupos, key=lambda t: orden.index(t) if t in orden else len(orden)):
        lineas.append(f"== {tipo} ({len(grupos[tipo])}) ==")
        for n in grupos[tipo]:
            lineas.append(f"* {n['titulo']}")
            lineas += [f"  {linea}" for linea in n["cuerpo"].splitlines()]
            if n.get("enlace"):
                lineas.append(f"  {n['enlace']}")
        lineas.append("")
    lineas += [f"Abrir Licita: {webui_url}", "", PIE]
    return "\n".join(lineas)


class Notificador:

    def __init__(self, repositorio: Optional[RepositorioNotificaciones] = None,
                 enviador: Optional[EnviadorCorreo] = None, config: Optional[Configuracion] = None):
        self.config = config or obtener_configuracion()
        self.repositorio = repositorio or RepositorioNotificaciones()
        self.enviador = enviador or EnviadorCorreo(self.config)

    def _hora_local(self, momento: datetime) -> datetime:
        return momento + timedelta(hours=self.config.notificaciones_utc_offset)

    def resumen_vencido(self, ultimo: Optional[datetime], ahora: datetime) -> bool:
        local = self._hora_local(ahora)
        if local.hour < self.config.notificaciones_hora_resumen:
            return False
        return ultimo is None or self._hora_local(ultimo).date() < local.date()

    def _enviar(self, destinatario: str, asunto: str, texto: str, ids: List[int]) -> bool:
        try:
            self.enviador.enviar(destinatario, asunto, texto)
        except Exception as e:
            # El aviso sigue en la aplicación; se reintenta en la siguiente ejecución.
            logger.warning(f"No se pudo enviar el correo a {destinatario}: {type(e).__name__}: {e}")
            self.repositorio.registrar_envio(ids, error=f"{type(e).__name__}: {e}")
            return False
        self.repositorio.registrar_envio(ids)
        return True

    def enviar_pendientes(self, ahora: Optional[datetime] = None) -> dict:
        resultado = {"correo_configurado": self.enviador.configurado, "enviados": 0, "fallidos": 0,
                     "resumenes": 0, "en_espera": 0}
        if not self.enviador.configurado:
            return resultado
        ahora = ahora or datetime.utcnow()
        url = self.config.webui_url
        for destinatario, grupo in self.repositorio.pendientes_de_correo(
                self.config.notificaciones_max_intentos).items():
            avisos = grupo["notificaciones"]
            if "@" not in destinatario:
                continue
            if grupo["frecuencia"] == Frecuencia.RESUMEN_DIARIO:
                if not self.resumen_vencido(grupo["ultimo_resumen_en"], ahora):
                    resultado["en_espera"] += len(avisos)
                    continue
                if self._enviar(destinatario, f"Licita · Resumen diario: {len(avisos)} avisos",
                                texto_resumen(avisos, url), [n["id"] for n in avisos]):
                    self.repositorio.marcar_resumen(destinatario, ahora)
                    resultado["resumenes"] += 1
                    resultado["enviados"] += len(avisos)
                else:
                    resultado["fallidos"] += len(avisos)
                continue
            for n in avisos:
                if self._enviar(destinatario, f"Licita · {n['titulo']}", texto_aviso(n, url), [n["id"]]):
                    resultado["enviados"] += 1
                else:
                    resultado["fallidos"] += 1
        if resultado["enviados"] or resultado["fallidos"]:
            logger.info(f"Notificador: {resultado}")
        return resultado


class AvisosAnalisis:
    """
    El trabajador de análisis avisa al analista cuando su análisis espera la revisión de
    requisitos o queda suspendido (Figura 9 y vista de contenedores: "Notifica revisión pendiente").
    """

    def __init__(self, repositorio: Optional[RepositorioNotificaciones] = None,
                 notificador: Optional[Notificador] = None):
        self.repositorio = repositorio or RepositorioNotificaciones()
        self.notificador = notificador or Notificador(self.repositorio)

    def _destinatarios(self, tarea: dict) -> List[str]:
        """Quien solicitó el análisis y el analista responsable de la oportunidad."""
        destinatarios = [tarea.get("solicitado_por"), self.repositorio.responsable_de(tarea.get("licitacion_id"))]
        return [d for d in dict.fromkeys(destinatarios) if d and d != "desconocido"]

    def avisar(self, tarea: dict, estado: str, motivo: Optional[str] = None) -> None:
        tarea_id = tarea["tarea_id"]
        proceso = tarea.get("licitacion_id") or ""
        if estado == "Esperando revisión":
            tipo, clave = TipoNotificacion.REVISION, f"revision:{tarea_id}"
            titulo = f"Requisitos listos para revisar · {proceso}"
            cuerpo = ("El agente extractor terminó. El análisis está detenido hasta que un analista revise y "
                      f"apruebe la lista de requisitos (tarea {tarea_id[:8]}).")
        else:
            tipo = TipoNotificacion.SUSPENSION
            clave = f"suspension:{tarea_id}:{datetime.utcnow():%Y%m%d%H%M}"
            titulo = f"Análisis suspendido · {proceso}"
            cuerpo = f"La tarea {tarea_id[:8]} quedó suspendida. {motivo or ''}".strip()
        try:
            for destinatario in self._destinatarios(tarea):
                self.repositorio.crear(destinatario, tipo, clave, titulo, cuerpo, id_proceso=proceso, tarea_id=tarea_id)
            self.notificador.enviar_pendientes()
        except Exception as e:
            # Tabla 16: ningún análisis se detiene porque falle un aviso.
            logger.warning(f"No se pudo avisar el estado de la tarea {tarea_id}: {type(e).__name__}: {e}")
