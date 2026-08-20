const L = require("./lib");
const { C, HEAD_FONT, BODY_FONT, M, W, CW } = L;
const { divider } = require("./part1");

function build(pptx) {
  // ------------------------------------------------------- 11 entity model
  {
    const s = L.mk(pptx, {
      kicker: "Topic 6",
      title: "The correct catalog entity model",
      pill: ["roadmap", "roadmap · phase 1"],
      sub: "An estate is not a list of services. Until the catalog can say what kind of thing something is, ownership and impact questions have to be answered by a human.",
      notes: `This is the honest gap slide, and it is the first phase of the roadmap for a reason.

Today every catalog object this platform creates is a Service. That is what the Terraform module emits — a service definition. There are no System, Datastore, Queue or API entities, and the registration schema has no kind field.

Why it matters in practice. "Which systems depend on this Azure SQL database?" cannot be answered, because the database is not an entity — it is a tag on a monitor. "What is the blast radius of this queue backing up?" has the same problem. Impact analysis today is done by a human who knows the estate, which does not scale and does not survive that human changing jobs.

The target is Datadog's v3 entity kinds: System, Datastore, Queue, API, Endpoint, Frontend App, Repository, External Provider. Phase one adds kind to the entity schema, builds the entity resolver, and reconciles discovered entities against declared ones.

A second number worth stating plainly: the live catalog holds 27 service-catalog entries; 3 of them are managed from this repository. The rest are demo or legacy entries that have not been reconciled. That reconciliation is the same phase-one work.

I want to be precise about what this does NOT break. Monitoring coverage does not depend on the entity model — coverage comes from tags. This gap costs us analysis and navigation, not detection.`,
    });
    s.addShape("roundRect", { x: M, y: 2.35, w: 5.85, h: 2.0, rectRadius: 0.07, fill: { color: "F3F4F6" }, line: { color: "F3F4F6" } });
    s.addText("TODAY", { x: M + 0.28, y: 2.52, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.muted, charSpacing: 1.6 });
    s.addText("Every catalog object is a Service", { x: M + 0.28, y: 2.84, w: 5.3, h: 0.4, margin: 0, fontSize: 17, bold: true, fontFace: HEAD_FONT, color: C.text, valign: "middle" });
    s.addText("The module emits service definitions only. A database, a queue or a gateway exists in the platform as a tag on a monitor, not as an entity with dependencies and an owner.", { x: M + 0.28, y: 3.28, w: 5.3, h: 0.9, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });

    s.addShape("roundRect", { x: M + 6.25, y: 2.35, w: 5.85, h: 2.0, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("TARGET — PHASE 1", { x: M + 6.53, y: 2.52, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.6 });
    s.addText("Eight entity kinds, declared in YAML", { x: M + 6.53, y: 2.84, w: 5.3, h: 0.4, margin: 0, fontSize: 17, bold: true, fontFace: HEAD_FONT, color: C.paper, valign: "middle" });
    s.addText("System · Datastore · Queue · API · Endpoint · Frontend App · Repository · External Provider — Datadog's v3 kinds, with kind: added to the entity schema and an entity resolver behind it.", { x: M + 6.53, y: 3.28, w: 5.3, h: 0.9, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "A9B6CB", valign: "top" });

    L.cards(s, [
      { t: "What the gap costs", b: "\"Which systems depend on this database?\" and \"what is the blast radius of this queue?\" are answered by a human who knows the estate — not by the catalog." },
      { t: "What it does not cost", b: "Detection. Coverage comes from tags, not from entity kinds. Every monitor works exactly as designed regardless of how the catalog models the thing." },
      { t: "The reconciliation number", b: "The live catalog holds 27 entries; 3 are managed from this repository. Merging discovered entities with declared intent is the same phase-one work." },
    ], { y: 4.55, h: 1.75, cols: 3 });
  }

  // -------------------------------------------------- 12 one YAML → everything
  {
    const s = L.mk(pptx, {
      kicker: "Topic 7",
      title: "How one YAML definition drives observability",
      pill: ["shipped", "shipped"],
      sub: "One archetype file describes a detection. The framework supplies naming, tags, priority, routing, runbook, automation, correlation, recovery and the SLO link — none of which the author writes.",
      notes: `This is the engine room slide.

An archetype is a monitor pattern: what is being measured, what kind of impact it represents, how it is detected, the query, the grouping, which environments and bands it applies to. About twenty lines. The author writes the detection and nothing else.

From that one file, the factory derives: the monitor name in a standard format, the full tag set, the priority — which is the impact class crossed with the alert band, clamped by the environment ceiling — whether it may page, the notification profile, the deterministic correlation and dedup keys, the runbook attachment, the diagnostic workflow, the auto-resolve window, and the SLO association.

The trick that makes it scale is the scope substitution. Every query contains a placeholder that is replaced at plan time with env plus alert band plus any extra selector. One archetype becomes one monitor per environment and band, and every matching resource in the estate is a GROUP inside it. 264 archetypes become 651 monitors, and those 651 cover an estate of any size.

The arithmetic on the right is the whole scalability argument, and it is asserted at plan time — the monitor, paging and P1 budgets in global.yaml are hard plan-time checks, so growth is a reviewed decision and never a drift.`,
    });
    s.addShape("roundRect", { x: M, y: 2.5, w: 4.5, h: 3.55, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("ONE ARCHETYPE FILE", { x: M + 0.26, y: 2.66, w: 4.0, h: 0.28, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.6 });
    s.addText(
      "k8s-pod-crashloop:\n  signal: availability\n  impact_class: degradation\n  detection: threshold\n  query: '...{__SCOPE__,\n     reason:crashloopbackoff}\n     by {cluster,namespace,\n     deployment} >= 1'\n  group_by: [cluster, ns, deploy]\n  notify_by: [cluster]\n  envs: [prod, stage, qa]\n  bands: [critical, standard]\n  slo_id: slo-k8s-availability\n  runbook: k8s-pod-crashloop",
      { x: M + 0.26, y: 2.98, w: 4.0, h: 2.9, margin: 0, fontSize: 10.5,
        fontFace: "Courier New", color: "D3DCE9", valign: "top", lineSpacingMultiple: 1.08 }
    );
    s.addShape("rightArrow", { x: M + 4.72, y: 4.15, w: 0.42, h: 0.24, fill: { color: C.amber }, line: { color: C.amber } });

    s.addText("The framework derives, and CI enforces", { x: M + 5.35, y: 2.5, w: 6.7, h: 0.34, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const derived = ["Monitor name + full tag set", "Priority = impact × band, capped by env", "Whether it may page a human", "Notification profile and routing", "correlation_key and dedup_key", "Runbook notebook attachment", "Diagnostic workflow on every alert", "Auto-resolve window (timeout_h)", "SLO association", "Recovery notification"];
    derived.forEach((d, i) => {
      const c = i % 2, r = Math.floor(i / 2);
      const x = M + 5.35 + c * 3.4, y = 2.92 + r * 0.5;
      s.addShape("roundRect", { x, y, w: 3.2, h: 0.42, rectRadius: 0.05, fill: { color: C.tint }, line: { color: C.tint } });
      s.addText(d, { x: x + 0.15, y, w: 2.95, h: 0.42, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.body, valign: "middle" });
    });

    s.addShape("roundRect", { x: M + 5.35, y: 5.5, w: 6.7, h: 0.85, rectRadius: 0.07, fill: { color: C.tintWarm }, line: { color: C.tintWarm } });
    s.addText(
      [
        { text: "264 archetypes  →  651 monitors  →  an estate of any size.  ", options: { bold: true } },
        { text: "__SCOPE__ is replaced at plan time with the environment and the alert band; every matching resource is a group inside a monitor that already exists.", options: {} },
      ],
      { x: M + 5.6, y: 5.62, w: 6.2, h: 0.62, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "5C4514", valign: "middle" }
    );
  }

  // ------------------------------------------------------ 13 monitoring profiles
  {
    const s = L.mk(pptx, {
      kicker: "Topic 8",
      title: "Monitoring profiles",
      pill: ["partial", "partial — telemetry input"],
      sub: "A profile is how strictly a thing is watched. Five profiles and two overlays cover the entire enterprise, and every one of them is resolved, never chosen.",
      notes: `Five profiles: observe_only, baseline, standard, critical, regulated. Two overlays: security_sensitive and release_gate. An overlay adds signal classes or redirects routing without creating a new profile — which is what holds the count at five.

The resolution chain is eight layers: global standards, then domain, then service archetype, then monitoring profile, then environment policy, then tier policy, then team policy, then a time-boxed exception. Terraform is a pure interpreter of that hierarchy — no monitoring decision is made in HCL.

Notice what a team supplies: tier and service_archetype. Everything else is derived. A team cannot select a profile, and specifically cannot select "critical" — that comes from the tier, which is a reviewed business decision.

Two things worth calling out. Regulated is promoted automatically by the compliance_scope tag, so PCI or similar scope does not depend on someone remembering. And observe_only always carries a recorded reason — check C10 fails on an observe_only resource with no reason, so "not monitored" is never allowed to be an accident.

Marked PARTIAL for one specific reason: telemetry availability is not yet an input to profile resolution. The platform will happily resolve a profile that expects metrics nobody emits, and the resulting monitor sits green and empty. Declaring required telemetry on every archetype and building an applicability engine is phase two.`,
    });
    const profs = [
      { t: "observe_only", b: "Telemetry and dashboards, no alerting. Needs a recorded reason — check C10 fails without one." },
      { t: "baseline", b: "Availability and telemetry-health only. QA, and low-value production." },
      { t: "standard", b: "Golden signals plus saturation. The tier2 default." },
      { t: "critical", b: "Full signal set, SLO, burn-rate paging, escalation. tier0 and tier1." },
      { t: "regulated", b: "Critical plus evidence and retention duties. Promoted by the compliance_scope tag." },
    ];
    L.cards(s, profs, { y: 2.45, h: 1.45, cols: 5, gap: 0.2, bodySize: 10.5, titleSize: 13.5 });

    s.addText("+ two overlays", { x: M, y: 4.0, w: 2.0, h: 0.3, margin: 0, fontSize: 11.5, bold: true, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    s.addText("security_sensitive — routes to the security team regardless of who owns the resource   ·   release_gate — stage + tier0 during an active release window", { x: M + 1.5, y: 4.0, w: 10.6, h: 0.3, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "middle" });

    s.addText("Resolved through eight layers — a team supplies two of them", { x: M, y: 4.5, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const layers = ["Global", "Domain", "Service archetype", "Profile", "Environment", "Tier", "Team", "Exception"];
    layers.forEach((l, i) => {
      const x = M + i * 1.52;
      const own = (l === "Service archetype" || l === "Tier");
      s.addShape("roundRect", { x, y: 4.92, w: 1.34, h: 0.72, rectRadius: 0.05, fill: { color: own ? C.ink : C.tint }, line: { color: own ? C.ink : C.tint } });
      s.addText(l, { x: x + 0.08, y: 4.92, w: 1.18, h: 0.72, margin: 0, fontSize: 10.5, bold: own, fontFace: BODY_FONT, color: own ? C.amber : C.body, align: "center", valign: "middle" });
      if (i < layers.length - 1) {
        s.addShape("rightArrow", { x: x + 1.36, y: 5.2, w: 0.14, h: 0.14, fill: { color: C.slate }, line: { color: C.slate } });
      }
    });
    s.addShape("roundRect", { x: M, y: 5.85, w: CW, h: 0.72, rectRadius: 0.06, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText(
      [
        { text: "Open gap — phase 2:  ", options: { bold: true } },
        { text: "telemetry availability is not yet an input to profile resolution. The platform will resolve a profile that expects metrics nobody emits, and the resulting monitor sits green and empty. Declaring required telemetry per archetype closes it.", options: {} },
      ],
      { x: M + 0.25, y: 5.85, w: CW - 0.5, h: 0.72, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "middle" }
    );
  }

  // ------------------------------------------------------------ 14 part 3 div
  divider(pptx, {
    part: "PART THREE",
    title: "Signals and\nobjectives",
    strap: "What we collect, what we run it on, and how customer harm becomes the thing that pages.",
    first: 9,
    topics: [
      "Telemetry collection",
      "Fleet and agent management",
      "How SLOs work",
      "How a service gets its own correct SLO",
      "Error budgets",
    ],
    notes: `Part three has the second-largest gap in the programme — fleet management — and the mechanism that makes paging defensible: burn rate on an objective.`,
  });

  // ---------------------------------------------------- 15 telemetry collection
  {
    const s = L.mk(pptx, {
      kicker: "Topic 9",
      title: "Telemetry collection",
      pill: ["partial", "partial — see slide 3"],
      sub: "Five sources feed the platform. Where no product publishes the signal the business asked for, the gap is named and given an emission contract rather than a plausible-looking proxy.",
      notes: `Five collection paths. The Datadog Agent on hosts and VMs. The Azure integration for every azure.* metric, which must be enabled per subscription. APM and RUM from instrumented applications. Logs, including log-derived metrics. And custom emitters for the signals nothing else publishes.

That last category is docs/telemetry-gaps.md, and it is a document I would like you to read if you take one artifact away. Eight metric families where the honest answer was "no product knows this, so something must emit it": database restore verification — backup age proves a file was written, not that it can be read; Snowflake per-task failures; Service Bus message AGE, because Azure publishes depth only and depth cannot distinguish a healthy drain from an hour-old backlog; NSG denied flows, because network security groups publish no Azure Monitor metrics at all; budget and forecast, because Datadog publishes spend but the budget lives in the Azure Consumption API; application connection pools, which live inside the process where neither the database nor the runtime can see them; hardware health normalised from IPMI; and patch and lifecycle state, which is an inventory fact, not telemetry.

Each one has a written contract: metric name, type, tags, and what the emitter must do. The contracts are specified. Most of the emitters are not yet deployed — that is honest scoping, and each is a small piece of work owned by the team that owns the system.

And the tag gap from slide 3 sits on top of all of it. The collection paths work. The tags they carry do not yet select.`,
    });
    L.cards(s, [
      { t: "Datadog Agent", b: "Hosts, VMs, VMware, SQL Server. Tags applied in datadog.yaml." },
      { t: "Azure integration", b: "Every azure.* metric. Enabled per subscription; resource tags carry identity." },
      { t: "APM · RUM", b: "Traces, runtime metrics, Core Web Vitals. DD_ENV, DD_SERVICE, DD_VERSION." },
      { t: "Logs", b: "Log-derived metrics where the signal exists only in logs — NSG flows, for one." },
      { t: "Custom emitters", b: "The acme.* families: the signals no product publishes." },
    ], { y: 2.4, h: 1.45, cols: 5, gap: 0.2, bodySize: 10.5, titleSize: 13 });

    s.addText("Named gaps with written emission contracts — specified, mostly not yet deployed", { x: M, y: 3.95, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const gaps = [
      ["acme.database.restore_verification_*", "Backup age proves a file was written, not that it can be restored"],
      ["acme.snowflake.task_failures", "The integration publishes account aggregates, never per-task outcomes"],
      ["acme.messaging.oldest_message_age_seconds", "Service Bus publishes depth; depth cannot see an hour-old backlog"],
      ["acme.network.nsg_denied_flows", "NSGs publish no Azure Monitor metrics at all — it is flow logs or nothing"],
      ["acme.finops.budget_utilization_pct", "Datadog publishes spend; the budget lives in the Azure Consumption API"],
      ["acme.app.db_pool.*", "The pool is inside the process — the database and the runtime both miss it"],
      ["acme.hardware.*", "IPMI sensor names differ per vendor — a raw name silently misses the next fleet"],
      ["acme.compliance.*", "Patch level and OS support dates are inventory facts, not telemetry"],
    ];
    gaps.forEach((g, i) => {
      const c = i % 2, r = Math.floor(i / 2);
      const x = M + c * 6.1, y = 4.35 + r * 0.62;
      s.addShape("roundRect", { x, y, w: 5.85, h: 0.55, rectRadius: 0.05, fill: { color: i % 2 ? "F7F8FA" : "F7F8FA" }, line: { color: "F7F8FA" } });
      s.addText(g[0], { x: x + 0.16, y: y + 0.02, w: 5.5, h: 0.26, margin: 0, fontSize: 10.5, bold: true, fontFace: "Courier New", color: C.amberDeep, valign: "middle" });
      s.addText(g[1], { x: x + 0.16, y: y + 0.26, w: 5.5, h: 0.26, margin: 0, fontSize: 10, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    });
  }

  // --------------------------------------------------------- 16 fleet management
  {
    const s = L.mk(pptx, {
      kicker: "Topic 10",
      title: "Fleet and agent management",
      pill: ["roadmap", "roadmap · phase 3"],
      sub: "The platform detects agent problems today. It does not yet deploy, configure or standardise agents — and it cannot yet tell you what percentage of the fleet is compliant.",
      notes: `I am not going to dress this one up. Fleet management is referenced in five of our documents and implemented in none of them.

What exists today, and works: archetypes that detect agent version drift, unhealthy agents, and OS patch and end-of-life state. If an agent breaks, we find out.

What does not exist: agent deployment automation. There is no Azure Policy path, no VM extension path, no golden-image path. There are no standard agent profiles — base, Windows, Linux, application host, SQL Server host — so what each agent collects depends on who installed it. And there is no compliance ratio: we can tell you which agents are unhealthy, we cannot tell you that 87% of hosts that should have an agent have one, because "should have" is not expressed anywhere.

Why this matters more than it sounds: the tagging problem from slide 3 and the fleet problem are the same problem seen from two ends. Azure Policy with a modify effect is what makes resource tags true over time, and the same mechanism installs and configures the agent. Phase three does both, which is why they are one phase.

The honest summary: monitoring the fleet is shipped. Managing the fleet is not.`,
    });
    s.addShape("roundRect", { x: M, y: 2.55, w: 5.85, h: 2.35, rectRadius: 0.07, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
    s.addText("SHIPPED — DETECTION", { x: M + 0.28, y: 2.72, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: "1D5C59", charSpacing: 1.6 });
    s.addText(
      [
        { text: "agent-version-drift — agents falling behind the fleet", options: { bullet: true, breakLine: true } },
        { text: "host-agent-unhealthy — the agent itself is failing", options: { bullet: true, breakLine: true } },
        { text: "os-critical-patch-missing, os-patch-age-excessive", options: { bullet: true, breakLine: true } },
        { text: "os-end-of-life — support runway per host", options: { bullet: true, breakLine: true } },
        { text: "ingest-pipeline-degraded — a 40% collapse in custom-metric ingest means part of the estate has gone dark", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 0.28, y: 3.06, w: 5.3, h: 1.7, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "1D5C59", valign: "top", paraSpaceAfter: 5 }
    );

    s.addShape("roundRect", { x: M + 6.25, y: 2.55, w: 5.85, h: 2.35, rectRadius: 0.07, fill: { color: "F3F4F6" }, line: { color: C.line } });
    s.addText("NOT BUILT — MANAGEMENT", { x: M + 6.53, y: 2.72, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.slate, charSpacing: 1.6 });
    s.addText(
      [
        { text: "No agent deployment automation — no Azure Policy, VM extension or golden-image path", options: { bullet: true, breakLine: true } },
        { text: "No standard agent profiles (base · Windows · Linux · application · SQL Server), so collection differs per installer", options: { bullet: true, breakLine: true } },
        { text: "No compliance percentage — we can name unhealthy agents, not the hosts that should have one and do not", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 6.53, y: 3.06, w: 5.3, h: 1.7, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "top", paraSpaceAfter: 6 }
    );

    s.addShape("roundRect", { x: M, y: 5.15, w: CW, h: 1.15, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("Why fleet and tagging are one phase, not two", { x: M + 0.3, y: 5.28, w: 11.4, h: 0.32, margin: 0, fontSize: 13, bold: true, fontFace: BODY_FONT, color: C.amber, valign: "middle" });
    s.addText("Azure Policy with a modify effect is the only mechanism that keeps resource tags true over time — and it is the same mechanism that installs and configures the agent. Phase 3 delivers both, plus DD_VERSION from the deployment pipeline, which is what makes deployment-to-incident correlation work.", { x: M + 0.3, y: 5.6, w: 11.4, h: 0.6, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "AEBACD", valign: "top" });
  }

  // ------------------------------------------------------------- 17 how SLOs work
  {
    const s = L.mk(pptx, {
      kicker: "Topic 11",
      title: "How SLOs work",
      pill: ["shipped", "shipped"],
      sub: "Paging concentrates at the top of the stack. An SLO burn-rate alert is a measurement of customer harm — which is why it is allowed to wake someone and a lone symptom is not.",
      notes: `The layer model first. A business or service SLO pages, on burn rate. Golden signals raise incidents and tickets. Dependencies raise incidents and context. Infrastructure is for diagnosis and almost never pages on its own.

Two scopes keep the count bounded. Twenty-one domain SLOs cover tier1 and tier2 across the whole estate, because a grouped SLI query covers every service in the domain. Then one SLO per tier0 service. Total today: 22 objectives, driving 41 burn-rate monitors.

Multi-window burn rate is the mechanism. Fast is a one-hour long window with a five-minute short window at 14.4× — that consumes 2% of a 30-day budget in an hour, and it pages. Medium is six hours at 6× — 5% in six hours, and it pages. Slow is 24 hours at 3× — 10% in a day, and it raises a ticket. The long window proves the burn is sustained rather than a spike; the short window proves it is still happening now, which is also what makes the alert recover quickly.

The slow window deliberately does not page. A 24-hour burn is a real problem with days of budget left. Waking someone for it teaches them that pages are not urgent, which is the most expensive lesson a platform can teach.

Which windows you get comes from your tier: tier0 gets all three, tier1 gets fast and slow, tier2 gets slow only.`,
    });
    const layers = [
      { t: "Business / service SLO", b: "burn rate — PAGES", fill: C.ink, tc: C.amber, bc: "D3DCE9" },
      { t: "Golden signals", b: "incidents + tickets", fill: C.tint },
      { t: "Dependencies", b: "incidents + context", fill: C.tint },
      { t: "Infrastructure", b: "diagnosis only, rarely pages", fill: C.tint },
    ];
    layers.forEach((l, i) => {
      const y = 2.45 + i * 0.62;
      const inset = i * 0.42;
      s.addShape("roundRect", { x: M + inset, y, w: 5.6 - inset * 2, h: 0.54, rectRadius: 0.05, fill: { color: l.fill }, line: { color: l.fill } });
      s.addText(l.t, { x: M + inset + 0.18, y, w: 3.1 - inset, h: 0.54, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: l.tc || C.text, valign: "middle" });
      s.addText(l.b, { x: M + 3.3, y, w: 2.1, h: 0.54, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: l.bc || C.muted, align: "right", valign: "middle" });
    });
    s.addText("Paging concentrates at the top. Infrastructure alerts support diagnosis; they almost never page alone.", { x: M, y: 5.0, w: 5.6, h: 0.6, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.muted, valign: "top" });

    s.addText("Multi-window burn rate", { x: M + 6.25, y: 2.4, w: 5.85, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const burn = [
      ["fast", "1h / 5m", "14.4×", "2% of budget in an hour", "PAGE"],
      ["medium", "6h / 30m", "6×", "5% in six hours", "PAGE"],
      ["slow", "24h / 2h", "3×", "10% in a day", "ticket"],
      ["trend", "72h / 6h", "1×", "informational", "—"],
    ];
    burn.forEach((b, i) => {
      const y = 2.82 + i * 0.56;
      s.addShape("roundRect", { x: M + 6.25, y, w: 5.85, h: 0.5, rectRadius: 0.05, fill: { color: i < 2 ? C.tintWarm : "F5F7FA" }, line: { color: i < 2 ? C.tintWarm : "F5F7FA" } });
      s.addText(b[0], { x: M + 6.45, y, w: 1.0, h: 0.5, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(b[1], { x: M + 7.4, y, w: 1.1, h: 0.5, margin: 0, fontSize: 11, fontFace: "Courier New", color: C.body, valign: "middle" });
      s.addText(b[2], { x: M + 8.5, y, w: 0.7, h: 0.5, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.body, valign: "middle" });
      s.addText(b[3], { x: M + 9.2, y, w: 2.0, h: 0.5, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
      s.addText(b[4], { x: M + 11.2, y, w: 0.75, h: 0.5, margin: 0, fontSize: 10, bold: i < 2, fontFace: BODY_FONT, color: i < 2 ? C.red : C.muted, align: "right", valign: "middle" });
    });
    s.addText("The long window proves the burn is sustained; the short window proves it is still happening, and lets the alert recover quickly. The slow window deliberately does not page.", { x: M + 6.25, y: 5.1, w: 5.85, h: 0.6, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.muted, valign: "top" });

    const st = [["22", "SLOs — 21 domain + 1 per tier0 service"], ["41", "burn-rate monitors"], ["3", "windows for tier0; tier1 gets 2, tier2 gets 1"]];
    st.forEach((x, i) => {
      L.stat(s, { x: M + i * 4.1, y: 5.75, w: 3.9, value: x[0], label: x[1], size: 28, vh: 0.5, labelSize: 11 });
    });
  }

  // ------------------------------------------------------- 18 correct SLO per service
  {
    const s = L.mk(pptx, {
      kicker: "Topic 12",
      title: "How a service gets its own correct SLO",
      pill: ["partial", "partial · phase 4"],
      sub: "Not every entity needs an SLO, and that is a design position rather than a gap. Tier is the decision that grants one.",
      notes: `The question I get most often is "why doesn't my service have its own SLO?" — so here is the rule.

Resolution today: enterprise defaults, then a domain SLO, then, if the service is tier0, a per-service objective from the tier0 template. Tier0 gets its own error budget, its own burn-rate alerts, and the freeze policy. Tier1 and tier2 are covered by the domain SLO, because a grouped SLI query already covers every service in that domain.

Tier 0 is 99.95% availability and 99.5% latency; tier1 is 99.9 and 99.0; tier2 is 99.5 and 98.0. Those are business statements, reviewed by the platform team, not numbers a team picks to make a dashboard green.

Infrastructure has no SLO at all, deliberately. A host does not have a customer-facing objective; the service running on it does.

Two honest limitations, both phase four. A service cannot declare multiple named objectives today — you get availability and latency from the template, not a checkout-completion objective alongside them. And there is no per-service objective override: two tier0 services on the same profile get the same target, even if one genuinely needs 99.99. Adding an slo_profile layer and a per-service override closes both.

There is also a governance gap worth naming: monitors carry an slo_id but not a relation — SLI-producing, supporting, impacting or diagnostic. So "which monitors actually feed this objective?" is not yet mechanically answerable.`,
    });
    L.flow(s, [
      { t: "Enterprise\ndefaults", fill: C.tint },
      { t: "Domain SLO\n21 objectives", fill: C.tint },
      { t: "Tier 0?\nper-service SLO", fill: C.ink, tc: C.amber },
      { t: "Burn-rate\nmonitors", fill: C.tintWarm },
      { t: "Error-budget\npolicy", fill: C.tintWarm },
    ], { y: 2.4, h: 0.95, size: 12 });

    const tiers = [
      ["tier0", "Own SLO · 99.95% availability · 99.5% latency", "fast + medium + slow", "feature freeze below 25% budget"],
      ["tier1", "Domain SLO · 99.9% · 99.0%", "fast + slow", "reliability work next sprint"],
      ["tier2", "Domain SLO · 99.5% · 98.0%", "slow only", "tracked in the ops review"],
      ["tier3", "No SLO — a decision, with a recorded reason", "—", "n/a"],
    ];
    s.addText("Tier decides the objective, the windows and the consequence", { x: M, y: 3.62, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    tiers.forEach((t, i) => {
      const y = 4.04 + i * 0.56;
      s.addShape("roundRect", { x: M, y, w: CW, h: 0.5, rectRadius: 0.05, fill: { color: i === 0 ? C.tintWarm : "F5F7FA" }, line: { color: i === 0 ? C.tintWarm : "F5F7FA" } });
      s.addText(t[0], { x: M + 0.2, y, w: 0.9, h: 0.5, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(t[1], { x: M + 1.15, y, w: 5.0, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "middle" });
      s.addText(t[2], { x: M + 6.2, y, w: 2.6, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "middle" });
      s.addText(t[3], { x: M + 8.85, y, w: 3.2, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    });

    s.addShape("roundRect", { x: M, y: 6.32, w: CW, h: 0.5, rectRadius: 0.05, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText(
      [
        { text: "Phase 4:  ", options: { bold: true } },
        { text: "a service cannot yet declare multiple named objectives, and two tier0 services on one profile cannot yet hold different targets. Monitors carry an slo_id but no relation (SLI-producing · supporting · impacting · diagnostic).", options: {} },
      ],
      { x: M + 0.25, y: 6.32, w: CW - 0.5, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "middle" }
    );
  }

  // --------------------------------------------------------------- 19 error budgets
  {
    const s = L.mk(pptx, {
      kicker: "Topic 13",
      title: "Error budgets",
      pill: ["shipped", "shipped — policy"],
      sub: "An error budget turns reliability from an argument into arithmetic. 99.95% over 30 days is 21 minutes and 36 seconds of permitted failure — that is the number, and it is either spent or it is not.",
      notes: `An error budget is the amount of failure the objective permits. At 99.95% over thirty days that is twenty-one minutes and thirty-six seconds. At 99.9% it is forty-three minutes. At 99.5% it is three hours and thirty-six minutes.

The point is not the arithmetic, it is what happens when the budget is gone. For tier0 the consequence is a feature freeze for the owning team until the budget recovers above 25%, and a documented exception is required to deploy. For tier1 reliability work is prioritised next sprint, and high-risk deploys go to change advisory. For tier2 it is tracked in the team's operational review with no freeze.

Two things this buys you as leadership. First, it converts "is it reliable enough?" from a debate into a number that both engineering and the business already agreed to. Second, it gives an owning team a legitimate, pre-agreed reason to say no to a feature — which is otherwise the hardest thing for a delivery team to do.

Note the honest boundary: the policy is defined, deployed and attached to the tiers. What we cannot yet show you is a trend of budget consumption over time, because the SLIs have no data — slide 3 again. The moment the tags land, this becomes the most useful chart in the programme.`,
    });
    const budg = [
      { v: "21m 36s", l: "monthly budget at 99.95% — tier 0" },
      { v: "43m 12s", l: "at 99.9% — tier 1" },
      { v: "3h 36m", l: "at 99.5% — tier 2" },
    ];
    budg.forEach((b, i) => {
      const x = M + i * 4.1;
      s.addShape("roundRect", { x, y: 2.5, w: 3.87, h: 1.5, rectRadius: 0.07, fill: { color: i === 0 ? C.ink : C.tint }, line: { color: i === 0 ? C.ink : C.tint } });
      L.stat(s, { x: x + 0.28, y: 2.68, w: 3.3, value: b.v, label: b.l, size: 30, vh: 0.6, color: i === 0 ? C.amber : C.text, labelColor: i === 0 ? "9FADC4" : C.muted, labelSize: 11 });
    });

    s.addText("What exhaustion actually triggers", { x: M, y: 4.25, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    L.rows(s, [
      { k: "tier0 — mission critical", v: "Feature freeze for the owning team until the budget recovers above 25%; a documented exception is required to deploy" },
      { k: "tier1 — business critical", v: "Reliability work prioritised next sprint; change-advisory review for high-risk deploys" },
      { k: "tier2 — standard", v: "Tracked in the team's operational review. No freeze — the objective is not worth stopping delivery for" },
    ], { y: 4.68, rh: 0.52, kw: 3.3, size: 12 });

    s.addShape("roundRect", { x: M, y: 6.32, w: CW, h: 0.5, rectRadius: 0.05, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText(
      [
        { text: "Honest boundary:  ", options: { bold: true } },
        { text: "the policy is deployed and attached to the tiers, but no budget-consumption trend can be shown yet — the SLIs have no data until the telemetry carries the tags. This becomes the most useful chart in the programme the week that changes.", options: {} },
      ],
      { x: M + 0.25, y: 6.32, w: CW - 0.5, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "middle" }
    );
  }

  // ------------------------------------------------------------ 20 part 4 div
  divider(pptx, {
    part: "PART FOUR",
    title: "From alert\nto resolution",
    strap: "Correlation, noise, incidents, on-call, tickets, runbooks and automation — the path a signal takes to a human who can fix it.",
    first: 14,
    topics: [
      "Event correlation",
      "Alert-noise reduction",
      "Incident management",
      "On-call",
      "Incident command",
      "ServiceNow",
      "Runbooks",
      "Workflow automation",
    ],
    notes: `Part four is the longest part — eight topics — because this is where an observability platform either earns trust or loses it.`,
  });
}

module.exports = { build };
