const L = require("./lib");
const { C, HEAD_FONT, BODY_FONT, M, W, CW } = L;
const { divider } = require("./part1");

function build(pptx) {
  // -------------------------------------------------------------- 31 dashboards
  {
    const s = L.mk(pptx, {
      kicker: "Topic 23",
      title: "The minimal dashboard strategy",
      pill: ["partial", "partial — 18, target 4"],
      sub: "Four boards for the enterprise. Per-service views are Datadog-native and free — a custom dashboard per service at estate scale is unmaintainable and redundant.",
      notes: `The design position is four dashboards, and the reasoning is that Datadog's Service Catalog, APM views and Infrastructure views are better than anything we would hand-build, and they are already there.

The four: an enterprise overview for leadership, an operations overview for the people running the estate, an on-call board for the person holding the pager, and an alert-quality board — which is the one that keeps the platform honest, because it shows pages per team, the noisiest monitors, actionability and auto-resolve rates.

Today there are eighteen: those four plus fourteen generated per-domain drill-downs. That is not a disaster — they are generated, consistent and cheap — but it is more than the design calls for, and every extra board is a thing that can go stale and mislead. Phase six retires the per-domain generator in favour of native domain views and keeps the four.

The rule I would ask this room to hold us to: a dashboard is not a deliverable. Nobody's reliability improved because a board existed. The four we keep are the ones that drive a decision — is the estate healthy, what is on fire, who is holding the pager, and is our alerting any good.`,
    });
    const keep = [
      { t: "Enterprise overview", b: "Estate health by domain, SLO status, error-budget position. The leadership view." },
      { t: "Operations overview", b: "What is alerting now, correlation groups, change events, the current storm state." },
      { t: "On-call board", b: "One screen for the person holding the pager: active pages, ack state, escalation." },
      { t: "Alert quality", b: "Pages per team, the top 20 noisiest monitors, actionability and auto-resolve rates." },
    ];
    L.cards(s, keep, { y: 2.5, h: 1.6, cols: 4 });

    s.addShape("roundRect", { x: M, y: 4.35, w: 5.85, h: 1.45, rectRadius: 0.07, fill: { color: C.tintWarm }, line: { color: C.tintWarm } });
    L.stat(s, { x: M + 0.3, y: 4.52, w: 5.3, value: "18 today  →  4", label: "Four hand-authored boards plus fourteen generated per-domain drill-downs. Phase 6 retires the generator in favour of Datadog's native domain views.", size: 28, vh: 0.55, color: "5C4514", labelColor: "7A5A1E", labelSize: 11 });

    s.addShape("roundRect", { x: M + 6.25, y: 4.35, w: 5.85, h: 1.45, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("THE RULE TO HOLD US TO", { x: M + 6.53, y: 4.5, w: 5.3, h: 0.3, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.5 });
    s.addText("A dashboard is not a deliverable. Nobody's reliability improved because a board existed. The four we keep each drive a decision: is the estate healthy, what is on fire, who holds the pager, and is our alerting any good.", { x: M + 6.53, y: 4.84, w: 5.3, h: 0.85, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "C6D0DF", valign: "top" });

    s.addText("Deliberately not built: a dashboard per service. At 100,000 services that is 100,000 boards to maintain, all of them worse than the Service Catalog entry Datadog generates for free.", { x: M, y: 5.98, w: CW, h: 0.6, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });
  }

  // -------------------------------------------------------------- 32 MCP Ask
  {
    const s = L.mk(pptx, {
      kicker: "Topic 24",
      title: "MCP — Ask",
      pill: ["roadmap", "roadmap · phase 7"],
      sub: "A conversational interface to the platform's own state, grounded in live data rather than in a model's recollection. Nothing of this exists today.",
      notes: `Let me start with the disclaimer, because this is the topic most likely to be over-sold in a room like this: a repository-wide search for MCP returns zero files. None of this is built. It is phase seven, after the platform is true.

What Ask mode will be: a server exposing the platform's own state — catalog, monitors, SLOs, events, incidents, on-call, fleet, reports — as tools, over the same policy engine the Terraform already reads. So the answer to "which tier0 services have no SLO?" comes from resolving the actual policy hierarchy, not from a model guessing.

The questions on the right are the kind of thing it must answer, and the acceptance test is specific: every one answered from live state, with the query it ran shown alongside the answer.

Why this matters more than it sounds. Today, answering "who owns this alert and why did it page?" requires someone who knows the repository. That person is a bottleneck and a single point of failure. Ask mode turns platform knowledge from a person into an interface.

Two design commitments I want on the record now, before anyone builds it. It is independent of Bits AI — this is our platform's state, exposed by us. And it is read-only: Ask cannot change anything. Changing things is the next slide, and it works completely differently.`,
    });
    s.addShape("roundRect", { x: M, y: 2.45, w: 5.85, h: 3.85, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("QUESTIONS IT MUST ANSWER FROM LIVE STATE", { x: M + 0.28, y: 2.62, w: 5.3, h: 0.3, margin: 0, fontSize: 9.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.3 });
    s.addText(
      [
        { text: "\"Which tier0 services have no SLO?\"", options: { breakLine: true } },
        { text: "\"Why did this monitor page me at 3am?\"", options: { breakLine: true } },
        { text: "\"What is the error-budget position for payments this month?\"", options: { breakLine: true } },
        { text: "\"Which resources are unowned, and for how long?\"", options: { breakLine: true } },
        { text: "\"What changed in the thirty minutes before this incident?\"", options: { breakLine: true } },
        { text: "\"Which monitors have fired more than ten times and never been acted on?\"", options: { breakLine: true } },
        { text: "\"What is our agent-fleet compliance by subscription?\"", options: { breakLine: false } },
      ],
      { x: M + 0.28, y: 3.0, w: 5.3, h: 3.1, margin: 0, fontSize: 12.5, fontFace: BODY_FONT, color: "D3DCE9", valign: "top", paraSpaceAfter: 9 }
    );

    L.cards(s, [
      { t: "Grounded, not generative", b: "Every answer resolves against the live org and the same policy files Terraform reads. The acceptance test is that the query it ran is shown next to the answer." },
      { t: "Independent of Bits AI", b: "This is our platform's state, exposed by us, over our own policy engine — not a dependency on a vendor feature roadmap." },
      { t: "Read-only, by construction", b: "Ask cannot change anything. Change is a separate mode with a completely different safety model — the next slide." },
      { t: "Why it matters", b: "Today, \"who owns this alert and why did it page?\" needs someone who knows the repository. That person is a bottleneck. This turns platform knowledge into an interface." },
    ], { x: M + 6.25, y: 2.45, w: 5.85, h: 1.8, cols: 2, gap: 0.22, rgap: 0.22, bodySize: 10.5, titleSize: 13 });
  }

  // -------------------------------------------------------------- 33 MCP Act
  {
    const s = L.mk(pptx, {
      kicker: "Topic 25",
      title: "MCP — Act",
      pill: ["roadmap", "roadmap · phase 7"],
      sub: "Act mode never writes to Datadog. It writes YAML, opens a pull request, and lets the existing gate decide — the same path a human takes, at machine speed.",
      notes: `Act mode is where an AI interface to an infrastructure platform usually goes wrong, so the design commitment is simple and absolute: the MCP server never touches Datadog directly. Not once, not for a small change, not in an emergency.

What it does instead: inspect the current state, validate a proposed change against the policy engine, generate the YAML, open a pull request, and let the existing CI gate run — schema, policy lint, cardinality, paging discipline, budget checks, plan determinism, and Datadog's own monitor validation API. A human approves. Terraform applies.

The acceptance criterion is exactly one sentence: a pull request created by the MCP server passes CI unmodified. If it cannot meet the same bar as a human contributor, it does not get to contribute.

The value is speed and correctness on the boring changes: a new service registration, a threshold rationale, a routing update, an exception with an expiry. Those are the changes that today wait days for someone with repository knowledge to find twenty minutes.

What it deliberately cannot do: bypass the gate, apply Terraform, mute a monitor, or edit anything in the Datadog UI. Every one of those would break the invariant that the repository is the only source of truth — and the moment that invariant breaks, the drift detection that keeps this platform honest becomes noise.`,
    });
    L.flow(s, [
      { t: "Inspect\ncurrent state", fill: C.tint },
      { t: "Validate\nagainst policy", fill: C.tint },
      { t: "Generate\nYAML", fill: C.tint },
      { t: "Open a\npull request", fill: C.ink, tc: C.amber },
      { t: "CI gate\n+ human approval", fill: C.tintWarm },
      { t: "Terraform\napplies", fill: C.tint },
    ], { y: 2.5, h: 1.0, size: 11.5 });

    s.addShape("roundRect", { x: M, y: 3.75, w: 5.85, h: 2.6, rectRadius: 0.07, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
    s.addText("WHAT IT WILL DO", { x: M + 0.28, y: 3.9, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: "1D5C59", charSpacing: 1.5 });
    s.addText(
      [
        { text: "Register a service, or correct its tier and archetype", options: { bullet: true, breakLine: true } },
        { text: "Draft a self-service monitor from a described symptom", options: { bullet: true, breakLine: true } },
        { text: "Add a rationale to a fixed threshold that lacks one", options: { bullet: true, breakLine: true } },
        { text: "File an exception with a reason, approver and expiry", options: { bullet: true, breakLine: true } },
        { text: "Update team routing or escalation in teams.yaml", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 0.28, y: 4.24, w: 5.3, h: 2.0, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "1D5C59", valign: "top", paraSpaceAfter: 7 }
    );

    s.addShape("roundRect", { x: M + 6.25, y: 3.75, w: 5.85, h: 2.6, rectRadius: 0.07, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
    s.addText("WHAT IT WILL NEVER DO", { x: M + 6.53, y: 3.9, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.red, charSpacing: 1.5 });
    s.addText(
      [
        { text: "Write to the Datadog API directly — not once, not in an emergency", options: { bullet: true, breakLine: true } },
        { text: "Run terraform apply", options: { bullet: true, breakLine: true } },
        { text: "Bypass the CI gate or self-approve a pull request", options: { bullet: true, breakLine: true } },
        { text: "Mute a monitor or edit anything in the Datadog UI", options: { bullet: true, breakLine: true } },
        { text: "Acceptance test: a pull request it opens passes CI unmodified — the same bar as a human contributor", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 6.53, y: 4.24, w: 5.3, h: 2.0, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "7A2E24", valign: "top", paraSpaceAfter: 7 }
    );
  }

  // -------------------------------------------------------- 34 MCP governance
  {
    const s = L.mk(pptx, {
      kicker: "Topic 26",
      title: "MCP governance",
      pill: ["roadmap", "roadmap · phase 7"],
      sub: "The safety model is designed before the server is, because an interface that can propose infrastructure changes is an interface that will be asked to do something it should refuse.",
      notes: `Five controls, and I want them agreed in principle before a line of the server is written.

Authentication: no anonymous access, no shared token. Identity comes from the corporate identity provider, and every session is attributable to a person.

Authorisation: the same RBAC model the platform already uses, mapped through. A user who cannot edit monitors in Datadog cannot open a monitor pull request through the MCP server. The interface never grants more than the person already has.

Dry run by default. Every write-shaped tool call returns a plan first. Nothing is committed without a second, explicit confirmation naming exactly what will change.

Approval: a human approves the pull request. The server is a contributor, never a reviewer, and never its own approver.

Audit: every tool call — read and write — is logged with the identity, the arguments, the result and the resulting pull request, and that log is queryable. If we cannot answer "what did it do last Tuesday and who asked it to", we should not run it.

The negative tests matter as much as the positive ones. An unauthorised write must be refused and logged. That is an acceptance criterion, not a nice-to-have.`,
    });
    const ctrl = [
      { t: "Authentication", b: "Identity from the corporate IdP. No anonymous access, no shared token, every session attributable to a person." },
      { t: "Authorisation", b: "The platform's existing RBAC mapped through. The interface never grants more than the person already has in Datadog." },
      { t: "Dry run by default", b: "Every write-shaped call returns a plan first. Nothing commits without a second, explicit confirmation naming what changes." },
      { t: "Human approval", b: "A person approves the pull request. The server is a contributor — never a reviewer, and never its own approver." },
      { t: "Audit", b: "Every call, read and write, logged with identity, arguments, result and resulting PR — and queryable afterwards." },
    ];
    L.cards(s, ctrl, { y: 2.6, h: 1.75, cols: 5, gap: 0.2, bodySize: 10.5, titleSize: 13 });

    s.addShape("roundRect", { x: M, y: 4.65, w: CW, h: 1.65, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("THE ACCEPTANCE TESTS ARE THE NEGATIVE ONES", { x: M + 0.3, y: 4.82, w: 11.4, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.5 });
    s.addText(
      [
        { text: "An unauthorised write is refused and logged", options: { bullet: true, breakLine: true } },
        { text: "A change that violates policy — a P1 on a tier2 service, a banned group-by key, a fixed threshold with no rationale — is rejected by the same linter that rejects a human's pull request, with the same message", options: { bullet: true, breakLine: true } },
        { text: "A request to \"just apply it directly\" has no code path that could satisfy it", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 0.3, y: 5.16, w: 11.4, h: 1.05, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "C6D0DF", valign: "top", paraSpaceAfter: 6 }
    );
  }

  // ------------------------------------------------------- 35 executive portal
  {
    const s = L.mk(pptx, {
      kicker: "Topic 27",
      title: "The executive portal",
      pill: ["roadmap", "roadmap · phase 8"],
      sub: "One read-only surface where a non-engineer can see estate health and drill from the enterprise down to a single incident without needing to know Datadog.",
      notes: `There is no web application in the repository. This is phase eight, and it is deliberately last among the product surfaces, because a portal over an estate whose telemetry is not tagged would show a very convincing picture of nothing.

The design: progressive drilldown in five levels. Enterprise health, then system, then service, then the SLO and its error budget, then the incident. Each level answers one question and offers exactly one way down.

Three non-negotiables. It reads live Datadog APIs — no copies, no nightly export that is quietly six hours stale. It shows data freshness on every panel, because an executive dashboard that silently displays stale numbers during an incident is worse than no dashboard. And it authenticates with corporate SSO against a read-only role — the Viewer / Auditor role already exists in our RBAC model and is exactly right for this.

Who it is for: everyone in this room who is not going to open Datadog. The value is that "how are we doing?" stops being a question someone has to build a slide to answer — which, I will note without irony, is what I have spent this week doing.`,
    });
    const levels = ["Enterprise", "System", "Service", "SLO + error budget", "Incident"];
    levels.forEach((l, i) => {
      const x = M + i * 2.43;
      s.addShape("roundRect", { x, y: 2.5, w: 2.25, h: 1.0, rectRadius: 0.06, fill: { color: i === 0 ? C.ink : C.tint }, line: { color: i === 0 ? C.ink : C.tint } });
      s.addText(l, { x: x + 0.12, y: 2.5, w: 2.0, h: 1.0, margin: 0, fontSize: 12.5, bold: true, fontFace: BODY_FONT, color: i === 0 ? C.amber : C.text, align: "center", valign: "middle" });
      if (i < levels.length - 1) {
        s.addShape("rightArrow", { x: x + 2.28, y: 2.9, w: 0.14, h: 0.18, fill: { color: C.slate }, line: { color: C.slate } });
      }
    });
    s.addText("Five levels. Each answers one question and offers exactly one way down.", { x: M, y: 3.62, w: 11.6, h: 0.3, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.muted, valign: "middle" });

    L.cards(s, [
      { t: "Live, not exported", b: "Reads the Datadog APIs directly. No nightly copy that is quietly six hours stale during the one hour it matters." },
      { t: "Freshness on every panel", b: "An executive view that silently shows stale numbers during an incident is worse than no view at all." },
      { t: "SSO, read-only", b: "Corporate SSO against the Viewer / Auditor role that already exists in the RBAC model — sees everything, changes nothing." },
    ], { y: 4.1, h: 1.55, cols: 3 });

    s.addShape("roundRect", { x: M, y: 5.85, w: CW, h: 0.75, rectRadius: 0.06, fill: { color: "F3F4F6" }, line: { color: C.line } });
    s.addText(
      [
        { text: "Sequenced last on purpose:  ", options: { bold: true } },
        { text: "a portal over an estate whose telemetry is not yet tagged would render a very convincing picture of nothing. Phases 1–3 make the data true; phase 8 makes it visible to people who will never open Datadog.", options: {} },
      ],
      { x: M + 0.3, y: 5.85, w: CW - 0.6, h: 0.75, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "middle" }
    );
  }

  // ------------------------------------------------------------ 36 part 6 div
  divider(pptx, {
    part: "PART SIX",
    title: "Operating it, and\nwhat good looks like",
    strap: "The two procedures every team will use, the outcomes we expect, and the numbers we will be judged on.",
    first: 28,
    topics: [
      "How to onboard a new service",
      "How to add a new monitor",
      "Expected outcomes",
      "The adoption model",
      "Success metrics",
    ],
    notes: `Part six is the practical close: two procedures, the outcomes, the adoption sequence, and the metrics we will publish monthly.`,
  });

  // -------------------------------------------------------- 37 onboard a service
  {
    const s = L.mk(pptx, {
      kicker: "Topic 28",
      title: "How to onboard a new service",
      pill: ["shipped", "shipped"],
      sub: "Six steps, one of which is writing a file. Everything after step 3 happens because the platform derives it, not because anyone configures it.",
      notes: `Walk through it, because this is the procedure most people in this room will actually touch.

Step one: tag the telemetry. env, service, team, tier, service_archetype — plus the alert_band that the platform derives and that must reach the telemetry. Agent config, Azure resource tags via policy, Kubernetes labels, or DD_TAGS depending on where the thing runs.

Step two: pick the service archetype honestly. Pick by what the thing IS, not what it is written in. A Java service behind HTTP is an api; the same codebase consuming a queue is an event_consumer. That single declaration selects the monitor packs.

Step three: write the registration file — five fields — and open a pull request. CI validates the schema, the tier, the routing resolution and the SLO association.

Step four: merge. It applies to qa and stage automatically; production is an explicit dispatch behind an approval gate.

Step five: verify. The coverage report will show the service as owned rather than as a C2 violation, and the service catalog entry appears with your team on it.

Step six: fill in your runbook sections. That is the only ongoing obligation, and it is the difference between an alert that helps at 3am and one that just wakes someone.

Elapsed engineering time for a team that already tags correctly: minutes. That is the point.`,
    });
    const steps = [
      { t: "1  Tag the telemetry", b: "env · service · team · tier · service_archetype, plus the derived alert_band. Agent config, Azure Policy, K8s labels or DD_TAGS." },
      { t: "2  Pick the archetype", b: "By what the thing IS, not what it is written in. A Java service behind HTTP is api; the same code consuming a queue is event_consumer." },
      { t: "3  Register — one file", b: "Five fields in platform/services/<name>.yaml. Open a pull request; CI validates schema, tier, routing and SLO association." },
      { t: "4  Merge", b: "qa and stage apply automatically. Production is an explicit dispatch behind the approval environment." },
      { t: "5  Verify", b: "The coverage report shows the service as owned instead of a C2 violation, and the catalog entry carries your team." },
      { t: "6  Fill in the runbook", b: "The only ongoing obligation — and the difference between an alert that helps at 3am and one that just wakes someone." },
    ];
    L.cards(s, steps, { y: 2.5, h: 1.65, cols: 3, rgap: 0.28 });

    s.addShape("roundRect", { x: M, y: 6.0, w: CW, h: 0.62, rectRadius: 0.06, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText(
      [
        { text: "You never write:  ", options: { bold: true, color: C.amber } },
        { text: "Terraform · a Datadog notification handle · a monitor definition · a threshold · a routing rule · an escalation policy. All of it is derived from two declarations: your tier and your service archetype.", options: { color: "C6D0DF" } },
      ],
      { x: M + 0.3, y: 6.0, w: CW - 0.6, h: 0.62, margin: 0, fontSize: 12, fontFace: BODY_FONT, valign: "middle" }
    );
  }

  // ---------------------------------------------------------- 38 add a monitor
  {
    const s = L.mk(pptx, {
      kicker: "Topic 29",
      title: "How to add a new monitor",
      pill: ["shipped", "shipped"],
      sub: "For a pattern everyone needs, one archetype. For a genuinely unique requirement, one manifest of about fifteen lines. You delete the monitor by deleting the file.",
      notes: `Two paths, and choosing between them is the only judgement call.

If the need is a pattern — anything that would apply to more than one service — it belongs in the archetype catalog, because then everyone with that archetype gets it. That is a pull request against platform/policy/archetypes, reviewed by the platform team.

If the need is genuinely unique to one service, it is a self-service manifest: one file, about fifteen lines, in platform/monitors. The requesting team owns it; the platform team reviews only exceptions.

Either way the gate is the same, and it is worth listing because it is what makes this safe: JSON schema, policy lint across twelve rule families, duplicate detection, cardinality limits, scope validation, routing resolution, SLO association, runbook presence, the quality score, plan-time preconditions and budget checks, plan determinism, and every planned monitor submitted to Datadog's own validation API. Then a terraform plan is posted to the pull request.

Three rules that come up every time. Thresholds are per archetype, never per host — if a host is genuinely special it needs its own service identity. You cannot raise your own priority; priority comes from tier, and tier is a reviewed business decision, so the validator rejects a P1 on a tier2 service and tells you why. And if it is noisy, that is a defect with an owner — open a pull request against the archetype so everyone benefits, or file an exception with a reason, an approver and an expiry. Do not mute it.`,
    });
    s.addShape("roundRect", { x: M, y: 2.5, w: 5.85, h: 1.35, rectRadius: 0.07, fill: { color: C.tint }, line: { color: C.tint } });
    s.addText("A PATTERN EVERYONE NEEDS  →  ONE ARCHETYPE", { x: M + 0.28, y: 2.64, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amberDeep, charSpacing: 1.3 });
    s.addText("A pull request against platform/policy/archetypes/. Every service with that archetype gets the coverage — which is why a pattern must never be solved with a per-service monitor.", { x: M + 0.28, y: 2.98, w: 5.3, h: 0.75, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });

    s.addShape("roundRect", { x: M + 6.25, y: 2.5, w: 5.85, h: 1.35, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("GENUINELY UNIQUE  →  ONE MANIFEST", { x: M + 6.53, y: 2.64, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.3 });
    s.addText("About fifteen lines in platform/monitors/. The requesting team owns it; the platform team reviews only exceptions. You delete the monitor by deleting the file.", { x: M + 6.53, y: 2.98, w: 5.3, h: 0.75, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "AEBACD", valign: "top" });

    s.addText("The same gate runs either way", { x: M, y: 4.0, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const gates = ["JSON schema", "Policy lint · 12 families", "Duplicate detection", "Cardinality limits", "Scope validation", "Routing resolution", "SLO association", "Runbook presence", "Quality score", "Plan preconditions", "Budget checks", "Datadog's validation API"];
    gates.forEach((g, i) => {
      const c = i % 6, r = Math.floor(i / 6);
      const x = M + c * 2.03, y = 4.42 + r * 0.5;
      s.addShape("roundRect", { x, y, w: 1.9, h: 0.42, rectRadius: 0.05, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
      s.addText(g, { x: x + 0.08, y, w: 1.74, h: 0.42, margin: 0, fontSize: 9.5, fontFace: BODY_FONT, color: "1D5C59", align: "center", valign: "middle" });
    });

    L.rows(s, [
      { k: "Thresholds are per archetype", v: "never per host. If a host is genuinely special it needs its own service identity — see ADR-014" },
      { k: "You cannot self-raise priority", v: "priority derives from tier; the validator rejects a P1 on a tier2 service and says so" },
      { k: "Noise is a defect with an owner", v: "fix the archetype so everyone benefits, or file an exception with a reason, approver and expiry. Never mute" },
    ], { y: 5.55, rh: 0.42, kw: 3.6, size: 11.5 });
  }

  // ------------------------------------------------------------ 39 outcomes
  {
    const s = L.mk(pptx, {
      kicker: "Topic 30",
      title: "Expected outcomes",
      pill: ["partial", "partial — structural, not yet measured"],
      sub: "The structural outcomes are real and verifiable today. The behavioural outcomes — noise, MTTA, MTTR — cannot be claimed until the telemetry carries the tags.",
      notes: `I have split this deliberately, because it is the slide most likely to be quoted back at me.

The structural outcomes are true today and you can verify every one. 651 monitors for an estate the naive model would need eight million for. Zero new Datadog objects when fifty thousand services are added. Seventy monitors — eleven percent — may page a human, budgeted at ninety at plan time. Zero monitors without a runbook, an SLO association, automation, resolvable routing or an auto-resolve window; all contract-enforced. Zero fixed thresholds without a written rationale; CI-enforced. One hundred percent coverage of the alertable estate. And 651 of 651 monitor queries validated by Datadog's own API on the last deploy.

The behavioural outcomes are what the business actually cares about: fewer pages per engineer per week, faster acknowledgement, faster resolution, and a measurable drop in alerts nobody acts on. I cannot show you a before-and-after on any of those, for two honest reasons. First, we have no trustworthy baseline from the previous model. Second, and more importantly, the monitors are not receiving data yet — so any noise number I showed you today would be zero, and zero would be a lie by omission.

That is the deal I am offering: structural outcomes now, behavioural outcomes measured and published from the month after the tagging lands. Hold me to the second half.`,
    });
    s.addText("Structural — true today, and independently verifiable", { x: M, y: 2.35, w: 11.6, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
    const outs = [
      ["651", "monitors vs ~8,000,000 in the naive model"],
      ["0", "new objects when 50,000 services are added"],
      ["11%", "of monitors may page — 70 of 651"],
      ["0", "monitors missing a runbook, SLO, automation or routing"],
      ["0", "fixed thresholds without a written rationale"],
      ["100%", "of the alertable estate covered"],
    ];
    outs.forEach((o, i) => {
      const c = i % 3, r = Math.floor(i / 3);
      const x = M + c * 4.1, y = 2.78 + r * 1.12;
      s.addShape("roundRect", { x, y, w: 3.87, h: 1.0, rectRadius: 0.06, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
      s.addText(o[0], { x: x + 0.24, y: y + 0.08, w: 1.5, h: 0.6, margin: 0, fontSize: 30, bold: true, fontFace: HEAD_FONT, color: "1D5C59", valign: "middle" });
      s.addText(o[1], { x: x + 1.8, y: y + 0.08, w: 1.9, h: 0.84, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
    });

    s.addShape("roundRect", { x: M, y: 5.15, w: CW, h: 1.45, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("BEHAVIOURAL — NOT YET CLAIMED, AND HERE IS WHY", { x: M + 0.3, y: 5.3, w: 11.4, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.5 });
    s.addText("Pages per engineer per week · time to acknowledge · time to resolve · the proportion of alerts nobody acts on. There is no trustworthy baseline from the previous model, and — more honestly — the monitors are not receiving data yet, so any noise number shown today would be zero, and zero would be a lie by omission. The deal: structural outcomes now, behavioural outcomes measured and published from the month after the tagging lands.", { x: M + 0.3, y: 5.64, w: 11.4, h: 0.85, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "C6D0DF", valign: "top" });
  }

  // ------------------------------------------------------- 40 adoption model
  {
    const s = L.mk(pptx, {
      kicker: "Topic 31",
      title: "The adoption model",
      pill: ["shipped", "shipped — the platform"],
      sub: "The platform is deployed. Adoption is a tagging campaign, and tagging is always the project — every other step is small by comparison.",
      notes: `The sequencing principle: nothing here is adopted by a big-bang cutover, and no team is asked to migrate their monitors. The monitors already exist; a team joins them by being correctly tagged.

Five movements. First, the platform lands — done: first full promotion completed green, all four environments, with the evidence artifact attached to the run. Second, the tagging campaign — this is the project, and it is where the effort actually is. Azure Policy with a modify effect on resource groups, agent configuration on hosts, Kubernetes labels, and DD_TAGS plus DD_VERSION in the deployment pipelines. Third, rosters and routing — teams name their primary and secondary and confirm their channels. Fourth, per-team onboarding: register services, choose tiers, fill in runbooks. Fifth, the surfaces — reports, MCP, the portal.

Note what is deliberately NOT in this list: a request for teams to write monitors, a migration of existing monitors, or a freeze. There is no cutover event.

The adoption unit is a team, not a service, because the tagging work, the roster and the runbook ownership are all team-level. Seven teams. A team that already tags cleanly is done in a day.

What we ask of leadership: an owner for the Azure Policy work, the rosters named, and the workflow quota released. Those three unblock everything else.`,
    });
    const moves = [
      { t: "1 · Platform lands", b: "Done. First full promotion green across qa, stage and production, with the evidence artifact attached to the run.", fill: "EAF3F1", tc: "1D5C59", bc: "1D5C59" },
      { t: "2 · Tag the estate", b: "The project. Azure Policy modify on resource groups, agent config, K8s labels, DD_TAGS and DD_VERSION in pipelines.", fill: "FBEEEB", tc: "7A2E24", bc: "7A2E24" },
      { t: "3 · Rosters", b: "Each team names a primary and a secondary and confirms its channels and ServiceNow group.", fill: "FBEEEB", tc: "7A2E24", bc: "7A2E24" },
      { t: "4 · Team onboarding", b: "Register services, choose tiers deliberately, fill in the runbook sections you own.", fill: C.tint },
      { t: "5 · Surfaces", b: "Reports, then MCP Ask and Act, then the executive portal — once the data underneath is true.", fill: C.tint },
    ];
    L.cards(s, moves, { y: 2.5, h: 1.65, cols: 5, gap: 0.2, bodySize: 10.5, titleSize: 13 });

    s.addShape("roundRect", { x: M, y: 4.4, w: 5.85, h: 1.9, rectRadius: 0.07, fill: { color: "F3F4F6" }, line: { color: C.line } });
    s.addText("DELIBERATELY NOT IN THE PLAN", { x: M + 0.28, y: 4.55, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.slate, charSpacing: 1.5 });
    s.addText(
      [
        { text: "No request for teams to write monitors", options: { bullet: true, breakLine: true } },
        { text: "No migration of existing monitors — the monitors already exist; a team joins them by being tagged", options: { bullet: true, breakLine: true } },
        { text: "No cutover event and no freeze", options: { bullet: true, breakLine: true } },
        { text: "The adoption unit is a team, not a service. Seven teams. A team that already tags cleanly is done in a day", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 0.28, y: 4.89, w: 5.3, h: 1.3, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: C.body, valign: "top", paraSpaceAfter: 5 }
    );

    s.addShape("roundRect", { x: M + 6.25, y: 4.4, w: 5.85, h: 1.9, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("WHAT WE NEED FROM THIS ROOM", { x: M + 6.53, y: 4.55, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.5 });
    s.addText(
      [
        { text: "An owner and a date for the Azure Policy tagging work", options: { bullet: true, breakLine: true } },
        { text: "Seven on-call rosters named, or the IdP group sync switched on", options: { bullet: true, breakLine: true } },
        { text: "The 18 legacy workflows deleted so the quota releases", options: { bullet: true, breakLine: true } },
        { text: "A decision on alert_band versus tier scoping — either is defensible; undecided is not", options: { bullet: true, breakLine: false } },
      ],
      { x: M + 6.53, y: 4.89, w: 5.3, h: 1.3, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "C6D0DF", valign: "top", paraSpaceAfter: 5 }
    );
  }

  // ------------------------------------------------------- 41 success metrics
  {
    const s = L.mk(pptx, {
      kicker: "Topic 32",
      title: "Success metrics",
      pill: ["partial", "partial — half are blocked on tagging"],
      sub: "Nine numbers, published monthly. Four can be reported today; five need the telemetry to carry the tags first.",
      notes: `Nine metrics, published monthly, in the alert-quality review with domain owners.

Reportable today: tag conformance — the percentage of resources carrying all six tags, which is currently the campaign's own progress bar. Coverage of the alertable estate, which is one hundred percent. Monitor quality — the fleet scorecard average, gated at 85 with zero failing monitors. And governance findings: open C1 to C17 items and the age of the oldest.

Blocked on the tagging: pages per engineer per week, which is the single best proxy for whether on-call is sustainable. Actionability — the proportion of pages that led to an action rather than an acknowledgement and a shrug. Time to acknowledge and time to resolve for P1s. Error-budget consumption by tier. And fleet compliance, which additionally needs phase three.

I want to be clear about the shape of this: the first four measure whether the platform is built correctly. The last five measure whether it is working. We can only currently report the first kind, and a programme that only ever reports the first kind is a programme that has confused shipping with succeeding.

The monthly alert-quality review is the forum, it already exists in the operating model, and I would like a standing fifteen minutes of a leadership meeting for the summary.`,
    });
    s.addText("Reportable today", { x: M, y: 2.35, w: 5.85, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
    const now = [
      ["Tag conformance", "% of resources carrying all six identity tags — the campaign's progress bar"],
      ["Coverage", "% of the alertable estate inside a monitor pack — 100% today"],
      ["Monitor quality", "fleet scorecard average, gated at ≥ 85 with zero failing monitors"],
      ["Governance findings", "open C1–C17 items and the age of the oldest"],
    ];
    now.forEach((n, i) => {
      const y = 2.74 + i * 0.66;
      s.addShape("roundRect", { x: M, y, w: 5.85, h: 0.62, rectRadius: 0.05, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
      s.addText(n[0], { x: M + 0.2, y: y + 0.03, w: 5.5, h: 0.28, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
      s.addText(n[1], { x: M + 0.2, y: y + 0.3, w: 5.5, h: 0.28, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "2C6F6B", valign: "middle" });
    });

    s.addText("Blocked until the telemetry carries the tags", { x: M + 6.25, y: 2.35, w: 5.85, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.red, valign: "middle" });
    const later = [
      ["Pages per engineer per week", "the single best proxy for whether on-call is sustainable"],
      ["Actionability", "% of pages that led to an action, not an ack and a shrug"],
      ["MTTA / MTTR for P1", "acknowledged in 5 minutes, resolved — measured, not assumed"],
      ["Error-budget consumption", "by tier, trended — the chart that makes reliability arithmetic"],
      ["Fleet compliance", "% of hosts that should carry an agent and do — also needs phase 3"],
    ];
    later.forEach((n, i) => {
      const y = 2.74 + i * 0.66;
      s.addShape("roundRect", { x: M + 6.25, y, w: 5.85, h: 0.62, rectRadius: 0.05, fill: { color: "FBEEEB" }, line: { color: "FBEEEB" } });
      s.addText(n[0], { x: M + 6.45, y: y + 0.03, w: 5.5, h: 0.28, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: "7A2E24", valign: "middle" });
      s.addText(n[1], { x: M + 6.45, y: y + 0.3, w: 5.5, h: 0.28, margin: 0, fontSize: 10.5, fontFace: BODY_FONT, color: "97564C", valign: "middle" });
    });

    s.addText("The first four measure whether the platform is built correctly. The last five measure whether it is working. Forum: the monthly alert-quality review, which already exists in the operating model.", { x: M, y: 6.1, w: CW, h: 0.55, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });
  }

  // ------------------------------------------------------------- 42 roadmap
  {
    const s = L.mk(pptx, {
      dark: true,
      kicker: "The honest roadmap",
      title: "Nine phases, ordered by dependency",
      notes: `This is the single slide I would keep if I could keep only one besides slide three.

Nine phases, ordered by dependency rather than by visibility. Phases one to three are the ones that change whether the platform WORKS: the entity model, telemetry requirements with an applicability engine, and fleet management with agent profiles and deployment metadata. Today 651 correct monitors return no data, and these three phases are what fixes that.

Phase four is SLO profiles and per-service overrides. Phase five is Control-M in-flight job monitoring, which does not exist at all today — a repository-wide search returns zero files. Phase six is the reports catalog, the dashboard consolidation, the survey and entity-aware scorecards.

Phases seven and eight are the product surfaces — the MCP server and the executive portal. They are last deliberately: they are surfaces on top of a platform that must be true first. A conversational interface over untagged telemetry would answer confidently and wrongly, which is worse than not having it.

Phase nine is this presentation and the final traceability review.

Each phase is independently shippable and leaves the platform working. There is no phase that has to complete before the platform is useful — it is useful now, for the resources that are correctly tagged. The phases decide how many resources that is.`,
    });
    const phases = [
      ["1", "Entity model — kind:, resolver, System/Datastore/Queue/API, catalog reconciliation", "changes whether it works"],
      ["2", "Telemetry requirements on every archetype + applicability engine", "changes whether it works"],
      ["3", "Fleet management, agent profiles, deployment metadata (DD_VERSION)", "changes whether it works"],
      ["4", "SLO profiles and per-service objective overrides", ""],
      ["5", "Control-M in-flight job monitoring — zero files exist today", ""],
      ["6", "Reports catalog · dashboard consolidation · survey · entity scorecards", ""],
      ["7", "MCP server — Ask, then Act, then governance", "surface"],
      ["8", "Executive portal", "surface"],
      ["9", "Presentation and final traceability review", "this deck"],
    ];
    phases.forEach((p, i) => {
      const y = 1.55 + i * 0.53;
      const hot = i < 3;
      s.addShape("roundRect", { x: M, y, w: CW, h: 0.5, rectRadius: 0.05, fill: { color: hot ? "2A1A16" : C.inkSoft }, line: { color: hot ? C.red : C.inkSoft } });
      s.addShape("ellipse", { x: M + 0.16, y: y + 0.09, w: 0.32, h: 0.32, fill: { color: hot ? C.red : C.slate }, line: { color: hot ? C.red : C.slate } });
      s.addText(p[0], { x: M + 0.16, y: y + 0.09, w: 0.32, h: 0.32, margin: 0, fontSize: 11, bold: true, fontFace: BODY_FONT, color: "FFFFFF", align: "center", valign: "middle" });
      s.addText(p[1], { x: M + 0.64, y, w: 8.6, h: 0.5, margin: 0, fontSize: 12.5, fontFace: BODY_FONT, color: hot ? "F3DDD8" : "C6D0DF", valign: "middle" });
      if (p[2]) {
        s.addText(p[2].toUpperCase(), { x: M + 9.3, y, w: 2.6, h: 0.5, margin: 0, fontSize: 9, bold: true, fontFace: BODY_FONT, color: hot ? C.red : C.slate, align: "right", valign: "middle", charSpacing: 1.2 });
      }
    });
    s.addText("Phases 1–3 decide whether the platform WORKS: today 651 correct monitors return no data. Phases 7–8 are surfaces on a platform that must be true first. Every phase is independently shippable and leaves the platform working.", { x: M, y: 6.4, w: CW, h: 0.5, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: "8E9DB5", valign: "top" });
  }

  // ---------------------------------------------------------------- 43 close
  {
    const s = L.mk(pptx, {
      dark: true, bare: true, title: "What we are asking for",
      notes: `To close, four asks and one commitment.

One: a named owner and a date for the Azure Policy tagging work — or a decision to take the tier-scoping shortcut instead. Either is defensible. Undecided is not, because undecided reads as covered.

Two: seven rosters named, or the identity-provider group sync switched on. Until then a page reaches nobody.

Three: someone with the right Datadog login deletes eighteen legacy workflows so twenty-five automations can deploy.

Four: agreement on the phase order — entity model, telemetry, fleet first; MCP and the portal last.

And the commitment from us: every number in this deck came from the repository or the last production deploy, and the same will be true of the monthly report. When something is not working we will show you that slide first, the way we did today.

Questions.`,
    });
    s.addText("IN CLOSING", { x: M, y: 1.15, w: 9, h: 0.32, margin: 0, fontSize: 11, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 2.2 });
    s.addText("What we are asking for", { x: M, y: 1.55, w: 9, h: 0.9, margin: 0, fontSize: 38, bold: true, fontFace: HEAD_FONT, color: C.paper, valign: "middle" });

    const asks = [
      { t: "An owner and a date", b: "for the Azure Policy tagging work — or the decision to scope on tier instead. Either is defensible; undecided is not." },
      { t: "Seven rosters", b: "named by their team leads, or the IdP group sync switched on. Until then a page executes correctly and reaches nobody." },
      { t: "The workflow quota", b: "released: 18 legacy workflows deleted by their owning login, unblocking 25 automations." },
      { t: "Agreement on the order", b: "entity model, telemetry and fleet first. MCP and the portal last, over data that is true." },
    ];
    L.cards(s, asks, { y: 2.75, h: 1.75, cols: 4, fill: C.inkSoft, titleColor: C.amber, bodyColor: "C6D0DF" });

    s.addShape("roundRect", { x: M, y: 4.85, w: CW, h: 1.3, rectRadius: 0.07, fill: { color: "1A2B28" }, line: { color: C.teal } });
    s.addText("AND THE COMMITMENT BACK", { x: M + 0.3, y: 5.0, w: 11.4, h: 0.3, margin: 0, fontSize: 10, bold: true, fontFace: BODY_FONT, color: "5FB8B2", charSpacing: 1.6 });
    s.addText("Every number in this deck came from the repository or the last production deploy. The same will be true of the monthly report — and when something is not working, we will show you that slide first, the way we did today.", { x: M + 0.3, y: 5.32, w: 11.4, h: 0.7, margin: 0, fontSize: 13.5, fontFace: BODY_FONT, color: "CFE3E0", valign: "top" });

    s.addText("Appendix follows: the traceability scorecard, the estate by domain, the priority and detection mix, the environment and routing matrices, the coverage checks, the tagging contract, and everything this deck deliberately does not claim.", { x: M, y: 6.35, w: CW, h: 0.5, margin: 0, fontSize: 11, fontFace: BODY_FONT, color: "6E7B92", valign: "top" });
  }
}

module.exports = { build };
