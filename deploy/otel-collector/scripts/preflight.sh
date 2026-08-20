#!/usr/bin/env bash
# Fail in seconds, not mid-deployment. Every check here corresponds to a
# failure that otherwise surfaces after Azure resources have been touched.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME="${1:?usage: preflight.sh <dev|qa|stage|prod>}"

step "preflight: tooling"
command -v az >/dev/null 2>&1 || die "Azure CLI not found on PATH."
az version --output tsv --query '"azure-cli"' 2>/dev/null | sed 's/^/  az        /'
az bicep version 2>/dev/null | sed 's/^/  bicep     /' || die "Bicep CLI not available (run: az bicep install)."
command -v jq >/dev/null 2>&1 || die "jq not found on PATH."

step "preflight: authentication"
az account show --output none 2>/dev/null \
  || die "not logged in to Azure. The pipeline should authenticate with a federated (OIDC) service connection before calling this script."
SUB_ID="$(az account show --query id -o tsv)"
SUB_NAME="$(az account show --query name -o tsv)"
log "  subscription: ${SUB_NAME} (${SUB_ID})"

step "preflight: inputs"
require_env RESOURCE_GROUP LOCATION IMAGE_TAG APP_VERSION KEY_VAULT_NAME DD_API_KEY_VAULT_URL
[ "${IMAGE_TAG}" != "latest" ] \
  || die "IMAGE_TAG is 'latest'. A mutable tag makes the deployment unreproducible and defeats revision tracking — use an immutable tag."
log "  resource group:  ${RESOURCE_GROUP}"
log "  location:        ${LOCATION}"
log "  image:           ${IMAGE_REPOSITORY:-otel/opentelemetry-collector-contrib}:${IMAGE_TAG}"
log "  key vault:       ${KEY_VAULT_NAME}"
log "  app version:     ${APP_VERSION}"
log "  parameter file:  $(param_file "$ENV_NAME")"

step "preflight: template compiles"
az bicep build --file "$TEMPLATE" --stdout >/dev/null || die "main.bicep failed to compile."
log "  main.bicep and its modules compile"

step "preflight: image exists"
# The collector image is public (Docker Hub) unless the org mirrors it into
# ACR. Only a mirrored image can be checked, and only then is it worth failing
# early — a missing mirror surfaces as an image-pull error on a revision that
# never starts.
if [ -n "${ACR_NAME:-}" ]; then
  repo="${IMAGE_REPOSITORY:-otel/opentelemetry-collector-contrib}"
  repo="${repo##*/}"
  if az acr repository show-tags --name "$ACR_NAME" --repository "$repo" -o tsv 2>/dev/null | grep -qx "$IMAGE_TAG"; then
    log "  ${ACR_NAME}/${repo}:${IMAGE_TAG} found"
  else
    die "image ${repo}:${IMAGE_TAG} not found in ACR '${ACR_NAME}'. Deploying a tag that was never pushed fails late, as an image-pull error on a revision that never starts."
  fi
else
  log "  ACR_NAME not set — skipping (public or externally-hosted image)"
fi

step "preflight: provider registration"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ManagedIdentity; do
  state="$(az provider show -n "$ns" --query registrationState -o tsv 2>/dev/null || echo Unknown)"
  if [ "$state" != "Registered" ]; then
    log "  ${ns}: ${state} — registering (idempotent)"
    az provider register -n "$ns" --wait || die "could not register ${ns}"
  else
    log "  ${ns}: Registered"
  fi
done

log ""
log "preflight OK"
