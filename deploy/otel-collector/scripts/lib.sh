#!/usr/bin/env bash
# Shared helpers. Sourced by every script here so the two pipelines run
# byte-identical logic — a bug fixed for one is fixed for both.
set -euo pipefail

BICEP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bicep" && pwd)"
TEMPLATE="${BICEP_DIR}/main.bicep"

log()  { printf '%s\n' "$*"; }
step() { printf '\n── %s %s\n' "$*" "$(printf '─%.0s' $(seq 1 $(( 60 - ${#*} > 0 ? 60 - ${#*} : 0 ))))"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_env() {
  local missing=()
  for v in "$@"; do [ -n "${!v:-}" ] || missing+=("$v"); done
  [ ${#missing[@]} -eq 0 ] || die "missing required environment variable(s): ${missing[*]}"
}

param_file() {
  local env_name="$1"
  local f="${BICEP_DIR}/params/${env_name}.bicepparam"
  [ -f "$f" ] || die "no parameter file for environment '${env_name}' (expected ${f})"
  printf '%s' "$f"
}

# A deployment NAME is a record, not a resource: making it unique per run keeps
# the deployment history readable. It has no bearing on idempotency — the
# RESOURCES are addressed by their deterministic names.
deployment_name() {
  printf 'otel-collector-%s-%s' "$1" "${BUILD_ID:-local}"
}
