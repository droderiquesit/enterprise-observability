terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }

  # NO backend block — state is git-backed (ADR-016).
  #
  # Terraform always runs on the default local backend. Around every
  # credentialed plan/apply, tools/tfstate-git.sh restores/persists this
  # stack's state from the orphan branch `tfstate` of this repository, one
  # file per environment (coverage/{qa,stage,prod}.tfstate). Locking is the
  # workflows' shared `concurrency: tfstate` group; versioning is the
  # branch's git history. Offline CI stages (fmt, validate, plan without
  # credentials) run with no state and no secrets at all.
}

# Credentials come exclusively from DD_API_KEY / DD_APP_KEY, injected by CI
# from the secret store using the least-privilege service account
# `svc-observability-terraform`. Never from tfvars, never personal keys.
provider "datadog" {
  api_url  = var.datadog_api_url
  validate = var.datadog_validate
}
