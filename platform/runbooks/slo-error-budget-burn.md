# Runbook: SLO Error Budget Burn

## Purpose and affected service
This runbook covers every `slo-burn` archetype monitor. The alert means the
error budget of the linked SLO (tag `slo_id`) is burning faster than
sustainable: at the alerted rate the monthly budget is exhausted early.

## Customer and business impact
Burn-rate alerts are the platform's primary customer-impact signal. A `fast`
(1h/5m, 14.4x) page means active, severe customer impact right now. A `slow`
(6h/30m, 6x) page means sustained degradation. A `warn` (24h/2h, 3x) ticket
means the objective is at risk this month without intervention.

## SLO and current error-budget status
Open the SLO from the `slo_id` tag in the alert (Service Mgmt → SLOs). Check
remaining error budget and the burn-down chart before anything else — it tells
you how much time you have.

## Likely causes and dependencies
1. A deployment in the last 4h (most common — the enrichment workflow attaches
   recent deploys to this event).
2. A dependency failure: check the correlated `app-dependency-degradation`
   alerts sharing this event's `correlation_key`.
3. Infrastructure/platform degradation: check the domain dashboard linked from
   the monitor.

## Validation and diagnostic steps
1. Confirm both burn windows are above threshold (rules out a short blip).
2. Identify which SLI component is failing (errors vs latency vs freshness).
3. Scope: one service/region/group, or platform-wide? Compare monitor groups.

## Safe remediation steps
- Deployment-correlated: roll back the deployment (see Rollback).
- Dependency-correlated: engage the owning team via the correlated alert; do
  not restart the affected service blindly.
- Capacity-correlated: scale out using the service's documented scaling
  runbook; scaling actions above 2x require owner approval.

## Rollback instructions
Use the service's standard deployment rollback (CI/CD "rollback" action on the
last release). Verify burn rate drops below 1x within two evaluation windows.

## Escalation path
Ack within the severity SLA. Auto-escalation follows the team escalation
policy (responder → full rotation → team management). For fast-burn on tier1,
the `auto-major-incident` workflow has already opened a Datadog incident —
join its channel.

## Links to relevant telemetry and recent changes
- The triggering monitor and its groups (from the alert).
- Domain dashboard `Domain — <domain>`; on-call dashboard for correlation.
- Change events: the enrichment workflow output attached to this event.
