# 28. Migration Strategy for Existing Monitors

Two migrations are covered: the **general enterprise case** (an org full of
hand-built monitors) and the **specific state of this org**, verified live on
2026-08-17.

---

## Part 1 — The general case

### The principle

**Nothing existing is deleted until its replacement has been proven quieter.**
A migration that deletes first is a migration that gets rolled back after the
first incident nobody was paged for.

### M0 — Baseline and classify (no changes)

Export every monitor, SLO, dashboard, notebook and workflow to a dated archive
branch. That archive is the rollback reference for every later phase.

Then classify each existing monitor:

| Class | Test | Action |
|---|---|---|
| **Replaced** | An archetype in the catalog covers the same signal for the same resource class | Retire in M4 once the archetype is proven |
| **Absorbed** | The signal is covered but the existing monitor is per-resource | Retire; the grouped archetype covers all of them at once |
| **Unique** | A genuinely service-specific condition | Convert to a self-service manifest |
| **Noise** | Never actioned in 90 days, or acknowledged and ignored | **Delete.** Migrating a monitor nobody acts on migrates the problem |
| **Unowned** | No resolvable team | Park in the unowned pool with a 14-day SLA; delete if unclaimed |

Run the classification with data, not opinion:

```
sum:datadog.monitor.alert_count{*} by {monitor_id}.as_count()   # volume
                                                                # vs incidents created
```

A monitor with high volume and no incidents is noise regardless of what it
claims to detect. Expect 30–60% of a legacy estate to land in **Noise**.

### M1 — Foundation (additive only)

Apply `stacks/foundation`: teams, on-call schedules, escalation policies,
notification rules, workflows, dashboards, RBAC, service catalog. Creates only
new objects; touches nothing existing. Alerts cannot route anywhere sensible
until this is done, so it goes first.

### M2 — Tagging campaign (the real work)

Everything depends on five tags: `env`, `service`, `team`, `tier`,
`service_archetype`. Sequence:

1. Run `build_inventory.py --live` and `profile_engine.py`. The violation list
   *is* the campaign backlog.
2. Fix tagging at source — Terraform for cloud resources, Helm values for
   Kubernetes, deployment pipelines for services. Never by hand in Datadog.
3. Register tier0 and tier1 services in `platform/services/` (a business
   decision, made once).
4. Track weekly: `with_violations` and `unowned` must trend to zero.

**Do not deploy monitors before this trends down.** A monitor scoped to
`alert_band:critical` covers exactly the resources that carry the tag.

### M3 — Shadow mode

Apply `stacks/coverage` with `environments = ["qa", "stage"]` first, then
production **muted by a downtime scoped to `managed_by:terraform`** for 48–72
hours. During the shadow window measure:

- alert volume per team per day against the storm limits
- monitor group counts against the 1,000-group budget (check C11)
- overlap: which new monitors fire at the same time as which legacy monitors

The shadow window is where thresholds get tuned. Legacy monitors are still live
and still paging, so nothing is at risk.

### M4 — Cut over, one domain at a time

Per domain, in this order — least to most customer-facing:
`platform → infrastructure → vmware → network → cloud → kubernetes →
database → data → messaging → integration → application → api → security`.

For each domain:

1. Unmute the new monitors.
2. Run both for one week.
3. Compare: incidents caught by new-only, legacy-only, both.
4. Retire the legacy monitors in the **Replaced** and **Absorbed** classes.
5. Anything the legacy monitor caught that the archetype missed becomes a
   **catalog change**, not an exception — one fix, every service benefits.

### M5 — SLO adoption and membership repair

Adopt surviving SLOs by ID; rebuild monitor-type SLO membership from
`member_archetypes`. This is the step that fixes the classic failure of SLOs
pointing at deleted monitors — and it cannot regress, because membership is
derived from the catalog on every apply.

### M6 — Self-service conversion

Convert the **Unique** class to manifests. Expect the count to be small: in a
1,000-monitor legacy estate, typically 10–30 are genuinely unique. Each
conversion is one YAML file and one PR.

### M7 — Lock the door

1. Remove `monitors_write` from every human role; only
   `svc-observability-terraform` retains it.
2. Check C9 (click-ops monitors) becomes a **hard failure** rather than a
   report line.
3. Enable the nightly drift job.
4. Open telemetry-gap tickets for any SLO whose producers are silent (C13).

### Rollback, at every phase

| Situation | Action |
|---|---|
| Any phase | `terraform apply` of the previous commit — state-backed, so removal is exact |
| Emergency, whole estate | One scoped downtime: `scope:"managed_by:terraform"` silences every new monitor without deleting anything |
| Imported objects | `terraform state rm` detaches without deleting; the org returns to its pre-migration configuration |
| Runbooks | The publisher restores from the M0 archive (`PUT` with archived cells) |
| A retired legacy monitor was needed | Restore from the M0 export; then fix the catalog so it is covered properly |

### Anti-patterns

- **Big-bang cutover.** Domain-by-domain, with a comparison week each.
- **Migrating noise.** If it was never actioned, delete it.
- **Per-resource monitors "just for now".** They become permanent, and they are
  the exact thing this framework exists to remove.
- **Skipping the tagging campaign.** Everything downstream silently under-covers.
- **Threshold exceptions to make the noise stop.** Fix the archetype.

---

## Part 2 — This org: what remains after the first deployment

The platform deployed end-to-end on 2026-08-18 (deploy run #24, green): 657
managed resources across foundation, qa, stage and prod, 152 published runbook
notebooks, idempotent second plan, coverage 100% of the alertable estate. The
pre-deployment snapshot of this org lives in
[docs/archive/2026-08-17-live-estate-reconciliation.md](archive/2026-08-17-live-estate-reconciliation.md).

What is still open, and who can do it:

| Item | Action | Who |
|---|---|---|
| ~18 legacy workflow automations (2026-08-07 experiment) hold the org's workflow quota | Delete in the Datadog UI, then raise `workflow_budget` in `stacks/foundation/budget.auto.tfvars` (ADR-017) | Their owning login — CI gets 403 |
| 58 stale legacy notebooks (unclaimed by the registry; reported by `publish_runbooks.py` on every publish) | Review, migrate any content worth keeping into `platform/runbooks/*.md`, then retire | Platform team |
| 5 legacy hand-made dashboards | Retire once the 3 platform dashboards are reviewed | Platform team |
| Notebook IDs not yet recorded in `platform/policy/runbooks.yaml` | Run `publish_runbooks.py --write-registry` with credentials; commit | Platform team |
| Estate tagging: the org's demo services lack the five owner-applied tags (coverage check C3; the nightly governance run opens issues for this) | The tagging campaign — M2 below, still the project | Service owners |
| Backup-success SLO telemetry (`acme.backup.jobs` custom metric, C13) | Deploy the metric producer | Infrastructure team |

The M-sequence for whatever estate migrates next (a real org onboarding real
services) is Part 1 above, unchanged: tagging (M2) is always the project.
