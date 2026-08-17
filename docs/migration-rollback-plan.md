# Migration & Rollback Plan

Context (see current-state assessment): the org holds a previous platform
generation — 21 SLOs, 63 runbooks, 18 workflows, 5 dashboards, 22 catalog
services — but **zero monitors**, and four monitor-type SLOs point at deleted
monitor IDs. Existing working resources are preserved and adopted; nothing is
deleted.

## Phases

**M0 — Baseline snapshot (before anything).** Export all SLOs, notebooks,
workflows, dashboards via API to a dated archive branch. This is the rollback
reference.

**M1 — Foundation apply (additive only).** Teams, notification rules,
downtimes, dashboards, RBAC. Foundation creates new objects; the 5 surviving
dashboards remain untouched until reviewed for retirement (they are not
managed and not deleted).

**M2 — Coverage apply in shadow mode.** First apply runs with
`environments=["staging"]` only, then prod with paging verified against a
test channel. Monitors are created muted-by-downtime for 48h ("shadow
window") while alert volume and group cardinality are observed (C11 check +
monitor-groups API).

**M3 — SLO adoption.** `adopt_existing_slos=true` activates the gated
`import` blocks: the four broken monitor-type SLOs
(`slo-cloud-azure-platform`, `slo-infra-database-availability`,
`slo-infra-identity-availability`, `slo-infra-storage-availability`) are
imported into state.

**M4 — SLO membership repair.** The same apply rewrites their `monitor_ids`
to the rebuilt archetype monitors (`member_archetypes` in `slos.yaml`) —
this is the fix for the "no valid monitors found" failures. Metric/time-slice
survivor SLOs stay referenced by ID (`adopted_slos`), unmodified.

**M5 — Workflow adoption.** `adopt_existing_workflows=true` imports the 18
workflows by UUID (registry: `platform/policy/workflows.yaml`). Until then
they run unmanaged but unmodified; monitors already reference them by
`automation_ref` tag either way.

**M6 — Runbook reconciliation.** `publish_runbooks.py --check` reports which
of the 63 surviving notebooks match templates in `platform/runbooks/`; content
is migrated into markdown templates incrementally, newest-touched first. Until
migrated, notebooks are adopted read-only via the ID registry.

**M7 — Unshadow + telemetry gaps.** Remove the shadow downtime; open the
three telemetry-gap tickets found in assessment (DG-1 backup metrics, DG-2
cert metrics, DG-3 security notification metrics — SLOs exist but their
custom-metric producers are silent; C13 tracks them until green).

## Rollback

- **Any phase:** `terraform apply` of the previous commit (state-backed, so
  removal of newly created objects is exact). Monitors carry
  `managed_by:terraform` — a scoped emergency mute
  (`downtime scope:"managed_by:terraform"`) silences the entire new estate in
  one action without deleting anything.
- **Imported objects (M3–M5):** `terraform state rm` detaches them without
  deletion — the org returns to exactly its pre-migration configuration
  (imports never mutated them until M4; M4's membership rewrite is reversible
  by re-applying the archived SLO definitions from M0).
- **Runbooks:** publisher restores from the M0 archive (`PUT` with archived
  cells).

## Verification per phase

Each phase ends with: idempotency plan (exit code 0), coverage report
delta review, and — for M2/M7 — the end-to-end alert path test described in
`docs/evidence-report.md` (synthetic trigger → page → ack → escalate →
workflow → recovery).
