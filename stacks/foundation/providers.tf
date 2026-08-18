terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }
  # NO backend block — state is git-backed on the orphan `tfstate` branch,
  # moved by tools/tfstate-git.sh around every credentialed plan/apply
  # (foundation/prod.tfstate). Full rationale: stacks/coverage/providers.tf
  # and ADR-016.
}

provider "datadog" {
  api_url  = var.datadog_api_url
  validate = var.datadog_validate
}
