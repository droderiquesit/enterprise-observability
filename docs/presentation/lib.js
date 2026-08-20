// Shared design system for the enterprise-observability executive deck.
// Palette: graphite + signal amber. Amber = alert, teal = shipped,
// slate = roadmap, red = the gap that must be closed.
const C = {
  ink: "12161F",
  inkSoft: "1E2531",
  inkLine: "323C4D",
  paper: "FFFFFF",
  tint: "EFF2F6",
  tintWarm: "FBF1E2",
  line: "D6DDE6",
  text: "161C28",
  body: "3A4557",
  muted: "6B7891",
  amber: "E09A2E",
  amberDeep: "B87914",
  teal: "27807C",
  red: "BE4A3F",
  slate: "5F7189",
};

const HEAD_FONT = "Cambria";
const BODY_FONT = "Calibri";

const M = 0.62; // page margin
const W = 13.333;
const H = 7.5;
const CW = W - 2 * M; // content width 12.093

const NOTES = [];

function record(title, notes) {
  NOTES.push({ n: NOTES.length + 1, title, notes });
}

function foot(slide, dark) {
  const n = NOTES.length; // slide number = current record count
  slide.addText("Enterprise Observability  ·  policy-as-data on Datadog", {
    x: M, y: 6.94, w: 8.0, h: 0.3, fontSize: 9, fontFace: BODY_FONT,
    color: dark ? "6E7B92" : C.muted, margin: 0, valign: "middle",
  });
  slide.addText(String(n), {
    x: W - M - 1.0, y: 6.94, w: 1.0, h: 0.3, fontSize: 9, fontFace: BODY_FONT,
    color: dark ? "6E7B92" : C.muted, align: "right", margin: 0, valign: "middle",
  });
}

// status pill: kind = shipped | partial | roadmap | action
function pill(slide, kind, label, x) {
  const map = {
    shipped: { fill: C.teal, color: "FFFFFF" },
    partial: { fill: C.amber, color: "2A1D06" },
    roadmap: { fill: "DFE5EE", color: C.slate },
    action: { fill: C.red, color: "FFFFFF" },
  };
  const s = map[kind];
  const w = Math.max(1.15, 0.105 * label.length + 0.42);
  const px = x === undefined ? W - M - w : x;
  slide.addShape("roundRect", {
    x: px, y: 0.46, w, h: 0.34, fill: { color: s.fill }, line: { color: s.fill },
    rectRadius: 0.17,
  });
  slide.addText(label.toUpperCase(), {
    x: px, y: 0.46, w, h: 0.34, fontSize: 9.5, bold: true, fontFace: BODY_FONT,
    color: s.color, align: "center", valign: "middle", margin: 0, charSpacing: 1,
  });
  return w;
}

function head(slide, o) {
  const dark = !!o.dark;
  if (o.kicker) {
    slide.addText(o.kicker.toUpperCase(), {
      x: M, y: 0.44, w: 9.6, h: 0.28, fontSize: 10.5, bold: true, fontFace: BODY_FONT,
      color: dark ? C.amber : C.amberDeep, charSpacing: 1.6, margin: 0, valign: "middle",
    });
  }
  slide.addText(o.title, {
    x: M, y: o.kicker ? 0.76 : 0.5, w: o.titleW || 11.4, h: 0.86,
    fontSize: o.titleSize || 31, bold: true, fontFace: HEAD_FONT,
    color: dark ? C.paper : C.text, margin: 0, valign: "middle",
  });
  if (o.sub) {
    slide.addText(o.sub, {
      x: M, y: 1.62, w: o.subW || 11.7, h: 0.5, fontSize: 14.5, fontFace: BODY_FONT,
      color: dark ? "AFBBCE" : C.body, margin: 0, valign: "top",
    });
  }
  if (o.pill) pill(slide, o.pill[0], o.pill[1]);
}

// grid of cards. items: {t, b, tag}
function cards(slide, items, o) {
  const cols = o.cols || items.length;
  const gap = o.gap === undefined ? 0.26 : o.gap;
  const w = (o.w || CW - (cols - 1) * gap) / (o.w ? 1 : 1) ;
  const cw = ((o.w || CW) - (cols - 1) * gap) / cols;
  const rows = Math.ceil(items.length / cols);
  const rh = o.h || 1.5;
  const rgap = o.rgap === undefined ? gap : o.rgap;
  items.forEach((it, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    const x = (o.x === undefined ? M : o.x) + c * (cw + gap);
    const y = o.y + r * (rh + rgap);
    slide.addShape("roundRect", {
      x, y, w: cw, h: rh, rectRadius: 0.06,
      fill: { color: it.fill || o.fill || C.tint },
      line: { color: it.fill || o.fill || C.tint },
    });
    const pad = 0.22;
    slide.addText(it.t, {
      x: x + pad, y: y + 0.16, w: cw - 2 * pad, h: 0.38, margin: 0,
      fontSize: o.titleSize || 14.5, bold: true, fontFace: BODY_FONT,
      color: it.tc || o.titleColor || C.text, valign: "top",
    });
    if (it.b) {
      slide.addText(it.b, {
        x: x + pad, y: y + 0.58, w: cw - 2 * pad, h: rh - 0.74, margin: 0,
        fontSize: o.bodySize || 11.5, fontFace: BODY_FONT,
        color: it.bc || o.bodyColor || C.body, valign: "top", lineSpacingMultiple: 1.02,
      });
    }
  });
}

// big statistic block
function stat(slide, o) {
  slide.addText(o.value, {
    x: o.x, y: o.y, w: o.w, h: o.vh || 0.95, margin: 0,
    fontSize: o.size || 46, bold: true, fontFace: HEAD_FONT,
    color: o.color || C.text, align: o.align || "left", valign: "middle",
  });
  slide.addText(o.label, {
    x: o.x, y: o.y + (o.vh || 0.95) - 0.04, w: o.w, h: o.lh || 0.6, margin: 0,
    fontSize: o.labelSize || 11.5, fontFace: BODY_FONT,
    color: o.labelColor || C.muted, align: o.align || "left", valign: "top",
  });
}

// horizontal flow of boxes with arrow separators
function flow(slide, steps, o) {
  const n = steps.length;
  const arrow = o.arrow === undefined ? 0.3 : o.arrow;
  const total = o.w || CW;
  const bw = (total - (n - 1) * arrow) / n;
  steps.forEach((s, i) => {
    const x = (o.x === undefined ? M : o.x) + i * (bw + arrow);
    slide.addShape("roundRect", {
      x, y: o.y, w: bw, h: o.h || 1.0, rectRadius: 0.06,
      fill: { color: s.fill || o.fill || C.tint },
      line: { color: s.line || s.fill || o.fill || C.tint },
    });
    slide.addText(s.t, {
      x: x + 0.12, y: o.y + 0.12, w: bw - 0.24, h: (o.h || 1.0) - 0.24, margin: 0,
      fontSize: o.size || 12.5, bold: true, fontFace: BODY_FONT,
      color: s.tc || o.color || C.text, align: "center", valign: "middle",
      lineSpacingMultiple: 1.0,
    });
    if (i < n - 1) {
      slide.addShape("rightArrow", {
        x: x + bw + 0.06, y: o.y + (o.h || 1.0) / 2 - 0.09, w: arrow - 0.12, h: 0.18,
        fill: { color: o.arrowColor || C.slate }, line: { color: o.arrowColor || C.slate },
      });
    }
  });
}

// labelled list of rows: {k, v}
function rows(slide, items, o) {
  const rh = o.rh || 0.52;
  items.forEach((it, i) => {
    const y = o.y + i * rh;
    if (i % 2 === 0 && o.zebra !== false) {
      slide.addShape("rect", {
        x: (o.x === undefined ? M : o.x) - 0.1, y, w: (o.w || CW) + 0.2, h: rh,
        fill: { color: o.zebraColor || "F5F7FA" }, line: { color: o.zebraColor || "F5F7FA" },
      });
    }
    slide.addText(it.k, {
      x: o.x === undefined ? M : o.x, y, w: o.kw || 3.6, h: rh, margin: 0,
      fontSize: o.size || 12.5, bold: true, fontFace: BODY_FONT,
      color: it.kc || o.kColor || C.text, valign: "middle",
    });
    slide.addText(it.v, {
      x: (o.x === undefined ? M : o.x) + (o.kw || 3.6) + 0.2, y,
      w: (o.w || CW) - (o.kw || 3.6) - 0.2, h: rh, margin: 0,
      fontSize: o.size || 12.5, fontFace: BODY_FONT,
      color: it.vc || o.vColor || C.body, valign: "middle",
    });
  });
}

// One call per slide: records the note, paints the background, draws the
// header and the footer, returns the slide for content.
function mk(pptx, o) {
  record(o.title, o.notes || "");
  const slide = pptx.addSlide();
  slide.background = { color: o.dark ? C.ink : C.paper };
  if (o.title && !o.bare) head(slide, o);
  foot(slide, !!o.dark);
  slide.addNotes(o.notes || "");
  return slide;
}

module.exports = { C, HEAD_FONT, BODY_FONT, M, W, H, CW, NOTES, record, foot, pill, head, cards, stat, flow, rows, mk };
