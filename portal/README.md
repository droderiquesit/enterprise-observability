# Executive real-time web portal

Requirement traceability **§47** (home view), **§48** (progressive drilldown),
**§49** (live reads, freshness, SSO, read-only role).

A single page that tells a non-technical executive four things, in the order
they are actually asked:

> **Is anything broken right now?** → **Are we meeting our promises?**
> → **What is about to break?** → **Do we even have eyes on it?**

This is **not** another engineering dashboard, and it is not related to the
(deliberately minimal) Datadog dashboards in `stacks/foundation`. Those are for
operators. This is for the people who fund the platform and have to answer for
it, and it is designed so they never have to learn Datadog to read it.

---

## Run it

```bash
# offline — the default. No credentials, no network, deterministic.
python portal/server.py
# → http://127.0.0.1:8787/

# live — reads the Datadog org. Credentials stay server-side.
export DD_API_KEY=…  DD_APP_KEY=…      # svc-observability keys, never personal
python portal/server.py --live
```

`--live` without both keys **exits with an error** rather than quietly serving
recorded data under a live label. An executive reading a snapshot that says
"live" is the worst thing this application could do.

| Environment variable | Default | Purpose |
|---|---|---|
| `DD_API_KEY`, `DD_APP_KEY` | — | required by `--live`; read server-side only |
| `DD_SITE` | `https://api.datadoghq.com` | Datadog API endpoint |
| `DD_APP_SITE` | `https://app.datadoghq.com` | base for the deep links out to Datadog |
| `PORTAL_HOST`, `PORTAL_PORT` | `127.0.0.1`, `8787` | bind address |
| `PORTAL_CACHE_TTL` | `60` | live-mode read cache, seconds (see *Caching*) |
| `PORTAL_STALE_AFTER` | `900` | when a live read is called stale |
| `PORTAL_REQUIRE_SSO` | unset | fail closed if the proxy asserts no identity |
| `PORTAL_EXEC_GROUPS` | unset | IdP groups mapped to the read-only role |
| `PORTAL_FIXTURE_REPLAY` | unset | demo aid; see *Recorded data ages* |

Tests:

```bash
python -m pytest portal/tests -q      # the portal
cd tools && python -m pytest ../tests/ -q   # the platform suite, unchanged
```

---

## What it reads

The portal **owns no data**. There is no portal database, no ETL and no second
store of truth — that would drift from the estate and be believed anyway, which
is the failure this repository exists to prevent. Three kinds of upstream:

| Source | Where from | Live? |
|---|---|---|
| `policy` | `platform/policy/*.yaml`, loaded through `tools/obs_common.py` | always local — the same loader Terraform-facing tooling uses |
| `report.coverage` | `generated/coverage_report.json` (`tools/coverage_report.py`) | falls back to `portal/fixtures/` |
| `report.reconciliation` | `generated/monitor_reconciliation.json` | falls back to `portal/fixtures/` |
| `report.scorecard` | `generated/scorecard.json` | falls back to `portal/fixtures/` |
| `datadog.slos` | `GET /api/v1/slo` | live with `--live`, else recorded |
| `datadog.incidents` | `GET /api/v2/incidents?include=commander_user` | ″ |
| `datadog.events` | `GET /api/v2/events` — the 24h raw alert window | ″ |
| `datadog.oncall` | `GET /api/v2/on-call/schedules` | ″ |
| `datadog.fleet` | `GET /api/v1/hosts` | ″ |
| `datadog.cost` | `GET /api/v2/usage/estimated_cost_by_org` | ″ |

Every response is rendered with its **origin**, **state** and **data age** in
the *Where these numbers come from* table at the foot of every view. A recorded
response is labelled `fixture` and says so; it is never labelled live.

### What is live and what is fixture

* **Fixture mode (default).** Everything under `datadog.*` is a recorded API
  response in `portal/fixtures/`. The report artifacts come from `generated/`
  if the tooling has run in this checkout, otherwise from the committed
  snapshots. Policy is always the real files.
* **Live mode (`--live`).** Everything under `datadog.*` is fetched from the
  org. Report artifacts still come from `generated/` — they are produced by
  this platform's tooling (`make coverage`), not by Datadog, and the nightly
  governance loop is what refreshes them.

The **adapters are the same in both modes**. A fixture parsed by an
offline-only code path would prove nothing about production, so
`portal/app/datadog.py` swaps the fetcher and nothing else.

### What it never writes

Nothing. Not to Datadog, not to a ticket system, not to disk.

* The HTTP layer serves **GET and HEAD**; every other method returns `405`.
* `portal/app/datadog.py` contains no verb but `GET`, and a test asserts it.
* There is no database, no cache file, no log of viewed data. The only writable
  state in the process is a bounded in-memory read cache (below).
* The browser receives `Settings.public()` — an explicit allow-list. A test
  asserts that no credential appears in any response body.

---

## What an executive sees

**Home (§47)** — one screen, in priority order:

1. **Enterprise status.** One word (Healthy / Watch / Degraded / Critical / Not
   visible), one sentence, and three counts: P1 incidents, P2 incidents,
   critical systems healthy.
2. **Reliability.** SLO attainment, error-budget state, 30-day availability,
   MTTR, MTTD, incident trend.
3. **Risk.** Objectives forecast to breach, recurring failures, capacity
   pressure, agent fleet, telemetry gaps, spend forecast. Nothing in this row
   is broken yet; all of it is on a trajectory.
4. **Coverage.** Ownership, monitoring, objectives, runbooks, on-call, agent —
   the six promises the platform makes about the estate.
5. **From noise to action.** Raw signals → correlated events → incidents, for
   the last 24 hours, with the reduction percentage.
6. **Active incidents.** Severity, business impact, probable cause, duration,
   commander, owning team, status.
7. **Systems**, then the **data-source table**.

**Drilldown (§48).** Enterprise → system → service → SLO → event/incident →
technical evidence, each level reachable from the one above:
`#/system/<domain>` → `#/service/<name>` → `#/slo/<id>` → `#/incident/<id>`.
The deepest level is one row per monitor — owner, route, escalation policy,
runbook attachment, auto-resolve window, contract status — and every row ends
in a **deep link into Datadog**. The portal does not reimplement Datadog's
graphs; it decides *what is worth looking at* and hands over.

The home page deliberately carries **no engineering graphs**. 651 monitors
exist; a test asserts the overview does not enumerate them.

---

## Design decisions worth knowing

### Why stdlib `http.server` and not FastAPI

The repository's runtime dependency list is two lines (PyYAML, requests) and
every tool runs on a bare Python. FastAPI would add starlette + pydantic +
uvicorn and their transitive tree to serve nine read-only JSON endpoints and one
HTML file — four new supply-chain surfaces for an application whose entire
threat model is *must not be able to change anything*. None of what FastAPI is
good at applies: no request bodies to validate, no auth flow to implement (auth
terminates at the proxy), no OpenAPI consumer, no async fan-out worth the
machinery. `route()` is a pure function, which is how the cost of a hand-written
router is paid back — `portal/tests/` exercises every endpoint without a socket.

If the portal ever grows a write path or a websocket, that is the moment to
revisit it. The router is ~40 lines and replaceable.

### Why no build toolchain

Three static files, no transpilation, no bundler, no `node_modules`, no
external origin. A CSP of `default-src 'none'; script-src 'self'` is achievable
because there is nothing to load from anywhere else. The cost — no JSX, no
framework state management — is not a cost for a page that renders a JSON
document and holds no state beyond the current route.

### Caching, and why the page shows data age

Datadog rate-limits per endpoint hard enough that a bulk caller in this repo has
already been 429'd on a real run (see `obs_common.dd_request`). An executive
portal is a fan-in: one open tab per viewer, all polling the same endpoints. An
unbounded pass-through would spend the org's rate-limit budget on refreshes and
starve the deploy pipeline. So **live mode only** keeps a 60-second in-memory
cache — and every cached payload carries the timestamp of the *fetch*, so the
freshness indicator reports the age of the **data**, never the age of the
request. Fixture mode has no cache; there is nothing to rate-limit.

Freshness budgets differ by kind of source, because "stale" means different
things: a live Datadog read (15 min), a nightly governance report (26 h), a
recorded snapshot (26 h). Policy files never go stale — their mtime records when
somebody edited a YAML file, which says nothing about currency.

### Degrading visibly (§49)

**An unavailable source must never render as a confident zero.** A page showing
"0 open incidents" because the incidents API returned 503 is worse than no page,
because it manufactures exactly the reassurance its reader came for.

* Every number is a `Measure` that can be `unknown`, carrying the reason.
* An unknown tile renders **hatched and dashed**, not blank and not green.
* A failed source raises a red banner naming it.
* `rollup()` keeps a running P1 as the headline while reporting blind spots
  separately — an uncomputable objective must not downgrade a SEV-1 to
  "Not visible".
* Where the platform genuinely cannot know something, the portal says so rather
  than computing a flattering number. **Agent coverage is permanently
  `unknown`** until §36/§37 ship: nothing declares which hosts are *required* to
  run an agent, and Datadog can only list hosts that already report — so any
  percentage would be 100% by construction.

### Accessibility

Status is never colour alone. Every status carries a glyph (● ◆ ▲ ■ ?) **and** a
word, so the page reads the same in greyscale, in print, and to a reader with
colour-vision deficiency. Bars and meters carry `role="img"` with the value in
the label. Contrast clears WCAG AA in both themes. Light/dark follows the system
and can be overridden; the choice persists.

### Where the numbers actually come from

Two of them are worth calling out because they are *measured*, not asserted:

* **Event reduction** is produced by running the recorded 24-hour event window
  through `tools/correlate_events.py` — the same module CI gates as the
  platform's executable correlation specification. If the correlation rules
  change, this number changes with them.
* **Probable root cause** on an incident, when the incident record does not
  carry one, is the highest-ranked signal in its correlation group, chosen by
  `platform/events/correlation-rules.yaml → root_cause_ranking`.

---

## SSO integration point (§49)

There is no identity provider in this environment, so `portal/app/auth.py` does
not pretend to authenticate anyone. What it does is make the seam real and
tested:

```
request → auth.identify(headers) → Principal → auth.authorize() → view
```

Authentication terminates at the reverse proxy in front of this process — Entra
ID application proxy, Azure Front Door with Entra authentication, or an OIDC
sidecar such as `oauth2-proxy`. The proxy validates the token and forwards the
assertion as headers; `auth.py` reads them. That split is deliberate: token
validation, key rotation and session handling are solved problems that do not
belong in a read-only view, and a hand-rolled OIDC client would be the least
reviewed security code in the repository.

**To enable it**

1. Put the portal behind the proxy and deny direct access to `PORTAL_PORT`.
2. Have the proxy inject `X-Auth-Request-Email`,
   `X-Auth-Request-Preferred-Username`, `X-Auth-Request-Groups` (all
   configurable — `PORTAL_SSO_*_HEADER`).
3. Set `PORTAL_REQUIRE_SSO=1`, so a request with no assertion is refused rather
   than falling back to the anonymous local principal.
4. Set `PORTAL_EXEC_GROUPS=<idp-group>` to map an IdP group to the read-only
   `executive_viewer` role.

The role model decides who may **look**. It cannot grant write access, because
no write path exists to grant.

---

## Recorded data ages

`portal/fixtures/*.json` carry a `_recorded_at` field (portal metadata; every
adapter ignores it) so a git checkout rewriting file mtimes cannot make a
year-old snapshot claim to be seconds old. As the snapshot ages the freshness
panel correctly reports it as stale — that is the feature working.

For a demonstration where the recorded day should play as *today*, set
`PORTAL_FIXTURE_REPLAY=1`. Every recorded timestamp is shifted forward by the
same interval, so durations and orderings are preserved exactly and only the
anchor moves — and the freshness panel says **REPLAY**. It is off by default,
because a page that silently relabels old data as current is the exact failure
this portal is built to avoid.

To re-record from a live org instead, run the platform's own tooling and point
the portal at it:

```bash
cd tools && python coverage_report.py --live && python reconciliation_report.py --live
python portal/server.py --live
```

---

## Layout

```
portal/
  server.py              entry point; --live is opt-in
  requirements.txt       PyYAML + requests, both already required by tools/
  app/
    config.py            settings, paths, and the browser-visible allow-list
    sources.py           SourceResult, Measure, freshness budgets, TTL cache
    datadog.py           GET-only client + the adapters shared by both modes
    view.py              the §47 home view and the §48 drilldown model
    auth.py              SSO seam and the read-only role
    http_app.py          stdlib router, static serving, security headers
  static/                index.html, styles.css, app.js — served as written
  fixtures/              recorded API responses + report snapshots
  tests/                 offline, freshness/failure, drilldown/access, contract
```
