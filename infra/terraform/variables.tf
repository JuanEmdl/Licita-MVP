# variables.tf - Parámetros que cambian entre entornos (Anexo G.2).
# Los valores por entorno viven en entornos/*.tfvars; los secretos se pasan por la
# canalización (TF_VAR_*) y nunca se escriben en estos archivos.

variable "subscription_id" {
  description = "Identificador de la suscripción de Azure de la fábrica de software."
  type        = string
}

variable "entorno" {
  description = "Entorno de despliegue: dev, pruebas o prod."
  type        = string
  validation {
    condition     = contains(["dev", "pruebas", "prod"], var.entorno)
    error_message = "El entorno debe ser dev, pruebas o prod."
  }
}

variable "ubicacion" {
  description = "Región de Azure. Queda parametrizada porque depende de la política de transferencia de datos (Ley 1581 de 2012)."
  type        = string
}

variable "prefijo" {
  description = "Prefijo de nombres de recurso."
  type        = string
  default     = "licita"
}

variable "sku_postgres" {
  description = "Referencia de cómputo del servidor flexible de PostgreSQL."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "almacenamiento_postgres_mb" {
  description = "Almacenamiento aprovisionado para PostgreSQL, en megabytes."
  type        = number
  default     = 32768
}

variable "worker_replicas_min" {
  description = "Réplicas mínimas del trabajador de análisis. Cero permite escalar a cero fuera de uso."
  type        = number
  default     = 0
}

variable "worker_replicas_max" {
  description = "Réplicas máximas del trabajador de análisis."
  type        = number
  default     = 4
}

variable "longitud_cola_por_replica" {
  description = "Mensajes en cola que disparan una réplica adicional (regla KEDA, ASR-08)."
  type        = number
  default     = 5
}

variable "retencion_respaldo_dias" {
  description = "Días de retención del respaldo de PostgreSQL (RPO, ASR-04)."
  type        = number
  default     = 7
}

variable "desplegar_openai" {
  description = "Crea el recurso de Azure OpenAI. En dev suele quedar en false y se reutiliza el de pruebas."
  type        = bool
  default     = true
}

variable "imagen_api" {
  description = "Imagen del contenedor de la API, publicada por la canalización."
  type        = string
}

variable "imagen_web" {
  description = "Imagen del contenedor de la interfaz web."
  type        = string
}

variable "imagen_worker" {
  description = "Imagen del trabajador de análisis."
  type        = string
}

variable "imagen_vigilancia" {
  description = "Imagen del trabajador de vigilancia (docker/worker_vigilance.Dockerfile)."
  type        = string
}

variable "registro" {
  description = "Registro de contenedores existente donde la canalización publica las imágenes."
  type = object({
    nombre = string
    grupo  = string
  })
  default = {
    nombre = "acrlicitacioneslicita01"
    grupo  = "rg-licitaciones-mvp"
  }
}

variable "max_entregas_mensaje" {
  description = "Entregas de un mensaje antes de pasar a la cola de mensajes fallidos (SERVICE_BUS_MAX_ENTREGAS)."
  type        = number
  default     = 10
}

variable "acceso_publico_almacenes" {
  description = "Permite llegar a Key Vault y Storage desde fuera de la red virtual (necesario si la canalización aplica desde un agente hospedado). En prod va en false (C-09)."
  type        = bool
  default     = true
}

# --- Modelo de lenguaje (DA-07) ---

variable "modelo_chat" {
  description = "Despliegue del modelo de chat en Azure OpenAI (AZURE_OPENAI_DEPLOYMENT). La versión debe existir en la región."
  type = object({
    nombre    = string
    version   = string
    capacidad = number
  })
  default = {
    nombre    = "gpt-5-mini"
    version   = "2025-08-07"
    capacidad = 50
  }
}

variable "modelo_embeddings" {
  description = "Despliegue de embeddings (1536 dimensiones, AZURE_OPENAI_EMBEDDING_DEPLOYMENT)."
  type = object({
    nombre    = string
    version   = string
    capacidad = number
  })
  default = {
    nombre    = "text-embedding-3-small"
    version   = "1"
    capacidad = 50
  }
}

variable "azure_openai_endpoint" {
  description = "Endpoint de un Azure OpenAI existente cuando desplegar_openai = false."
  type        = string
  default     = ""
}

variable "azure_openai_clave" {
  description = "Clave del Azure OpenAI existente cuando desplegar_openai = false (TF_VAR_azure_openai_clave)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cuota_tokens_periodo" {
  description = "Tokens permitidos por periodo mensual (RF-028, ASR-13). 0 = sin límite."
  type        = number
  default     = 5000000
}

# --- Identidad (DA-10) ---

variable "auth_mode" {
  description = "oidc en pruebas y producción (RN-02); local solo para demostraciones."
  type        = string
  default     = "oidc"
}

variable "oidc_authority" {
  description = "Autoridad del App Registration, p. ej. https://login.microsoftonline.com/<inquilino>/v2.0."
  type        = string
  default     = ""
}

variable "oidc_client_id" {
  description = "Id. de aplicación (cliente) del App Registration."
  type        = string
  default     = ""
}

variable "oidc_client_secret" {
  description = "Secreto del App Registration (TF_VAR_oidc_client_secret). Se guarda en Key Vault."
  type        = string
  default     = ""
  sensitive   = true
}

variable "admin_email" {
  description = "Correo institucional del primer administrador (ADMIN_EMAIL)."
  type        = string
  default     = ""
}

# --- Correo (RF-016, RF-017, RF-020) ---

variable "smtp" {
  description = "Servidor de correo para las notificaciones. Vacío: solo avisos en la aplicación."
  type = object({
    host      = string
    puerto    = number
    usuario   = string
    remitente = string
    seguridad = string
  })
  default = {
    host      = ""
    puerto    = 587
    usuario   = ""
    remitente = ""
    seguridad = "starttls"
  }
}

variable "smtp_clave" {
  description = "Contraseña del servidor de correo (TF_VAR_smtp_clave). Se guarda en Key Vault."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Observabilidad (Tabla 49) ---

variable "correos_alertas" {
  description = "Correos del equipo técnico que reciben las alertas de la Tabla 49."
  type        = list(string)
  default     = []
}

variable "etiquetas" {
  description = "Etiquetas comunes a todos los recursos."
  type        = map(string)
  default = {
    proyecto = "licita-mvp-multiagente"
    origen   = "terraform"
  }
}
