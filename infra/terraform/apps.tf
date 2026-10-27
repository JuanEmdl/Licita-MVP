# apps.tf - Unidades de despliegue sobre Azure Container Apps (DA-01, DA-12, Anexo G.4).
# Las variables de entorno son las que lee src/shared/config; los secretos llegan por
# referencia a Key Vault con la identidad administrada (ASR-05).

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.nombre}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  tags                       = local.etiquetas
}

# Expediente documental compartido por la API, el trabajador y la vigilancia.
resource "azurerm_container_app_environment_storage" "expedientes" {
  name                         = "expedientes"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.st.name
  share_name                   = azurerm_storage_share.expedientes.name
  access_key                   = azurerm_storage_account.st.primary_access_key
  access_mode                  = "ReadWrite"
}

locals {
  nombre_web = "ca-web-${var.entorno}"
  nombre_api = "ca-api-${var.entorno}"
  url_web    = "https://${local.nombre_web}.${azurerm_container_app_environment.env.default_domain}"
  # Dentro del entorno, una aplicación con ingreso interno se alcanza por su nombre.
  url_api = "http://${local.nombre_api}"

  variables_comunes = {
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.appi.connection_string
    AUTH_MODE                             = var.auth_mode
    OIDC_AUTHORITY                        = var.oidc_authority
    OIDC_CLIENT_ID                        = var.oidc_client_id
    ADMIN_EMAIL                           = var.admin_email
    WEBUI_URL                             = local.url_web
    UTC_OFFSET                            = "-5"
    # DefaultAzureCredential usa la identidad asignada por el usuario (almacén de informes).
    AZURE_CLIENT_ID = azurerm_user_assigned_identity.app.client_id
  }
  variables_backend = {
    SERVICE_BUS_QUEUE_NAME            = azurerm_servicebus_queue.trabajos.name
    SERVICE_BUS_MAX_ENTREGAS          = tostring(var.max_entregas_mensaje)
    AZURE_OPENAI_ENDPOINT             = local.openai_endpoint
    AZURE_OPENAI_DEPLOYMENT           = var.modelo_chat.nombre
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = var.modelo_embeddings.nombre
    CUOTA_TOKENS_PERIODO              = tostring(var.cuota_tokens_periodo)
    EXPEDIENTES_DIR                   = "/app/data/expedientes"
    INFORMES_DIR                      = "/app/data/informes"
    ALMACEN_INFORMES_URL              = "${azurerm_storage_account.st.primary_blob_endpoint}${azurerm_storage_container.informes.name}"
  }
  variables_correo = {
    SMTP_HOST      = var.smtp.host
    SMTP_PUERTO    = tostring(var.smtp.puerto)
    SMTP_USUARIO   = var.smtp.usuario
    SMTP_REMITENTE = var.smtp.remitente
    SMTP_SEGURIDAD = var.smtp.seguridad
  }

  # Variable de entorno => secreto de Key Vault, por unidad. Solo los que existen.
  secretos_por_app = {
    web        = { SESION_SECRETO = "sesion-secreto", OIDC_CLIENT_SECRET = "oidc-secreto" }
    api        = { DB_CONNECTION_STRING = "db-conexion", SERVICE_BUS_CONNECTION_STRING = "service-bus-conexion", SESION_SECRETO = "sesion-secreto", AZURE_OPENAI_API_KEY = "openai-clave", OIDC_CLIENT_SECRET = "oidc-secreto" }
    worker     = { DB_CONNECTION_STRING = "db-conexion", SERVICE_BUS_CONNECTION_STRING = "service-bus-conexion", AZURE_OPENAI_API_KEY = "openai-clave" }
    vigilancia = { DB_CONNECTION_STRING = "db-conexion", SMTP_CLAVE = "smtp-clave" }
  }
  secretos_app = { for app, mapa in local.secretos_por_app :
  app => { for variable, secreto in mapa : variable => secreto if contains(local.nombres_secretos, secreto) } }
}

# Interfaz web: afinidad de sesión porque NiceGUI guarda estado por usuario (DA-13).
resource "azurerm_container_app" "web" {
  name                         = local.nombre_web
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.web))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2
    container {
      name   = "web"
      image  = var.imagen_web
      cpu    = 0.25
      memory = "0.5Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, { API_URL = local.url_api })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.web
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}

# El proveedor azurerm no expone la afinidad de sesión del ingreso: se fija con la CLI,
# que la canalización ya usa, cada vez que se recrea la aplicación.
resource "terraform_data" "afinidad_web" {
  triggers_replace = azurerm_container_app.web.id
  provisioner "local-exec" {
    command = "az containerapp ingress sticky-sessions set --name ${azurerm_container_app.web.name} --resource-group ${azurerm_resource_group.rg.name} --affinity sticky"
  }
}

# API: siempre una réplica activa para sostener la respuesta 202 de ASR-11.
resource "azurerm_container_app" "api" {
  name                         = local.nombre_api
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.api))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  ingress {
    external_enabled = false
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3
    container {
      name   = "api"
      image  = var.imagen_api
      cpu    = 0.5
      memory = "1Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_backend, { CORS_ORIGINS = local.url_web })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.api
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
      volume_mounts {
        name = "informes"
        path = "/app/data/informes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
    # Copia local de trabajo; el informe emitido vive en Blob Storage inmutable.
    volume {
      name         = "informes"
      storage_type = "EmptyDir"
    }
  }
}

# Trabajador de análisis: escala por longitud de cola, sin tocar código (ASR-08).
resource "azurerm_container_app" "worker" {
  name                         = "ca-worker-${var.entorno}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  revision_mode                = "Single"
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.worker))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  template {
    min_replicas = var.worker_replicas_min
    max_replicas = var.worker_replicas_max

    container {
      name   = "worker"
      image  = var.imagen_worker
      cpu    = 1.0
      memory = "2Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_backend)
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.worker
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
      volume_mounts {
        name = "informes"
        path = "/app/data/informes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
    volume {
      name         = "informes"
      storage_type = "EmptyDir"
    }

    custom_scale_rule {
      name             = "cola-analisis"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = azurerm_servicebus_queue.trabajos.name
        namespace    = azurerm_servicebus_namespace.sb.name
        messageCount = tostring(var.longitud_cola_por_replica)
      }
      authentication {
        secret_name       = "service-bus-conexion"
        trigger_parameter = "connection"
      }
    }
  }
}

# Trabajador de vigilancia: trabajo programado cada hora; cada ejecución hace un barrido,
# envía los avisos pendientes y termina (VIGILANCIA_INTERVALO_MIN=0).
resource "azurerm_container_app_job" "vigilancia" {
  name                         = "caj-vigilancia-${var.entorno}"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  container_app_environment_id = azurerm_container_app_environment.env.id
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 1
  tags                         = local.etiquetas
  depends_on                   = [azurerm_role_assignment.kv_lectura, azurerm_role_assignment.acr_descarga]

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = data.azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = toset(values(local.secretos_app.vigilancia))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.app.id
      key_vault_secret_id = azurerm_key_vault_secret.secretos[secret.value].versionless_id
    }
  }

  schedule_trigger_config {
    cron_expression          = "0 * * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "vigilancia"
      image  = var.imagen_vigilancia
      cpu    = 0.25
      memory = "0.5Gi"
      dynamic "env" {
        for_each = merge(local.variables_comunes, local.variables_correo, {
          EXPEDIENTES_DIR          = "/app/data/expedientes"
          VIGILANCIA_INTERVALO_MIN = "0"
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secretos_app.vigilancia
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      volume_mounts {
        name = "expedientes"
        path = "/app/data/expedientes"
      }
    }
    volume {
      name         = "expedientes"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.expedientes.name
    }
  }
}
