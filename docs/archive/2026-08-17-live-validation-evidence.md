> **ARCHIVED SNAPSHOT (2026-08-17).** Read-only validation evidence cited by
> ADR-014/ADR-015. Counts predate the burn-alert membership fix (the estate
> is 474 monitors / 44 burn monitors since) and the deployment itself —
> current evidence is the post-deploy-evidence artifact on the latest green
> deploy run. The defect classes and method described here remain accurate
> history.

# Live Validation Evidence

Executed **2026-08-17** against the live Datadog organisation using
read-only credentials. No `apply` was performed and nothing was created,
modified or deleted.

---

## 1. Terraform

| Check | Result |
|---|---|
| `terraform fmt -recursive -check` | clean |
| `terraform validate` — 10 modules | pass |
| `terraform validate` — 2 stacks | pass |
| Offline plan `stacks/coverage` | **499 resources: 476 monitors + 23 SLOs**, 0 errors |
| Offline plan `stacks/foundation` | **178 resources**: 118 notification rules, 27 workflows, 18 dashboards, 8 teams, 5 catalog entries, 2 downtimes |
| Plan-time budget assertions | pass (476 ≤ 1500 monitors · 69 ≤ 90 paging · 62 ≤ 70 P1) |

## 2. Live monitor validation — the important one

Every planned monitor submitted to `POST /api/v1/monitor/validate`:

```
live validation: 423/423 monitors valid (53 skipped — query known only after apply)
```

The 53 skipped are SLO burn-rate monitors whose queries embed an SLO ID that
does not exist until the SLO is created. Their **shape** was validated
separately against a real SLO in this org: **HTTP 200**.

### What live validation found, and what was fixed

This is the section that justifies the exercise. Six classes of defect survived
`terraform validate`, the policy linter, 85 unit tests, and a clean offline
plan — and were caught only by asking Datadog:

| # | Defect | Monitors affected | Fix |
|---|---|---|---|
| 1 | `priority` is a **reserved tag key** accepting only `p1`–`p4` | **385** | Tag value lowercased at emission; the policy model still speaks in P1–P4 |
| 2 | `support_model` is a **reserved tag key** accepting only `24x7`, `business-hours`, `best-effort` | **209** | Tier vocabulary corrected (`business_hours` → `business-hours`, `none` → `best-effort`) |
| 3 | Forecast alerts accept only `min`/`max` aggregators | 25 | All forecast queries changed from `avg(next_*)` to `max(next_*)` |
| 4 | Forecast horizons must be between 12h and 3mo | 13 | `next_2h`/`next_4h` → `next_1d` |
| 5 | **Monitor thresholds must match the number inside the query** | 27 | Automatic per-environment threshold scaling **removed** — see below |
| 6 | `new_group_delay` only applies to multi-alert monitors | 6 | Set to null when `group_by` is empty |
| 7 | Host monitors must notify on no-data | 6 | `notify_no_data: true` on `host-unavailable` |
| 8 | Warning must be strictly better than critical | 1 | Removed a `warning: 0` equal to `critical: 0` |

### The design change that came out of it

Finding #5 was not a typo — it invalidated a feature.

The environment policy originally scaled thresholds by a
`sensitivity_multiplier` so staging would be 20% more tolerant than production.
Datadog rejects that: `monitor_thresholds` must equal the numeric literal inside
the query. Making it work would mean **rewriting a number inside a query string
at plan time**, so the deployed monitor differs from the reviewed catalog entry
in a way no diff shows. (The float multiply also produced
`3.60000000000000000002`, which is its own argument.)

So automatic threshold scaling was removed, and two consequences followed:

- **Environment tolerance** is now expressed only through mechanisms that
  cannot silently disagree with the query: which bands are instantiated, the
  priority ceiling, **wider evaluation windows**, and renotify intervals.
- **`threshold` was removed as an exception control.** If a number is wrong it
  is wrong in the catalog, where changing it produces a reviewable diff — or it
  belongs in a self-service monitor with `archetype: custom` and its own
  explicit query. The self-service validator now rejects a numeric override on
  an inherited archetype and explains both options.

That is the whole argument for stage 23 of the CI pipeline: a policy linter can
only enforce rules someone thought to write down. The vendor's own validator
enforces the rules nobody knew about.

## 3. Test suite — 85/85 passing

| Group | Covers |
|---|---|
| `test_policy_model.py` (17) | priority derivation, the environment-can-only-quieten property over the whole matrix, paging discipline, budgets, predictive ratio, every archetype reaches a real destination, the bounded-object invariant |
| `test_profile_engine.py` (13) | the golden path, tier→band, registration outranking tags, invalid tags flagged not dropped, exceptions attributed, **1.2M resources / 100k services fully assigned**, monitor count unchanged as the estate grows 100× |
| `test_coverage_report.py` (13) | run against the **real planned estate** (fixtures generated from `terraform plan`): contract clean, 100% coverage, and each seeded defect caught by the right check |
| `test_correlation.py` (10) | six-alert database cascade → 1 group, 1 page, 4 suppressed; change as context; vendor outage absorbing downstream; recovery closing only when all children recover; maintenance dropped; scope uplift |
| `test_self_service.py` (17) | the compliant manifests pass; 15 distinct rejection paths each produce a specific explanation |
| `test_quality_and_docs.py` (15) | scorecard behaviour, generated-doc staleness, runbook completeness and determinism |

## 4. Live governance loop

`build_inventory.py --live` → `profile_engine.py` → `coverage_report.py --live`:

```
inventory:          22 resources, 22 services (service catalog)
profiles:           19 standard · 2 regulated · 1 observe_only
                    22 with violations (missing owner-applied tags)
coverage:           0.0%  (0 / 21 alertable)
C1  unmonitored ....... 21      C3  missing/invalid tags ... 22
C13 SLO telemetry gap ... 1     PASS ..................... false
```

**This is the correct output.** The org has zero monitors, so coverage is zero
and the report says so. It does not round up, and it does not treat an inferred
tag as a known one: every one of the 22 services is missing the five
owner-applied tags, so the profile engine infers what it can and records a
violation for each inference.

`EXC-2026-001` matched real data — `efront_bts_int` exists in this org, so the
single resource excluded from alerting is excluded by an approved, expiring,
attributed decision rather than an oversight.

## 5. Quality scorecard

```
monitors scored   422       fleet average  96.5 (A)
distribution      A: 422    failing        0
```

## 6. Honest limitations

1. **No apply was executed.** Everything up to the API write boundary is
   verified; applies run from `deploy.yml` behind the `datadog-production`
   approval gate using `svc-observability-terraform`.
2. **On-call rosters are empty.** `oncall_members` defaults to `{}`, so
   schedules, escalation policies and On-Call routing rules plan to zero
   resources. Teams and notification rules exist; **paging is not operational
   until the IdP sync provides rosters.** This is the largest remaining gap
   between "implemented" and "working".
3. **906 runbook sections are marked `TODO(owner)`.** Every archetype has a
   runbook with all ten mandatory sections and a generated frame containing what
   a machine genuinely knows; the human sections (validation, likely causes,
   remediation) are a tracked backlog reported per domain by
   `generate_runbooks.py --report`. One fully-authored exemplar exists:
   `slo-error-budget-burn.md`.
4. **The metric names are the contract, not the reality.** Archetypes reference
   metrics that must actually exist (`acme.batch.hours_since_success`,
   `acme.data.minutes_since_update`, `acme.security.control_checks`, …). Where a
   producer is absent, check C13 tracks it and the report stays red rather than
   claiming coverage the telemetry cannot back.
5. **Provider gaps** are documented with controlled API paths: notebooks
   (ADR-006, hash-drift publisher) and event-correlation rule CRUD (ADR-007,
   deterministic keys + versioned ruleset + reference engine proven in CI).
6. **The credentials used were personal-scope keys pasted into a chat.** They
   were used read-only and were not written into the repository. Per §19 and the
   operating model, deploys must use `svc-observability-terraform` from the
   secret store; **these keys should be rotated.**
