const L = require("./lib");
const { C, HEAD_FONT, BODY_FONT, M, W, CW } = L;
const { divider } = require("./part1");

function build(pptx) {
  // --------------------------------------------------------- 21 event correlation
  {
    const s = L.mk(pptx, {
      kicker: "Topic 14",
      title: "Event correlation",
      pill: ["partial", "partial — native keys only"],
      sub: "Five alerts for one problem become one incident with four children and the change that caused it attached as context.",
      notes: `The goal is one sentence: five alerts for one problem become one incident with four children, and the change that caused it attached as context.

The mechanism is two deterministic keys stamped on every monitor by the factory. correlation_key is failure domain, environment and service — that is grouping identity. dedup_key is service, environment and archetype — that is event identity. Native Datadog Event Management aggregation works off those tags with zero custom rules, and that part is live on all 651 monitors.

On top of that sits versioned policy with six rules. Group by correlation key. Attach change context — deployments, Terraform applies, Kubernetes rollouts, cloud platform events, ServiceNow changes — which never page and never become the parent; they explain it. Platform causes adopt application symptoms in the same environment and region. A confirmed vendor outage adopts every dependent integration error, so "it is them, not us" is one statement instead of twelve tickets. Maintenance-window events are dropped. And scope uplift: if a group spans more than a quarter of a pack's services, the parent rises one priority, because breadth is business impact.

Root-cause ranking decides who becomes the parent: availability is nearly always a cause, latency is nearly always a symptom.

This is proven on every pull request. A six-alert database cascade collapses to one group, one page, one incident and four suppressed children. A deployment attaches as context and never becomes the parent. Unrelated failures in different regions stay separate. Recovery closes the group only when every child has recovered.

Why PARTIAL: Datadog's Event Management correlation rules have no GA Terraform resource or public CRUD API, so the rules file is an executable specification with a reference engine in CI, not something we configure in the product. When the API goes GA, the same YAML becomes its input with zero monitor changes. Also, the Control-M correlation rule does not exist, because Control-M itself is phase five.`,
    });
    s.addShape("roundRect", { x: M, y: 2.35, w: 5.85, h: 1.05, rectRadius: 0.06, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("correlation_key = <failure_domain>.<env>.<service>\ndedup_key       = <service>.<env>.<archetype>", { x: M + 0.25, y: 2.45, w: 5.4, h: 0.85, margin: 0, fontSize: 11.5, fontFace: "Courier New", color: C.amber, valign: "middle", lineSpacingMultiple: 1.1 });
    s.addText("Stamped on all 651 monitors by the factory. Native aggregation works off these tags with zero custom rules.", { x: M, y: 3.48, w: 5.85, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.muted, valign: "top" });

    s.addText("Proven on every pull request", { x: M, y: 4.1, w: 5.85, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    L.flow(s, [
      { t: "6 alerts\ndatabase cascade", fill: C.tint },
      { t: "1 group\n4 suppressed", fill: C.tintWarm },
      { t: "1 page\n1 incident", fill: C.ink, tc: C.amber },
    ], { x: M, y: 4.5, w: 5.85, h: 0.9, size: 11, arrow: 0.26 });
    s.addText("Plus: a deployment attaches as context and never becomes the parent; a vendor outage absorbs its downstream symptoms; unrelated regions stay separate; recovery closes the group only when every child recovers.", { x: M, y: 5.5, w: 5.85, h: 0.85, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "top" });

    s.addText("Six rules, versioned as policy", { x: M + 6.25, y: 2.35, w: 5.85, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const rules = [
      ["group-by-correlation-key", "one case per failure domain + env + service"],
      ["attach-change-context", "deploys and changes explain, never page, never parent"],
      ["platform-cause-suppresses-app-symptom", "infra adopts application symptoms in the same region"],
      ["vendor-outage-suppresses-integration", "\"it is them, not us\" — once, not twelve times"],
      ["maintenance-window-suppression", "events inside a downtime never open a group"],
      ["scope-uplift", "a group spanning >25% of a pack rises one priority"],
    ];
    rules.forEach((r, i) => {
      const y = 2.72 + i * 0.58;
      s.addShape("roundRect", { x: M + 6.25, y, w: 5.85, h: 0.52, rectRadius: 0.05, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addText(r[0], { x: M + 6.45, y: y + 0.03, w: 5.5, h: 0.26, margin: 0, fontSize: 10.5, bold: true, fontFace: "Courier New", color: C.amberDeep, valign: "middle" });
      s.addText(r[1], { x: M + 6.45, y: y + 0.27, w: 5.5, h: 0.26, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    });
    s.addText("Why partial: Datadog's correlation rules have no GA Terraform resource or public API. The rules file is an executable specification, proven in CI — when the API ships, the same YAML becomes its input with no monitor changes.", { x: M + 6.25, y: 6.28, w: 5.85, h: 0.6, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: C.slate, valign: "top" });
  }

  // ------------------------------------------------------------- 22 noise reduction
  {
    const s = L.mk(pptx, {
      kicker: "Topic 15",
      title: "Alert-noise reduction",
      pill: ["shipped", "shipped"],
      sub: "Priority states the required human response. A second, narrower rule decides paging — conflating the two is the main cause of alert fatigue.",
      notes: `This is the most important rule in the framework, so I will read it out.

Pages equals: environment is production, AND the alert band is critical, AND either the priority is P1 — an unambiguous outage — or the source is an SLO burn-rate alert or a composite.

The consequence: a P2 raised by a single symptom archetype — a deadlock, an OOMKill, a failed cron, a retry storm — creates an incident, creates a ServiceNow record, notifies the team channel, and wakes nobody. An SLO burn alert is a measurement of customer harm. A composite has already confirmed two independent conditions. A lone symptom has established neither.

That takes the estate from 651 monitors to 70 that may page — eleven percent. And the number is budgeted at plan time: max_paging_monitors is 90, max_p1_monitors is 85. Raising either is a reviewed pull request with a stated reason, never a side effect of adding archetypes.

Four more mechanisms sit underneath. Multi-alert grouping: the monitor evaluates per group, not per resource. notify_by collapse — the single most effective control — a monitor grouped by cluster, namespace and deployment with notify_by cluster evaluates four thousand groups and sends one notification per cluster. Deduplication and flap suppression: identical dedup key within fifteen minutes is one event, and a group transitioning more than four times an hour is muted with a ticket raised instead. And storm limits: a hundred groups on one monitor collapses to a single "N groups alerting" notification; twenty-five notifications per team per hour suppresses and pages the platform team; fifty pages globally per hour declares a major incident, stops paging and opens the bridge.

Banned group-by keys are enforced three times — policy lint, plan-time precondition, and runtime check C11 — because one container_id in a group_by turns a single alert into thousands.`,
    });
    s.addShape("roundRect", { x: M, y: 2.35, w: 7.0, h: 1.5, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("THE PAGING RULE", { x: M + 0.28, y: 2.5, w: 6.4, h: 0.28, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.6 });
    s.addText("pages =  env == prod\n     AND alert_band == critical\n     AND ( priority == P1  OR  source in (slo_burn, composite) )", { x: M + 0.28, y: 2.8, w: 6.5, h: 0.95, margin: 0, fontSize: 12.5, fontFace: "Courier New", color: C.paper, valign: "middle", lineSpacingMultiple: 1.12 });

    L.stat(s, { x: M + 7.5, y: 2.4, w: 2.2, value: "70", label: "of 651 monitors may page a human", size: 44, vh: 0.85, color: C.red });
    L.stat(s, { x: M + 9.9, y: 2.4, w: 2.2, value: "11%", label: "budgeted at 90 in global.yaml; raising it is a reviewed PR", size: 44, vh: 0.85, color: C.text });

    s.addText("Four mechanisms underneath, applied in order", { x: M, y: 4.05, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    L.cards(s, [
      { t: "Multi-alert grouping", b: "The monitor evaluates per group, not per resource. Maximum three group keys, enforced at plan time — a monitor that breaks it cannot be created." },
      { t: "notify_by collapse", b: "Grouped by cluster + namespace + deployment, notifying by cluster: 4,000 groups evaluated, one notification sent." },
      { t: "Dedup + flap control", b: "Identical dedup_key inside 15 minutes is one event. More than four transitions in an hour is flapping: muted, ticket raised." },
      { t: "Storm limits", b: "100 groups → one summary. 25 per team per hour → suppress and page the platform. 50 pages an hour globally → major incident, stop paging, open the bridge." },
    ], { y: 4.42, h: 1.95, cols: 4 });
  }

  // ---------------------------------------------------------- 23 incident management
  {
    const s = L.mk(pptx, {
      kicker: "Topic 16",
      title: "Incident management",
      pill: ["partial", "partial — no PIR automation"],
      sub: "Severity is derived from the same priority model as everything else, so an incident is opened by policy rather than by whoever happens to be reading the channel.",
      notes: `Incident creation is declared in the notification profiles, and it derives from the same priority model as routing and paging. A P1 opens a SEV-1. A P2 opens a SEV-2. A P3 does not open an incident — it becomes a ServiceNow task when it is sustained. A P4 opens nothing and is reviewed in aggregate.

The response contract is the tier table: P1 acknowledges in five minutes and escalates in ten, twenty-four by seven, with an incident commander on the bridge. P2 acknowledges in ten and escalates in twenty. P3 is next business day. P4 is reviewed monthly.

The flow on the right is what actually happens when a monitor fires, and every step of it is automatic up to the point where a human opens the runbook.

Why PARTIAL, precisely: the severity-to-incident intent is declared and deployed, but there is no incident-command role model in the platform and no timeline or post-incident-review automation. Datadog can hold the incident; we have not yet encoded who does what inside it, or automated the write-up afterwards. That is the next slide.`,
    });
    const sev = [
      ["P1", "SEV-1 incident + ServiceNow P1 + page + major-incident channel + exec notification", "ack 5m · escalate 10m", C.red],
      ["P2", "SEV-2 incident + ServiceNow P2 + team channel — pages only on confirmed impact", "ack 10m · escalate 20m", C.amber],
      ["P3", "No incident. ServiceNow task when sustained past two renotifications", "next business day", C.slate],
      ["P4", "Nothing. Reviewed in aggregate at the monthly alert-quality review", "—", C.muted],
    ];
    sev.forEach((r, i) => {
      const y = 2.4 + i * 0.72;
      s.addShape("roundRect", { x: M, y, w: 7.0, h: 0.64, rectRadius: 0.05, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addShape("roundRect", { x: M + 0.15, y: y + 0.14, w: 0.62, h: 0.36, rectRadius: 0.05, fill: { color: r[3] }, line: { color: r[3] } });
      s.addText(r[0], { x: M + 0.15, y: y + 0.14, w: 0.62, h: 0.36, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: "FFFFFF", align: "center", valign: "middle" });
      s.addText(r[1], { x: M + 0.92, y: y + 0.02, w: 4.5, h: 0.6, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.body, valign: "middle" });
      s.addText(r[2], { x: M + 5.45, y: y + 0.02, w: 1.45, h: 0.6, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.muted, align: "right", valign: "middle" });
    });

    s.addShape("roundRect", { x: M + 7.4, y: 2.4, w: 4.7, h: 3.35, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("WHAT HAPPENS WHEN A MONITOR FIRES", { x: M + 7.65, y: 2.56, w: 4.2, h: 0.3, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.3 });
    s.addText(
      [
        { text: "Diagnostics attach automatically (every alert)", options: { bullet: true, breakLine: true } },
        { text: "Correlation groups it; change events attach as context", options: { bullet: true, breakLine: true } },
        { text: "Rules resolve tags → Teams + ServiceNow + On-Call", options: { bullet: true, breakLine: true } },
        { text: "Responder opens the runbook linked in the alert", options: { bullet: true, breakLine: true } },
        { text: "Remediation: manual, approval-gated or automatic", options: { bullet: true, breakLine: true } },
        { text: "Recovery notification; the group closes when every child recovers", options: { bullet: true, breakLine: true } },
        { text: "Error-budget impact recorded against the SLO", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 7.65, y: 2.94, w: 4.2, h: 2.7, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: "C6D0DF", valign: "top", paraSpaceAfter: 6 }
    );

    s.addShape("roundRect", { x: M, y: 5.95, w: CW, h: 0.62, rectRadius: 0.05, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText(
      [
        { text: "Why partial:  ", options: { bold: true } },
        { text: "severity-to-incident intent is declared and deployed, but there is no incident-command role model in the platform and no timeline or post-incident-review automation. Datadog holds the incident; we have not yet encoded who does what inside it.", options: {} },
      ],
      { x: M + 0.25, y: 5.95, w: CW - 0.5, h: 0.62, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "middle" }
    );
  }

  // -------------------------------------------------------------------- 24 on-call
  {
    const s = L.mk(pptx, {
      kicker: "Topic 17",
      title: "On-call",
      pill: ["action", "act now — rosters"],
      sub: "The structure is built and deployed: 7 teams, 14 schedules, 7 four-step escalation policies. The rosters are empty, so today a page reaches nobody.",
      notes: `I need to be blunt about this one, because it is the second thing this room has to act on.

The structure is real and deployed. Seven teams. Fourteen schedules — a primary and a secondary per team. Seven escalation policies, four steps each: primary, secondary, team lead, then incident commander. Routing rules that split high and low urgency. Ack and escalation timeouts derived from the priority model, not set per team, because a P1 has the same urgency contract everywhere in the enterprise.

And every position is unassigned. Rosters come from the identity-provider sync and are empty at bootstrap. The module builds the full structure regardless and holds an unassigned position rather than inventing a name — which is the correct behaviour, because a fabricated rotation is worse than an obviously empty one. But the operational consequence is simple: if a P1 fired in production this afternoon, the escalation policy would execute correctly and reach nobody.

The fix is not engineering. It is the identity-provider group sync plus each team naming its primary and secondary. That is a people decision, and it belongs to the seven team leads in this room.

One more design note while we are here: teams never configure routing. There is no field for it in the self-service schema and no destination string anywhere in a monitor. Changing where a team's P1s go is one line in teams.yaml and touches zero monitors.`,
    });
    const st = [["7", "teams"], ["14", "schedules — primary + secondary"], ["7", "escalation policies, 4 steps each"], ["0", "positions currently assigned"]];
    st.forEach((x, i) => {
      const px = M + i * 3.05;
      s.addShape("roundRect", { x: px, y: 2.4, w: 2.85, h: 1.3, rectRadius: 0.07, fill: { color: i === 3 ? "FBEEEB" : C.tint }, line: { color: i === 3 ? "FBEEEB" : C.tint } });
      L.stat(s, { x: px + 0.24, y: 2.55, w: 2.4, value: x[0], label: x[1], size: 34, vh: 0.62, color: i === 3 ? C.red : C.text, labelSize: 10.5 });
    });

    s.addText("The escalation chain, derived from the priority model", { x: M, y: 3.92, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    L.flow(s, [
      { t: "Primary\non-call", fill: C.tint },
      { t: "Secondary\non-call", fill: C.tint },
      { t: "Team\nlead", fill: C.tint },
      { t: "Incident\ncommander", fill: C.ink, tc: C.amber },
    ], { x: M, y: 4.32, w: 7.0, h: 0.85, size: 11.5, arrow: 0.26 });
    L.rows(s, [
      { k: "P1", v: "ack 5 min · escalate 10 min · 24×7" },
      { k: "P2 (paging)", v: "ack 10 min · escalate 20 min" },
      { k: "P3 · P4", v: "team channel; never pages" },
    ], { x: M + 7.4, y: 4.32, w: 4.7, kw: 1.6, rh: 0.4, size: 11.5, zebraColor: "F5F7FA" });

    s.addShape("roundRect", { x: M, y: 5.62, w: CW, h: 1.05, rectRadius: 0.07, fill: { color: "FBEEEB" }, line: { color: C.red } });
    s.addText("ACT NOW — the rosters", { x: M + 0.3, y: 5.74, w: 5.0, h: 0.3, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.red, valign: "middle" });
    s.addText("Every schedule position is unassigned. The module holds an UNASSIGNED position rather than inventing a name — a fabricated rotation is worse than an obviously empty one. If a P1 fired this afternoon the policy would execute correctly and reach nobody. The fix is the IdP group sync plus each team naming a primary and a secondary: a people decision, not engineering work.", { x: M + 0.3, y: 5.96, w: 11.4, h: 0.6, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "top" });
  }

  // ---------------------------------------------------------- 25 incident command
  {
    const s = L.mk(pptx, {
      kicker: "Topic 18",
      title: "Incident command",
      pill: ["partial", "partial · phase 6"],
      sub: "The escalation chain has a fourth step reserved for the incident commander. The role model behind that step is written policy, not yet platform configuration.",
      notes: `Incident command is where I want to be most careful about what we claim.

What is real: the fourth escalation step exists on all seven policies and is reserved for the incident commander. The framework declares that a P1 has an IC on the bridge. The global storm limit — fifty pages an hour — automatically declares a major incident, stops paging and opens the bridge, which is exactly the situation an IC exists for.

What is not real: there is no leadership team provisioned in Datadog yet, so step four currently falls back to the owning team. The configuration literally carries an empty leadership team id with a comment saying wire the real id the moment a leadership handle exists. There is no role model in the platform for commander, communications lead, operations lead or scribe. And there is no timeline capture or post-incident-review automation.

The roles on the right are the intended model. Getting there is three concrete pieces of work: provision the leadership team and wire its id, encode the roles in the incident settings, and automate the timeline and PIR. That is scheduled with the reports and dashboards work in phase six.

The honest framing for this room: we have a working escalation path and a written command doctrine. We do not yet have the platform enforcing the doctrine.`,
    });
    const roles = [
      { t: "Incident commander", b: "Owns the incident, not the fix. Decides, delegates, and is the single point of coordination. Step 4 of every escalation policy." },
      { t: "Operations lead", b: "Runs the technical response — the responders, the runbooks, the remediation attempts and their sequencing." },
      { t: "Communications lead", b: "Owns stakeholder and executive updates so the responders are not interrupted for status." },
      { t: "Scribe", b: "Captures the timeline as it happens, which is what makes the post-incident review honest rather than reconstructed." },
    ];
    L.cards(s, roles, { y: 2.45, h: 1.75, cols: 4 });

    s.addShape("roundRect", { x: M, y: 4.45, w: 5.85, h: 1.9, rectRadius: 0.07, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
    s.addText("WHAT IS REAL TODAY", { x: M + 0.28, y: 4.6, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: "1D5C59", charSpacing: 1.5 });
    s.addText(
      [
        { text: "Step 4 of all 7 escalation policies is reserved for the IC", options: { bullet: true, breakLine: true } },
        { text: "P1 declares an IC on the bridge, by policy", options: { bullet: true, breakLine: true } },
        { text: "50 pages in an hour automatically declares a major incident, stops paging and opens the bridge", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 0.28, y: 4.94, w: 5.3, h: 1.3, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "1D5C59", valign: "top", paraSpaceAfter: 6 }
    );

    s.addShape("roundRect", { x: M + 6.25, y: 4.45, w: 5.85, h: 1.9, rectRadius: 0.07, fill: { color: "F3F4F6" }, line: { color: C.line } });
    s.addText("WHAT IS NOT", { x: M + 6.53, y: 4.6, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.slate, charSpacing: 1.5 });
    s.addText(
      [
        { text: "No leadership team provisioned — step 4 falls back to the owning team (leadership_team_id is empty)", options: { bullet: true, breakLine: true } },
        { text: "No role model encoded in incident settings", options: { bullet: true, breakLine: true } },
        { text: "No timeline capture, no post-incident-review automation", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 6.53, y: 4.94, w: 5.3, h: 1.3, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "top", paraSpaceAfter: 6 }
    );
  }

  // ---------------------------------------------------------------- 26 ServiceNow
  {
    const s = L.mk(pptx, {
      kicker: "Topic 19",
      title: "ServiceNow",
      pill: ["shipped", "shipped"],
      sub: "Used deliberately, at one priority level of separation from paging — so the ticket queue records what happened without becoming the thing that wakes people.",
      notes: `ServiceNow is used intentionally, and the intent is the four rows on this slide.

A P1 creates a ServiceNow incident at P1 and pages. A P2 creates a ServiceNow incident at P2 and, unless it comes from a burn-rate alert or a composite, does not page. A P3 creates a task, but only when it is sustained past two renotifications — that is how "actionable but not urgent" avoids becoming "quietly ignored forever". A P4 creates nothing.

Non-production is deliberately different: QA and stage create ServiceNow TASKS, never incidents, and never page. A failing test environment is a work item, not an operational event.

The design principle underneath: the ticket system records and schedules work; the pager interrupts a human life. Those are different decisions, and conflating them is how organisations end up with a ticket queue nobody reads and a pager nobody trusts.

Routing to ServiceNow is resolved by the notification rules from tags — no monitor names a ServiceNow group, so moving a team's tickets to a different assignment group is a one-line change.`,
    });
    const rows = [
      ["P1", "ServiceNow Incident · P1", "Pages · SEV-1 · exec notification", C.red],
      ["P2", "ServiceNow Incident · P2", "Pages only from a burn-rate alert or composite", C.amber],
      ["P3", "ServiceNow Task — when sustained past two renotifications", "Never pages", C.slate],
      ["P4", "Nothing", "Reviewed in aggregate", C.muted],
    ];
    rows.forEach((r, i) => {
      const y = 2.5 + i * 0.78;
      s.addShape("roundRect", { x: M, y, w: 7.6, h: 0.68, rectRadius: 0.05, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      s.addShape("roundRect", { x: M + 0.16, y: y + 0.16, w: 0.64, h: 0.36, rectRadius: 0.05, fill: { color: r[3] }, line: { color: r[3] } });
      s.addText(r[0], { x: M + 0.16, y: y + 0.16, w: 0.64, h: 0.36, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: "FFFFFF", align: "center", valign: "middle" });
      s.addText(r[1], { x: M + 0.96, y, w: 3.9, h: 0.68, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
      s.addText(r[2], { x: M + 4.9, y, w: 2.6, h: 0.68, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
    });

    s.addShape("roundRect", { x: M + 8.0, y: 2.5, w: 4.1, h: 3.24, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("THE PRINCIPLE", { x: M + 8.28, y: 2.68, w: 3.6, h: 0.3, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.5 });
    s.addText("The ticket system records and schedules work.\n\nThe pager interrupts a human life.\n\nThose are different decisions. Conflating them produces a queue nobody reads and a pager nobody trusts.", { x: M + 8.28, y: 3.02, w: 3.6, h: 2.4, margin: 0, fontSize: 13, fontFace: BODY_FONT, color: "C6D0DF", valign: "top", lineSpacingMultiple: 1.05 });

    s.addText("Non-production creates ServiceNow tasks, never incidents, and never pages — a failing test environment is a work item, not an operational event. No monitor names a ServiceNow group: routing is resolved from tags, so moving a team's assignment group is one line.", { x: M, y: 5.95, w: CW, h: 0.6, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });
  }

  // ----------------------------------------------------------------- 27 runbooks
  {
    const s = L.mk(pptx, {
      kicker: "Topic 20",
      title: "Runbooks",
      pill: ["shipped", "shipped"],
      sub: "Native Datadog notebooks attached to the monitor as an asset — not a link to a wiki page that rotted two reorganisations ago.",
      notes: `Two hundred and sixty-one runbooks, published as native Datadog notebooks, attached to all 651 monitors as an asset. Zero runbook URLs pasted into alert bodies — that is measured, and it is a contract check, not an aspiration.

The generation model is the interesting part. One runbook per archetype, id-matched, so "every monitor has a runbook" is mechanically checkable rather than a claim. The generator writes the block a machine genuinely knows — what fired, why it matters, which SLO it affects, which automation is attached, how it is grouped, and the escalation contract — between autogenerated markers, and regenerates it on every catalog change. Human sections outside those markers are preserved forever.

Publishing is API-backed with an embedded content hash, which makes it idempotent, makes drift detectable, and lets CI fail if a published runbook has been edited in the UI away from the repository.

The honest part: sections marked TODO by owner are tracked per domain. That is a visible backlog rather than 261 empty files or 261 stale ones. A generated frame with a named gap is more useful at 3am than a beautifully written runbook for a monitor that no longer exists.

Ownership: the runbook content belongs to the team that owns the archetype's domain, and it changes by pull request like everything else.`,
    });
    const st = [["261", "runbooks published as native notebooks"], ["651 / 651", "monitors with a runbook attached"], ["0", "runbook URLs pasted into alert bodies"]];
    st.forEach((x, i) => {
      const px = M + i * 4.1;
      s.addShape("roundRect", { x: px, y: 2.45, w: 3.87, h: 1.35, rectRadius: 0.07, fill: { color: i === 2 ? C.ink : C.tint }, line: { color: i === 2 ? C.ink : C.tint } });
      L.stat(s, { x: px + 0.28, y: 2.62, w: 3.3, value: x[0], label: x[1], size: 32, vh: 0.6, color: i === 2 ? C.amber : C.text, labelColor: i === 2 ? "9FADC4" : C.muted, labelSize: 10.5 });
    });

    L.flow(s, [
      { t: "Archetype\nchanges", fill: C.tint },
      { t: "Generator writes\nthe machine block", fill: C.tint },
      { t: "Human sections\npreserved", fill: C.tintWarm },
      { t: "Published with\na content hash", fill: C.tint },
      { t: "Attached to the\nmonitor as an asset", fill: C.ink, tc: C.amber },
    ], { y: 4.05, h: 1.0, size: 11.5 });

    L.cards(s, [
      { t: "Mechanically checkable", b: "One runbook per archetype, id-matched. \"Every monitor has a runbook\" is a contract check (C5, C16), not a claim." },
      { t: "Drift-detecting", b: "The embedded content hash makes publishing idempotent and lets CI fail when a notebook is edited away from the repository." },
      { t: "An honest backlog", b: "Sections still marked TODO(owner) are tracked per domain — visible, rather than hidden behind 261 empty or stale files." },
    ], { y: 5.3, h: 1.4, cols: 3 });
  }

  // -------------------------------------------------------- 28 workflow automation
  {
    const s = L.mk(pptx, {
      kicker: "Topic 21",
      title: "Workflow automation",
      pill: ["action", "act now — quota"],
      sub: "Automation is classified by blast radius, and the module refuses to publish a workflow whose class does not match its safeguards.",
      notes: `Twenty-seven workflows are catalogued and classified into four classes by blast radius.

Diagnostic-only is read-only. It gathers context and changes nothing, and it runs automatically on every single alert — so by the time a human opens the page, the error samples, the last three deploys and the dependency health summary are already attached. That is the class that saves the most time and carries the least risk.

Fully automatic changes production, but only where the action is provably safe, idempotent and reversible, and only with a blast-radius cap. The module refuses to publish one without reversible true and a maximum actions per hour.

Approval-required prepares everything and waits for a human decision. Manual means the runbook documents it and no automation exists yet — which is an honest state, not a failure.

That guardrail did real work during construction: a job-rerun workflow was marked irreversible with owner approval, and the resolution was to make the guardrail explicit — the workflow now refuses to touch a job that has not declared itself idempotent.

And now the action item. Only two of the twenty-seven are deployed. The organisation's Datadog plan caps total workflows at about twenty, and eighteen of those slots are held by workflows from an August experiment owned by a different Datadog login. Our CI credentials get a 403 trying to delete them, because of per-resource restriction policies. Someone with that login, or an org admin using each workflow's permissions UI, needs to delete those eighteen. Then we raise the budget in one tfvars line and the rest of the catalog deploys.

That is a five-minute task blocking twenty-five automations.`,
    });
    const classes = [
      { t: "diagnostic_only", b: "Read-only. Gathers context, changes nothing, runs automatically on every alert. No approval.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
      { t: "fully_automatic", b: "Changes production, but provably safe, idempotent and reversible — with a blast-radius cap.", fill: C.tint },
      { t: "approval_required", b: "Prepares everything and waits for a human decision. Anything that can lose data lands here.", fill: C.tint },
      { t: "manual", b: "Documented in the runbook; no automation exists yet. An honest state, not a failure.", fill: "F3F4F6" },
    ];
    L.cards(s, classes, { y: 2.45, h: 1.5, cols: 4 });

    s.addShape("roundRect", { x: M, y: 4.15, w: 5.85, h: 1.15, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("The rule the module enforces (ADR-008)", { x: M + 0.28, y: 4.28, w: 5.3, h: 0.3, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.amber, valign: "middle" });
    s.addText("A workflow attached to a monitor may only be fully_automatic if reversible: true AND blast_radius is bounded. Anything that can lose data, restart a stateful service or scale cost is approval_required.", { x: M + 0.28, y: 4.58, w: 5.3, h: 0.65, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "AEBACD", valign: "top" });

    L.stat(s, { x: M + 6.45, y: 4.2, w: 2.4, value: "27", label: "workflows catalogued and classified", size: 40, vh: 0.75, color: C.text });
    L.stat(s, { x: M + 9.2, y: 4.2, w: 2.9, value: "2", label: "deployed — the rest are blocked by the org's workflow quota", size: 40, vh: 0.75, color: C.red });

    s.addShape("roundRect", { x: M, y: 5.5, w: CW, h: 1.1, rectRadius: 0.07, fill: { color: "FBEEEB" }, line: { color: C.red } });
    s.addText("ACT NOW — release the workflow quota", { x: M + 0.3, y: 5.62, w: 6.0, h: 0.3, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.red, valign: "middle" });
    s.addText("The plan caps total workflows at roughly 20, and 18 slots are held by workflows from an earlier experiment owned by a different Datadog login — our CI credentials get a 403 deleting them, because of per-resource restriction policies. That login, or an org admin via each workflow's Permissions UI, deletes those 18; we then raise one line in budget.auto.tfvars and the remaining 25 automations deploy. A five-minute task is blocking the catalog.", { x: M + 0.3, y: 5.92, w: 11.4, h: 0.62, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "top" });
  }

  // ------------------------------------------------------------ 29 part 5 div
  divider(pptx, {
    part: "PART FIVE",
    title: "Surfaces\nand access",
    strap: "How people who are not on-call engineers get to the platform: reports, dashboards, a conversational interface, and an executive view.",
    first: 22,
    topics: [
      "Reports",
      "The minimal dashboard strategy",
      "MCP — Ask",
      "MCP — Act",
      "MCP governance",
      "The executive portal",
    ],
    notes: `Part five is where most of the remaining roadmap lives. Five of these six topics are not built. I will be explicit about each one and about the order we build them in.`,
  });

  // ------------------------------------------------------------------ 30 reports
  {
    const s = L.mk(pptx, {
      kicker: "Topic 22",
      title: "Reports",
      pill: ["roadmap", "roadmap · phase 6"],
      sub: "Four operational reports run today and gate the pipeline. The five audience-facing report families do not exist yet.",
      notes: `Four reports exist today and they are not cosmetic — three of them gate the pipeline.

The coverage and compliance report runs seventeen checks, C1 to C17, against the live org, and blocks a production deploy on platform-integrity findings. The quality scorecard grades every monitor across eight dimensions and fails CI below a fleet average of 85 or on any failing monitor. The monitor reconciliation report gives one row per managed monitor — service, owner, severity, route, escalation policy, runbook, notebook id, auto-resolve, SLO, workflow, status. And the coverage matrix documents every archetype instance and is regenerated by CI so it cannot drift.

What does not exist is the report catalog: an executive report, an operations report, a platform report, a database report and an Azure report — five named audiences, five recurring outputs, delivered rather than pulled. That is phase six, alongside the dashboard consolidation.

The distinction matters. What we have is engineering instrumentation that happens to be readable. What we do not have is a product that arrives in an executive's inbox on the first Monday of the month. I am not going to describe the second one as if it exists.`,
    });
    s.addText("Running today — three of these gate the pipeline", { x: M, y: 2.35, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    L.cards(s, [
      { t: "Coverage & compliance", b: "17 checks (C1–C17) against the live org. Blocks a production deploy on platform-integrity findings; the nightly run opens an issue.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
      { t: "Quality scorecard", b: "Every monitor scored out of 100 across 8 dimensions. CI fails below a fleet average of 85, or on any single failing monitor.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
      { t: "Monitor reconciliation", b: "One row per managed monitor: owner, severity, route, escalation policy, runbook, notebook id, SLO, workflow, status.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
      { t: "Coverage matrix", b: "Every archetype instance with its detection, environment, band, priority and grouping. Regenerated by CI so it cannot drift.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
    ], { y: 2.72, h: 1.75, cols: 4 });

    s.addText("Not built — the five audience-facing report families", { x: M, y: 4.65, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.slate, valign: "middle" });
    const fam = ["Executive", "Operations", "Platform", "Database", "Azure / cloud cost"];
    fam.forEach((f, i) => {
      const x = M + i * 2.43;
      s.addShape("roundRect", { x, y: 5.08, w: 2.25, h: 0.75, rectRadius: 0.05, fill: { color: "F3F4F6" }, line: { color: C.line } });
      s.addText(f, { x: x + 0.12, y: 5.08, w: 2.0, h: 0.75, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: C.slate, align: "center", valign: "middle" });
    });
    s.addText("The distinction matters: what exists is engineering instrumentation that happens to be readable. What does not exist is a product that arrives in a named audience's inbox on a schedule. Phase 6 builds the second one, alongside the dashboard consolidation.", { x: M, y: 6.0, w: CW, h: 0.6, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });
  }
}

module.exports = { build };
