#!/usr/bin/env bash
# Deploy one environment. `az group create` and `az deployment group create`
# are both idempotent by construction: ARM incremental mode converges the
# declared state and does nothing when it already matches.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME="${1:?usage: deploy.sh <dev|qa|stage|prod>}"
PARAMS="$(param_file "$ENV_NAME")"
NAME="$(deployment_name "$ENV_NAME")"

require_env RESOURCE_GROUP LOCATION IMAGE_REPOSITORY IMAGE_TAG APP_VERSION

step "resource group"
# Idempotent: creates on first run, no-ops thereafter.
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
log "  ${RESOURCE_GROUP} ready in ${LOCATION}"

step "what-if (preview)"
# Printed for the human reading the log / approving the release. This is the
# preview, NOT the gate — the gate runs after the deployment.
az deployment group what-if \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE" \
  --parameters "$PARAMS" \
  --name "${NAME}-preview" \
  --result-format FullResourcePayloads \
  || log "  (what-if preview reported a non-zero exit; the deployment below is authoritative)"

step "deploy"
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file "$TEMPLATE" \
  --parameters "$PARAMS" \
  --name "$NAME" \
  --mode Incremental \
  --output none
log "  deployment ${NAME} succeeded"

step "outputs"
az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$NAME" \
  --query 'properties.outputs' -o json | jq '.'
