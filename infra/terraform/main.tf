# main.tf - Recursos del inventario de infraestructura del MVP (apartado 3.28, Anexo G.3).
#
# Diferencias con el Anexo G, para que la infraestructura coincida con el código:
# - Una sola cola (analisis-licitaciones): el tipo de trabajo viaja en el mensaje (Tabla 46).
# - Red virtual con subred delegada para PostgreSQL: con acceso público desactivado, el
#   servidor solo es alcanzable desde las Container Apps (C-09).
# - Los secretos se guardan en Key Vault y las Container Apps los leen por referencia con la
#   identidad administrada; el código los recibe como variables de entorno (ASR-05).
# - El expediente documental vive en un recurso compartido de Azure Files (lo escriben la API
#   y la vigilancia, lo lee el trabajador); los informes, en Blob Storage inmutable (DA-06).

locals {
  nombre     = "${var.prefijo}-${var.entorno}"
  nombre_san = replace("${var.prefijo}${var.entorno}", "-", "")
  # Sufijo para los nombres que deben ser únicos en todo Azure.
  unico     = random_string.sufijo.result
  etiquetas = merge(var.etiquetas, { entorno = var.entorno })
}

resource "random_string" "sufijo" {
  length  = 4
  upper   = false
  special = false
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.nombre}"
  location = var.ubicacion
  tags     = local.etiquetas
}

# --- Identidad administrada: evita credenciales en la configuración (ASR-05) ---

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  tags                = local.etiquetas
}

# --- Observabilidad (RF-043) ---

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.etiquetas
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "web"
  tags                = local.etiquetas
}

# --- Red privada (C-09): las aplicaciones y la base de datos no se exponen ---

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  address_space       = ["10.20.0.0/16"]
  tags                = local.etiquetas
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.0.0/23"]
  service_endpoints    = ["Microsoft.KeyVault", "Microsoft.Storage"]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.20.2.0/24"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "vnet-${local.nombre}"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}

# --- Mensajería: cola de trabajos (DA-04, Tabla 46) ---

resource "azurerm_servicebus_namespace" "sb" {
  name                = "sb-${local.nombre}-${local.unico}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  minimum_tls_version = "1.2"
  tags                = local.etiquetas
}

resource "azurerm_servicebus_queue" "trabajos" {
  name         = "analisis-licitaciones"
  namespace_id = azurerm_servicebus_namespace.sb.id
  # Agotadas las entregas, el mensaje pasa a la cola de mensajes fallidos (ASR-07, C-13).
  max_delivery_count                   = var.max_entregas_mensaje
  lock_duration                        = "PT5M"
  dead_lettering_on_message_expiration = true
}

# El código se conecta con cadena de conexión (azure-servicebus). Manage permite leer la
# longitud de la cola para la métrica de la Tabla 49 y para la regla de escalado.
resource "azurerm_servicebus_namespace_authorization_rule" "app" {
  name         = "licita-app"
  namespace_id = azurerm_servicebus_namespace.sb.id
  listen       = true
  send         = true
  manage       = true
}

# --- Persistencia: PostgreSQL con pgvector (DA-05) ---

resource "random_password" "pg" {
  length = 32
  # Solo caracteres que no hay que escapar en la cadena de conexión.
  special          = true
  override_special = "-_~"
}

resource "azurerm_postgresql_flexible_server" "pg" {
  name                          = "psql-${local.nombre}-${local.unico}"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = "16"
  sku_name                      = var.sku_postgres
  storage_mb                    = var.almacenamiento_postgres_mb
  backup_retention_days         = var.retencion_respaldo_dias
  administrator_login           = "licitaadmin"
  administrator_password        = random_password.pg.result
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  tags                          = local.etiquetas

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  lifecycle {
    # Azure elige la zona de disponibilidad; no se fuerza en cada plan.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "db" {
  name      = "licita"
  server_id = azurerm_postgresql_flexible_server.pg.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# pgvector se habilita como extensión permitida del servidor.
resource "azurerm_postgresql_flexible_server_configuration" "extensiones" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.pg.id
  value     = "VECTOR,PGCRYPTO"
}

# --- Almacenamiento: expediente documental e informes inmutables (DA-06) ---

resource "azurerm_storage_account" "st" {
  name                            = substr("st${local.nombre_san}${local.unico}", 0, 24)
  resource_group_name             = azurerm_resource_group.rg.name
  location                        = azurerm_resource_group.rg.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = local.etiquetas

  network_rules {
    default_action             = var.acceso_publico_almacenes ? "Allow" : "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
}

resource "azurerm_storage_container" "informes" {
  name                  = "informes"
  storage_account_id    = azurerm_storage_account.st.id
  container_access_type = "private"
}

# Política de inmutabilidad de los informes emitidos (ASR-06, C-03): lo escrito no se
# modifica ni se borra durante el periodo. ALMACEN_INFORMES_URL apunta a este contenedor.
resource "azurerm_storage_container_immutability_policy" "informes" {
  storage_container_resource_manager_id = azurerm_storage_container.informes.id
  immutability_period_in_days           = 90
  protected_append_writes_all_enabled   = false
}

# Expediente documental (RF-021, RF-022): montado en /app/data/expedientes.
resource "azurerm_storage_share" "expedientes" {
  name               = "expedientes"
  storage_account_id = azurerm_storage_account.st.id
  quota              = 50
}

# --- Secretos y claves (ASR-05, C-08) ---

data "azurerm_client_config" "actual" {}

resource "azurerm_key_vault" "kv" {
  name                       = substr("kv-${local.nombre}-${local.unico}", 0, 24)
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  tenant_id                  = data.azurerm_client_config.actual.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = var.entorno == "prod"
  soft_delete_retention_days = 7
  tags                       = local.etiquetas

  network_acls {
    default_action             = var.acceso_publico_almacenes ? "Allow" : "Deny"
    bypass                     = "AzureServices"
    virtual_network_subnet_ids = [azurerm_subnet.apps.id]
  }
}

# Quien aplica Terraform (la canalización) escribe los secretos; la aplicación solo los lee.
resource "azurerm_role_assignment" "kv_escritura_despliegue" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.actual.object_id
}

resource "random_password" "sesion" {
  length  = 48
  special = false
}

locals {
  openai_endpoint = var.desplegar_openai ? azurerm_cognitive_account.openai[0].endpoint : var.azure_openai_endpoint
  openai_clave    = var.desplegar_openai ? azurerm_cognitive_account.openai[0].primary_access_key : var.azure_openai_clave

  # Nombre del secreto en Key Vault => valor. Los opcionales se crean solo si se configuraron;
  # la lista de nombres no depende de valores sensibles para poder usarla en for_each.
  valores_secretos = {
    "postgres-admin-password" = random_password.pg.result
    "db-conexion"             = "postgresql://licitaadmin:${random_password.pg.result}@${azurerm_postgresql_flexible_server.pg.fqdn}:5432/${azurerm_postgresql_flexible_server_database.db.name}?sslmode=require"
    "service-bus-conexion"    = azurerm_servicebus_namespace_authorization_rule.app.primary_connection_string
    "sesion-secreto"          = random_password.sesion.result
    "openai-clave"            = local.openai_clave
    "oidc-secreto"            = var.oidc_client_secret
    "smtp-clave"              = var.smtp_clave
  }
  nombres_secretos = concat(
    ["postgres-admin-password", "db-conexion", "service-bus-conexion", "sesion-secreto"],
    var.desplegar_openai || var.azure_openai_endpoint != "" ? ["openai-clave"] : [],
    var.oidc_client_id != "" ? ["oidc-secreto"] : [],
    var.smtp.host != "" ? ["smtp-clave"] : [],
  )
}

resource "azurerm_key_vault_secret" "secretos" {
  for_each     = toset(local.nombres_secretos)
  name         = each.value
  value        = local.valores_secretos[each.value]
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [azurerm_role_assignment.kv_escritura_despliegue]
}

# --- Permisos de la identidad de la aplicación ---

resource "azurerm_role_assignment" "kv_lectura" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Sube los informes al contenedor inmutable (ALMACEN_INFORMES_URL) y los lee.
resource "azurerm_role_assignment" "storage_escritura" {
  scope                = azurerm_storage_container.informes.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

data "azurerm_container_registry" "acr" {
  name                = var.registro.nombre
  resource_group_name = var.registro.grupo
}

resource "azurerm_role_assignment" "acr_descarga" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# --- Inferencia (DA-07) ---

resource "azurerm_cognitive_account" "openai" {
  count                 = var.desplegar_openai ? 1 : 0
  name                  = "oai-${local.nombre}-${local.unico}"
  resource_group_name   = azurerm_resource_group.rg.name
  location              = azurerm_resource_group.rg.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${local.nombre}-${local.unico}"
  tags                  = local.etiquetas
}

resource "azurerm_cognitive_deployment" "chat" {
  count                = var.desplegar_openai ? 1 : 0
  name                 = var.modelo_chat.nombre
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  model {
    format  = "OpenAI"
    name    = var.modelo_chat.nombre
    version = var.modelo_chat.version
  }
  sku {
    name     = "GlobalStandard"
    capacity = var.modelo_chat.capacidad
  }
}

resource "azurerm_cognitive_deployment" "embeddings" {
  count                = var.desplegar_openai ? 1 : 0
  name                 = var.modelo_embeddings.nombre
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  model {
    format  = "OpenAI"
    name    = var.modelo_embeddings.nombre
    version = var.modelo_embeddings.version
  }
  sku {
    name     = "Standard"
    capacity = var.modelo_embeddings.capacidad
  }
  depends_on = [azurerm_cognitive_deployment.chat]
}
