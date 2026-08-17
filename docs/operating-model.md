# Operating Model & Ownership

## Who owns what

| Component | Owner | Change path |
|---|---|---|
| Policy hierarchy, archetype catalog, modules, stacks | observability-platform | PR + CI + approval gate |
| Self-service manifests (`platform/monitors/`) | requesting team | PR; CI validates; platform reviews only exceptions |
| Service registrations (`platform/services/`) | owning team | PR; tier changes reviewed by the platform team |
| Runbook content | the archetype's owning team | PR to `platform/runbooks/`; the publisher deploys |
| On-call rosters (`oncall_members`) | each team | tfvars from IdP sync — never edited by hand |
| Exceptions | requesting team + approver | PR; approver recorded; expiry enforced by CI |
| Coverage findings | the team named in the report | 14-day SLA for C2 (unowned); next business day for C9 (click-ops) |
| Alert quality | domain owners | Monthly review; below-C monitors retuned or deleted after two cycles |

## Cadences

- **Every PR** — 23 CI stages, including the live Datadog validation gate.
- **On merge to main** — promote to qa + stage automatically; production behind
  the `datadog-production` approval environment, concurrency-locked.
- **Daily 06:00 UTC** — drift detection (Terraform + runbook content hash).
- **Weekdays 07:00 UTC** — coverage & compliance report + quality scorecard. A
  red run opens a governance issue automatically.
- **Monthly** — alert-quality review with domain owners: pages per team, top 20
  noisiest monitors, actionability rate, auto-resolved rate.
- **Quarterly** — exception re-approval sweep; RBAC access review; archetype
  catalog review; tier re-validation for tier0 and tier1.

## Change safety rules

1. **Nothing is deployed outside Terraform and the runbook publisher.**
   Click-ops objects are detected within a day (C9) and either imported or
   deleted.
2. **Secrets.** Only `svc-observability-terraform` (deploy) and
   `svc-observability-coverage` (read) service-account keys, held in the CI
   secret store and injected as environment variables. Personal API keys are
   never used, never pasted into a channel, and never written to the repository.
   gitleaks scans every PR.
3. **Destructive changes** — more than 10 monitor deletions, or any SLO
   deletion — require the plan artifact attached to the PR and a second
   reviewer.
4. **Maintenance** uses recurring, tag-scoped downtimes (`modules/downtime`).
   Regulated scopes additionally require a change ticket recorded on the window.
5. **Break-glass.** The Platform Administrator role is held by ≤3 humans, is
   audit-logged, and every use is reconciled back into code within 24 hours —
   the nightly drift job catches anything forgotten.
6. **Budgets are raised deliberately.** The monitor, paging and P1 budgets in
   `global.yaml` are plan-time assertions. Raising one is a reviewed PR with a
   stated reason, not a side effect of adding archetypes.

## On-call & escalation

Derived entirely from the priority model and tier policy:

| | Ack | Escalate | Chain |
|---|---|---|---|
| P1 | 5 min | 10 min | primary → secondary → team lead → incident commander |
| P2 (paging) | 10 min | 20 min | primary → secondary → team lead |
| P3 | 4 h | next day | team channel → team lead |
| P4 | — | — | reviewed in aggregate |

Non-production never pages. Recovery notifications are part of the standard
message contract at every priority.

## Incident response flow

```
Monitor fires
   → workflow attaches diagnostics automatically (diagnostic_only, every alert)
   → correlation groups it with related alerts; change events attach as context
   → notification rules resolve tags → Teams + ServiceNow + On-Call
   → responder opens the runbook linked in the alert
   → remediation: manual, approval-gated, or fully automatic per blast radius
   → recovery notification; correlation group closes when all children recover
   → error-budget impact recorded against the SLO
```

## When the platform itself is the problem

Seven archetypes in the `platform` domain watch the monitoring estate: managed
monitor budget exceeded, click-ops monitors detected, telemetry ingest degraded,
expired exceptions, unowned-resource backlog, shared platform service
unavailable, CI/CD pipeline failing. They are owned by observability-platform
and route like any other domain.

The highest-leverage of these is `ingest-pipeline-degraded`: a 40% collapse in
custom-metric ingest means a large part of the estate has gone dark. It is what
stops "all green" from meaning "all blind".
