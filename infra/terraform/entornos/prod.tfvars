# Entorno de producción (Anexo G.8): cómputo mayor, réplica mínima activa, más retención de
# respaldo e imágenes con versión fija. Key Vault y Storage solo desde la red virtual (C-09):
# la canalización aplica desde un agente con acceso a la red.
entorno                    = "prod"
ubicacion                  = "eastus2"
sku_postgres               = "B_Standard_B2s"
almacenamiento_postgres_mb = 65536
worker_replicas_min        = 1
worker_replicas_max        = 6
retencion_respaldo_dias    = 14
desplegar_openai           = true
acceso_publico_almacenes   = false
auth_mode                  = "oidc"
imagen_api                 = "acrlicitacioneslicita01.azurecr.io/api:1.0.0"
imagen_web                 = "acrlicitacioneslicita01.azurecr.io/webui:1.0.0"
imagen_worker              = "acrlicitacioneslicita01.azurecr.io/worker-analisis:1.0.0"
imagen_vigilancia          = "acrlicitacioneslicita01.azurecr.io/worker-vigilancia:1.0.0"
