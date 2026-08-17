terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }

  # State lives in the org's remote backend; configured per environment via
  # `terraform init -backend-config=...` in CI. Never local in production.
  backend "local" {}
}

# Credentials come exclusively from DD_API_KEY / DD_APP_KEY environment
# variables injected by CI from the secret store — never from tfvars, never
# personal keys (least-privilege service account `svc-observability-terraform`).
provider "datadog" {
  api_url  = var.datadog_api_url
  validate = var.datadog_validate
}
