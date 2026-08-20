const L = require("./lib");
const { C, HEAD_FONT, BODY_FONT, M, W, CW } = L;
const { divider } = require("./part1");

function build(pptx) {
  // ------------------------------------------------------------ 44 appendix div
  divider(pptx, {
    part: "APPENDIX",
    title: "The detail\nbehind the deck",
    strap: "Every table someone in the room is about to ask for, plus a full register of what this deck does not claim.",
    first: 1,
    topics: [
      "Requirement traceability scorecard",
      "The estate by domain",
      "Priority and paging mix",
      "Detection mix",
      "Environment policy matrix",
      "Routing matrix",
      "SLO catalog and burn windows",
      "Coverage checks C1–C17",
      "The tagging contract",
      "What this deck does not claim",
      "Evidence and sources",
    ],
    notes: `The appendix is reference material. I will not walk through it — it is here so that the answer to a detailed question is a slide rather than a promise to follow up.`,
  });

  // --------------------------------------------------- 45 traceability scorecard
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A1",
      title: "Requirement traceability scorecard",
      sub: "60 requirement sections, audited against the repository and the live estate — not against memory of what was built. Every MISSING row was confirmed by a repository-wide search that returned zero matches.",
      notes: `The audit method matters as much as the result. Every section was checked against the repository AND the last production deploy's evidence artifact — 651 monitors, 22 SLOs, 111 notification rules, 261 runbooks. Nothing is recorded as MISSING because it could not be found quickly; each MISSING row was confirmed by a repository-wide search returning zero matches.

The shape of the result: strong on the monitor to SLO to routing to runbook spine. Absent on the product surfaces — MCP server, executive portal, survey — and on fleet and agent operations and Control-M.`,
    });
    const groups = [
      ["1–3", "Audit, completion discipline, technology scope", "OK", C.teal],
      ["4", "Payments removal", "resolved", C.teal],
      ["5–7", "Catalog and entity modelling", "PARTIAL", C.amber],
      ["8", "Unified tagging", "PARTIAL + MISSING (CI/CD metadata)", C.red],
      ["9–10", "YAML as source of intent", "OK + PARTIAL", C.amber],
      ["11–15", "SLOs", "PARTIAL · one MISSING (monitor→SLO relation)", C.amber],
      ["16–18", "Profiles, single-file monitors, predictive-first", "OK · one IMPROVE", C.teal],
      ["19–23", "Coverage by technology", "OK · one IMPROVE (VMware HA/DRS)", C.teal],
      ["24", "Control-M", "MISSING — zero files", C.red],
      ["25–30", "Events, incidents, on-call, routing, ServiceNow", "PARTIAL · OK on routing and ServiceNow", C.amber],
      ["31–35", "Runbooks, workflows, dashboards, reports, survey", "OK on runbooks · two MISSING", C.amber],
      ["36–41", "Fleet, agents, telemetry requirements, scorecards", "MISSING on fleet and agent profiles", C.red],
      ["42–46", "MCP server", "MISSING — zero files", C.red],
      ["47–50", "Executive surfaces", "MISSING — this deck closes §50", C.red],
      ["51–57", "Outcomes, SOPs, CI/CD, RBAC, architecture", "OK on SOPs and RBAC · PARTIAL elsewhere", C.amber],
      ["58–60", "Deliverables, proofs, acceptance", "PARTIAL — 38 of 62 acceptance criteria met", C.amber],
    ];
    groups.forEach((g, i) => {
      const c = i % 2, r = Math.floor(i / 2);
      const x = M + c * 6.1, y = 2.3 + r * 0.5;
      s.addShape("roundRect", { x, y, w: 5.85, h: 0.46, rectRadius: 0.04, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addText("§" + g[0], { x: x + 0.14, y, w: 0.75, h: 0.48, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(g[1], { x: x + 0.92, y, w: 2.85, h: 0.48, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: C.body, valign: "middle" });
      s.addText(g[2], { x: x + 3.8, y, w: 1.95, h: 0.48, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: g[3], align: "right", valign: "middle" });
    });
    const tot = [["21", "OK"], ["9", "IMPROVE"], ["12", "PARTIAL"], ["15", "MISSING"], ["2", "N/A"]];
    tot.forEach((t, i) => {
      const x = M + i * 2.43;
      s.addShape("roundRect", { x, y: 6.32, w: 2.25, h: 0.56, rectRadius: 0.05, fill: { color: C.ink }, line: { color: C.ink } });
      s.addText(t[0], { x: x + 0.2, y: 6.32, w: 0.8, h: 0.56, margin: 0, fontSize: 20, bold: true, fontFace: HEAD_FONT, color: C.amber, valign: "middle" });
      s.addText(t[1], { x: x + 1.0, y: 6.32, w: 1.1, h: 0.56, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: "9FADC4", valign: "middle" });
    });
  }

  // ------------------------------------------------------ 46 estate by domain
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A2",
      title: "The estate by domain",
      sub: "651 monitor instances across 14 technology domains, from the plan-derived fixture that CI regenerates on every change.",
      notes: `This is every managed monitor grouped by domain, taken from the plan fixture that CI regenerates — so it cannot drift from what Terraform actually deploys.

Cloud and database dominate, which is what you would expect from an Azure estate with SQL Server, Azure SQL, Cosmos and Snowflake in it. The counts are archetype times environment times alert band, not per-resource — every one of these covers every matching resource in the estate as a group.`,
    });
    const data = [
      { name: "Monitor instances", labels: ["Cloud", "Database", "Application", "Kubernetes", "Infrastructure", "Messaging", "Integration", "Network", "Data platform", "API", "SaaS", "Security", "VMware", "Platform"], values: [105, 102, 85, 54, 47, 41, 37, 37, 36, 33, 22, 21, 18, 13] },
    ];
    s.addChart(pptx.ChartType.bar, data, {
      x: M, y: 2.2, w: 7.6, h: 4.4,
      barDir: "bar", barGapWidthPct: 45,
      chartColors: [C.amber],
      showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.body, dataLabelFontSize: 10, dataLabelFontFace: BODY_FONT,
      showLegend: false, showTitle: false,
      catAxisLabelColor: C.body, catAxisLabelFontSize: 10.5, catAxisLabelFontFace: BODY_FONT,
      valAxisLabelColor: C.muted, valAxisLabelFontSize: 9, valAxisMaxVal: 120,
      valGridLine: { color: "EDF0F4", size: 1 }, catGridLine: { style: "none" },
      valAxisLineShow: false, catAxisLineShow: false,
    });

    L.cards(s, [
      { t: "Counts are decisions, not resources", b: "Each bar is archetype × environment × alert band. One instance covers every matching resource in the estate as a group inside it." },
      { t: "Owned by seven teams", b: "cloud 200 · data 138 · sre 105 · infrastructure 102 · application-development 69 · security 24 · observability-platform 13." },
      { t: "Regenerated, never typed", b: "The figures come from tests/fixtures/monitors_planned.json, rebuilt from the actual Terraform plan and staleness-gated in CI." },
    ], { x: M + 8.0, y: 2.2, w: 4.1, cols: 1, h: 1.5, rgap: 0.2, bodySize: 10.5, titleSize: 12.5 });
  }

  // -------------------------------------------------- 47 priority + paging mix
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A3",
      title: "Priority and paging mix",
      sub: "Priority states the required human response. Paging is a separate, narrower rule — which is why 141 P2s produce only a handful of pages.",
      notes: `The priority distribution: 69 P1, 141 P2, 351 P3, 90 P4.

Then the paging rule cuts across it. Seventy monitors may page — production, critical band, and either P1 or a confirmed-impact source. That is why 141 P2s do not produce 141 pagers: a P2 raised by a lone symptom creates an incident and a ticket and wakes nobody.

Both numbers are budgeted at plan time: 90 paging monitors maximum, 85 P1 monitors maximum. Growth is a reviewed pull request.`,
    });
    s.addChart(pptx.ChartType.doughnut, [
      { name: "Priority", labels: ["P3 — next business day", "P2 — rapid response", "P4 — informational", "P1 — major outage"], values: [351, 141, 90, 69] },
    ], {
      x: M, y: 2.2, w: 5.6, h: 4.2,
      chartColors: ["9AA8BD", C.amber, "D6DDE6", C.red],
      holeSize: 55, showLegend: true, legendPos: "b", legendColor: C.body, legendFontSize: 11, legendFontFace: BODY_FONT,
      showValue: true, dataLabelColor: "FFFFFF", dataLabelFontSize: 11, dataLabelFontFace: BODY_FONT,
      showTitle: false,
    });

    const facts = [
      { t: "70 of 651 may page", b: "11% of the estate. Requires prod + the critical band + either P1 or a confirmed-impact source (burn rate or composite)." },
      { t: "Budgeted at plan time", b: "max_paging_monitors: 90 and max_p1_monitors: 85 are hard plan-time checks. Raising one is a reviewed PR with a reason." },
      { t: "By impact class", b: "degradation 262 · customer_impact 168 · risk 151 · hygiene 70 — crossed with the band, clamped by the env ceiling." },
      { t: "By environment", b: "prod 445 · stage 171 · qa 20 · dev 15. Dev is P4 and informational; non-production never pages, in any configuration." },
    ];
    L.cards(s, facts, { x: M + 6.25, y: 2.2, w: 5.85, cols: 1, h: 1.08, rgap: 0.08, bodySize: 10.5, titleSize: 12.5 });
  }

  // -------------------------------------------------------------- 48 detection
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A4",
      title: "Detection mix",
      sub: "258 of 651 instances — 40% — use predictive detection. Every fixed threshold that remains carries a written rationale, and CI rejects the ones that do not.",
      notes: `Forty percent of instances use predictive detection: anomaly, seasonal anomaly, forecast, outlier or rate of change. Add the SLO burn-rate monitors and it is nearly half.

Fixed thresholds survive where the number itself is the operational contract — a certificate expiry, an SLA, a quota, a protocol limit, a DLQ depth. Every one of them carries a rationale_fixed_threshold in the catalog, and the policy linter rejects any that does not, whether or not the signal is behavioural. The test suite additionally asserts that predictive instances outnumber fixed ones by at least 0.6 times, so the ratio cannot quietly erode.

The two canonical replacements are worth remembering: CPU greater than 80% becomes an anomaly against the host's own normal, because a batch node at 95% on schedule is healthy and an API node at 55% when it normally runs at 20% is not. And disk greater than 90% becomes a three-day linear forecast, because a volume steady at 92% for two years is not an incident and a volume at 60% growing 8% a day is.`,
    });
    s.addChart(pptx.ChartType.bar, [
      { name: "Instances", labels: ["Threshold (with rationale)", "Anomaly", "Forecast", "Rate of change", "SLO burn rate", "Service check", "Event", "Composite", "Seasonal anomaly", "Outlier"], values: [312, 141, 61, 48, 41, 25, 8, 7, 5, 3] },
    ], {
      x: M, y: 2.25, w: 7.3, h: 4.3,
      barDir: "bar", barGapWidthPct: 45,
      chartColors: [C.slate],
      showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.body, dataLabelFontSize: 10, dataLabelFontFace: BODY_FONT,
      showLegend: false, showTitle: false,
      catAxisLabelColor: C.body, catAxisLabelFontSize: 10.5, catAxisLabelFontFace: BODY_FONT,
      valAxisLabelColor: C.muted, valAxisLabelFontSize: 9, valAxisMaxVal: 350,
      valGridLine: { color: "EDF0F4", size: 1 }, catGridLine: { style: "none" },
      valAxisLineShow: false, catAxisLineShow: false,
    });

    s.addShape("roundRect", { x: M + 7.7, y: 2.25, w: 4.4, h: 2.05, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("BEFORE", { x: M + 7.95, y: 2.4, w: 3.9, h: 0.26, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: "8E9DB5", charSpacing: 1.4 });
    s.addText("CPU > 80%", { x: M + 7.95, y: 2.66, w: 3.9, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: "Courier New", color: "8E9DB5", valign: "middle" });
    s.addText("AFTER", { x: M + 7.95, y: 3.02, w: 3.9, h: 0.26, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.4 });
    s.addText("anomalies(avg:system.cpu.user{...}\n  by {cluster,host}, 'agile', 3)", { x: M + 7.95, y: 3.28, w: 3.9, h: 0.55, margin: 0, fontSize: 10.5, fontFace: "Courier New", color: C.paper, valign: "top" });
    s.addText("A batch node at 95% on schedule is healthy. An API node at 55% when it normally runs at 20% is not.", { x: M + 7.95, y: 3.85, w: 3.9, h: 0.4, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "AEBACD", valign: "top" });

    s.addShape("roundRect", { x: M + 7.7, y: 4.5, w: 4.4, h: 2.05, rectRadius: 0.07, fill: { color: C.tint }, line: { color: C.tint } });
    s.addText("BEFORE", { x: M + 7.95, y: 4.65, w: 3.9, h: 0.26, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: C.muted, charSpacing: 1.4 });
    s.addText("disk > 90%", { x: M + 7.95, y: 4.91, w: 3.9, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: "Courier New", color: C.muted, valign: "middle" });
    s.addText("AFTER", { x: M + 7.95, y: 5.27, w: 3.9, h: 0.26, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: C.amberDeep, charSpacing: 1.4 });
    s.addText("forecast(avg:system.disk.in_use{...},\n  'linear', 1) over next_3d > 0.95", { x: M + 7.95, y: 5.53, w: 3.9, h: 0.55, margin: 0, fontSize: 10.5, fontFace: "Courier New", color: C.text, valign: "top" });
    s.addText("A volume steady at 92% for two years is not an incident. One at 60% growing 8% a day is.", { x: M + 7.95, y: 6.1, w: 3.9, h: 0.4, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.body, valign: "top" });
  }

  // ------------------------------------------------------- 49 environment policy
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A5",
      title: "Environment policy matrix",
      sub: "The same archetype definition runs in every environment. The environment never changes what is detected — only how loud the result is.",
      notes: `The same definition is used everywhere. The environment changes loudness, never detection.

Dev instantiates only fifteen baseline liveness monitors, all P4, all informational, and routes nowhere. QA is release-blocking only, at the baseline band, capped at P3. Stage is production-shaped at P3. Production is the full set.

Three design notes. Environments can only ever make a signal quieter — there is no code path anywhere that raises a priority in a non-production environment, and that is asserted as a property test over the whole matrix. Evaluation windows widen instead of thresholds moving: last_15m in production becomes last_30m in stage and QA. And thresholds are never rewritten anywhere, because scaling an anomaly threshold silently changes the algorithm — it is a deviation count, not a value.

The one sanctioned exception is the release gate: a tier0 release-gate archetype in stage may reach P2 and notify the release channel during an active release window, so a bad release is stopped before production. It still never pages, and it is currently not provisioned — it waits on the release-window signal from the deployment pipeline.`,
    });
    const cols = ["", "DEV", "QA", "STAGE", "PROD"];
    const table = [
      ["Alerting", "informational only", "release-blocking only", "production-shaped", "full"],
      ["Bands instantiated", "baseline", "baseline", "standard, critical", "baseline, standard, critical"],
      ["Monitors instantiated", "15", "20", "171", "445"],
      ["Priority ceiling", "P4", "P3", "P3", "P1"],
      ["Pages", "never", "never", "never", "tier-driven"],
      ["Incident creation", "no", "no", "no", "P1, P2"],
      ["ServiceNow", "no", "Task", "Task", "Incident"],
      ["Teams channel", "no", "<team>-nonprod", "<team>-nonprod", "<team>"],
      ["Counts toward the SLO", "no", "no", "no", "yes"],
      ["Evaluation window", "—", "×2", "×1.5", "×1.0"],
    ];
    const colX = [M + 0.2, M + 3.5, M + 5.5, M + 7.6, M + 9.9];
    const colW = [3.2, 1.9, 2.0, 2.2, 2.1];
    s.addShape("rect", { x: M, y: 2.3, w: CW, h: 0.44, fill: { color: C.ink }, line: { color: C.ink } });
    cols.forEach((c, j) => {
      s.addText(c, { x: colX[j], y: 2.3, w: colW[j], h: 0.44, margin: 0, fontSize: 11, bold: true, fontFace: BODY_FONT, color: j === 4 ? C.amber : C.paper, valign: "middle" });
    });
    table.forEach((r, i) => {
      const y = 2.74 + i * 0.38;
      if (i % 2 === 0) s.addShape("rect", { x: M, y, w: CW, h: 0.38, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      r.forEach((cell, j) => {
        s.addText(cell, { x: colX[j], y, w: colW[j], h: 0.38, margin: 0, fontSize: 10.5, bold: j === 0, fontFace: BODY_FONT, color: j === 0 ? C.text : (j === 4 ? C.text : C.body), valign: "middle" });
      });
    });
    s.addText("Environments only make a signal quieter — no code path raises a priority outside production. Windows widen; thresholds are never rewritten anywhere (ADR-014).", { x: M, y: 6.6, w: CW, h: 0.34, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: C.muted, valign: "top" });
  }

  // ------------------------------------------------------------- 50 routing
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A6",
      title: "Routing matrix",
      sub: "Monitors contain no destinations. 111 notification rules resolve notification profile × priority × pages × team into Teams, ServiceNow and On-Call.",
      notes: `Six profiles cover the entire enterprise, and 111 notification rules implement them. Adding a team adds its routing automatically; adding a monitor adds none.

The security routing decision is worth calling out: security signals route to the security team regardless of who owns the resource, because the responder is not the owner. The owning team is notified in parallel for context, never as the primary responder — and it is expressed as a domain-level routing override so it cannot be forgotten on an individual monitor.

The release-gate profile is defined but not provisioned: it waits on the release-window signal from the deployment pipeline, so no dead notification rules exist in the meantime.`,
    });
    const prof = [
      ["production_critical", "prod + critical band", "Page + SEV-1 + SNOW P1 + team channel + major-incident + exec", C.red],
      ["production_standard", "prod + standard band", "SEV-2 + SNOW P2 + team channel — no page", C.amber],
      ["production_baseline", "prod + baseline band", "Low-noise channel; SNOW when sustained", C.slate],
      ["nonprod_standard", "qa or stage", "<team>-nonprod + ServiceNow task. Never pages", C.slate],
      ["security_operational", "domain: security", "Pages security + SEV-1 + SNOW P1, owner cc'd for context", C.red],
      ["release_gate", "stage + tier0 + release window", "Release channel + SNOW task. Defined, not yet provisioned", C.muted],
    ];
    prof.forEach((p, i) => {
      const y = 2.35 + i * 0.66;
      s.addShape("roundRect", { x: M, y, w: CW, h: 0.58, rectRadius: 0.05, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addText(p[0], { x: M + 0.2, y, w: 3.1, h: 0.58, margin: 0, fontSize: 11.5, bold: true, fontFace: "Courier New", color: p[3], valign: "middle" });
      s.addText(p[1], { x: M + 3.4, y, w: 3.0, h: 0.58, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
      s.addText(p[2], { x: M + 6.5, y, w: 5.4, h: 0.58, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.body, valign: "middle" });
    });

    s.addText(
      [
        { text: "111 notification rules", options: { bold: true } },
        { text: " = 18 routing rows × the teams each applies to. Adding a team adds its routing automatically; adding a monitor adds none. Where a team's P1s go is one line in teams.yaml and touches zero monitors — no monitor contains a destination string anywhere in the estate.", options: {} },
      ],
      { x: M, y: 6.42, w: CW, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "top" }
    );
  }

  // --------------------------------------------------------------- 51 SLO catalog
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A7",
      title: "SLO catalog and burn windows",
      sub: "21 domain objectives cover tier1 and tier2 across the whole estate; tier0 services each add their own. 22 SLOs today, driving 41 burn-rate monitors.",
      notes: `The twenty-one domain SLOs. A grouped SLI query covers every service in the domain, which is what keeps the count bounded — the alternative, one SLO per service, is twenty-seven thousand objectives that nobody reviews.

Tier0 services add their own on top. Today that is one service, identity-api, giving twenty-two objectives and forty-one burn-rate monitors.

Which windows apply comes from the tier: tier0 gets fast, medium and slow; tier1 gets fast and slow; tier2 gets slow only. Fast and medium page. Slow raises a ticket. Trend is informational.`,
    });
    const slos = ["app-availability", "app-latency", "web-availability", "worker-throughput", "api-availability", "api-latency", "k8s-workload-availability", "infra-compute-availability", "infra-backup-success", "vmware-cluster-availability", "cloud-platform-availability", "database-availability", "database-latency", "data-freshness", "messaging-delivery", "network-availability", "security-telemetry", "external-dependency", "integration-delivery", "batch-completion", "platform-services"];
    slos.forEach((sl, i) => {
      const c = i % 3, r = Math.floor(i / 3);
      const x = M + c * 4.1, y = 2.32 + r * 0.46;
      s.addShape("roundRect", { x, y, w: 3.87, h: 0.4, rectRadius: 0.04, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addText("slo-" + sl, { x: x + 0.16, y, w: 3.6, h: 0.4, margin: 0, fontSize: 10.5, fontFace: "Courier New", color: C.body, valign: "middle" });
    });

    s.addShape("roundRect", { x: M, y: 5.7, w: 5.85, h: 0.95, rectRadius: 0.06, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("+ one per tier0 service", { x: M + 0.28, y: 5.82, w: 5.3, h: 0.3, margin: 0, fontSize: 12.5, bold: true, fontFace: BODY_FONT, color: C.amber, valign: "middle" });
    s.addText("Today: identity-api. Total 22 objectives → 41 burn-rate monitors. Infrastructure carries no SLO, deliberately — a host has no customer-facing objective; the service on it does.", { x: M + 0.28, y: 6.08, w: 5.3, h: 0.56, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "AEBACD", valign: "top" });

    const burn = [["fast", "1h / 5m · 14.4×", "PAGE"], ["medium", "6h / 30m · 6×", "PAGE"], ["slow", "24h / 2h · 3×", "ticket"], ["trend", "72h / 6h · 1×", "informational"]];
    burn.forEach((b, i) => {
      const x = M + 6.25 + (i % 2) * 2.95, yy = 5.65 + Math.floor(i / 2) * 0.48;
      s.addShape("roundRect", { x, y: yy, w: 2.8, h: 0.42, rectRadius: 0.04, fill: { color: i < 2 ? C.tintWarm : "F5F7FA" }, line: { color: i < 2 ? C.tintWarm : "F5F7FA" } });
      s.addText(b[0] + "  " + b[1], { x: x + 0.14, y: yy, w: 2.0, h: 0.42, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(b[2], { x: x + 2.05, y: yy, w: 0.65, h: 0.42, margin: 0, fontSize: 8.5, bold: true, fontFace: BODY_FONT, color: i < 2 ? C.red : C.muted, align: "right", valign: "middle" });
    });
    s.addText("tier0 gets fast + medium + slow · tier1 fast + slow · tier2 slow only", { x: M + 6.25, y: 6.62, w: 5.85, h: 0.3, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
  }

  // ------------------------------------------------------- 52 coverage checks
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A8",
      title: "Coverage checks C1–C17",
      sub: "Every check maps to a promise the framework makes. A red report is a governance incident for the platform team, not a warning.",
      notes: `Seventeen runtime checks against the live organisation. Three of them gate the production deploy — the platform-integrity ones — and all seventeen gate the nightly governance run, which opens a GitHub issue when it goes red.

The distinction between the two gates matters: a deploy must not go permanently red over a tag on a resource the platform does not own. Estate-hygiene findings stay in the report and are chased by the nightly run; platform-integrity findings block the deploy.

The two I would watch as a leader are C2 — resources without a resolvable owner, which has a fourteen-day SLA — and C9, click-ops monitors, which is how we detect somebody quietly creating a monitor in the UI. Both are about whether the operating model is actually being followed.`,
    });
    const checks = [
      ["C1", "Resources with an alerting band but no covering monitor pack"],
      ["C2", "Resources without a resolvable owner — 14-day SLA"],
      ["C3", "Missing or invalid required tags, on resources and monitors"],
      ["C4", "Services with no SLO association"],
      ["C5", "Monitors without a runbook"],
      ["C6", "Monitors without workflow automation"],
      ["C7", "Monitors without resolvable routing (team + priority + profile)"],
      ["C8", "Duplicate or overlapping monitors"],
      ["C9", "Unmanaged click-ops monitors — next-business-day SLA"],
      ["C10", "Resources on the wrong monitoring profile"],
      ["C11", "Cardinality risk: too many group keys, or a missing collapse key"],
      ["C12", "Expired exceptions"],
      ["C13", "SLO integrity — missing SLOs and silent telemetry"],
      ["C14", "Paging discipline: anything paging that policy says should not"],
      ["C15", "Monitors with no actionable response"],
      ["C16", "Monitors with no native runbook attachment"],
      ["C17", "Monitors with no auto-resolve window (timeout_h)"],
    ];
    checks.forEach((c, i) => {
      const col = i % 2, r = Math.floor(i / 2);
      const x = M + col * 6.1, y = 2.28 + r * 0.48;
      s.addShape("roundRect", { x, y, w: 5.85, h: 0.42, rectRadius: 0.04, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addText(c[0], { x: x + 0.16, y, w: 0.55, h: 0.42, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.amberDeep, valign: "middle" });
      s.addText(c[1], { x: x + 0.75, y, w: 5.0, h: 0.42, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.body, valign: "middle" });
    });
    s.addText("The deploy gate blocks on platform-integrity findings only; the nightly governance gate blocks on every finding and opens an issue — a deploy must not go permanently red over a tag on a resource the platform does not own.", { x: M, y: 6.55, w: CW, h: 0.38, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: C.muted, valign: "top" });
  }

  // ------------------------------------------------------- 53 tagging contract
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A9",
      title: "The tagging contract",
      sub: "Six tags on the telemetry, applied at the source. Everything else — priority, routing, runbook, SLO, escalation, on-call, auto-resolve — is derived.",
      notes: `This is the appendix slide to photograph. Six tags, and the four ways to apply them.

For hosts and VMs it is the tags block in datadog.yaml. For Azure resources it is resource tags collected by the Azure integration — and Azure Policy with a modify effect is the only mechanism that keeps them true over time. Tagging by hand at creation decays within a quarter. For Kubernetes it is the tags.datadoghq.com labels, which Datadog picks up automatically, plus DD_KUBERNETES_POD_LABELS_AS_TAGS for the remaining four. For APM and custom metrics it is the environment variables, including DD_VERSION and DD_GIT_COMMIT_SHA, which are what make deployment-to-incident correlation work.

Two more worth setting deliberately: cost_center on Azure resources, which is what makes a cost alert routable to someone who can act on it instead of to a finance inbox; and compliance_scope, which automatically promotes a service to the regulated profile.

And the banned list at the bottom — never group by an identity key. Each one turns a single alert into thousands, and the limit of three group keys is enforced at plan time, so a monitor that violates it cannot be created.`,
    });
    s.addShape("roundRect", { x: M, y: 2.3, w: 5.85, h: 1.05, rectRadius: 0.06, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("env    service    team    tier\nservice_archetype    alert_band", { x: M + 0.3, y: 2.4, w: 5.3, h: 0.85, margin: 0, fontSize: 15, bold: true, fontFace: "Courier New", color: C.amber, valign: "middle", lineSpacingMultiple: 1.1 });

    const srcs = [
      ["Agent — datadog.yaml", "tags:\n  - env:prod\n  - service:orders-sql\n  - tier:tier0\n  - service_archetype:datastore\n  - alert_band:critical"],
      ["Azure — resource tags", "env = prod\nservice = checkout-api\ntier = tier0\nservice_archetype = api\nalert_band = critical\ncost_center = cc-identity"],
      ["Kubernetes — labels", "tags.datadoghq.com/env: prod\ntags.datadoghq.com/service: ...\ntags.datadoghq.com/version: ...\nteam / tier / service_archetype\n(DD_KUBERNETES_POD_LABELS_AS_TAGS)"],
      ["APM — environment", "DD_ENV=prod\nDD_SERVICE=checkout-api\nDD_VERSION=2026.08.19\nDD_GIT_COMMIT_SHA=<sha>\nDD_TAGS=\"team:...,tier:...\""],
    ];
    srcs.forEach((sc, i) => {
      const x = M + (i % 2) * 6.1, y = 3.55 + Math.floor(i / 2) * 1.55;
      s.addShape("roundRect", { x, y, w: 5.85, h: 1.42, rectRadius: 0.06, fill: { color: C.tint }, line: { color: C.tint } });
      s.addText(sc[0], { x: x + 0.22, y: y + 0.1, w: 5.4, h: 0.28, margin: 0, fontSize: 11.5, bold: true, fontFace: BODY_FONT, color: C.amberDeep, valign: "middle" });
      s.addText(sc[1], { x: x + 0.22, y: y + 0.38, w: 5.4, h: 0.98, margin: 0, fontSize: 9.5, fontFace: "Courier New", color: C.body, valign: "top", lineSpacingMultiple: 1.02 });
    });
    s.addShape("roundRect", { x: M + 6.25, y: 2.3, w: 5.85, h: 1.05, rectRadius: 0.06, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText("Never group by:", { x: M + 6.5, y: 2.38, w: 5.4, h: 0.26, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.red, valign: "middle" });
    s.addText("host_ip · container_id · pod_name · request_id · trace_id · path · url · user_id · session_id · instance_id · uuid — each turns one alert into thousands. Maximum 3 group keys, enforced at plan time.", { x: M + 6.5, y: 2.64, w: 5.4, h: 0.65, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "7A2E24", valign: "top" });
  }

  // -------------------------------------------------- 54 what we do not claim
  {
    const s = L.mk(pptx, {
      dark: true,
      kicker: "Appendix A10",
      title: "What this deck does not claim",
      sub: "The complete register of gaps, in one place, so nobody has to reconstruct it from the individual slides.",
      notes: `This is the whole gap register on one slide, so that nobody has to reconstruct it from fifteen individual footnotes — and so that if someone quotes this deck back at us in six months, the gaps are as quotable as the wins.

Read it as the counter-argument to everything else I have said. If you want to test the programme, test it here.`,
    });
    const gaps = [
      ["Telemetry does not carry alert_band", "Every archetype query resolves to an empty set today", "phase 2/3"],
      ["No CI/CD deployment metadata", "No pipeline sets DD_VERSION or DD_GIT_COMMIT_SHA", "phase 3"],
      ["Catalog has one entity kind", "Every object is a Service; 3 of 27 live entries are managed", "phase 1"],
      ["No fleet or agent management", "No deployment automation, no agent profiles, no compliance %", "phase 3"],
      ["No Control-M integration", "Repository-wide search returns zero files", "phase 5"],
      ["On-call rosters are empty", "Every schedule position is unassigned — a page reaches nobody", "people"],
      ["No incident-command role model", "No timeline capture, no post-incident-review automation", "phase 6"],
      ["25 of 27 workflows undeployed", "Org workflow quota held by 18 legacy workflows", "quota"],
      ["18 dashboards, not 4", "Per-domain generator still running alongside the four boards", "phase 6"],
      ["No report catalog", "The five audience-facing report families do not exist", "phase 6"],
      ["No observability survey", "Repository-wide search returns zero files", "phase 6"],
      ["No MCP server", "Ask, Act and governance: zero files exist", "phase 7"],
      ["No executive portal", "No web application in the repository", "phase 8"],
      ["Scorecards are local, not Datadog", "A Python scorecard over monitors, not entity-aware Datadog Scorecards", "phase 6"],
      ["No monitor-to-SLO relation", "Monitors carry slo_id but not SLI-producing / supporting / impacting", "phase 4"],
      ["No measured before-and-after", "No trustworthy baseline, and no data flowing yet to build one", "after tagging"],
    ];
    gaps.forEach((g, i) => {
      const c = i % 2, r = Math.floor(i / 2);
      const x = M + c * 6.1, y = 2.2 + r * 0.58;
      s.addShape("roundRect", { x, y, w: 5.85, h: 0.5, rectRadius: 0.04, fill: { color: C.inkSoft }, line: { color: C.inkSoft } });
      s.addText(g[0], { x: x + 0.16, y: y + 0.02, w: 4.6, h: 0.24, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: "E6ECF5", valign: "middle" });
      s.addText(g[1], { x: x + 0.16, y: y + 0.25, w: 4.6, h: 0.24, margin: 0, fontSize: 9.5, fontFace: BODY_FONT, color: "8E9DB5", valign: "middle" });
      s.addText(g[2], { x: x + 4.8, y, w: 0.9, h: 0.5, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: C.amber, align: "right", valign: "middle" });
    });
  }

  // ----------------------------------------------------------- 55 evidence
  {
    const s = L.mk(pptx, {
      kicker: "Appendix A11",
      title: "Evidence and sources",
      sub: "Where every number in this deck came from, so any of it can be checked without asking us.",
      notes: `Every figure in this deck is traceable to one of these sources, and all of them are in the repository or attached to a deploy run.

If you want to check a number: the monitor counts come from the plan-derived fixture that CI regenerates and staleness-gates. The runbook, routing and paging figures come from the reconciliation report, which is generated with live Datadog ids after every production apply. The status labels come from the traceability matrix. The tagging findings come from the last live profiling run.

Nothing in this deck was typed from memory, and nothing was rounded in our favour.`,
    });
    const src = [
      ["651 monitors · 70 paging · 651/651 runbooks attached · 0 URLs in alert bodies", "docs/monitor-reconciliation.md — generated with live Datadog ids after every production apply"],
      ["264 archetypes · 21 domain SLOs · detection mix · per-domain counts", "docs/monitor-coverage-matrix.md and tests/fixtures/monitors_planned.json — regenerated and staleness-gated by CI"],
      ["Priority, band, environment and team distributions", "tests/fixtures/monitors_planned.json — derived from the actual Terraform plan"],
      ["Status labels: OK · IMPROVE · PARTIAL · MISSING", "docs/requirement-traceability.md — 60 sections audited against the repo and the live estate"],
      ["alert_band 0/27 · env:production 22 · service_archetype inferred 27", "docs/tagging-standard.md — the last live profile_engine run; accepted exception EXC-2026-006"],
      ["Budgets: 1500 monitors · 90 paging · 85 P1 · workflow_budget 2", "platform/policy/global.yaml and stacks/foundation/budget.auto.tfvars — plan-time assertions"],
      ["7 teams · 14 schedules · 7 escalation policies · 4 RBAC roles", "stacks/foundation/main.tf and modules/team_oncall, modules/rbac"],
      ["Deployment status, promotion model and governance cadences", "docs/deployment.md and docs/operating-model.md"],
    ];
    src.forEach((r, i) => {
      const y = 2.3 + i * 0.54;
      s.addShape("roundRect", { x: M, y, w: CW, h: 0.5, rectRadius: 0.04, fill: { color: i % 2 ? "FFFFFF" : "F5F7FA" }, line: { color: i % 2 ? "FFFFFF" : "F5F7FA" } });
      s.addText(r[0], { x: M + 0.2, y, w: 5.6, h: 0.5, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(r[1], { x: M + 5.9, y, w: 6.0, h: 0.5, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    });
    s.addText("Nothing in this deck was typed from memory, and nothing was rounded in our favour. Speaker notes for every slide: docs/presentation/speaker-notes.md", { x: M, y: 6.7, w: CW, h: 0.34, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.amberDeep, valign: "top" });
  }
}

module.exports = { build };
