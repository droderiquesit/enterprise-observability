# Service Registry

This directory is step 1 of the golden path: **register the service once.**

One YAML file per service. The platform derives everything else — monitoring
profile, alert band, SLO scope, routing, dashboards, on-call, catalog entry.

```yaml
service:
  name: checkout-api              # must match the `service` tag on telemetry
  team: payments                  # must exist in platform/policy/teams.yaml
  tier: tier0                     # tier0 | tier1 | tier2 | tier3
  service_archetype: api          # selects the monitor packs
  description: Customer checkout and payment orchestration API.
  envs: [dev, qa, stage, prod]
  dependencies: [payments-ledger, stripe]
  links:
    - { name: Repository, type: repo, url: https://github.com/acme/checkout-api }
```

## What registration gets you

| Automatically applied | Source |
|---|---|
| Baseline monitors for every pack in your archetype | `service_archetypes.yaml` |
| Monitoring profile + alert band | `tiers.yaml` |
| SLOs (per-service for tier0, domain SLO otherwise) | `slos.yaml` |
| Burn-rate paging | `global.yaml` burn windows |
| Notification routing, on-call, ServiceNow group | `notification_profiles.yaml` + `teams.yaml` |
| Environment behavior across dev/qa/stage/prod | `environments.yaml` |
| Datadog Service Catalog entry with ownership | `modules/service_catalog` |
| Runbook links on every alert | `runbooks.yaml` |

## What you must do outside this file

Tag your telemetry with the five owner-applied tags:

```
env  service  team  tier  service_archetype
```

If those tags are present, the monitors already cover you — the registry file
adds ownership metadata, tier0 SLOs, and catalog presence. If they are absent,
`tools/coverage_report.py` will list your resources as unowned or untagged
within a day.

## Discovery vs registration

Registration is **not** required for coverage. `tools/build_inventory.py`
discovers every resource from the Datadog APIs, cloud metadata and the service
catalog, and `tools/profile_engine.py` assigns a profile to all of them from
their tags. Registration exists to make ownership explicit and to unlock tier0
treatment — it is the difference between *covered* and *owned*.
