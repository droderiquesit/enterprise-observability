variable "services" {
  description = "Service catalog entries generated from the inventory + profile engine (generated/assignments.json)."
  type = map(object({
    team               = string
    owner_email        = string
    description        = optional(string, "")
    tier               = string
    domain             = string
    monitoring_profile = string
    env                = optional(string, "prod")
    links              = optional(list(object({ name = string, type = string, url = string })), [])
  }))
}
