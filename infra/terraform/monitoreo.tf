# monitoreo.tf - Alertas de la Tabla 49 sobre la telemetría que exporta el código (RF-043).
# Las métricas llegan a Application Insights con el nombre que les da src/shared/telemetria.py
# (tabla customMetrics) y los spans de cada análisis, a la tabla dependencies.

resource "azurerm_monitor_action_group" "equipo" {
  name                = "ag-${local.nombre}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "licita"
  tags                = local.etiquetas

  dynamic "email_receiver" {
    for_each = toset(var.correos_alertas)
    content {
      name                    = replace(email_receiver.value, "@", "-")
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

locals {
  # nombre => (descripción, consulta KQL, ventana, severidad). Una fila devuelta dispara la alerta.
  alertas = {
    tiempo-analisis = {
      descripcion = "ASR-01: percentil 90 del tiempo de análisis superior a 10 minutos en 30 minutos."
      ventana     = "PT30M"
      severidad   = 2
      consulta    = <<-KQL
        dependencies
        | where name == "analisis"
        | summarize p90 = percentile(duration, 90)
        | where p90 > 600000
      KQL
    }
    longitud-cola = {
      descripcion = "ASR-02, ASR-07: más de 20 mensajes en espera o cualquier mensaje en la cola de fallidos."
      ventana     = "PT5M"
      severidad   = 2
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.cola.mensajes"
        | extend estado = tostring(customDimensions.estado)
        | summarize maximo = max(value) by estado
        | where (estado == "en_espera" and maximo > 20) or (estado == "fallidos" and maximo > 0)
      KQL
    }
    disyuntor = {
      descripcion = "ASR-07: el disyuntor del proveedor del modelo se abrió (la Tabla 49 alerta si sigue abierto 5 minutos)."
      ventana     = "PT5M"
      severidad   = 2
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.llm.disyuntor.aperturas"
        | summarize aperturas = sum(valueSum)
        | where aperturas > 0
      KQL
    }
    suspension-inyeccion = {
      descripcion = "ASR-10: tarea suspendida por sospecha de inyección."
      ventana     = "PT5M"
      severidad   = 1
      consulta    = <<-KQL
        customMetrics
        | where name == "licita.analisis.suspendidas"
        | where tostring(customDimensions.causa) == "inyeccion"
        | summarize total = sum(valueSum)
        | where total > 0
      KQL
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "tabla49" {
  for_each             = local.alertas
  name                 = "alerta-${each.key}-${local.nombre}"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = azurerm_resource_group.rg.location
  description          = each.value.descripcion
  scopes               = [azurerm_application_insights.appi.id]
  evaluation_frequency = "PT5M"
  window_duration      = each.value.ventana
  severity             = each.value.severidad
  tags                 = local.etiquetas

  criteria {
    query                   = each.value.consulta
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.equipo.id]
  }
}
