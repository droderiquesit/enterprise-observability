output "service_names" {
  value = keys(datadog_service_definition_yaml.this)
}
