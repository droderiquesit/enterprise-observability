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

Schema: [`platform/schemas/service.schema.json`](../schemas/service.schema.json)
(CI-enforced). Remember to tag the telemetry itself with the five
owner-applied tags — `env service team tier service_archetype` — or
`tools/coverage_report.py` will list your resources as untagged within a day.
