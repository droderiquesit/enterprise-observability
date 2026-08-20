# Observability survey

**This survey is deliberately short, and most of it will not apply to you.**

Its job is to surface *exceptions* — the handful of facts about your service
that no amount of telemetry or policy can tell us. It is not an exercise in
designing your monitoring: that is already decided. You declare six tags
(`env`, `service`, `team`, `tier`, `service_archetype`, plus `version` from your
pipeline) and the platform derives your domain, owner, alert band, monitor
packs, priorities, routing, runbooks and SLOs from
[`platform/policy/`](../platform/policy). See
[the golden path](golden-path.md) — that is the part you do not have to think
about.

So there is no question here asking what you want to monitor, what threshold to
use, or which channel to alert. Every one of those is derived, and asking you
would invite an answer that contradicts the policy and then has to be argued
back down.

**Sixteen questions. Most teams answer four of them and skip the rest.**

| Field | |
|---|---|
| **When** | Once at onboarding, then at the annual tier review, or whenever an answer changes |
| **Who answers** | The service owner, in one sitting — not a workshop |
| **Where it goes** | Answers that change platform behaviour become entries in `platform/entities/<name>.yaml`, `platform/policy/exceptions.yaml`, or a Datadog downtime. Everything else is context recorded on the Service Catalog entry |
| **How long** | If it takes more than 20 minutes, something is wrong with the survey, not with you |

Each question states **why it cannot be inferred**. If you can show that one of
them *is* inferable from telemetry we already collect, that question gets
deleted — that is the standing rule for this document, and it is how the survey
stays sixteen questions long instead of growing to sixty.

---

## A. Impact — what it costs when this breaks

### 1. When this service is completely down, what stops for a customer or for the business?

*One or two sentences. Plain language, not metrics.*

> **Why we cannot infer it.** Telemetry proves a service stopped responding. It
> cannot say whether that means an order was not placed, a report was late, or
> nobody noticed until Tuesday. Every priority, page and error-budget policy in
> the platform hangs off this sentence, and it is the only input to the tier
> decision that is genuinely a business judgement.

### 2. Is there a time of day, week or month when the impact of an outage is materially worse?

*Examples: month-end close, market open, the nightly settlement window, payroll.*

> **Why we cannot infer it.** Traffic seasonality is visible in the data;
> *consequence* seasonality is not. A quiet 2am window can be the most expensive
> hour of the month if that is when a batch has to complete. This drives
> maintenance-window placement and change-freeze scheduling.

### 3. Is this service in regulatory or audit scope, and what data classification does it handle?

*If yes, name the regime (SOX, PCI, HIPAA, GDPR, internal audit).*

> **Why we cannot infer it.** Compliance scope is a legal determination. It
> moves the service onto the `regulated` monitoring profile, changes retention
> and access, and makes several otherwise-optional checks mandatory — none of
> which can be guessed from a metric.

---

## B. Reality — the parts of your system we cannot see

### 4. What does this service depend on that would NOT appear in APM, logs or metrics?

*Examples: a mainframe, an SFTP drop, a partner file feed, a manual step, a
Control-M job, a vendor batch, a shared spreadsheet.*

> **Why we cannot infer it.** Dependency discovery sees what is instrumented.
> An uninstrumented dependency is invisible by definition, and it is
> disproportionately where real incidents start — precisely because nothing was
> watching it.

### 5. Who depends on you in a way we would not see in traces?

*Examples: a team that reads your database directly, a nightly export somebody
built, a partner polling an endpoint.*

> **Why we cannot infer it.** Same reason as question 4, in the other
> direction. This is what makes a "low-tier internal service" turn out to be
> load-bearing at the worst moment.

### 6. Is anything about this service scheduled to change materially in the next two quarters?

*Migration, decommission, re-platforming, major version, region move.*

> **Why we cannot infer it.** Intent is not in telemetry. A service being
> retired in six weeks should not have a full monitoring pack, an SLO and a
> runbook built for it; a service about to triple in traffic should have its
> capacity forecasts reviewed before, not after.

---

## C. Response — what should actually happen at 3am

### 7. Should a failure of this service wake someone outside business hours?

*Yes / No / Only for these specific conditions.*

> **Why we cannot infer it.** The platform derives a `support_model` from your
> tier, and that derivation is right most of the time. This question exists to
> catch the cases where it is wrong in the expensive direction: a tier2 service
> that genuinely must be recovered overnight, or a tier1 service where waking
> somebody achieves nothing because the fix needs a vendor who opens at 9am.

### 8. If we page your team at 3am, who actually answers — and what happens if they do not?

*Name the rotation, not a person. If there is no rotation, say so.*

> **Why we cannot infer it.** `teams.yaml` records the escalation chain the
> platform will follow. It cannot verify that a human agreed to carry that
> pager. A paging monitor owned by a team with no real rotation is a page into
> the void, and it looks fully covered on every report until the night it
> matters. (This is exactly what `ops-oncall-coverage` reports on — but the
> report can only check that the *policy* is complete, not that it is true.)

### 9. What can a responder safely do without you?

*Restart, fail over, scale up, drain, roll back — and what they must never do
alone.*

> **Why we cannot infer it.** This is the difference between a runbook that
> resolves an incident and one that says "escalate to the owning team". The
> platform generates the diagnostic half of every runbook automatically; the
> remediation half needs your permission, and nothing in the telemetry grants it.

### 10. Are there conditions that look alarming and are known to be fine?

*Examples: nightly batch spikes CPU to 100%, the queue always backs up during
the 6am load, restarts during a rolling deploy are normal.*

> **Why we cannot infer it.** An anomaly baseline learns that a spike is
> *usual*. It cannot learn that it is *acceptable*. These answers become
> scheduled downtimes or recorded exceptions instead of being rediscovered as
> false pages by whoever is on call that week.

---

## D. Correctness — where "up" is not the same as "working"

### 11. Can this service be fully available and still be wrong?

*Examples: it serves stale data, it silently drops a message class, it returns
200 with an empty result.*

> **Why we cannot infer it.** Availability and latency are generic and the
> platform monitors them for you. Correctness is domain-specific: only you know
> that a report delivered on time with yesterday's numbers is a worse failure
> than one that did not arrive at all. If the answer is yes, we add a
> correctness or freshness signal — which is a monitor, not a survey follow-up.

### 12. Does this service emit any custom metric that our monitoring would depend on?

*Name it, and say who deploys the thing that produces it.*

> **Why we cannot infer it.** A custom metric that has never been emitted is
> indistinguishable from one whose producer is broken: both are absent. This is
> the single most common cause of an SLO that looks healthy and is measuring
> nothing, and it is why `telemetry_dependency` exists in the SLO catalog.

### 13. Is there anywhere the agent cannot be installed, or telemetry cannot leave?

*Appliances, vendor-managed hosts, air-gapped segments, licensing limits.*

> **Why we cannot infer it.** From the outside, "no agent by policy" and "agent
> failed to install" look identical: a host with no data. Declaring the first
> one means the second stops being invisible.

---

## E. Recovery — only if you have a DR position

*Skip this section entirely unless your service is tier0 or tier1.*

### 14. What is the agreed recovery time and recovery point for this service?

*RTO / RPO, or "never formally agreed" — which is itself a useful answer.*

> **Why we cannot infer it.** These are commitments, not measurements. We can
> observe how long a recovery took; we cannot observe how long it was allowed
> to take.

### 15. Is failover automatic, manual, or untested?

> **Why we cannot infer it.** A replica that exists is not a failover that
> works. Telemetry shows the standby is healthy, not that anyone has ever
> promoted it successfully or knows how.

### 16. What did your previous monitoring get wrong that you do not want repeated?

*The alert you muted. The dashboard nobody opened. The page that always came
too late.*

> **Why we cannot infer it.** This is institutional memory, and it is the
> highest-value question on the page. It is asked last because it is the one
> people answer honestly once they have stopped worrying that the survey is a
> test.

---

## What happens to your answers

| Answer | Where it lands | Effect |
|---|---|---|
| 1, 2 | tier decision, `platform/entities/<name>.yaml` | Alert band, paging, SLO scope, error-budget policy |
| 3 | `compliance_scope` on the service | Moves to the `regulated` monitoring profile |
| 4, 5, 12 | Service Catalog dependencies, `telemetry_dependency` on the SLO | Correlation, and an honest gap instead of a silent one |
| 6 | Review date on the catalog entry | Stops us building a full pack for something being retired |
| 7, 8 | `support_model`, on-call rotation | Whether anything pages, and where it goes |
| 9, 10 | Runbook remediation sections, scheduled downtimes, `exceptions.yaml` | Fewer false pages, faster real ones |
| 11 | A correctness or freshness archetype | The failure availability monitoring cannot see |
| 13 | Recorded telemetry exception | "No agent by policy" stops looking like "agent broken" |
| 14, 15 | Runbook recovery section, DR review | Recovery expectations written down before they are needed |
| 16 | The alert-quality review backlog | We do not rebuild the thing you already learned to ignore |

## What this survey deliberately does not ask

Stated plainly, because the questions people expect are the ones most worth
justifying the absence of:

- **"What do you want to monitor?"** — derived from `service_archetype` via the
  archetype packs. Asking would invite an answer that contradicts policy.
- **"What threshold should we use?"** — predictive detection derives its own
  baseline; fixed thresholds require a written rationale and platform review.
- **"Which channel should alerts go to?"** — resolved from `team` + `priority`
  by the notification rules. No monitor in this platform contains a destination.
- **"Which dashboards do you need?"** — almost certainly none. Per-service views
  are Datadog-native (Service Catalog, APM, Infrastructure, SLO list) and there
  are three custom dashboards in the entire platform (ADR-010).
- **"How critical is this, 1 to 5?"** — a self-assessed number with no
  definition behind it. Question 1 asks for the consequence instead, and the
  tier is derived from that by someone who has to defend the derivation.
