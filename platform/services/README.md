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
