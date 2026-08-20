terraform {
  required_version = ">= 1.7.0"
  required_providers {
    datadog = {
      source = "DataDog/datadog"
      # `datadog_software_catalog` landed in provider 3.44.0 (Sept 2024) and is
      # present in the pinned 3.91.0 — verified with `terraform providers
      # schema -json`, which reports one attribute, `entity`. The repository's
      # existing floor is 3.60.0, comfortably above it.
      version = ">= 3.60.0, < 4.0.0"
    }
  }
}
