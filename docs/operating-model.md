# Operating Model & Ownership

## Who owns what

| Component | Owner | Change path |
|---|---|---|
| Policy hierarchy, archetypes, modules, stacks | observability-platform | PR + CI + approval gate |
| Self-service manifests (`platform/requests/`) | requesting team | PR; CI validates; platform team reviews only exceptions |
| Runbook content | archetype's owning team | PR to `platform/runbooks/`; publisher deploys |
| On-call rosters (`oncall_members`) | each team | tfvars fed from IdP sync job — not edited by hand |
| Exceptions (`exceptions.yaml`) | requesting team + approver | PR; approver recorded; expiry enforced by CI |
| Coverage findings | named in the report (team tag) | 14-day SLA for C2 (unowned); next business day for C9 (click-ops) |

## Cadences

- **Continuous:** CI on every PR; deploys from `main` behind the
  `datadog-production` approval environment; concurrency-locked applies.
- **Daily:** drift detection (Terraform + runbooks), 06:00 UTC.
- **Weekdays:** coverage & compliance report, 07:00 UTC; red run = governance
  incident for observability-platform.
- **Monthly:** SLO objective review per owning team (recorded in slos.yaml
  descriptions); alert-quality review (renotify volume, non-actionable rate).
- **Quarterly:** exception re-approval sweep; RBAC access review; archetype
  catalog review with domain owners.

## Change safety rules

1. Nothing is deployed outside Terraform + the runbook publisher. Click-ops
   objects are detected within a day (C9) and either imported or deleted.
2. Secrets: only the `svc-observability-terraform` (deploy) and
   `svc-observability-coverage` (read) service-account keys, held in the CI
   secret store, injected as env vars. Personal API keys are never used;
   gitleaks scans every PR.
3. Destructive changes (monitor deletions > 10, any SLO deletion) require a
   plan artifact attached to the PR and a second reviewer.
4. Maintenance: recurring windows via `modules/downtime` (tag-scoped).
   Regulated scopes additionally require a change ticket recorded on the
   window (validated in CI).
5. Break-glass: Platform Administrator role, ≤3 humans, audit-logged, every
   use reconciled back into code within 24h (drift job catches forgotten
   changes).

## On-call & escalation (per team, from `routing.yaml`)

sev1: ack 5 min → escalate 10 min; sev2: ack 10 min → escalate 20 min;
escalation chain responder → full rotation → team management; sev3 and below
never page (ServiceNow work items, business hours). Staging never pages
(severity floor sev3). Recovery notifications are part of the standard
message contract.
