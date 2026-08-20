# Service Registry

Step 1 of the golden path: **register the service once.** One YAML file per
service; the platform derives everything else. What registration buys, what
discovery covers without it, and the tag contract are all in
[docs/golden-path.md](../../docs/golden-path.md).

```yaml
service:
  name: identity-api              # must match the `service` tag on telemetry
  team: application-development                  # must exist in platform/policy/teams.yaml
  tier: tier0                     # tier0 | tier1 | tier2 | tier3
  service_archetype: api          # selects the monitor packs
  description: Customer identity and session API.
  envs: [dev, qa, stage, prod]
  dependencies: [identity-store, okta]
  links:
    - { name: Repository, type: repo, url: https://github.com/acme/identity-api }
```

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
