#!/usr/bin/env bash
# Políticas de rama de Azure DevOps para main y develop (CONTRIBUTING.md, apartado 3.36).
# Requiere la CLI de Azure con la extensión azure-devops:
#   az extension add --name azure-devops
#   az login
# Uso: ./infra/devops/politicas_rama.sh <id de la definición de la canalización azure-pipelines.yml>
set -euo pipefail

ORGANIZACION="https://dev.azure.com/TRABAJOGRADOJLDL"
PROYECTO="AGENTE IA TG"
REPOSITORIO="AGENTE IA TG"
CANALIZACION="${1:?Indique el id de la canalización (Pipelines > la canalización > definitionId en la URL)}"

az devops configure --defaults organization="$ORGANIZACION" project="$PROYECTO"
REPO_ID=$(az repos show --repository "$REPOSITORIO" --query id --output tsv)

for RAMA in main develop; do
  # Revisión por pares: aprueba el otro integrante; el voto del autor no cuenta.
  az repos policy approver-count create --repository-id "$REPO_ID" --branch "$RAMA" \
    --blocking true --enabled true --minimum-approver-count 1 --creator-vote-counts false \
    --allow-downvotes false --reset-on-source-push true --output none

  # La canalización (pruebas, aptitud, Terraform y seguridad) debe pasar antes de fusionar.
  az repos policy build create --repository-id "$REPO_ID" --branch "$RAMA" \
    --blocking true --enabled true --build-definition-id "$CANALIZACION" \
    --display-name "Pruebas, aptitud y seguridad" --queue-on-source-update-only false \
    --manual-queue-only false --valid-duration 720 --output none

  # Comentarios resueltos y vínculo con la historia del tablero.
  az repos policy comment-required create --repository-id "$REPO_ID" --branch "$RAMA" \
    --blocking true --enabled true --output none
  az repos policy work-item-linking create --repository-id "$REPO_ID" --branch "$RAMA" \
    --blocking true --enabled true --output none

  # Historial lineal: se fusiona aplastando los commits de la rama de trabajo.
  az repos policy merge-strategy create --repository-id "$REPO_ID" --branch "$RAMA" \
    --blocking true --enabled true --allow-squash true --allow-no-fast-forward false \
    --allow-rebase false --allow-rebase-merge false --output none

  echo "Políticas aplicadas a $RAMA"
done
