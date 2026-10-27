#!/usr/bin/env bash
# Crea, una sola vez, la cuenta de almacenamiento del estado de Terraform (apartado 4.3).
# Es el único recurso que no crea Terraform: el estado no puede depender del propio estado.
# Uso: az login && ./bootstrap/crear_backend.sh [región]
set -euo pipefail

UBICACION="${1:-eastus2}"
GRUPO="rg-licita-tfstate"
CUENTA="stlicitatfstate"

az group create --name "$GRUPO" --location "$UBICACION" --output none
az storage account create --name "$CUENTA" --resource-group "$GRUPO" --location "$UBICACION" \
  --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false --output none
# Versionado y borrado temporal: un estado dañado o borrado por error se recupera.
az storage account blob-service-properties update --account-name "$CUENTA" --resource-group "$GRUPO" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 30 --output none
az storage container create --name tfstate --account-name "$CUENTA" --auth-mode login --output none

echo "Estado remoto listo: $GRUPO / $CUENTA / tfstate"
