# 25. The Golden Path — what a team actually does

## For most teams: nothing

```
Create service
      ↓
Apply 5 standard tags        env · service · team · tier · service_archetype
      ↓
Register it (one small YAML) platform/entities/<name>.yaml
      ↓
─────────────────────────────────────────────────────────────
Baseline monitors            automatic   (packs for your archetype)
SLO                          automatic   (domain SLO, or your own if tier0)
Burn-rate paging             automatic
Alert routing                automatic   (team tag → your channel + rotation)
Environment behaviour        automatic   (dev silent, qa baseline, stage/prod full)
Tier policy                  automatic   (escalation, renotify, error budget)
Runbook links                automatic
On-call routing              automatic
Ownership + service catalog  automatic
Event correlation            automatic
Predictive baselines         start learning immediately
Dashboard visibility         automatic   (Service Catalog + Datadog-native views)
```

**No monitor configuration is required.** If your telemetry carries the five
tags, the monitors that cover you already exist — you join them as a group.

The one thing a machine cannot derive is the handful of facts only you know:
what actually breaks for a customer, what you depend on that is not
instrumented, and what looks alarming but is fine. Those are the sixteen
questions in [the observability survey](observability-survey.md) — most teams
answer four of them and skip the rest.

### What registration adds over just tagging

Discovery covers everything; registration adds *intent*.

| | Tagged only | Tagged + registered |
|---|---|---|
| Covered by packs | ✓ | ✓ |
| Ownership in Datadog's catalog | inferred | declared |
| Tier | inferred from environment | **your business decision** |
| Per-service SLO (tier0) | — | ✓ |
| Appears in coverage as *owned* | ✗ (violation) | ✓ |

---

## For a genuinely unique requirement: one YAML file

```
Write platform/monitors/<name>.yaml    ~15 lines
      ↓
Open a pull request
      ↓
CI validates                            schema · policy · duplicates ·
                                        cardinality · scope · routing ·
                                        SLO · runbook · quality score ·
                                        live Datadog validation
      ↓
terraform plan posted to the PR
      ↓
Approval
      ↓
Deploy
```

You never write Terraform. You never write a Datadog notification handle. You
delete the monitor by deleting the file.

---

## Which environments alert, and how loudly

| | dev | qa | stage | prod |
|---|---|---|---|---|
| Monitors created for you | **none** | availability + telemetry health | full production set | full production set |
| Maximum priority | — | P3 | P3 | P1 |
| Pages you | never | never | never | tier-driven |
| Creates a ticket | no | ServiceNow task | ServiceNow task | ServiceNow incident |
| Where it goes | nowhere | `<your-team>-nonprod` | `<your-team>-nonprod` | `<your-team>` + rotation |

---

## FAQ

**"My dev service isn't alerting."**
By policy. `dev` instantiates zero monitors. Telemetry, dashboards, traces and
the service catalog all work normally.

**"I need a different threshold for one host."**
Not supported, by design. Thresholds are per archetype. If a host is genuinely
special it needs its own service identity, or a request manifest with
`archetype: custom` and an explicit query.

**"Can I raise my monitor to P1?"**
Only by raising your service's **tier**, which is a reviewed business decision
in the registry. A team cannot obtain a pager by editing a YAML file — the
validator rejects P1/P2 on a tier2 service and says so.

**"Why didn't this page me?"**
Probably because it is a P2 symptom. P2 pages only from SLO burn-rate monitors
and composites — signals that have *confirmed* customer impact. A single
symptom raises an incident and notifies your channel. See §3 of the reference
architecture.

**"Who gets paged?"**
Your `team` tag → your rotation, at the priority the matrix derives. Verify with
your team's schedule in Datadog On-Call.

**"I created a monitor in the UI."**
It will be flagged by check C9 within a day and either imported or deleted.
Write the YAML instead — it takes less time than the UI form.

**"The alert is noisy."**
Good — say so. Noise is a defect with an owner. Open a PR against the archetype
(everyone benefits), or an exception with a reason, an approver and an expiry.
Do not mute it.

**"I need an exception."**
Add an entry to `platform/policy/exceptions.yaml` in the same PR: scope, control,
value, reason, owner, approver, expiry. All six are mandatory. Expired
exceptions fail CI, appear in the coverage report, and trigger a runtime alert.
`threshold` is deliberately not an available control — see ADR-014.
