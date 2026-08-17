# Self-Service Onboarding Guide (for application & platform teams)

## What you get without doing anything

If your service emits telemetry with the required tags (`env`, `service`,
`team`, plus `criticality` if you're not tier2), you already have:

- Error-rate, latency, traffic, dependency, deploy-regression and
  telemetry-loss monitoring (grouped monitors — your service is a group).
- SLO burn-rate paging through the platform SLOs for your domain.
- Routing to your team's Teams channel, ServiceNow queue, and on-call
  rotation, by severity.
- Runbooks and automated diagnostics attached to every alert.
- A service-catalog entry with your ownership, tier, and profile.

**Do not create monitors in the Datadog UI.** They will be flagged as
unmanaged (check C9) within a day and removed or imported.

## When you need something specialized

Write one YAML file in `platform/requests/` and open a PR. Full example:
`platform/requests/payments-checkout-latency.yaml`. Fields:

```yaml
kind: monitor-request
title: <descriptive sentence, 10–120 chars>
service: <your catalog service>
env: prod            # from the env vocabulary
domain: application  # your domain
team: <your team handle>       # must exist in teams.yaml
criticality: tier1             # drives severity & priority mapping
severity_class: page           # page_fast | page | ticket
monitor_type: query alert
query: "<must be scoped to your env AND service>"
thresholds: { critical: 2.5, warning: 2.0 }
group_by: []                   # ≤3 keys; identity keys are banned
slo_id: slo-app-latency        # must exist in the platform SLO catalog
runbook: "Runbook: Application Latency Degradation"   # from the registry
workflow: auto-enrich-latency                          # from the registry
summary: "<one sentence for the alert body>"
impact: "<business impact statement>"
justification: >               # required when deviating from standards,
  <e.g. fixed threshold on a behavioral signal>
```

CI validates the manifest (`tools/validate_manifests.py`) and rejects:
unknown teams/SLOs/runbooks/workflows, unscoped queries, cardinality
violations, wrong-direction warning thresholds, unjustified fixed thresholds,
and missing fields — with a per-line explanation in the PR check output.

On merge, Terraform generates a fully compliant monitor (contract message,
all governance tags, routing, recovery, correlation keys) tagged
`managed_source:self_service` and `request_id:<file name>` — you never write
Terraform, and you can delete the monitor by deleting the file.

## When you need an exception

Add an entry to `platform/policy/exceptions.yaml` in the same PR: owner,
business justification, approver, and an expiry date are mandatory. Expired
exceptions fail CI until renewed or removed, and all exceptions appear in the
coverage report.

## FAQ

- **"My dev service isn't alerting."** By policy: dev/sandbox are
  observe-only. Telemetry and dashboards still work.
- **"I need a different threshold for one host."** Not supported by design —
  thresholds are per archetype. If a host is genuinely special, it needs its
  own service identity or a request manifest.
- **"Who gets paged?"** Your `team` tag → your rotation, per severity
  (routing.yaml). Verify with your team's on-call schedule in Datadog.
