# Executive presentation

The requirement-set deliverable §50: one deck covering 32 topics for a mixed
audience — executives, engineering leadership, SRE, infrastructure, cloud, data
engineering, DBAs, security, application development and operations.

| File | What it is |
|---|---|
| `enterprise-observability.pptx` | The deck. 55 slides: 43 main + a 12-slide appendix |
| `speaker-notes.md` | Full speaker notes, one section per slide |
| `build.js` + `lib.js` + `part[1-5].js` | The generator. **Edit these, not the outputs** |

## Rebuilding

```bash
npm install pptxgenjs          # not vendored here
node docs/presentation/build.js
```

Both outputs are rewritten from the generator, so a number that changes in the
repository is changed in one place — the slide that states it.

## The rules this deck is written under

1. **Every figure comes from the repository or the last production deploy.**
   Sources are listed on the final appendix slide: the reconciliation report,
   the plan-derived fixture, the coverage matrix, the traceability matrix, the
   policy budgets and the last live profiling run.
2. **Nothing unshipped is presented as shipped.** Every topic slide carries a
   status pill — SHIPPED, PARTIAL, ROADMAP · PHASE n, or ACT NOW — taken from
   [`../requirement-traceability.md`](../requirement-traceability.md).
   Appendix A10 is the complete register of what the deck does not claim.
3. **Slide 3 is the point.** The platform's 651 monitors are correct and return
   no data, because the telemetry does not carry `alert_band`, uses
   `env:production` instead of `env:prod`, and omits `service_archetype`. The
   fix and the decision it needs are on that slide; the contract behind it is
   [`../tagging-standard.md`](../tagging-standard.md).

## Structure

| Slides | Part |
|---|---|
| 1–3 | Title · how to read the deck · the one thing to act on |
| 4–8 | **Part 1 — Why we are changing** (topics 1–4) |
| 9–13 | **Part 2 — The model underneath** (topics 5–8) |
| 14–19 | **Part 3 — Signals and objectives** (topics 9–13) |
| 20–28 | **Part 4 — From alert to resolution** (topics 14–21) |
| 29–35 | **Part 5 — Surfaces and access** (topics 22–27) |
| 36–41 | **Part 6 — Operating it, and what good looks like** (topics 28–32) |
| 42–43 | The nine-phase roadmap · the asks |
| 44–55 | Appendix A1–A11 |

If the estate numbers change, regenerate the deck rather than editing the
`.pptx`: the figures live in the `part*.js` files next to the sentence that
uses them.
