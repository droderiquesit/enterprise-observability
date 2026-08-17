terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }
  backend "local" {}
}

provider "datadog" {
  api_url  = var.datadog_api_url
  validate = var.datadog_validate
}
