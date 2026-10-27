# Entorno de desarrollo (Anexo G.6): una réplica máxima del trabajador, sin Azure OpenAI
# propio (se reutiliza el de pruebas con TF_VAR_azure_openai_endpoint y _clave).
entorno                    = "dev"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B1ms"
almacenamiento_postgres_mb = 32768
worker_replicas_min        = 0
worker_replicas_max        = 1
retencion_respaldo_dias    = 7
desplegar_openai           = false
acceso_publico_almacenes   = true
auth_mode                  = "local"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:dev"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:dev"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:dev"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:dev"
