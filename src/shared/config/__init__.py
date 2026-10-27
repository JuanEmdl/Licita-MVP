"""
Configuración central del sistema.
Todas las variables de entorno se leen aquí para que ningún módulo fije valores
por su cuenta (deployment del modelo, versión de API, umbrales, etc.).
"""
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional

from dotenv import load_dotenv

# En desarrollo local carga el .env; en Docker/Azure las variables ya vienen del entorno
# y load_dotenv no las sobrescribe. Las pruebas automatizadas fijan CARGAR_DOTENV=0
# (tests/conftest.py) para no leer jamás las credenciales reales del .env.
if os.getenv("CARGAR_DOTENV", "1").strip() != "0":
    load_dotenv()


def _leer(nombre: str, defecto: str = "") -> str:
    # strip() evita que un espacio al final del .env quede como parte del valor.
    return os.getenv(nombre, defecto).strip()


def _lista(nombre: str, defecto: str) -> List[str]:
    return [v.strip() for v in _leer(nombre, defecto).split(",") if v.strip()]


def normalizar_endpoint_azure(url: str) -> str:
    """
    Deja solo la raíz del recurso (https://<recurso>.openai.azure.com o
    https://<recurso>.services.ai.azure.com). Azure AI Foundry muestra también el
    endpoint del proyecto (…/api/projects/<proyecto>); con ese, la API de Azure
    OpenAI responde "API version not supported" sea cual sea la versión.
    """
    url = url.strip().rstrip("/")
    url = re.sub(r"/api/projects/[^?#]*$", "", url)
    return re.sub(r"/openai(/v1)?$", "", url)


def _temperatura(nombre: str, defecto: str) -> Optional[float]:
    valor = _leer(nombre, defecto)
    return float(valor) if valor else None


@dataclass(frozen=True)
class Configuracion:
    # --- Base de datos (DA-05) ---
    db_connection_string: str = field(
        default_factory=lambda: _leer(
            "DB_CONNECTION_STRING", "postgresql://user:password@localhost:5432/licitaciones"
        )
    )

    # --- API ---
    api_url: str = field(default_factory=lambda: _leer("API_URL", "http://localhost:8000"))
    cors_origins: List[str] = field(
        default_factory=lambda: _lista("CORS_ORIGINS", "http://localhost:8080")
    )

    # --- Cola de trabajo (ASR-11) ---
    service_bus_connection_string: str = field(
        default_factory=lambda: _leer("SERVICE_BUS_CONNECTION_STRING")
    )
    service_bus_queue_name: str = field(
        default_factory=lambda: _leer("SERVICE_BUS_QUEUE_NAME", "analisis-licitaciones")
    )

    # --- Modelo de lenguaje (DA-07) ---
    azure_openai_endpoint: str = field(default_factory=lambda: _leer("AZURE_OPENAI_ENDPOINT"))
    # Endpoint tal como vino en el .env, solo para avisar si hubo que corregirlo.
    azure_openai_endpoint_original: str = field(default_factory=lambda: _leer("AZURE_OPENAI_ENDPOINT"))
    azure_openai_api_key: str = field(default_factory=lambda: _leer("AZURE_OPENAI_API_KEY"))
    azure_openai_deployment: str = field(
        default_factory=lambda: _leer("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    )
    azure_openai_api_version: str = field(
        default_factory=lambda: _leer("AZURE_OPENAI_API_VERSION", "2024-10-21")
    )
    azure_openai_embedding_deployment: str = field(
        default_factory=lambda: _leer("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    )
    # Tiempo máximo por llamada al modelo. Sin él, una llamada colgada bloquea la tarea.
    llm_timeout_s: float = field(default_factory=lambda: float(_leer("LLM_TIMEOUT_S", "120")))
    # Llamadas simultáneas al modelo dentro de una tarea: fragmentos al extraer y requisitos al
    # evaluar (RNF-001). Más paralelismo acorta el análisis y concentra el consumo (apartado 2.12).
    analisis_paralelismo: int = field(default_factory=lambda: max(1, int(_leer("ANALISIS_PARALELISMO", "4"))))
    # --- Pasarela del modelo: cuota, anonimización y disyuntor (DA-07) ---
    # Tokens (entrada + salida) permitidos por periodo mensual (RF-028, ASR-13). 0 = sin límite.
    cuota_tokens_periodo: int = field(default_factory=lambda: int(_leer("CUOTA_TOKENS_PERIODO", "5000000")))
    # Porcentaje de la cuota a partir del cual se alerta (Tabla 49).
    cuota_alerta_porcentaje: float = field(default_factory=lambda: float(_leer("CUOTA_ALERTA_PORCENTAJE", "80")))
    # Términos que nunca salen hacia el proveedor (ASR-05): nombre de la fábrica, clientes, personas…
    anonimizacion_terminos: List[str] = field(default_factory=lambda: _lista("ANONIMIZACION_TERMINOS", ""))
    # Fallas transitorias seguidas que abren el disyuntor y segundos que permanece abierto (ASR-07).
    disyuntor_fallas: int = field(default_factory=lambda: int(_leer("DISYUNTOR_FALLAS", "5")))
    disyuntor_espera_s: float = field(default_factory=lambda: float(_leer("DISYUNTOR_ESPERA_S", "60")))
    # Entregas de un mensaje antes de darlo por fallido (igual al MaxDeliveryCount de la cola).
    service_bus_max_entregas: int = field(default_factory=lambda: int(_leer("SERVICE_BUS_MAX_ENTREGAS", "10")))
    # Telemetría (RF-043): sin cadena de conexión no se exporta nada.
    applicationinsights_connection_string: str = field(
        default_factory=lambda: _leer("APPLICATIONINSIGHTS_CONNECTION_STRING"))
    # Vacía = no se envía. Los modelos de razonamiento (gpt-5*, o1, o3, o4) solo aceptan la
    # predeterminada y la pasarela la omite con ellos aunque aquí haya un valor.
    llm_temperatura: Optional[float] = field(default_factory=lambda: _temperatura("LLM_TEMPERATURA", "0"))

    # --- SECOP II / Datos Abiertos (ASR-03) ---
    secop_base_url: str = field(
        default_factory=lambda: _leer("SECOP_BASE_URL", "https://www.datos.gov.co/resource/p6dx-8zbt.json")
    )
    # Token de aplicación de Socrata (X-App-Token). Sin él la API funciona, con menor cuota.
    socrata_app_token: str = field(default_factory=lambda: _leer("SOCRATA_APP_TOKEN"))
    # El secreto solo se usa para operaciones autenticadas de Socrata; las lecturas no lo envían.
    socrata_app_secret: str = field(default_factory=lambda: _leer("SOCRATA_APP_SECRET"))
    # Conjunto de Datos Abiertos con los archivos de cada proceso (RF-011).
    secop_documentos_url: str = field(
        default_factory=lambda: _leer("SECOP_DOCUMENTOS_URL", "https://www.datos.gov.co/resource/dmgg-8hin.json")
    )
    # false = no se intenta descargar: los documentos quedan como faltantes para la carga manual.
    secop_descargar_documentos: bool = field(
        default_factory=lambda: _leer("SECOP_DESCARGAR_DOCUMENTOS", "true").lower() in ("1", "true", "si", "sí"))

    # --- Expediente documental (RF-021, RF-022) ---
    expedientes_dir: str = field(default_factory=lambda: _leer("EXPEDIENTES_DIR", "data/expedientes"))
    # Tamaño máximo de cada archivo del expediente, descargado o cargado a mano.
    expediente_max_mb: int = field(default_factory=lambda: int(_leer("EXPEDIENTE_MAX_MB", "25")))

    # --- Vigilancia de oportunidades (lectura automática de SECOP II) ---
    # Días hacia atrás que revisa cada barrido.
    vigilancia_dias: int = field(default_factory=lambda: int(_leer("VIGILANCIA_DIAS", "7")))
    # Afinidad mínima (0-100) para registrar un proceso como alerta.
    vigilancia_umbral: float = field(default_factory=lambda: float(_leer("VIGILANCIA_UMBRAL", "30")))
    # Minutos entre barridos cuando el worker corre en modo continuo (0 = un solo barrido).
    vigilancia_intervalo_min: int = field(default_factory=lambda: int(_leer("VIGILANCIA_INTERVALO_MIN", "0")))
    # Máximo de procesos que se descargan por barrido.
    vigilancia_max_procesos: int = field(default_factory=lambda: int(_leer("VIGILANCIA_MAX_PROCESOS", "500")))
    # Horas tras las cuales los datos se muestran como desactualizados si no hubo una
    # sincronización exitosa (HU-04 CA-04).
    vigilancia_vigencia_horas: int = field(default_factory=lambda: int(_leer("VIGILANCIA_VIGENCIA_HORAS", "26")))

    # --- Notificaciones por correo (RF-016, RF-017, RF-020; SMTP/TLS según el documento) ---
    # Sin SMTP_HOST las notificaciones quedan solo en la aplicación.
    smtp_host: str = field(default_factory=lambda: _leer("SMTP_HOST"))
    smtp_puerto: int = field(default_factory=lambda: int(_leer("SMTP_PUERTO", "587")))
    # starttls (puerto 587), ssl (puerto 465) o ninguna (solo para un servidor de pruebas local).
    smtp_seguridad: str = field(default_factory=lambda: _leer("SMTP_SEGURIDAD", "starttls").lower())
    smtp_usuario: str = field(default_factory=lambda: _leer("SMTP_USUARIO"))
    smtp_clave: str = field(default_factory=lambda: _leer("SMTP_CLAVE"))
    smtp_remitente: str = field(default_factory=lambda: _leer("SMTP_REMITENTE"))
    # Hora local (0-23) a partir de la cual sale el resumen diario y desfase horario (Colombia: -5).
    notificaciones_hora_resumen: int = field(default_factory=lambda: int(_leer("NOTIFICACIONES_HORA_RESUMEN", "7")))
    notificaciones_utc_offset: int = field(
        default_factory=lambda: int(_leer("NOTIFICACIONES_UTC_OFFSET") or _leer("UTC_OFFSET", "-5")))
    # Desfase de la hora local respecto de UTC para mostrar fechas (Colombia: -5). La base guarda UTC.
    utc_offset: int = field(default_factory=lambda: int(_leer("UTC_OFFSET", "-5")))
    # Intentos de envío de un correo antes de dejarlo solo en la aplicación (Tabla 16).
    notificaciones_max_intentos: int = field(default_factory=lambda: int(_leer("NOTIFICACIONES_MAX_INTENTOS", "5")))
    # Dirección de la interfaz para los enlaces de los correos.
    webui_url: str = field(default_factory=lambda: _leer("WEBUI_URL", "http://localhost:8080").rstrip("/"))

    # --- Informes (RF-016) ---
    informes_dir: str = field(default_factory=lambda: _leer("INFORMES_DIR", "data/informes"))
    # Contenedor de Blob Storage con política de inmutabilidad (DA-06). Vacío: solo INFORMES_DIR.
    almacen_informes_url: str = field(default_factory=lambda: _leer("ALMACEN_INFORMES_URL"))

    # --- Reglas de recomendación (DA-09) ---
    umbral_ofertar: float = field(default_factory=lambda: float(_leer("UMBRAL_OFERTAR", "80")))
    umbral_revision: float = field(default_factory=lambda: float(_leer("UMBRAL_REVISION", "50")))

    # --- Identidad (DA-10) ---
    # local: usuarios y sesiones propios (inicio de sesión con correo y contraseña).
    # oidc: JWT de Entra ID. desarrollo: un token fijo sin usuarios (solo pruebas).
    auth_mode: str = field(default_factory=lambda: _leer("AUTH_MODE", "local").lower())
    oidc_authority: str = field(default_factory=lambda: _leer("OIDC_AUTHORITY").rstrip("/"))
    oidc_client_id: str = field(default_factory=lambda: _leer("OIDC_CLIENT_ID"))
    # La interfaz es un cliente confidencial (DA-10): canjea el código con este secreto.
    oidc_client_secret: str = field(default_factory=lambda: _leer("OIDC_CLIENT_SECRET"))
    # Vacía = WEBUI_URL + /auth/callback. Debe estar registrada tal cual en el proveedor.
    oidc_redirect_uri: str = field(default_factory=lambda: _leer("OIDC_REDIRECT_URI"))
    oidc_scopes: str = field(default_factory=lambda: _leer("OIDC_SCOPES", "openid profile email"))
    # true: al cerrar sesión en Licita también se cierra en el proveedor de identidad.
    oidc_cerrar_en_proveedor: bool = field(
        default_factory=lambda: _leer("OIDC_CERRAR_EN_PROVEEDOR", "true").lower() in ("1", "true", "si", "sí"))
    api_token_desarrollo: str = field(default_factory=lambda: _leer("API_TOKEN_DESARROLLO"))

    # --- Sesiones (modo local, RF-005 a RF-007, RNF-010) ---
    # Clave HS256 con la que la API firma los tokens de sesión.
    sesion_secreto: str = field(default_factory=lambda: _leer("SESION_SECRETO"))
    # Vigencia máxima de una sesión aunque haya actividad.
    sesion_duracion_min: int = field(default_factory=lambda: int(_leer("SESION_DURACION_MIN", "480")))
    # La sesión expira si pasa este tiempo sin solicitudes a la API.
    sesion_inactividad_min: int = field(default_factory=lambda: int(_leer("SESION_INACTIVIDAD_MIN", "30")))
    # Intentos fallidos de inicio de sesión antes de bloquear temporalmente la cuenta.
    login_max_intentos: int = field(default_factory=lambda: int(_leer("LOGIN_MAX_INTENTOS", "5")))
    login_bloqueo_min: int = field(default_factory=lambda: int(_leer("LOGIN_BLOQUEO_MIN", "5")))
    # Administrador inicial: se crea al arrancar solo si no existe ningún usuario.
    admin_email: str = field(default_factory=lambda: _leer("ADMIN_EMAIL").lower())
    admin_password: str = field(default_factory=lambda: _leer("ADMIN_PASSWORD"))
    admin_nombre: str = field(default_factory=lambda: _leer("ADMIN_NOMBRE", "Administrador"))

    def __post_init__(self):
        # frozen=True: object.__setattr__ es la forma de normalizar dentro del constructor.
        object.__setattr__(self, "azure_openai_endpoint", normalizar_endpoint_azure(self.azure_openai_endpoint))

    @property
    def usa_service_bus(self) -> bool:
        return bool(self.service_bus_connection_string)

    @property
    def oidc_habilitado(self) -> bool:
        """
        Inicio con la cuenta institucional disponible: siempre en AUTH_MODE=oidc y, en local, cuando
        el App Registration está configurado (entonces conviven ambos inicios de sesión).
        """
        configurado = bool(self.oidc_authority and self.oidc_client_id and self.oidc_client_secret)
        return self.auth_mode == "oidc" or (self.auth_mode == "local" and configurado)

    @property
    def oidc_redirect(self) -> str:
        return self.oidc_redirect_uri or f"{self.webui_url}/auth/callback"

    @property
    def correo_configurado(self) -> bool:
        return bool(self.smtp_host and self.smtp_remitente)

    @property
    def llm_configurado(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    def diagnostico(self, componente: str) -> List[str]:
        """
        Advertencias de configuración para el componente indicado ("api", "worker").
        Solo nombra variables: nunca incluye sus valores.
        """
        avisos: List[str] = []
        if componente in ("api", "worker") and not self.db_connection_string:
            avisos.append("DB_CONNECTION_STRING está vacía.")
        if componente == "api":
            if self.auth_mode == "desarrollo" and not self.api_token_desarrollo:
                avisos.append("AUTH_MODE=desarrollo sin API_TOKEN_DESARROLLO: la API rechazará todo.")
            if self.auth_mode == "oidc" and not (self.oidc_authority and self.oidc_client_id):
                avisos.append("AUTH_MODE=oidc sin OIDC_AUTHORITY u OIDC_CLIENT_ID: la API rechazará todo.")
            if self.auth_mode == "oidc" and len(self.sesion_secreto) < 32:
                avisos.append("AUTH_MODE=oidc requiere SESION_SECRETO de al menos 32 caracteres: la API "
                              "emite su propia sesión tras validar al usuario en el proveedor.")
            if self.auth_mode == "local" and len(self.sesion_secreto) < 32:
                avisos.append("AUTH_MODE=local requiere SESION_SECRETO de al menos 32 caracteres: la API rechazará todo.")
            if self.auth_mode not in ("local", "oidc", "desarrollo"):
                avisos.append(f"AUTH_MODE='{self.auth_mode}' no es válido (use local, oidc o desarrollo).")
        if componente == "worker" or (componente == "api" and not self.usa_service_bus):
            if not self.llm_configurado:
                avisos.append(
                    "AZURE_OPENAI_ENDPOINT o AZURE_OPENAI_API_KEY vacías: la extracción y la "
                    "evaluación fallarán (estado Fallida)."
                )
        if self.azure_openai_endpoint_original.rstrip("/") not in ("", self.azure_openai_endpoint):
            avisos.append(
                "AZURE_OPENAI_ENDPOINT apunta a un proyecto o ruta de Azure AI Foundry; se usa la raíz "
                f"del recurso ({self.azure_openai_endpoint}). Conviene corregirlo en el .env."
            )
        if self.umbral_revision > self.umbral_ofertar:
            avisos.append("UMBRAL_REVISION es mayor que UMBRAL_OFERTAR.")
        return avisos

    def registrar_diagnostico(self, componente: str) -> None:
        log = logging.getLogger("configuracion")
        avisos = self.diagnostico(componente)
        for aviso in avisos:
            log.warning(aviso)
        log.info(
            f"Configuración [{componente}]: AUTH_MODE={self.auth_mode}, "
            f"cola={'Service Bus' if self.usa_service_bus else 'en proceso (desarrollo)'}, "
            f"modelo={'configurado' if self.llm_configurado else 'NO configurado'}, "
            f"deployment={self.azure_openai_deployment}, api_version={self.azure_openai_api_version}"
        )


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()
