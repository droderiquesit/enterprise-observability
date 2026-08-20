const L = require("./lib");
const { C, HEAD_FONT, BODY_FONT, M, W, CW } = L;

function divider(pptx, o) {
  const s = L.mk(pptx, { dark: true, title: o.title, bare: true, notes: o.notes });
  s.addText(o.part, {
    x: M, y: 1.55, w: 6.0, h: 0.5, margin: 0, fontSize: 12, bold: true,
    fontFace: BODY_FONT, color: C.amber, charSpacing: 2.4,
  });
  s.addText(o.title, {
    x: M, y: 2.05, w: 7.4, h: 1.9, margin: 0, fontSize: 40, bold: true,
    fontFace: HEAD_FONT, color: C.paper, valign: "top",
  });
  if (o.strap) {
    s.addText(o.strap, {
      x: M, y: 4.1, w: 6.6, h: 0.9, margin: 0, fontSize: 14, fontFace: BODY_FONT,
      color: "9FADC4", valign: "top",
    });
  }
  const items = o.topics.map((t, i) => ({
    text: `${o.first + i}.  ${t}`,
    options: { breakLine: i < o.topics.length - 1 },
  }));
  s.addShape("roundRect", {
    x: 8.05, y: 1.5, w: W - M - 8.05, h: 4.85, rectRadius: 0.07,
    fill: { color: C.inkSoft }, line: { color: C.inkLine },
  });
  s.addText("TOPICS IN THIS PART", {
    x: 8.4, y: 1.78, w: 4.2, h: 0.3, margin: 0, fontSize: 9.5, bold: true,
    fontFace: BODY_FONT, color: C.amber, charSpacing: 1.6,
  });
  s.addText(items, {
    x: 8.4, y: 2.18, w: 4.35, h: 3.9, margin: 0, fontSize: 13, fontFace: BODY_FONT,
    color: "D3DCE9", valign: "top", paraSpaceAfter: 7,
  });
  return s;
}

function build(pptx) {
  // ---------------------------------------------------------------- 1 title
  {
    const s = L.mk(pptx, {
      dark: true, bare: true, title: "Enterprise Observability",
      notes: `Welcome. One room, one platform, one standard.

This deck covers 32 topics in six parts. It is deliberately split: the main deck is the argument and the numbers; the appendix has the tables people will ask for.

Two ground rules for the next hour. First, every number on these slides comes from the repository or the last production deploy — nothing is illustrative. Second, anything not yet shipped is labelled ROADMAP with the phase it lands in. If you see a claim without evidence behind it, stop me.

The one slide you must not miss is slide 3.`,
    });
    s.addText("ENTERPRISE OBSERVABILITY PROGRAMME", {
      x: M, y: 1.85, w: 9, h: 0.35, margin: 0, fontSize: 12, bold: true,
      fontFace: BODY_FONT, color: C.amber, charSpacing: 2.4,
    });
    s.addText("Monitoring as policy,\nnot as configuration", {
      x: M, y: 2.25, w: 8.6, h: 2.0, margin: 0, fontSize: 42, bold: true,
      fontFace: HEAD_FONT, color: C.paper, valign: "top", lineSpacingMultiple: 1.05,
    });
    s.addText(
      "One reviewed YAML hierarchy drives every monitor, SLO, route, runbook and " +
      "automation in Datadog. This is what is running today, what is not, and what happens next.",
      { x: M, y: 4.35, w: 7.6, h: 0.9, margin: 0, fontSize: 14.5, fontFace: BODY_FONT,
        color: "A9B6CB", valign: "top" }
    );
    const stats = [
      { v: "651", l: "managed monitors" },
      { v: "264", l: "archetypes" },
      { v: "70", l: "may page a human" },
      { v: "100%", l: "of the alertable estate" },
    ];
    stats.forEach((st, i) => {
      L.stat(s, {
        x: M + i * 3.05, y: 5.45, w: 2.8, value: st.v, label: st.l,
        size: 34, vh: 0.62, color: C.paper, labelColor: "8E9DB5", labelSize: 11,
      });
    });
    s.addText("Executive briefing  ·  20 August 2026  ·  observability-platform", {
      x: 7.6, y: 4.35, w: 5.1, h: 0.5, margin: 0, fontSize: 11.5, fontFace: BODY_FONT,
      color: "6E7B92", align: "right", valign: "top",
    });
  }

  // ------------------------------------------------------- 2 how to read it
  {
    const s = L.mk(pptx, {
      kicker: "How to read this deck",
      title: "Everything here is labelled shipped, partial or roadmap",
      sub: "The platform is strong on the monitor → SLO → routing → runbook spine and honest about the product surfaces that are not built yet. Labels come from the requirement traceability matrix, which was audited against the live estate, not against memory.",
      notes: `The labels are not decoration. They come from docs/requirement-traceability.md, which audited 60 requirement sections against the repository AND the last production deploy's evidence artifact.

Scorecard: 21 OK, 9 IMPROVE, 12 PARTIAL, 15 MISSING, 1 obsolete-and-resolved, 2 N/A.

If a slide says SHIPPED, it is deployed in production today and you can open it in Datadog. If it says PARTIAL, some of it works and I will tell you which part does not. If it says ROADMAP, none of it exists and I will tell you which phase builds it.

The reason for this discipline: an overclaimed capability is discovered in the first incident, and it costs more credibility than an honest roadmap slide ever does.`,
    });
    const legend = [
      ["shipped", "shipped", "deployed in production today; you can open it in Datadog now"],
      ["partial", "partial", "part of it works; the slide names the part that does not"],
      ["roadmap", "roadmap", "not built; the slide names the phase that builds it"],
      ["action", "act now", "something this room has to decide or assign an owner to"],
    ];
    const colmap = { shipped: [C.teal, "FFFFFF"], partial: [C.amber, "2A1D06"], roadmap: ["DFE5EE", C.slate], action: [C.red, "FFFFFF"] };
    legend.forEach((k, i) => {
      const y = 2.7 + i * 0.62;
      const col = colmap[k[0]];
      s.addShape("roundRect", { x: M, y, w: 1.4, h: 0.36, rectRadius: 0.18, fill: { color: col[0] }, line: { color: col[0] } });
      s.addText(k[1].toUpperCase(), {
        x: M, y, w: 1.4, h: 0.36, margin: 0, fontSize: 9.5, bold: true,
        fontFace: BODY_FONT, color: col[1], align: "center", valign: "middle", charSpacing: 1,
      });
      s.addText(k[2], {
        x: M + 1.62, y, w: 5.0, h: 0.36, margin: 0, fontSize: 12, fontFace: BODY_FONT,
        color: C.body, valign: "middle",
      });
    });

    s.addShape("roundRect", {
      x: 7.35, y: 2.5, w: W - M - 7.35, h: 3.9, rectRadius: 0.07,
      fill: { color: C.tint }, line: { color: C.tint },
    });
    s.addText("THE AUDIT BEHIND THE LABELS", {
      x: 7.7, y: 2.78, w: 4.6, h: 0.3, margin: 0, fontSize: 9.5, bold: true,
      fontFace: BODY_FONT, color: C.amberDeep, charSpacing: 1.6,
    });
    const score = [
      { k: "OK — exists and is correct", v: "21" },
      { k: "IMPROVE — works, one defect", v: "9" },
      { k: "PARTIAL — some of it exists", v: "12" },
      { k: "MISSING — nothing implements it", v: "15" },
      { k: "Obsolete (removed) · N/A", v: "1 · 2" },
    ];
    score.forEach((r, i) => {
      const y = 3.22 + i * 0.56;
      s.addText(r.k, {
        x: 7.7, y, w: 3.6, h: 0.44, margin: 0, fontSize: 12, fontFace: BODY_FONT,
        color: C.body, valign: "middle",
      });
      s.addText(r.v, {
        x: 11.3, y, w: 1.0, h: 0.44, margin: 0, fontSize: 16, bold: true,
        fontFace: HEAD_FONT, color: C.text, align: "right", valign: "middle",
      });
    });
    s.addText("60 requirement sections · docs/requirement-traceability.md", {
      x: 7.7, y: 6.0, w: 4.6, h: 0.3, margin: 0, fontSize: 10, fontFace: BODY_FONT,
      color: C.muted, valign: "middle",
    });
  }

  // ---------------------------------------------------------- 3 THE one thing
  {
    const s = L.mk(pptx, {
      dark: true, bare: true, title: "The one thing to act on",
      notes: `This is the slide that matters. If you remember nothing else, remember this.

The 651 monitors are correct. Every query was validated against Datadog's own validation API on the last deploy — 651 of 651 PASS. And today they return no data, because the telemetry does not carry the tags they select on.

Three concrete findings from the last live profiling run, which graded 27 resources: alert_band present on ZERO of them; 22 carry env:production, which is not in the vocabulary — the platform coerces it to prod and flags it; and 27 of 27 have no service_archetype, so every one was guessed as api.

Why this is dangerous rather than merely incomplete: a monitor that returns no data looks exactly like a monitor that is healthy. Coverage reports 100% because 100% of the alertable estate has a monitor pack. Nothing is lying — the monitors exist. But they are selecting on an empty set.

The fix is in docs/tagging-standard.md and there are two options. Option 1 is the design intent: push the six tags onto the telemetry — Azure Policy with a modify effect on resource groups, agent datadog.yaml tags, Kubernetes pod labels, DD_TAGS for APM. Option 2 is the pragmatic path: change one policy line so queries scope on tier instead of alert_band — no telemetry work, but coarser, because tier0 and tier1 share a band today.

What I need from this room is a decision on which option, and an owner for the Azure Policy work. Leaving it undecided is the worst outcome, because undecided reads as "covered".`,
    });
    s.addText("THE SINGLE MOST IMPORTANT OPERATIONAL TRUTH", {
      x: M, y: 0.62, w: 9.5, h: 0.32, margin: 0, fontSize: 11, bold: true,
      fontFace: BODY_FONT, color: C.amber, charSpacing: 2.2,
    });
    s.addText("651 monitors are correct.\nToday they return no data.", {
      x: M, y: 1.02, w: 11.5, h: 1.5, margin: 0, fontSize: 38, bold: true,
      fontFace: HEAD_FONT, color: C.paper, valign: "top", lineSpacingMultiple: 1.02,
    });
    s.addText(
      "The queries select on tags the telemetry does not carry. A monitor that returns no data looks identical to a healthy one — which is why coverage reports 100% and the estate is still effectively unwatched.",
      { x: M, y: 2.52, w: 11.6, h: 0.8, margin: 0, fontSize: 14.5, fontFace: BODY_FONT,
        color: "B7C3D6", valign: "top" }
    );

    const gaps = [
      { t: "alert_band", b: "Present on 0 of 27 profiled resources. Every archetype query filters on it, so every query resolves to an empty set." },
      { t: "env:production", b: "22 resources use production. The vocabulary is dev · qa · stage · prod. production, prd and PROD match nothing." },
      { t: "service_archetype", b: "Absent on 27 of 27. Without it the platform guesses — every one was inferred as api." },
    ];
    L.cards(s, gaps, {
      y: 3.5, h: 1.55, cols: 3, fill: C.inkSoft, titleColor: C.amber,
      bodyColor: "AEBACD", titleSize: 16, bodySize: 11.5,
    });

    s.addShape("roundRect", {
      x: M, y: 5.35, w: CW, h: 1.35, rectRadius: 0.07,
      fill: { color: "2A1A16" }, line: { color: C.red },
    });
    s.addText("THE FIX — DECIDE ONE, THIS WEEK", {
      x: M + 0.28, y: 5.5, w: 5.0, h: 0.3, margin: 0, fontSize: 10, bold: true,
      fontFace: BODY_FONT, color: C.red, charSpacing: 1.6,
    });
    s.addText(
      [
        { text: "1  Push the tags onto the telemetry", options: { bold: true, breakLine: false } },
        { text: "  — Azure Policy modify effect on resource groups, agent datadog.yaml tags, Kubernetes pod labels, DD_TAGS for APM. Correct and explicit; this is the design intent.", options: { breakLine: true } },
        { text: "2  Or scope queries on tier instead", options: { bold: true, breakLine: false } },
        { text: "  — one policy change, no telemetry work, but coarser: tier0 and tier1 share a band today.", options: { breakLine: false } },
      ],
      { x: M + 0.28, y: 5.82, w: CW - 0.56, h: 0.8, margin: 0, fontSize: 12,
        fontFace: BODY_FONT, color: "E8D5CF", valign: "top", lineSpacingMultiple: 1.05 }
    );
  }

  // ------------------------------------------------------------ 4 part 1 div
  divider(pptx, {
    part: "PART ONE",
    title: "Why we are\nchanging",
    strap: "The case for the programme, what the old model cost us, and the model that replaces it.",
    first: 1,
    topics: [
      "Why the programme exists",
      "What was wrong with the previous model",
      "The target operating model",
      "What teams actually have to do",
    ],
    notes: `Part one is four topics and about eight minutes. The argument is simple: the old model scaled with resources, the new one scales with decisions.`,
  });

  // ----------------------------------------------------------------- 5 why
  {
    const s = L.mk(pptx, {
      kicker: "Topic 1",
      title: "Why the programme exists",
      pill: ["shipped", "shipped"],
      notes: `The naive enterprise model is services × environments × signals. At the scale we target — 100,000 services — that is roughly eight million monitors. Nobody can review, tune, cost or trust an estate that size, so in practice it degrades into two failure modes: teams stop reading alerts, and coverage becomes unknowable.

This platform produces 651 managed objects for the same coverage, because resources are GROUPS inside grouped multi-alert monitors, selected by tag. Adding fifty thousand services adds zero Datadog objects.

That is the invariant, and everything else in the deck is a consequence of it: the number of managed objects grows with the number of monitoring DECISIONS, not the number of monitored RESOURCES.

Three business reasons this matters beyond elegance. Cost: monitor count drives both licence and human review cost. Trust: an alert estate nobody reviews is an alert estate nobody believes at 3am. Auditability: 651 objects generated from reviewed YAML can be explained to a regulator; eight million hand-made ones cannot.`,
    });
    s.addText("The invariant the whole platform is built on", {
      x: M, y: 1.66, w: 11.6, h: 0.4, margin: 0, fontSize: 15, fontFace: BODY_FONT,
      color: C.body, valign: "top",
    });
    s.addShape("roundRect", {
      x: M, y: 2.2, w: 5.75, h: 2.05, rectRadius: 0.07,
      fill: { color: C.tint }, line: { color: C.tint },
    });
    L.stat(s, { x: M + 0.35, y: 2.42, w: 5.0, value: "~8,000,000", label: "monitors — the naive model: 100k services × 4 environments × 20 signals", size: 40, color: C.muted, labelSize: 11.5 });
    s.addShape("roundRect", {
      x: M + 6.05, y: 2.2, w: 5.75, h: 2.05, rectRadius: 0.07,
      fill: { color: C.ink }, line: { color: C.ink },
    });
    L.stat(s, { x: M + 6.4, y: 2.42, w: 5.0, value: "651", label: "monitors — this platform, same coverage, every one reviewed in a pull request", size: 40, color: C.amber, labelColor: "9FADC4", labelSize: 11.5 });

    L.cards(s, [
      { t: "Cost", b: "Object count drives licence spend and, more expensively, the human review time nobody budgets for." },
      { t: "Trust", b: "An estate nobody can review is an estate nobody believes at 3am. Belief is the product." },
      { t: "Auditability", b: "651 objects generated from reviewed YAML can be explained. Eight million hand-made ones cannot." },
      { t: "Scale", b: "Adding 50,000 services creates zero new Datadog objects. Growth is free by construction." },
    ], { y: 4.5, h: 1.5, cols: 4 });
  }

  // -------------------------------------------------------- 6 previous model
  {
    const s = L.mk(pptx, {
      kicker: "Topic 2",
      title: "What was wrong with the previous model",
      pill: ["shipped", "shipped"],
      notes: `Six specific defects, each with the specific mechanism that replaces it. These are not strawmen — they are the failure modes that produce alert fatigue in every large estate.

One: a monitor per resource. Every new VM, database or service needed someone to create monitors for it, so coverage tracked hiring, not risk. Now a resource is a group inside a monitor that already exists.

Two: thresholds copied between teams. CPU > 80% means nothing without context — a batch node at 95% on schedule is healthy, an API node at 55% when it normally runs at 20% is not. Now roughly 40% of instances use predictive detection, and any fixed threshold must carry a written rationale that CI enforces.

Three: destinations hard-coded in monitors. Changing where a team's P1s go meant editing hundreds of monitors. Now monitors carry no destinations at all — 111 notification rules resolve tags to people.

Four: every alert paged. Now paging is a separate, narrower rule than priority: 70 of 651 monitors, 11%, can wake a human.

Five: runbooks as links to a wiki that had rotted. Now the runbook is a Datadog notebook attached to the monitor as an asset — 651 of 651 attached, zero URLs pasted into alert bodies.

Six: silence read as health. Now telemetry-loss monitors exist precisely so that "no alerts" cannot silently mean "no data" — which, as slide 3 says, is exactly the state we are in and exactly why we know about it.`,
    });
    s.addText("BEFORE", {
      x: M, y: 1.7, w: 5.7, h: 0.3, margin: 0, fontSize: 10.5, bold: true,
      fontFace: BODY_FONT, color: C.muted, charSpacing: 1.8,
    });
    s.addText("NOW", {
      x: M + 6.35, y: 1.7, w: 5.7, h: 0.3, margin: 0, fontSize: 10.5, bold: true,
      fontFace: BODY_FONT, color: C.teal, charSpacing: 1.8,
    });
    const pairs = [
      ["A monitor per resource — coverage tracked hiring", "A resource is a group inside a monitor that exists"],
      ["Thresholds copied between teams: CPU > 80%", "~40% predictive; fixed numbers need a written rationale"],
      ["Destinations hard-coded into each monitor", "Monitors carry no destinations; 111 rules resolve tags"],
      ["Everything paged, so nothing did", "70 of 651 monitors (11%) may wake a human"],
      ["Runbook = a link to a wiki page that had rotted", "651/651 native notebooks attached to the monitor"],
      ["Silence read as health", "Telemetry-loss monitors make absence detectable"],
    ];
    pairs.forEach((p, i) => {
      const y = 2.08 + i * 0.77;
      s.addShape("roundRect", { x: M, y, w: 5.7, h: 0.66, rectRadius: 0.05, fill: { color: "F3F4F6" }, line: { color: "F3F4F6" } });
      s.addText(p[0], { x: M + 0.2, y, w: 5.3, h: 0.66, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.muted, valign: "middle" });
      s.addShape("rightArrow", { x: M + 5.85, y: y + 0.24, w: 0.32, h: 0.18, fill: { color: C.slate }, line: { color: C.slate } });
      s.addShape("roundRect", { x: M + 6.35, y, w: 5.7, h: 0.66, rectRadius: 0.05, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
      s.addText(p[1], { x: M + 6.55, y, w: 5.3, h: 0.66, margin: 0, fontSize: 12, bold: true, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
    });
  }

  // --------------------------------------------------- 7 target operating model
  {
    const s = L.mk(pptx, {
      kicker: "Topic 3",
      title: "The target operating model",
      pill: ["shipped", "shipped"],
      sub: "Policy is data. Terraform interprets it. No monitoring decision lives in HCL, in a UI, or in anyone's head.",
      notes: `One sentence: every monitoring decision lives in reviewed YAML, and Terraform is a pure interpreter of those files.

The delivery path: you edit YAML under platform/, open a pull request, and CI runs the full gate — schema, the pytest suite, terraform fmt and validate, offline plans with every precondition and budget check, plan determinism, Trivy and gitleaks, and a credentialed plan whose monitors are submitted to Datadog's own validation API. Merge to main applies qa then stage automatically. Production is an explicit dispatch behind an approval environment.

Three control loops keep it true. Delivery is PR-driven, as described. Discovery is scheduled: rebuild the inventory from the live org, assign profiles, converge the catalog — new resources are covered by existing monitors immediately, the loop only updates ownership accounting. Governance is scheduled: nightly Terraform and runbook drift detection, weekday coverage and quality reports, and a red run opens a GitHub issue automatically.

Ownership: the platform team owns the hierarchy and the interpreter. Teams own their service registration, their runbook content and their rosters. Exceptions are time-boxed, owned, approved and expiring — CI fails on an expired one.

The important cultural point is the last one: every standard in this platform is a command. If a rule cannot be checked mechanically, it does not belong in the standard.`,
    });
    L.flow(s, [
      { t: "YAML policy\nplatform/*.yaml", fill: C.tint },
      { t: "Pull request\nreview + CI gate", fill: C.tint },
      { t: "Terraform\npure interpreter", fill: C.tint },
      { t: "Datadog\nqa → stage → prod", fill: C.ink, tc: C.paper },
      { t: "Governance loops\ndrift · coverage · quality", fill: C.tintWarm },
    ], { y: 2.3, h: 1.05, size: 12.5 });

    L.cards(s, [
      { t: "Delivery loop — every PR", b: "Schema · policy lint · pytest · terraform validate · offline plan with budget checks · plan determinism · Trivy + gitleaks · every planned monitor validated by Datadog's own API." },
      { t: "Discovery loop — scheduled", b: "Rebuild inventory from the live org, assign owner / domain / profile / band, converge the catalog. New resources are already covered; the loop only updates accounting." },
      { t: "Governance loop — scheduled", b: "Nightly Terraform and runbook drift. Weekday coverage report (C1–C17) and quality scorecard. A red run opens a governance issue automatically." },
    ], { y: 3.75, h: 1.85, cols: 3 });

    L.rows(s, [
      { k: "Platform team owns", v: "the policy hierarchy, the archetype catalog, the Terraform modules and the CI gate" },
      { k: "Service teams own", v: "their registration, their tier decision, their runbook content and their on-call roster" },
      { k: "Nothing is deployed", v: "outside Terraform and the runbook publisher — click-ops objects are detected within a day (check C9)" },
    ], { y: 5.70, rh: 0.38, kw: 2.9, size: 11.5 });
  }

  // ------------------------------------------------- 8 what teams need to do
  {
    const s = L.mk(pptx, {
      kicker: "Topic 4",
      title: "What teams actually have to do",
      pill: ["partial", "partial — the tags"],
      sub: "For most teams: apply the tags and register the service. That is the whole obligation. No Terraform, no notification handles, no monitor configuration.",
      notes: `This is the slide for the engineering managers in the room, because it is the total ask.

Five identity tags you should already be emitting: env, service, team, tier, service_archetype. Plus alert_band, which the platform derives for you but which has to land back on the telemetry — that is the gap from slide 3, and it is why this slide is marked PARTIAL rather than SHIPPED.

Then one small YAML file to register the service: name, team, tier, service_archetype, envs. Five fields. That gives you the catalog entry, declared ownership, and — at tier0 — your own SLO with burn-rate alerting.

What you get without doing anything else: baseline monitors from your archetype's packs, an SLO, burn-rate paging, alert routing to your channel and rotation, environment behaviour, tier policy, runbook links, on-call routing, ownership in the catalog, event correlation, predictive baselines that start learning immediately, and dashboard visibility.

What you never do: write Terraform, write a Datadog notification handle, or configure a monitor. If you genuinely need something unique, that is one YAML file of about fifteen lines, and you delete the monitor by deleting the file.

Two rules that come up every time. You cannot obtain a pager by editing YAML — priority derives from your tier, and tier is a reviewed business decision. And if an alert is noisy, that is a defect with an owner: open a PR against the archetype so everyone benefits, or file an exception with a reason, an approver and an expiry. Do not mute it.`,
    });
    s.addShape("roundRect", { x: M, y: 2.28, w: 5.9, h: 2.35, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("1 · TAG THE TELEMETRY", {
      x: M + 0.3, y: 2.48, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true,
      fontFace: BODY_FONT, color: C.amber, charSpacing: 1.6,
    });
    s.addText("env   service   team   tier   service_archetype", {
      x: M + 0.3, y: 2.82, w: 5.3, h: 0.42, margin: 0, fontSize: 15, bold: true,
      fontFace: "Courier New", color: C.paper, valign: "middle",
    });
    s.addText("alert_band", {
      x: M + 0.3, y: 3.26, w: 5.3, h: 0.36, margin: 0, fontSize: 15, bold: true,
      fontFace: "Courier New", color: C.red, valign: "middle",
    });
    s.addText("Five you already own, plus the band the platform derives for you — which must land on the telemetry. That last one is the open gap from slide 3.", {
      x: M + 0.3, y: 3.68, w: 5.3, h: 0.8, margin: 0, fontSize: 11.5, fontFace: BODY_FONT,
      color: "A9B6CB", valign: "top",
    });

    s.addShape("roundRect", { x: M + 6.2, y: 2.28, w: 5.9, h: 2.35, rectRadius: 0.07, fill: { color: C.tint }, line: { color: C.tint } });
    s.addText("2 · REGISTER THE SERVICE", {
      x: M + 6.5, y: 2.48, w: 5.3, h: 0.3, margin: 0, fontSize: 10, bold: true,
      fontFace: BODY_FONT, color: C.amberDeep, charSpacing: 1.6,
    });
    s.addText(
      "service:\n  name: checkout-api\n  team: application-development\n  tier: tier0\n  service_archetype: api\n  envs: [dev, qa, stage, prod]",
      { x: M + 6.5, y: 2.8, w: 5.3, h: 1.6, margin: 0, fontSize: 11.5,
        fontFace: "Courier New", color: C.text, valign: "top", lineSpacingMultiple: 1.06 }
    );

    s.addText("Everything below is then automatic — no monitor configuration is required", {
      x: M, y: 4.82, w: 11.6, h: 0.32, margin: 0, fontSize: 13, bold: true,
      fontFace: BODY_FONT, color: C.text, valign: "middle",
    });
    const auto = ["Baseline monitors", "SLO + burn-rate paging", "Alert routing", "Environment behaviour", "Tier policy", "Runbook links", "On-call routing", "Catalog ownership", "Event correlation", "Predictive baselines", "Dashboard visibility", "Auto-resolve windows"];
    auto.forEach((a, i) => {
      const c = i % 4, r = Math.floor(i / 4);
      const x = M + c * 3.05, y = 5.22 + r * 0.5;
      s.addShape("roundRect", { x, y, w: 2.85, h: 0.42, rectRadius: 0.05, fill: { color: "EAF3F1" }, line: { color: "EAF3F1" } });
      s.addText(a, { x: x + 0.16, y, w: 2.6, h: 0.42, margin: 0, fontSize: 11.5, fontFace: BODY_FONT, color: "1D5C59", valign: "middle" });
    });
  }

  // ------------------------------------------------------------ 9 part 2 div
  divider(pptx, {
    part: "PART TWO",
    title: "The model\nunderneath",
    strap: "How an entity joins the platform, and how one file becomes a monitored estate.",
    first: 5,
    topics: [
      "Entity onboarding",
      "The correct catalog entity model",
      "How one YAML definition drives observability",
      "Monitoring profiles",
    ],
    notes: `Part two is the mechanism. Four topics, and one of them — the entity model — is the largest single piece of engineering still ahead of us.`,
  });

  // ------------------------------------------------------ 10 entity onboarding
  {
    const s = L.mk(pptx, {
      kicker: "Topic 5",
      title: "Entity onboarding",
      pill: ["partial", "partial — services only"],
      sub: "Discovery covers everything that emits telemetry. Registration adds intent — the part discovery cannot infer.",
      notes: `There are two ways an entity becomes visible, and they do different jobs.

Discovery is automatic. A service that starts emitting traces is inside the API pack's grouping on its first trace. There is no onboarding step for coverage.

Registration is a choice. It declares the things telemetry cannot tell you: who owns this, how much the business cares, and what kind of thing it is. Tier in particular is a business decision, not an inference — and it is the single input that decides how much monitoring machinery the service receives.

The comparison table is the honest version of "do I have to register?". Tagged-only gets you covered by packs and inferred ownership. Tagged and registered gets you declared ownership in Datadog's catalog, your tier as a business decision, a per-service SLO if you are tier0, and you stop appearing in the coverage report as an unowned resource — which is a violation, check C2, with a 14-day SLA.

Marked PARTIAL for two reasons. First, registration works for services and only services — the entity kinds on the next slide are not yet supported. Second, the live catalog holds 27 entries and only 3 are managed from this repository; reconciling discovered against managed is phase one work. We read discovery today, we do not yet merge it with declared intent.`,
    });
    s.addShape("roundRect", { x: M, y: 2.25, w: 5.85, h: 1.5, rectRadius: 0.07, fill: { color: C.tint }, line: { color: C.tint } });
    s.addText("DISCOVERY — automatic", { x: M + 0.28, y: 2.42, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.amberDeep, charSpacing: 1.4 });
    s.addText("A resource that emits correctly-tagged telemetry becomes a group inside monitors that already exist. First trace, first metric — covered. No ticket, no onboarding queue, no platform-team involvement.", { x: M + 0.28, y: 2.76, w: 5.3, h: 0.85, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: C.body, valign: "top" });

    s.addShape("roundRect", { x: M + 6.25, y: 2.25, w: 5.85, h: 1.5, rectRadius: 0.07, fill: { color: C.ink }, line: { color: C.ink } });
    s.addText("REGISTRATION — one YAML file", { x: M + 6.53, y: 2.42, w: 5.3, h: 0.3, margin: 0, fontSize: 10.5, bold: true, fontFace: BODY_FONT, color: C.amber, charSpacing: 1.4 });
    s.addText("Declares what telemetry cannot infer: the owning team, the business tier, the kind of thing it is, and the environments it runs in. Five fields, reviewed in a pull request.", { x: M + 6.53, y: 2.76, w: 5.3, h: 0.85, margin: 0, fontSize: 12, fontFace: BODY_FONT, color: "A9B6CB", valign: "top" });

    s.addText("What registration adds over tagging alone", { x: M, y: 3.95, w: 8, h: 0.32, margin: 0, fontSize: 14, bold: true, fontFace: BODY_FONT, color: C.text, valign: "middle" });
    const tbl = [
      ["", "Tagged only", "Tagged + registered"],
      ["Covered by monitor packs", "yes", "yes"],
      ["Ownership in Datadog's catalog", "inferred", "declared"],
      ["Tier", "inferred from environment", "your business decision"],
      ["Per-service SLO (tier0)", "—", "yes"],
      ["Appears in coverage as owned", "no — a C2 violation", "yes"],
    ];
    tbl.forEach((r, i) => {
      const y = 4.35 + i * 0.42;
      if (i === 0) {
        s.addShape("rect", { x: M, y, w: CW, h: 0.42, fill: { color: C.ink }, line: { color: C.ink } });
      } else if (i % 2 === 1) {
        s.addShape("rect", { x: M, y, w: CW, h: 0.42, fill: { color: "F5F7FA" }, line: { color: "F5F7FA" } });
      }
      const cols = [[M + 0.2, 5.4], [M + 5.8, 3.0], [M + 8.9, 3.1]];
      r.forEach((cell, j) => {
        s.addText(cell, {
          x: cols[j][0], y, w: cols[j][1], h: 0.42, margin: 0,
          fontSize: 12, bold: i === 0 || j === 0,
          fontFace: BODY_FONT,
          color: i === 0 ? C.paper : (j === 2 ? "1D5C59" : C.body),
          valign: "middle",
        });
      });
    });
  }
}

module.exports = { build, divider };
