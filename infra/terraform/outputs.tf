# outputs.tf - Valores que consume la canalización después de aplicar (Anexo G.5).

output "url_interfaz" {
  description = "URL pública de la interfaz web. Registrar <url>/auth/callback como URI de redirección en Entra ID."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "servidor_postgres" {
  description = "Nombre completo del servidor de base de datos (solo alcanzable desde la red virtual)."
  value       = azurerm_postgresql_flexible_server.pg.fqdn
}

output "espacio_service_bus" {
  description = "Espacio de nombres de la cola de trabajos."
  value       = azurerm_servicebus_namespace.sb.name
}

output "identidad_aplicacion" {
  description = "Identificador de cliente de la identidad administrada."
  value       = azurerm_user_assigned_identity.app.client_id
}

output "almacen_informes" {
  description = "Contenedor inmutable de los informes emitidos (ALMACEN_INFORMES_URL)."
  value       = "${azurerm_storage_account.st.primary_blob_endpoint}${azurerm_storage_container.informes.name}"
}

output "key_vault" {
  description = "Almacén de secretos del entorno."
  value       = azurerm_key_vault.kv.vault_uri
}

output "aplicaciones" {
  description = "Nombres de las unidades de despliegue, para la canalización."
  value = {
    web        = azurerm_container_app.web.name
    api        = azurerm_container_app.api.name
    worker     = azurerm_container_app.worker.name
    vigilancia = azurerm_container_app_job.vigilancia.name
    grupo      = azurerm_resource_group.rg.name
  }
}
