# Entorno de pruebas (Anexo G.7): hasta cuatro réplicas, Azure OpenAI propio e imágenes
# candidatas a liberación. Se crea para cada campaña de pruebas y se destruye al terminar.
entorno                    = "pruebas"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B1ms"
almacenamiento_postgres_mb = 32768
worker_replicas_min        = 0
worker_replicas_max        = 4
retencion_respaldo_dias    = 7
desplegar_openai           = true
acceso_publico_almacenes   = true
auth_mode                  = "oidc"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:rc"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:rc"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:rc"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:rc"
