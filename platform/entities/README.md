# Entity Registry

Step 1 of the golden path: **register the thing once, whatever kind of thing it
is.** One YAML file per entity; the platform derives the rest.

This directory replaces `platform/services/` as the place registrations are
written. The reason is the §5 defect: the old format had no `kind`, so every
object it produced was a Datadog *Service* — a database was a service, a
Service Bus topic was a service, a VM was a service. Ownership, dependency
maps and scorecards were all wrong downstream of that one missing field.

```yaml
entity:
  kind: datastore                 # service | system | datastore | queue | api
                                  # | frontend_app | repository
  name: orders-sql                # must match the identity on the telemetry
  team: data-engineering          # must exist in platform/policy/teams.yaml
  criticality: tier1              # tier0 | tier1 | tier2 | tier3
  service_archetype: datastore    # selects the monitor packs
  platform: azure_sql             # what it runs ON  → spec.type + platform tag
  domain: database                # derived from the archetype when omitted
  region: eastus2
  description: Azure SQL database of record for order capture.
  envs: [dev, qa, stage, prod]
  env: prod                       # which env the CATALOG ENTRY describes
  slo: { profile: domain }        # per_service | domain | none
  oncall: { team: data-engineering, schedule: data-engineering-primary }
  dependencies: [identity-api, datastore:orders-sql]   # service-shaped kinds only
```

Schema: [`entity.schema.json`](../schemas/entity.schema.json) (CI-enforced).
Kind semantics, and what each kind becomes in Datadog:
[`policy/entity_kinds.yaml`](../policy/entity_kinds.yaml).
Resolution (kind, tags, ownership, system edges):
[`tools/entity_resolver.py`](../../tools/entity_resolver.py).

## What each field buys you

| Field | Consequence |
|---|---|
| `kind` | Which Datadog entity kind is emitted — or, for `repository`, that none is |
| `criticality` | Monitoring profile, alert band, paging, SLO scope, support model |
| `service_archetype` | Which monitor packs apply, and the derived runbook links |
| `platform` | `spec.type`, the `platform:` tag, and the §9 platform inheritance layer |
| `dependencies` | `spec.dependsOn` — resolved to `kind:name`, so the map is typed |
| `components` (systems) | `spec.components`, and the derived `componentOf` on each member |
| `oncall` | An `operator` additional-owner and the `oncall_team:` tag |

## What this registry cannot do

Three limits, all of them the API's rather than ours, all recorded in
`policy/entity_kinds.yaml` next to the kind they constrain:

1. **A VM is not an entity.** `service_archetype: infrastructure_resource` maps
   to *no* kind. Hosts, ESXi hosts, network devices and cluster nodes live in
   Datadog's infrastructure list and are monitored by the `host-core` pack
   through tags. Registering one here is a lint error — that is the whole point
   of the change.
2. **`frontend_app` is emitted as a `service`** with `spec.type: web`. The v3
   entity union has no UI kind.
3. **`repository` emits nothing.** Datadog has no repository entity; a
   repository declaration contributes a `repo` link to the entities it owns.

## Why `platform:` is missing from the migrated services

`identity-api`, `order-events-consumer` and `reporting-portal` carry no
`platform:`. Nothing in this repository records what they run on, and an
optional field left empty is honest where a guessed one would become a wrong
tag on a tier0 entity. Fill it in when the estate says so, not before.

## Relationship to `platform/services/`

The old directory still loads and still validates — nothing that reads it
broke — but it is empty by design, the same way `platform/monitors/` is. See
[`../services/README.md`](../services/README.md).
