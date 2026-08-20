/* =============================================================================
   Executive portal — the entire frontend.

   No framework, no build step, no external origin. The page is a renderer for
   what /api/* returns and holds no state of its own beyond the current route
   and the theme choice; there is nothing here that could disagree with the
   backend, because there is nothing here that decides anything.

   The one rule that shapes every function below: a value the server marked
   `known: false` is rendered as a VISIBLE GAP with the server's reason
   attached. There is no `|| 0`, no `|| "—"` that hides a missing number, and
   no default that could turn an outage into a green tile.
   ============================================================================= */
"use strict";

/* --- status vocabulary ------------------------------------------------------
   Glyph + word + colour. The glyph and the word are the accessible channels;
   colour is the third. Never remove one and rely on the others being enough. */
const GLYPH = { ok: "●", watch: "◆", risk: "▲", critical: "■",
                unknown: "?", neutral: "○" };
const WORD = { ok: "Healthy", watch: "Watch", risk: "Degraded",
               critical: "Critical", unknown: "No data", neutral: "Steady" };

const $ = (sel, root) => (root || document).querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
};

/* Everything user- or API-supplied goes through textContent, never innerHTML,
   so a service name containing markup cannot become markup. */
function frag(nodes) {
  const f = document.createDocumentFragment();
  nodes.filter(Boolean).forEach((n) => f.appendChild(n));
  return f;
}

function pill(state, text) {
  const p = el("span", `pill pill-${state || "neutral"}`);
  p.appendChild(el("span", "glyph", GLYPH[state] || GLYPH.neutral)).setAttribute(
    "aria-hidden", "true");
  p.appendChild(document.createTextNode(text || WORD[state] || state || ""));
  return p;
}

function num(v) {
  if (typeof v !== "number") return String(v);
  return v.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

/* --- data ------------------------------------------------------------------ */
let CONFIG = {};

async function api(path) {
  try {
    const r = await fetch(path, { headers: { Accept: "application/json" } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: body.error || `HTTP ${r.status}`, status: r.status };
    return { ok: true, data: body };
  } catch (e) {
    /* A network failure here means the PORTAL is unreachable, which is a
       different statement from "the estate is fine". Say the former. */
    return { ok: false, error: `the portal API could not be reached (${e.message})` };
  }
}

/* --- rendering primitives -------------------------------------------------- */

/** A measure tile. `m.known === false` produces the hatched no-data card. */
function measureCard(title, m, opts) {
  opts = opts || {};
  const card = el("div", "card" + (m && m.known === false ? " is-unknown" : ""));
  card.appendChild(el("h3", null, title));
  if (!m) {
    card.appendChild(el("div", "value", "Not reported"));
    return card;
  }
  if (m.known === false) {
    const v = el("div", "value");
    v.appendChild(pill("unknown", "No data"));
    card.appendChild(v);
    card.appendChild(el("p", "label", "This figure is not available."));
    if (m.note) card.appendChild(el("p", "note", "Why: " + m.note));
    if (m.source) card.appendChild(el("p", "src", "source: " + m.source));
    return card;
  }
  const value = el("div", "value" + (typeof m.value === "number" ? "" : " is-text"));
  value.appendChild(document.createTextNode(num(m.value)));
  if (m.unit) value.appendChild(el("span", "unit", m.unit === "USD" ? " USD" : m.unit));
  card.appendChild(value);

  const label = el("p", "label");
  label.appendChild(pill(m.state, WORD[m.state] || m.state));
  label.appendChild(document.createTextNode(" " + (m.label || "")));
  card.appendChild(label);

  if (opts.meter && typeof m.value === "number") {
    const meter = el("div", `meter state-${m.state}`);
    const bar = el("span");
    bar.style.width = Math.max(0, Math.min(100, m.value)) + "%";
    meter.appendChild(bar);
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `${num(m.value)}% — ${m.label || WORD[m.state]}`);
    card.appendChild(meter);
  }
  if (Array.isArray(m.series)) card.appendChild(spark(m.series));
  if (Array.isArray(m.items) && m.items.length) card.appendChild(itemList(m.items));
  if (m.detail) card.appendChild(detailList(m.detail));
  if (m.note) card.appendChild(el("p", "note", m.note));
  if (m.source) card.appendChild(el("p", "src", "source: " + m.source));
  return card;
}

function spark(series) {
  const max = Math.max(...series, 1);
  const wrap = el("div", "spark");
  wrap.setAttribute("role", "img");
  wrap.setAttribute("aria-label", "Weekly counts: " + series.join(", "));
  series.forEach((v) => {
    const b = el("i");
    b.style.height = Math.max(2, (v / max) * 34) + "px";
    wrap.appendChild(b);
  });
  return wrap;
}

function itemList(items) {
  const ul = el("ul", "rows");
  items.forEach((it) => {
    const li = el("li");
    const primary = it.name || it.correlation_key || it.service || it.schedule ||
                    it.id || "";
    if (it.link) {
      const a = el("a", "drill ext", primary);
      a.href = it.link;
      a.target = "_blank";
      a.rel = "noreferrer noopener";
      li.appendChild(a);
    } else {
      li.appendChild(el("span", "k", primary));
    }
    if (it.detail) li.appendChild(el("span", "k", " " + it.detail));
    const v = it.days !== undefined ? `${it.days} d`
      : it.occurrences !== undefined ? `${it.occurrences}×`
      : it.budget_remaining_pct !== undefined ? `${it.budget_remaining_pct}%` : "";
    if (v) li.appendChild(el("span", "v", v));
    ul.appendChild(li);
  });
  return ul;
}

function detailList(detail) {
  const ul = el("ul", "rows");
  Object.entries(detail).forEach(([k, v]) => {
    if (v === null || v === undefined || typeof v === "object") return;
    const li = el("li");
    li.appendChild(el("span", "k", k.replace(/_/g, " ")));
    li.appendChild(el("span", "v", num(v)));
    ul.appendChild(li);
  });
  return ul;
}

function section(title, sub, body) {
  const s = el("section");
  s.appendChild(el("h2", null, title));
  if (sub) s.appendChild(el("p", "sub", sub));
  if (body) s.appendChild(body);
  return s;
}

function grid(cls, nodes) {
  const g = el("div", `grid ${cls}`);
  nodes.filter(Boolean).forEach((n) => g.appendChild(n));
  return g;
}

function banner(text, kind) {
  const b = el("div", "banner" + (kind ? " " + kind : ""));
  b.appendChild(el("strong", null, kind === "warn" ? "Note: " : "Data problem: "));
  b.appendChild(document.createTextNode(text));
  return b;
}

/* --- freshness (§49) ------------------------------------------------------- */
function renderFreshness(freshness, sources) {
  const host = $("#freshness");
  host.textContent = "";
  if (!freshness) {
    host.appendChild(pill("unknown", "Freshness unknown"));
    return;
  }
  host.appendChild(pill(freshness.state, freshness.label));
  const age = el("span", "age",
    `oldest data ${freshness.worst_age_label}` +
    (freshness.worst_source ? ` (${freshness.worst_source})` : ""));
  host.appendChild(age);

  const origins = new Set((sources || []).map((s) => s.origin));
  if (CONFIG.mode !== "live") {
    host.appendChild(pill("neutral",
      CONFIG.fixture_replay ? "RECORDED · REPLAY" : "RECORDED DATA"));
  } else if (origins.has("fixture")) {
    host.appendChild(pill("watch", "PARTLY RECORDED"));
  } else {
    host.appendChild(pill("ok", "LIVE"));
  }
}

function sourceTable(sources) {
  const wrap = el("div", "tablewrap");
  const t = el("table");
  const head = el("tr");
  ["Source", "Origin", "State", "Data age", "Detail"].forEach((h) =>
    head.appendChild(el("th", null, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  (sources || []).forEach((s) => {
    const tr = el("tr");
    tr.appendChild(el("td", "mono", s.name));
    tr.appendChild(el("td", null, s.origin));
    const st = el("td");
    st.appendChild(pill(
      s.status === "ok" ? "ok" : s.status === "stale" ? "watch" : "critical",
      s.status === "ok" ? "Current" : s.status === "stale" ? "Stale" : "Unavailable"));
    tr.appendChild(st);
    tr.appendChild(el("td", null, s.age_label));
    tr.appendChild(el("td", null, s.error ? `${s.error} — ${s.detail || ""}` : (s.detail || "")));
    body.appendChild(tr);
  });
  t.appendChild(body);
  wrap.appendChild(t);
  return wrap;
}

/* --- home view (§47) ------------------------------------------------------- */
function renderHome(d) {
  const main = $("#main");
  main.textContent = "";
  const out = [];

  const down = (d.freshness && d.freshness.unavailable) || [];
  if (down.length) {
    out.push(banner(
      `${down.length} data source(s) could not be read (${down.join(", ")}). ` +
      "Panels that depend on them show NO DATA — they are not zero and they are " +
      "not healthy."));
  }
  if (CONFIG.mode !== "live") {
    out.push(banner(
      "This portal is running on recorded data from portal/fixtures/ — no " +
      "Datadog credentials are configured. Start it with --live for the real " +
      "estate.", "warn"));
  }

  /* 1. the headline: what an executive reads in the first two seconds. */
  const h = d.health.overall;
  const head = el("div", `headline state-${h.state}`);
  const left = el("div");
  left.appendChild(el("h2", null, "Enterprise status"));
  const word = el("div", "status-word");
  word.appendChild(el("span", "glyph", GLYPH[h.state])).setAttribute("aria-hidden", "true");
  word.appendChild(document.createTextNode(h.label));
  left.appendChild(word);
  left.appendChild(el("p", "say", h.note));
  head.appendChild(left);

  const counts = el("div", "counts");
  counts.appendChild(countBox(d.health.incidents.p1, "P1 incidents"));
  counts.appendChild(countBox(d.health.incidents.p2, "P2 incidents"));
  counts.appendChild(countBox(d.health.tier1, "Critical systems"));
  head.appendChild(counts);
  out.push(head);

  /* 2. reliability — are we meeting our promises? */
  const r = d.reliability;
  out.push(section("Reliability", "Against the objectives the organisation published.",
    grid("g3", [
      measureCard("SLO attainment", r.attainment, { meter: true }),
      measureCard("Error budget", r.error_budget),
      measureCard("Availability (30d)", r.availability),
      measureCard("Mean time to restore", r.mttr),
      measureCard("Mean time to detect", r.mttd),
      measureCard("Incident trend", r.trend),
    ])));

  /* 3. risk — what is about to break? */
  const k = d.risk;
  out.push(section("Risk", "Nothing here is broken yet. All of it is on a trajectory.",
    grid("g3", [
      measureCard("Objectives forecast to breach", k.slo_breach_forecast),
      measureCard("Recurring failures (24h)", k.recurring_issues),
      measureCard("Capacity pressure", k.capacity),
      measureCard("Agent fleet", k.fleet),
      measureCard("Telemetry gaps", k.telemetry_gaps),
      measureCard("Observability spend", k.cost),
    ])));

  /* 4. coverage — do we even have eyes on it? */
  const c = d.coverage;
  out.push(section("Coverage",
    "Six promises the platform makes about the estate. A gap here is why an " +
    "incident is found late, or by a customer.",
    grid("g3", [
      measureCard("Ownership", c.ownership, { meter: true }),
      measureCard("Monitoring", c.monitoring, { meter: true }),
      measureCard("Objectives", c.slo, { meter: true }),
      measureCard("Runbooks", c.runbook, { meter: true }),
      measureCard("On-call", c.oncall, { meter: true }),
      measureCard("Agent coverage", c.agent, { meter: true }),
    ])));

  /* 5. event reduction — noise into signal. */
  out.push(section("From noise to action (last 24 hours)",
    "The same alerts, three times: as raised, as grouped, and as escalated.",
    reductionPanel(d.event_reduction)));

  /* 6. active incidents. */
  out.push(section("Active incidents", null, incidentList(d.active_incidents)));

  /* 7. systems — the drilldown entry point. */
  out.push(section("Systems",
    "Every technology domain the platform governs. Select one to go deeper.",
    systemGrid(d.systems)));

  /* 8. data sources — the audit trail for everything above. */
  out.push(section("Where these numbers come from",
    "The portal owns no data. Each source, its origin and its age:",
    sourceTable(d.sources)));

  main.appendChild(frag(out));
}

function countBox(m, label) {
  const b = el("div", "count-box");
  if (!m || m.known === false) {
    b.appendChild(el("div", "n", "—"));
    b.appendChild(el("div", "k", label + " · no data"));
    return b;
  }
  b.appendChild(el("div", "n", num(m.value)));
  b.appendChild(el("div", "k", label));
  return b;
}

function reductionPanel(er) {
  if (!er || !er.available) {
    const c = el("div", "card is-unknown");
    c.appendChild(el("h3", null, "Event reduction"));
    const v = el("div", "value");
    v.appendChild(pill("unknown", "No data"));
    c.appendChild(v);
    c.appendChild(el("p", "note", "Why: " + ((er && er.reason) || "event stream unavailable")));
    return c;
  }
  const card = el("div", "card");
  const top = el("p", "label");
  top.appendChild(pill("ok", `${er.reduction_pct}% fewer things to look at`));
  top.appendChild(document.createTextNode(
    ` ${er.paging_events} of these were allowed to wake a human.`));
  card.appendChild(top);

  const max = Math.max(...er.stages.map((s) => s.value), 1);
  const f = el("div", "funnel");
  er.stages.forEach((s) => {
    const row = el("div", "funnel-row");
    row.appendChild(el("div", "fk", s.label));
    const bar = el("div", "fbar");
    const fill = el("span");
    fill.style.width = (s.value / max) * 100 + "%";
    bar.appendChild(fill);
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${s.label}: ${s.value}`);
    row.appendChild(bar);
    row.appendChild(el("div", "fn", num(s.value)));
    row.appendChild(el("div", "fd", s.detail));
    f.appendChild(row);
  });
  card.appendChild(f);
  card.appendChild(el("p", "note", er.note));
  card.appendChild(el("p", "src", "source: " + er.source));
  return card;
}

function incidentList(block) {
  if (!block || !block.available) {
    return banner((block && block.reason) ||
      "the incident feed is unavailable — this is NOT a statement that there are " +
      "no incidents");
  }
  if (!block.items.length) {
    const ok = el("div", "card");
    ok.appendChild(el("h3", null, "Open incidents"));
    const v = el("div", "value");
    v.appendChild(pill("ok", "None open"));
    ok.appendChild(v);
    ok.appendChild(el("p", "note",
      "Datadog Incident Management reported no incident in the active state."));
    return ok;
  }
  const g = el("div", "grid g2");
  block.items.forEach((i) => g.appendChild(incidentCard(i)));
  return g;
}

function incidentCard(i) {
  const c = el("div", `incident state-${i.state_class}`);
  const top = el("div");
  top.appendChild(pill(i.state_class, i.severity));
  top.appendChild(document.createTextNode(" "));
  top.appendChild(pill(i.customer_impacted ? "risk" : "neutral",
    i.customer_impacted ? "Customer impact" : "No customer impact recorded"));
  c.appendChild(top);
  c.appendChild(el("h3", null, i.title));

  const dl = el("dl");
  const add = (k, v) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  };
  add("Impact", i.impact);
  add("Probable cause", i.probable_cause);
  if (i.probable_cause_source) add("Cause from", i.probable_cause_source);
  add("Running for", i.duration_label);
  add("Commander", i.commander);
  add("Owning team", i.owner);
  add("Systems", i.services || "not recorded");
  if (i.correlated_signals) add("Signals grouped", String(i.correlated_signals));
  c.appendChild(dl);

  const nav = el("p");
  const drill = el("a", "drill", "Evidence and timeline →");
  drill.href = `#/incident/${encodeURIComponent(i.public_id || i.id)}`;
  nav.appendChild(drill);
  if (i.link) {
    nav.appendChild(document.createTextNode("  "));
    const ext = el("a", "drill ext", "Open in Datadog");
    ext.href = i.link;
    ext.target = "_blank";
    ext.rel = "noreferrer noopener";
    nav.appendChild(ext);
  }
  c.appendChild(nav);
  return c;
}

function systemGrid(systems) {
  if (!systems || !systems.length) return el("p", "empty", "No system reported.");
  const g = el("div", "grid gsys");
  systems.forEach((s) => {
    const card = el("div", "card" + (s.state === "unknown" ? " is-unknown" : ""));
    const a = el("a", "drill", s.name);
    a.href = `#/system/${encodeURIComponent(s.id)}`;
    card.appendChild(el("h3")).appendChild(a);
    const p = el("p", "label");
    p.appendChild(pill(s.state, WORD[s.state]));
    if (s.critical) {
      p.appendChild(document.createTextNode(" "));
      p.appendChild(pill("neutral", "Business critical"));
    }
    card.appendChild(p);
    card.appendChild(el("p", "note", s.reason));
    const ul = el("ul", "rows");
    [["Objectives", s.slo_count], ["Open incidents", s.incident_count],
     ["Systems", s.service_count],
     ["Monitors", s.monitor_count === null ? "not reported" : s.monitor_count],
     ["Monitor quality", s.monitor_grade
       ? `${s.monitor_grade.grade} (${s.monitor_grade.average})` : "not graded"]]
      .forEach(([k, v]) => {
        const li = el("li");
        li.appendChild(el("span", "k", k));
        li.appendChild(el("span", "v", num(v)));
        ul.appendChild(li);
      });
    card.appendChild(ul);
    card.appendChild(el("p", "src", "owner: " + (s.owner || "unassigned")));
    g.appendChild(card);
  });
  return g;
}

/* --- drilldown views (§48) ------------------------------------------------- */
function sloTable(slos, caption) {
  if (!slos || !slos.length) return el("p", "empty", caption || "No objective here.");
  const wrap = el("div", "tablewrap");
  const t = el("table");
  const head = el("tr");
  ["Objective", "State", "Target", "Current", "Budget left", "Owner", ""].forEach((h) =>
    head.appendChild(el("th", null, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  slos.forEach((s) => {
    const tr = el("tr");
    const nameCell = el("td");
    const a = el("a", "drill", s.name);
    a.href = `#/slo/${encodeURIComponent(s.slo_id)}`;
    nameCell.appendChild(a);
    nameCell.appendChild(el("div", "src", s.slo_id));
    tr.appendChild(nameCell);
    const st = el("td");
    st.appendChild(pill(s.state, WORD[s.state]));
    st.appendChild(el("div", "src", s.state_reason || ""));
    tr.appendChild(st);
    tr.appendChild(el("td", "num", s.target === null ? "—" : `${s.target}%`));
    tr.appendChild(el("td", "num", s.sli === null ? "not computable" : `${num(s.sli)}%`));
    tr.appendChild(el("td", "num",
      s.error_budget_remaining_pct === null || s.error_budget_remaining_pct === undefined
        ? "—" : `${num(s.error_budget_remaining_pct)}%`));
    tr.appendChild(el("td", null, s.team || "—"));
    const link = el("td");
    if (s.link) {
      const ext = el("a", "drill ext", "Datadog");
      ext.href = s.link;
      ext.target = "_blank";
      ext.rel = "noreferrer noopener";
      link.appendChild(ext);
    }
    tr.appendChild(link);
    body.appendChild(tr);
  });
  t.appendChild(body);
  wrap.appendChild(t);
  return wrap;
}

function monitorTable(monitors) {
  if (!monitors || !monitors.length) {
    return el("p", "empty",
      "No monitor rows available. The reconciliation report has not been " +
      "generated, or nothing here is monitored — the two are different, and the " +
      "data-source table above says which.");
  }
  const wrap = el("div", "tablewrap");
  const t = el("table");
  const head = el("tr");
  ["Monitor", "Env", "Sev", "Pages", "Owner", "Route", "Runbook", "Auto-resolve",
   "Contract", ""].forEach((h) => head.appendChild(el("th", null, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  monitors.slice(0, 200).forEach((m) => {
    const tr = el("tr");
    tr.appendChild(el("td", null, m.name));
    tr.appendChild(el("td", null, m.env));
    tr.appendChild(el("td", null, m.priority));
    tr.appendChild(el("td", null, m.pages ? "yes" : "no"));
    tr.appendChild(el("td", null, m.owner));
    tr.appendChild(el("td", null, m.route));
    tr.appendChild(el("td", null, `${m.runbook} (${m.attachment})`));
    tr.appendChild(el("td", null, m.auto_resolve));
    const st = el("td");
    st.appendChild(pill(m.status === "PASS" ? "ok" : "risk", m.status));
    tr.appendChild(st);
    const link = el("td");
    if (m.link) {
      const ext = el("a", "drill ext", "Datadog");
      ext.href = m.link;
      ext.target = "_blank";
      ext.rel = "noreferrer noopener";
      link.appendChild(ext);
    }
    tr.appendChild(link);
    body.appendChild(tr);
  });
  t.appendChild(body);
  wrap.appendChild(t);
  return wrap;
}

function renderSystem(d) {
  const main = $("#main");
  main.textContent = "";
  const s = d.system;
  const out = [];
  const head = el("div", `headline state-${s.state}`);
  const left = el("div");
  left.appendChild(el("h2", null, "System"));
  const word = el("div", "status-word");
  word.appendChild(el("span", "glyph", GLYPH[s.state])).setAttribute("aria-hidden", "true");
  word.appendChild(document.createTextNode(s.name));
  left.appendChild(word);
  left.appendChild(el("p", "say", s.reason));
  head.appendChild(left);
  const counts = el("div", "counts");
  [["Objectives", s.slo_count], ["Open incidents", s.incident_count],
   ["Services", s.service_count], ["Monitors", s.monitor_count]].forEach(([k, v]) => {
    const b = el("div", "count-box");
    b.appendChild(el("div", "n", v === null ? "—" : num(v)));
    b.appendChild(el("div", "k", k));
    counts.appendChild(b);
  });
  head.appendChild(counts);
  out.push(head);

  if (d.errors && d.errors.slos) out.push(banner(d.errors.slos));

  out.push(section("Objectives", null, sloTable(d.slos)));
  out.push(section("Open incidents", null,
    d.incidents && d.incidents.length
      ? frag(d.incidents.map((i) => incidentCard({
          ...i,
          state_class: i.state_class || "watch",
          impact: i.impact || "not recorded",
          probable_cause: i.probable_cause || "not recorded",
          owner: i.teams || "unassigned",
          commander: i.commander || "unassigned",
        })))
      : el("p", "empty", "No incident is open against this system.")));
  out.push(section("Services", null, serviceTable(d.services)));
  out.push(section("Failure domains",
    "The correlation vocabulary for this system — what an event here is grouped by.",
    el("p", "mono", (s.failure_domains || []).join(" · ") || "none declared")));
  out.push(section("Where these numbers come from", null, sourceTable(d.sources)));
  main.appendChild(frag(out));
}

function serviceTable(services) {
  if (!services || !services.length) {
    return el("p", "empty", "No service is registered against this system.");
  }
  const wrap = el("div", "tablewrap");
  const t = el("table");
  const head = el("tr");
  ["Service", "State", "Kind", "Tier", "Team", "Objectives", ""].forEach((h) =>
    head.appendChild(el("th", null, h)));
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  services.forEach((s) => {
    const tr = el("tr");
    const c = el("td");
    const a = el("a", "drill", s.name);
    a.href = `#/service/${encodeURIComponent(s.name)}`;
    c.appendChild(a);
    tr.appendChild(c);
    const st = el("td");
    st.appendChild(pill(s.state, WORD[s.state]));
    tr.appendChild(st);
    tr.appendChild(el("td", null, (s.kind || "").replace(/_/g, " ")));
    tr.appendChild(el("td", null, s.tier || "not declared"));
    tr.appendChild(el("td", null, s.team || "—"));
    tr.appendChild(el("td", "num", num(s.slo_count)));
    const link = el("td");
    if (s.link) {
      const ext = el("a", "drill ext", "Datadog");
      ext.href = s.link;
      ext.target = "_blank";
      ext.rel = "noreferrer noopener";
      link.appendChild(ext);
    }
    tr.appendChild(link);
    body.appendChild(tr);
  });
  t.appendChild(body);
  wrap.appendChild(t);
  return wrap;
}

function renderService(d) {
  const main = $("#main");
  main.textContent = "";
  const s = d.service;
  const out = [];
  const head = el("div", `headline state-${s.state}`);
  const left = el("div");
  left.appendChild(el("h2", null, "Service"));
  const word = el("div", "status-word");
  word.appendChild(el("span", "glyph", GLYPH[s.state])).setAttribute("aria-hidden", "true");
  word.appendChild(document.createTextNode(s.name));
  left.appendChild(word);
  left.appendChild(el("p", "say", s.description ||
    `${(s.kind || "").replace(/_/g, " ")} owned by ${s.team || "an unassigned team"}.`));
  head.appendChild(left);
  const counts = el("div", "counts");
  [["Tier", s.tier || "not declared"], ["Team", s.team || "unassigned"],
   ["Objectives", (d.slos || []).length], ["Monitors", (d.monitors || []).length]]
    .forEach(([k, v]) => {
      const b = el("div", "count-box");
      b.appendChild(el("div", "n", typeof v === "number" ? num(v) : v));
      b.appendChild(el("div", "k", k));
      counts.appendChild(b);
    });
  head.appendChild(counts);
  out.push(head);

  out.push(section("Objectives", null, sloTable(d.slos)));
  out.push(section("Incidents", null,
    d.incidents && d.incidents.length
      ? frag(d.incidents.map((i) => incidentCard({
          ...i, state_class: i.state_class || "watch",
          impact: i.impact || "not recorded",
          probable_cause: i.probable_cause || "not recorded",
          owner: i.teams || "unassigned",
          commander: i.commander || "unassigned",
        })))
      : el("p", "empty", "No incident recorded against this service.")));
  out.push(section("Technical evidence",
    "Every monitor that defends this service, with its owner, route, runbook " +
    "and contract status. This is the deepest level the portal renders — " +
    "the graphs live in Datadog.",
    monitorTable(d.monitors)));
  out.push(section("Where these numbers come from", null, sourceTable(d.sources)));
  main.appendChild(frag(out));
}

function renderSlo(d) {
  const main = $("#main");
  main.textContent = "";
  const s = d.slo;
  const out = [];
  const head = el("div", `headline state-${s.state}`);
  const left = el("div");
  left.appendChild(el("h2", null, "Objective"));
  const word = el("div", "status-word");
  word.appendChild(el("span", "glyph", GLYPH[s.state])).setAttribute("aria-hidden", "true");
  word.appendChild(document.createTextNode(s.name));
  left.appendChild(word);
  left.appendChild(el("p", "say", s.state_reason || ""));
  head.appendChild(left);
  const counts = el("div", "counts");
  [["Target", s.target === null || s.target === undefined ? "—" : s.target + "%"],
   ["Current", s.sli === null || s.sli === undefined ? "not computable" : num(s.sli) + "%"],
   ["Budget left", s.error_budget_remaining_pct === null ||
     s.error_budget_remaining_pct === undefined
     ? "—" : num(s.error_budget_remaining_pct) + "%"],
   ["Exhausted in", s.days_to_exhaustion === null || s.days_to_exhaustion === undefined
     ? "no trend" : `${Math.round(s.days_to_exhaustion)} d`]].forEach(([k, v]) => {
    const b = el("div", "count-box");
    b.appendChild(el("div", "n", v));
    b.appendChild(el("div", "k", k));
    counts.appendChild(b);
  });
  head.appendChild(counts);
  out.push(head);

  if (s.telemetry_dependency) {
    out.push(banner("Declared telemetry dependency: " + s.telemetry_dependency, "warn"));
  }
  if (s.link) {
    const p = el("p");
    const a = el("a", "drill ext", "Open this objective in Datadog");
    a.href = s.link;
    a.target = "_blank";
    a.rel = "noreferrer noopener";
    p.appendChild(a);
    out.push(p);
  }
  if (d.event_groups && d.event_groups.length) {
    out.push(section("Events that consumed this budget", null,
      frag(d.event_groups.map(groupCard))));
  }
  out.push(section("Monitors defending this objective", null, monitorTable(d.monitors)));
  out.push(section("Where these numbers come from", null, sourceTable(d.sources)));
  main.appendChild(frag(out));
}

function groupCard(g) {
  const c = el("div", "card");
  const p = el("p", "label");
  p.appendChild(pill(g.priority === "P1" ? "critical" : g.priority === "P2" ? "risk" : "watch",
    g.priority));
  p.appendChild(document.createTextNode(" " + g.parent));
  c.appendChild(p);
  const ul = el("ul", "rows");
  [["Correlation key", g.correlation_key],
   ["Signals suppressed under this cause", g.suppressed],
   ["Creates an incident", g.creates_incident ? "yes" : "no"],
   ["Group closed", g.closed ? "yes" : "no"]].forEach(([k, v]) => {
    const li = el("li");
    li.appendChild(el("span", "k", k));
    li.appendChild(el("span", "v", String(v)));
    ul.appendChild(li);
  });
  c.appendChild(ul);
  if (g.children && g.children.length) {
    c.appendChild(el("p", "note", "Symptoms: " + g.children.join(" · ")));
  }
  if (g.context && g.context.length) {
    c.appendChild(el("p", "note", "Change context: " + g.context.join(" · ")));
  }
  if (g.link) {
    const a = el("a", "drill ext", "Open the event group in Datadog");
    a.href = g.link;
    a.target = "_blank";
    a.rel = "noreferrer noopener";
    c.appendChild(el("p")).appendChild(a);
  }
  return c;
}

function renderIncident(d) {
  const main = $("#main");
  main.textContent = "";
  const i = d.incident;
  const out = [];
  const head = el("div", `headline state-${i.state_class || "watch"}`);
  const left = el("div");
  left.appendChild(el("h2", null, `Incident ${i.public_id || ""}`));
  const word = el("div", "status-word");
  word.appendChild(el("span", "glyph", GLYPH[i.state_class || "watch"]))
    .setAttribute("aria-hidden", "true");
  word.appendChild(document.createTextNode(i.severity));
  left.appendChild(word);
  left.appendChild(el("p", "say", i.title));
  head.appendChild(left);
  const counts = el("div", "counts");
  [["State", i.state], ["Running", i.duration_label],
   ["Commander", i.commander || "unassigned"],
   ["Owner", i.teams || "unassigned"]].forEach(([k, v]) => {
    const b = el("div", "count-box");
    b.appendChild(el("div", "n", v));
    b.appendChild(el("div", "k", k));
    counts.appendChild(b);
  });
  head.appendChild(counts);
  out.push(head);

  const facts = el("div", "card");
  const dl = el("dl");
  const add = (k, v) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v || "not recorded"));
  };
  add("Business impact", i.impact);
  add("Probable cause", i.probable_cause);
  add("Systems", i.services);
  add("Opened", i.created);
  add("Detected", i.detected);
  add("Resolved", i.resolved || "still open");
  facts.appendChild(dl);
  out.push(section("What is happening", null, facts));

  out.push(section("Correlated evidence",
    "What the platform grouped under this cause, and the changes attached as " +
    "context.",
    d.correlation ? groupCard(d.correlation)
      : el("p", "empty",
        "No correlation group matched this incident's key in the last 24 hours.")));
  out.push(section("Monitors on the affected systems", null, monitorTable(d.monitors)));
  if (i.link) {
    const p = el("p");
    const a = el("a", "drill ext", "Open the incident in Datadog");
    a.href = i.link;
    a.target = "_blank";
    a.rel = "noreferrer noopener";
    p.appendChild(a);
    out.push(p);
  }
  out.push(section("Where these numbers come from", null, sourceTable(d.sources)));
  main.appendChild(frag(out));
}

/* --- routing --------------------------------------------------------------- */
const ROUTES = [
  [/^#\/system\/(.+)$/, (m) => ({ api: `/api/systems/${m[1]}`, render: renderSystem,
    crumbs: (d) => [["Enterprise", "#/"], [d.system.name, null]] })],
  [/^#\/service\/(.+)$/, (m) => ({ api: `/api/services/${m[1]}`, render: renderService,
    crumbs: (d) => [["Enterprise", "#/"],
      [d.service.domain || "System", d.service.domain ? `#/system/${d.service.domain}` : null],
      [d.service.name, null]] })],
  [/^#\/slo\/(.+)$/, (m) => ({ api: `/api/slos/${m[1]}`, render: renderSlo,
    crumbs: (d) => [["Enterprise", "#/"],
      [d.slo.domain || "System", d.slo.domain ? `#/system/${d.slo.domain}` : null],
      [d.slo.service || "Service", d.slo.service ? `#/service/${d.slo.service}` : null],
      [d.slo.name, null]] })],
  [/^#\/incident\/(.+)$/, (m) => ({ api: `/api/incidents/${m[1]}`, render: renderIncident,
    crumbs: (d) => [["Enterprise", "#/"],
      [`Incident ${d.incident.public_id || ""}`, null]] })],
];

function renderCrumbs(items) {
  const nav = $("#crumbs");
  nav.textContent = "";
  items.forEach((entry, idx) => {
    const [label, href] = entry;
    if (idx) nav.appendChild(el("span", "sep", "›"));
    if (href) {
      const a = el("a", null, label);
      a.href = href;
      nav.appendChild(a);
    } else {
      nav.appendChild(el("span", "here", label));
    }
  });
}

function fail(message) {
  const main = $("#main");
  main.textContent = "";
  main.appendChild(banner(message));
  main.appendChild(el("p", "empty",
    "Nothing on this page should be read as a status while this error stands. " +
    "An empty portal is not a healthy estate."));
  renderFreshness({ state: "critical", label: "Portal could not load data",
                    worst_age_label: "unknown" }, []);
}

/* Two things the router has to get right beyond fetching:

   1. Moving to a NEW view clears the old one first. Leaving the previous page
      on screen while the next loads is how somebody reads last week's system
      as this one — the same class of mistake as a stale number with no age.
   2. An in-place refresh (the 60s timer, the Refresh button) must NOT blank
      the page; it replaces content only once the new content has arrived.

   `NAVIGATION` also discards a response whose navigation has been superseded,
   so a slow view cannot overwrite the faster one the reader is now looking at.
*/
let NAVIGATION = 0;
let RENDERED_HASH = null;

async function router() {
  const hash = location.hash || "#/";
  const token = ++NAVIGATION;
  const isNewView = hash !== RENDERED_HASH;
  if (isNewView) {
    const main = $("#main");
    main.textContent = "";
    main.appendChild(el("p", "loading", "Loading…"));
  }

  for (const [re, build] of ROUTES) {
    const m = hash.match(re);
    if (!m) continue;
    const route = build(m.map(decodeURIComponent));
    const res = await api(route.api);
    if (token !== NAVIGATION) return;          /* a newer navigation won */
    if (!res.ok) return fail(res.error);
    renderCrumbs(route.crumbs(res.data));
    route.render(res.data);
    renderFreshness(res.data.freshness, res.data.sources);
    RENDERED_HASH = hash;
    if (isNewView) $("#main").focus();
    return;
  }
  const res = await api("/api/overview");
  if (token !== NAVIGATION) return;
  if (!res.ok) return fail(res.error);
  renderCrumbs([["Enterprise", null]]);
  renderHome(res.data);
  renderFreshness(res.data.freshness, res.data.sources);
  RENDERED_HASH = hash;
}

/* --- theme ----------------------------------------------------------------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("portal-theme", theme); } catch (e) { /* private mode */ }
}

function cycleTheme() {
  const order = ["auto", "light", "dark"];
  const current = document.documentElement.getAttribute("data-theme") || "auto";
  applyTheme(order[(order.indexOf(current) + 1) % order.length]);
}

/* --- boot ------------------------------------------------------------------ */
async function boot() {
  try {
    const saved = localStorage.getItem("portal-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
  } catch (e) { /* private mode: keep the automatic theme */ }

  const session = await api("/api/session");
  if (session.ok) {
    CONFIG = session.data.config || {};
    const p = session.data.principal || {};
    $("#session").textContent =
      `signed in as ${p.display_name || "unknown"} · role ${p.role} · ` +
      `read-only ${p.read_only ? "yes" : "no"} · ` +
      `SSO ${session.data.sso_required ? "required" : "not enforced in this deployment"}`;
  } else {
    $("#session").textContent = "session could not be read: " + session.error;
  }

  $("#refresh").addEventListener("click", router);
  $("#theme").addEventListener("click", cycleTheme);
  window.addEventListener("hashchange", router);
  await router();

  /* Auto-refresh. Slower than the server's live cache TTL on purpose: polling
     faster than the cache only ages the page, it does not freshen it. */
  const period = Math.max(30, (CONFIG.cache_ttl_seconds || 60)) * 1000;
  setInterval(router, period);
}

boot();
