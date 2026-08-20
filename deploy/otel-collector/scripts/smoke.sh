#!/usr/bin/env bash
# Post-deploy health. A successful ARM deployment means the resource was
# accepted, NOT that the container started — an image that crash-loops still
# deploys "successfully".
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME="${1:?usage: smoke.sh <dev|qa|stage|prod>}"
require_env RESOURCE_GROUP
APP_NAME="${APP_NAME:-ca-otel-collector-${ENV_NAME}}"

step "smoke: latest revision"
for attempt in $(seq 1 12); do
  rev_json="$(az containerapp revision list \
      --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
      --query "sort_by([].{name:name,active:properties.active,health:properties.healthState,running:properties.runningState,replicas:properties.replicas,created:properties.createdTime}, &created) | [-1]" \
      -o json 2>/dev/null || echo '{}')"

  name="$(printf '%s' "$rev_json"  | jq -r '.name // "unknown"')"
  health="$(printf '%s' "$rev_json"| jq -r '.health // "Unknown"')"
  running="$(printf '%s' "$rev_json" | jq -r '.running // "Unknown"')"
  log "  attempt ${attempt}: ${name} health=${health} running=${running}"

  # A scale-to-zero revision is legitimately Running/0 with no health signal.
  if [ "$running" = "Running" ] || [ "$running" = "RunningAtMaxScale" ] || [ "$running" = "Scaled To Zero" ]; then
    if [ "$health" = "Healthy" ] || [ "$health" = "None" ] || [ "$health" = "Unknown" ]; then
      log ""
      log "  revision ${name} is serving"
      exit 0
    fi
  fi
  if [ "$running" = "Failed" ] || [ "$health" = "Unhealthy" ]; then
    log ""
    log "  recent logs:"
    az containerapp logs show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
      --revision "$name" --tail 50 2>/dev/null || true
    die "revision ${name} failed to start (health=${health} running=${running})."
  fi
  sleep 10
done
die "revision did not reach a running state within 2 minutes."
