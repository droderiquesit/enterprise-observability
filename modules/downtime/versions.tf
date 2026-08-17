terraform {
  required_version = ">= 1.6.0"
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = ">= 3.60.0, < 4.0.0"
    }
  }
}
