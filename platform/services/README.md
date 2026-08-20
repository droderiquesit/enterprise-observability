# Service Registry — SUPERSEDED by `platform/entities/`

Registrations are now written in [`platform/entities/`](../entities/README.md).
The three services that lived here — `identity-api`,
`order-events-consumer`, `reporting-portal` — were migrated field for field;
nothing was dropped, and `tier:` was renamed to `criticality:` (the §10 name)
with the same vocabulary and the same tag on the telemetry.

**Why the move.** This format had no `kind`, so everything it produced was a
Datadog *Service*. That is the §5 defect: an Azure SQL database, a Service Bus
topic and a VM all appeared in the Software Catalog as services, which makes
ownership, dependency maps and entity scorecards wrong at the source. The
entity schema adds `kind`, `platform`, `env`, `region`, `monitoring_profile`,
`slo.profile`, `oncall` and typed `dependencies`.

**Why this directory still exists, empty.** The loader
(`obs_common.load_services()`), the JSON schema, the CI schema stage and both
Terraform stacks still read `*.yaml` here and merge whatever they find with the
entity registry. A team mid-PR, or a fork carrying its own service files, keeps
working unchanged; nothing had to be migrated in lockstep with this commit.
It ships empty for the same reason `platform/monitors/` does: a file here is
APPLIED, so leaving the three migrated services behind would have created two
sources of truth for one catalog object — and, worse, two Terraform resources
(`datadog_service_definition_yaml` and `datadog_software_catalog`) writing the
same Datadog entity.

Schema (still enforced):
[`platform/schemas/service.schema.json`](../schemas/service.schema.json).

Delete this directory once no branch in flight registers a service the old way.
## Objectives (optional)

Registration alone already resolves objectives: a tier0 service gets the
availability SLO its tier promises, measured with the SLI its entity type
defines. The `slo:` block is for the two cases where that is not enough — a
service that owes MORE than availability, and a service whose promise differs
from other, technically identical services.

```yaml
service:
  # ...
  slo:
    profile: api-critical         # a named objective set from platform/policy/slo_profiles.yaml
    objectives:
      availability:
        target: 99.99             # overrides the profile AND the tier — last word in the chain
        rationale: >
          Contractual: the partner agreement commits to four nines with
          service credits (CONTRACT-4471).
```

Resolution order, later wins:
`enterprise defaults → entity type → platform → criticality (tier) →
environment → slo_profile → this file`. See
[`platform/policy/slo_profiles.yaml`](../policy/slo_profiles.yaml) for the
chain and the profile catalog, and run
`python tools/slo_resolver.py --service <name>` to see what a service resolves
to and which layer decided each field.

Two rules worth knowing before you write one: an override must carry a
`rationale` (it beats every reviewed layer, so the reason has to be readable in
the pull request), and a profile can only be applied to the entity types it can
actually measure — `batch-standard` on an API is a CI failure, not an SLO with
an SLI that never reports.

Schema: [`platform/schemas/service.schema.json`](../schemas/service.schema.json)
(CI-enforced). Remember to tag the telemetry itself with the five
owner-applied tags — `env service team tier service_archetype` — or
`tools/coverage_report.py` will list your resources as untagged within a day.
