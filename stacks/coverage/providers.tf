terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }

  # NO backend block is committed.
  #
  # Deployments inject one: CI copies stacks/backend.azurerm.tf.example to
  # backend.tf and runs `terraform init -backend-config=backend.prod.hcl`.
  # Offline CI stages (fmt, validate, plan without credentials) then work with
  # the default local state and no secrets at all.
  #
  # Committing `backend "local" {}` and passing remote backend settings to it
  # is a common and silent misconfiguration — init accepts the flags and the
  # state still lands on the runner's disk. Keeping the block out of the repo
  # makes the intended backend explicit at deploy time.
}

# Credentials come exclusively from DD_API_KEY / DD_APP_KEY, injected by CI
# from the secret store using the least-privilege service account
# `svc-observability-terraform`. Never from tfvars, never personal keys.
provider "datadog" {
  api_url  = var.datadog_api_url
  validate = var.datadog_validate
}
