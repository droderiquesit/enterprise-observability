variable "entities" {
  description = <<-EOT
    Map of fully-resolved catalog entities, keyed by entity name. The value is
    the OUTPUT of the entity resolution performed in the calling stack from
    platform/entities/*.yaml and platform/policy/entity_kinds.yaml — this
    module makes no policy decisions, it renders the v3 document and enforces
    the one contract the provider does not (see main.tf).

    `tools/entity_resolver.py` produces the same fields under the same names;
    it is the reference implementation and the tests assert against it.
  EOT
  type = map(object({
    # kind resolution — `emits: false` means this entity deliberately produces
    # no Datadog object (a repository has no Datadog kind), and `datadog_kind`
    # is not necessarily our kind (`frontend_app` emits `service`).
    emits        = bool
    datadog_kind = optional(string)

    # identity & classification
    display_name = optional(string)
    description  = string
    lifecycle    = optional(string, "production")
    tier         = string
    spec_type    = optional(string)
    tags         = list(string)

    # ownership
    team        = string
    oncall_team = string
    contacts    = optional(list(object({ name = string, type = string, contact = string })), [])

    # graph — resolved to `kind:name` references by the caller, and empty for
    # any kind whose v3 spec cannot carry that edge
    depends_on   = optional(list(string), [])
    components   = optional(list(string), [])
    component_of = optional(list(string), [])

    performance_data_tags = optional(list(string), [])
    links                 = optional(list(object({ name = string, type = string, url = string })), [])
  }))
}

variable "datadog_entity_kinds" {
  description = <<-EOT
    The kinds Datadog's v3 entity union actually accepts. Passed in rather than
    hard-coded so that platform/policy/entity_kinds.yaml stays the single place
    the list is written — Python reads the same key.
  EOT
  type        = list(string)
  default     = ["service", "datastore", "queue", "system", "api"]
}
