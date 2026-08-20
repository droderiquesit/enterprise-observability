#!/usr/bin/env bash
# THE IDEMPOTENCY GATE.
#
# Re-runs what-if against the template that was just deployed. If the
# deployment is truly idempotent, Azure has nothing left to change and every
# reported change type is NoChange or Ignore. Anything else means running the
# same pipeline twice would modify infrastructure — the defect this gate
# exists to catch.
#
# Change types, and why each is treated the way it is:
#   NoChange / Ignore      expected — the resource matches, or what-if is not
#                          asked to evaluate it.
#   Create / Delete /
#   Modify                 FAIL. The template does not converge.
#   Deploy / Unsupported   WARN. ARM cannot diff these resource types, so it
#                          reports "will be deployed" without knowing whether
#                          anything differs. Failing on them would make the
#                          gate permanently red and therefore ignored.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENV_NAME="${1:?usage: idempotency-gate.sh <dev|qa|stage|prod>}"
PARAMS="$(param_file "$ENV_NAME")"
require_env RESOURCE_GROUP

step "idempotency gate: re-running what-if"
RAW="$(az deployment group what-if \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "$TEMPLATE" \
        --parameters "$PARAMS" \
        --name "$(deployment_name "$ENV_NAME")-idempotency" \
        --no-pretty-print -o json)"

printf '%s' "$RAW" | jq -e 'has("changes")' >/dev/null \
  || die "what-if returned no 'changes' array; cannot assert idempotency."

summary="$(printf '%s' "$RAW" | jq -r '[.changes[].changeType] | group_by(.) | map({(.[0]): length}) | add // {}')"
log "  change summary: ${summary}"

BLOCKING="$(printf '%s' "$RAW" | jq -r '
  [.changes[] | select(.changeType == "Create" or .changeType == "Delete" or .changeType == "Modify")]')"
WARNING="$(printf '%s' "$RAW" | jq -r '
  [.changes[] | select(.changeType == "Deploy" or .changeType == "Unsupported")]')"

warn_count="$(printf '%s' "$WARNING" | jq 'length')"
if [ "$warn_count" -gt 0 ]; then
  log ""
  log "  ${warn_count} resource(s) ARM cannot diff (reported, not gated):"
  printf '%s' "$WARNING" | jq -r '.[] | "    \(.changeType)  \(.resourceId)"'
fi

blocking_count="$(printf '%s' "$BLOCKING" | jq 'length')"
if [ "$blocking_count" -gt 0 ]; then
  log ""
  log "  NOT IDEMPOTENT — ${blocking_count} resource(s) would still change:"
  printf '%s' "$BLOCKING" | jq -r '.[] | "    \(.changeType)  \(.resourceId)"'
  printf '%s' "$BLOCKING" | jq -r '
    .[] | select(.delta != null) | "    └─ \(.resourceId)\n" +
    ([.delta[] | "         \(.path): \(.before // "<absent>") -> \(.after // "<absent>")"] | join("\n"))'
  die "idempotency gate failed: a second run of this pipeline would modify infrastructure."
fi

log ""
log "  IDEMPOTENT: a second deployment would change nothing."
