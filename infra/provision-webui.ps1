<#
    Aprovisiona en Azure lo minimo para publicar la interfaz web.

    Alcance de esta primera vuelta: solo la Container App de la webui con sus
    datos mock. Sin base de datos, sin workers y sin Service Bus. El objetivo es
    validar toda la cadena de despliegue de punta a punta antes de meter
    servicios que cuestan dinero y que pueden fallar a la vez.

    No hace falta Docker instalado: 'az acr build' construye la imagen en la
    nube a partir del codigo fuente.

    Uso:
        az login
        az account set --subscription "<ID O NOMBRE>"
        ./infra/provision-webui.ps1

    Es idempotente: se puede volver a ejecutar sin romper nada.
#>

$ErrorActionPreference = 'Stop'

# --- Parametros. El sufijo evita choques de nombres globales en ACR. ---
$sufijo     = 'licita01'                 # cambiar si el nombre del ACR ya existe
$grupo      = 'rg-licitaciones-mvp'
$region     = 'eastus'                   # Container Apps no esta en todas las regiones
$acr        = "acrlicitaciones$sufijo"   # 5-50 caracteres, solo minusculas y numeros
$entorno    = 'cae-licitaciones-mvp'
$app        = 'ca-licitaciones-webui'
$imagen     = 'webui'
$etiqueta   = 'v1'

Write-Host "`n=== 1/6  Registrando proveedores de recursos ===" -ForegroundColor Cyan
# Sin esto, la primera suscripcion suele fallar al crear el entorno.
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az provider register --namespace Microsoft.ContainerRegistry --wait

Write-Host "`n=== 2/6  Grupo de recursos ===" -ForegroundColor Cyan
az group create --name $grupo --location $region --output table

Write-Host "`n=== 3/6  Container Registry ===" -ForegroundColor Cyan
# Basic es suficiente para un MVP. El registro es el unico costo fijo real aqui.
az acr create --resource-group $grupo --name $acr --sku Basic --admin-enabled true --output table

Write-Host "`n=== 4/6  Construyendo la imagen en la nube ===" -ForegroundColor Cyan
# El contexto es la raiz del repo para que el Dockerfile vea requirements.txt y src/.
az acr build `
    --registry $acr `
    --image "${imagen}:${etiqueta}" `
    --file docker/webui.Dockerfile `
    .

Write-Host "`n=== 5/6  Entorno de Container Apps ===" -ForegroundColor Cyan
az containerapp env create --name $entorno --resource-group $grupo --location $region --output table

Write-Host "`n=== 6/6  Publicando la aplicacion ===" -ForegroundColor Cyan
$servidor = az acr show --name $acr --query loginServer --output tsv
$usuario  = az acr credential show --name $acr --query username --output tsv
$clave    = az acr credential show --name $acr --query "passwords[0].value" --output tsv

# --ingress external con --target-port 8080: NiceGUI escucha ahi y necesita
# WebSocket, que Container Apps soporta sin configuracion extra.
# --min-replicas 1 porque NiceGUI mantiene estado de sesion en memoria: si la
# replica se apaga, las sesiones abiertas se caen.
az containerapp create `
    --name $app `
    --resource-group $grupo `
    --environment $entorno `
    --image "$servidor/${imagen}:${etiqueta}" `
    --registry-server $servidor `
    --registry-username $usuario `
    --registry-password $clave `
    --target-port 8080 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 1 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --output table

$url = az containerapp show --name $app --resource-group $grupo --query "properties.configuration.ingress.fqdn" --output tsv
Write-Host "`nListo. La interfaz esta en: https://$url`n" -ForegroundColor Green
Write-Host "Para borrar todo y dejar de gastar:" -ForegroundColor Yellow
Write-Host "    az group delete --name $grupo --yes --no-wait`n"
