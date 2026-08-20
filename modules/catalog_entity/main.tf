# =============================================================================
# SOFTWARE CATALOG ENTITY (v3) — one Datadog entity of the CORRECT KIND.
#
# WHY this module exists next to service_catalog rather than inside it.
# `modules/service_catalog` emits `datadog_service_definition_yaml`, schema
# v2.2. That resource has exactly one shape: a Service. It is the reason the
# audit's §5 row says "every catalog object is a Service" — a database, a
# Service Bus topic and a VM all arrived in the catalog as services. v2.2 has
# no `kind` to add, so the fix is a different resource, not a bigger variable.
#
# CONSTRAINT (checked against the pinned provider, DataDog/datadog 3.91.0, and
# against the generated API client): `datadog_software_catalog` takes ONE
# free-form `entity` string and validates only that `apiVersion` is >= v3. It
# does NOT validate `kind`, so an unsupported kind fails at APPLY, against the
# live org, not at plan. The precondition below is what moves that failure back
# to plan time — the same contract-enforcement role modules/monitor_factory
# plays for monitors.
#
# SECOND CONSTRAINT: a v2.2 service definition and a v3 entity with the same
# name are the SAME catalog object. Managing one name with both resources means
# two Terraform resources fighting over one Datadog entity, so the calling
# stack passes each name to exactly one of the two modules. See
# stacks/foundation/main.tf.
#
# This module makes no policy decisions. Kind resolution, tag derivation and
# the dependency/system graph all happen in the calling stack from
# platform/policy/entity_kinds.yaml — the same file tools/entity_resolver.py
# reads, so HCL and Python interpret one source instead of each other.
# =============================================================================

locals {
  # A kind may resolve to "no Datadog entity at all" — `repository` does, and
  # so does anything whose service_archetype is infrastructure_resource. That
  # is a correct outcome, not an omission: a VM belongs in the infrastructure
  # list, and Datadog has no repository kind.
  emitted = { for name, e in var.entities : name => e if e.emits }

  entity_yaml = { for name, e in local.emitted : name => yamlencode(merge(
    {
      apiVersion = "v3"
      kind       = e.datadog_kind
      metadata = merge(
        {
          name        = name
          description = e.description
          # `owner` is the ROUTING owner — a Datadog team handle. The
          # accountable human/DL travels as a contact, because Datadog resolves
          # `owner` against its team directory and a mailbox is not a team.
          owner = e.team
          tags  = sort(e.tags)
        },
        e.display_name == null ? {} : { displayName = e.display_name },
        length(e.contacts) == 0 ? {} : { contacts = e.contacts },
        # The on-call carrier, when it is not the owning team. `operator` is
        # the v3 additional-owner type for "runs it but does not own it".
        e.oncall_team == e.team ? {} : {
          additionalOwners = [{ name = e.oncall_team, type = "operator" }]
        },
        length(e.links) == 0 ? {} : {
          links = [for l in e.links : { name = l.name, type = l.type, url = l.url }]
        },
      )
      spec = merge(
        {
          lifecycle = e.lifecycle
          # Datadog's own examples use "1"/"2". This platform's vocabulary is
          # tier0..tier3 and `tier` is one of the six owner-applied telemetry
          # tags, so spec.tier carries the same string the telemetry does —
          # otherwise a join between a monitor and its entity needs a lookup
          # table that exists nowhere.
          tier = e.tier
        },
        e.spec_type == null ? {} : { type = e.spec_type },
        # Only service-shaped specs have dependsOn; only a system has
        # components; system is the one kind with no componentOf. The caller
        # resolves these to empty for kinds that cannot carry them, so an
        # empty list here means "nothing declared", never "silently dropped".
        length(e.depends_on) == 0 ? {} : { dependsOn = e.depends_on },
        length(e.components) == 0 ? {} : { components = e.components },
        length(e.component_of) == 0 ? {} : { componentOf = e.component_of },
      )
    },
    # Which telemetry belongs to this entity. Emitted only where the telemetry
    # really is keyed by the `service` tag: a datastore is keyed by
    # db_instance and a queue by namespace, and claiming otherwise produces an
    # entity whose performance tab is permanently empty.
    length(e.performance_data_tags) == 0 ? {} : {
      datadog = { performanceData = { tags = e.performance_data_tags } }
    },
  )) }
}

resource "datadog_software_catalog" "this" {
  for_each = local.entity_yaml

  entity = each.value

  lifecycle {
    precondition {
      condition = contains(var.datadog_entity_kinds, var.entities[each.key].datadog_kind)
      error_message = format(
        "entity %q resolves to Datadog kind %q, which the v3 entity union does not accept (%s). The provider does not validate `kind`, so this would fail at apply against the live org.",
        each.key, var.entities[each.key].datadog_kind, join(", ", var.datadog_entity_kinds)
      )
    }
  }
}
