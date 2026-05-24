// Renders the Canopy wiki diagrams to PNG.
//
// Diagrams are authored as SVG in this file (no browser needed) and rasterized
// with @resvg/resvg-js. To regenerate after editing:
//
//   npm install @resvg/resvg-js
//   node scripts/render-diagrams.mjs
//
// Output: docs/images/*.png  (referenced by docs/WIKI.md)

import { Resvg } from "@resvg/resvg-js";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "docs", "images");
mkdirSync(OUT, { recursive: true });

const FONT = "DejaVu Sans";
const C = {
  ink: "#16242f", muted: "#55636e", line: "#cbd5e0", arrow: "#647281",
  green: "#2f8f63", greenDk: "#1f6f54", greenBg: "#e7f4ee",
  teal: "#2c7a7b", tealBg: "#e1efef",
  blue: "#2b6cb0", blueBg: "#e7f0fb",
  amber: "#b7791f", amberBg: "#fbf1d9",
  red: "#c0392b", redBg: "#fbe7e4",
  violet: "#6b46c1", violetBg: "#efe9fb",
  slate: "#475569", slateBg: "#eef2f7",
  frame: "#e2e8f0", white: "#ffffff",
};

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function text(x, y, s, o = {}) {
  const { size = 14, weight = "normal", fill = C.ink, anchor = "middle", opacity = 1, spacing = 0 } = o;
  const ls = spacing ? ` letter-spacing="${spacing}"` : "";
  return `<text x="${x}" y="${y}" font-family="${FONT}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" opacity="${opacity}"${ls}>${esc(s)}</text>`;
}

// Vertically center a stack of text lines around cy.
function linesCentered(cx, cy, items, gap = 6) {
  const total = items.reduce((a, it) => a + (it.size || 14), 0) + gap * (items.length - 1);
  let y = cy - total / 2;
  let out = "";
  for (const it of items) {
    const sz = it.size || 14;
    y += sz;
    out += text(cx, y - sz * 0.2, it.t, { size: sz, weight: it.weight, fill: it.fill, anchor: it.anchor || "middle", spacing: it.spacing });
    y += gap;
  }
  return out;
}

function box(x, y, w, h, o = {}) {
  const { fill = C.white, stroke = C.line, sw = 1.6, rx = 12, opacity = 1, dash = null } = o;
  const d = dash ? ` stroke-dasharray="${dash}"` : "";
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" ry="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" opacity="${opacity}"${d}/>`;
}

// A card: rounded box, optional left accent bar, centered title + sublines.
function card(x, y, w, h, o = {}) {
  const { fill = C.white, stroke = C.line, sw = 1.6, rx = 12, accent = null,
    title = "", titleSize = 15, titleColor = C.ink, titleWeight = "bold",
    sub = [], subSize = 11.5, subColor = C.muted } = o;
  let s = box(x, y, w, h, { fill, stroke, sw, rx });
  if (accent) s += `<rect x="${x}" y="${y}" width="6" height="${h}" rx="3" ry="3" fill="${accent}"/><rect x="${x + 3}" y="${y}" width="3" height="${h}" fill="${accent}"/>`;
  const items = [{ t: title, size: titleSize, weight: titleWeight, fill: titleColor },
    ...sub.map((t) => ({ t, size: subSize, weight: "normal", fill: subColor }))];
  s += linesCentered(x + w / 2 + (accent ? 3 : 0), y + h / 2, items, 6);
  return s;
}

function markers() {
  const mk = (id, col) =>
    `<marker id="${id}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7.5" markerHeight="7.5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${col}"/></marker>`;
  return `<defs>${mk("a-arrow", C.arrow)}${mk("a-green", C.green)}${mk("a-amber", C.amber)}${mk("a-red", C.red)}${mk("a-teal", C.teal)}${mk("a-blue", C.blue)}${mk("a-violet", C.violet)}</defs>`;
}

const MK = { [C.arrow]: "a-arrow", [C.green]: "a-green", [C.amber]: "a-amber", [C.red]: "a-red", [C.teal]: "a-teal", [C.blue]: "a-blue", [C.violet]: "a-violet" };

function arrow(x1, y1, x2, y2, o = {}) {
  const { color = C.arrow, w = 2, dash = null } = o;
  const d = dash ? ` stroke-dasharray="${dash}"` : "";
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="${w}" marker-end="url(#${MK[color]})"${d} stroke-linecap="round"/>`;
}

function pathArrow(d, o = {}) {
  const { color = C.arrow, w = 2, dash = null } = o;
  const da = dash ? ` stroke-dasharray="${dash}"` : "";
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" marker-end="url(#${MK[color]})"${da} stroke-linecap="round"/>`;
}

// little label chip on an arrow / free-floating
function chip(cx, cy, s, o = {}) {
  const { size = 11, fill = C.muted, bg = C.white, padX = 6, weight = "normal" } = o;
  const w = s.length * size * 0.56 + padX * 2;
  return `<rect x="${cx - w / 2}" y="${cy - size / 2 - 4}" width="${w}" height="${size + 8}" rx="6" fill="${bg}" stroke="${C.frame}" stroke-width="1"/>` +
    text(cx, cy + size * 0.34, s, { size, fill, weight });
}

function frame(w, h, title, subtitle) {
  let s = `<rect x="0" y="0" width="${w}" height="${h}" rx="18" fill="${C.white}" stroke="${C.frame}" stroke-width="2"/>`;
  s += `<rect x="0" y="0" width="${w}" height="64" rx="18" fill="${C.greenBg}"/><rect x="0" y="46" width="${w}" height="18" fill="${C.greenBg}"/>`;
  s += `<rect x="28" y="24" width="14" height="14" rx="3" fill="${C.greenDk}"/>`;
  s += text(54, 36, title, { size: 19, weight: "bold", fill: C.greenDk, anchor: "start" });
  if (subtitle) s += text(w - 28, 36, subtitle, { size: 12.5, fill: C.green, anchor: "end" });
  return s;
}

function svg(w, h, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${markers()}${body}</svg>`;
}

function render(name, w, h, body, scale = 2) {
  const s = svg(w, h, body);
  const r = new Resvg(s, { fitTo: { mode: "width", value: w * scale }, font: { loadSystemFonts: true, defaultFontFamily: FONT } });
  writeFileSync(join(OUT, name + ".png"), r.render().asPng());
  console.log("wrote", name + ".png", `${w * scale}x${h * scale}`);
}

/* ----------------------------------------------------------------------- */
/* 1. System architecture — two front doors, one backend                   */
/* ----------------------------------------------------------------------- */
function architecture() {
  const W = 1060, H = 660;
  let b = frame(W, H, "Architecture — two front doors, one backend", "REST /api/v1");

  // clients
  b += card(110, 96, 360, 96, {
    fill: C.blueBg, stroke: C.blue, accent: C.blue, title: "React Dashboard",
    titleColor: C.blue, sub: ["Portfolio · Initiatives · Gantt · Board · Risk", "Decisions · Architecture · Drift · Team · /me"],
  });
  b += card(590, 96, 360, 96, {
    fill: C.violetBg, stroke: C.violet, accent: C.violet, title: "Claude Code Plugin",
    titleColor: C.violet, sub: ["MCP server · ~61 curated tools", "6 skills · 4 subagents"],
  });

  // API bar
  b += card(110, 232, 840, 64, { fill: C.greenDk, stroke: C.greenDk, title: "FastAPI backend  —  REST API  /api/v1", titleColor: "#ffffff", titleSize: 17 });
  b += arrow(290, 192, 290, 230, { color: C.arrow });
  b += arrow(770, 192, 770, 230, { color: C.arrow });
  b += chip(530, 214, "same API for both doors", { size: 11, fill: C.muted });

  // services
  const svcs = [
    ["Scheduling", "CPM critical path"],
    ["Risk & Drift", "leading scores"],
    ["Forecast", "Monte-Carlo P50/P85"],
    ["Capacity & Flow", "WIP · aging · alloc"],
    ["Connectors", "sync · webhooks"],
  ];
  const sx = 110, sw = 156, sgap = 15;
  svcs.forEach(([t, s], i) => {
    b += card(sx + i * (sw + sgap), 336, sw, 78, { fill: C.slateBg, stroke: C.line, accent: C.teal, title: t, titleSize: 13.5, sub: [s], subSize: 10.5 });
  });
  b += arrow(530, 296, 530, 334, { color: C.arrow });
  b += chip(530, 316, "pure, unit-tested services", { size: 10.5, fill: C.muted });

  // data layer
  b += card(110, 454, 405, 64, { fill: C.white, stroke: C.line, accent: C.slate, title: "PostgreSQL + Alembic", titleSize: 14, sub: ["SQLModel · real migrations"], subSize: 10.5 });
  b += card(545, 454, 405, 64, { fill: C.white, stroke: C.line, accent: C.slate, title: "arq worker + Redis", titleSize: 14, sub: ["Jira poll · nightly risk snapshots · webhooks"], subSize: 10.5 });
  b += arrow(312, 414, 312, 452, { color: C.arrow });
  b += arrow(747, 414, 747, 452, { color: C.arrow });

  // externals
  b += text(110, 566, "Systems of record (Canopy mirrors / reads — never owns)", { size: 12.5, weight: "bold", fill: C.muted, anchor: "start" });
  const ext = [["Jira", C.blue, "epics · stories · status"], ["GitHub", C.ink, "code · PRs · docs"], ["Google Drive", C.green, "design docs"]];
  ext.forEach(([t, col, s], i) => {
    b += card(110 + i * 285, 580, 265, 56, { fill: C.white, stroke: col, title: t, titleColor: col, titleSize: 14, sub: [s], subSize: 10.5 });
    b += arrow(110 + i * 285 + 132, 580, 110 + i * 285 + 132, 520, { color: C.arrow, dash: "5 4" });
  });

  render("architecture", W, H, b);
}

/* ----------------------------------------------------------------------- */
/* 2. The intent spine                                                      */
/* ----------------------------------------------------------------------- */
function intentSpine() {
  const W = 940, H = 720;
  let b = frame(W, H, "The intent spine — velocity flows down, verification flows up");

  const cx = 360, w = 440, x = cx - w / 2;
  const levels = [
    ["Initiative", "outcome + hypothesis — why, and how we'll know", C.greenBg, C.greenDk],
    ["Project", "a bet toward the outcome — the slice a team owns", C.tealBg, C.teal],
    ["Decision / ADR", "the architectural choices — one-way vs two-way doors", C.blueBg, C.blue],
  ];
  let y = 96;
  const ys = [];
  levels.forEach(([t, s, bg, col]) => {
    b += card(x, y, w, 70, { fill: bg, stroke: col, accent: col, title: t, titleColor: col, titleSize: 16, sub: [s], subSize: 11 });
    ys.push(y);
    y += 70;
    b += arrow(cx, y, cx, y + 28, { color: C.arrow });
    b += text(cx + 14, y + 20, "intent", { size: 10.5, fill: C.muted, anchor: "start" });
    y += 28;
  });

  // branch: fitness + work
  const by = y;
  b += card(x, by, 205, 66, { fill: C.amberBg, stroke: C.amber, accent: C.amber, title: "Fitness function", titleColor: C.amber, titleSize: 13.5, sub: ["decision made", "continuously verifiable"], subSize: 10 });
  b += card(x + 235, by, 205, 66, { fill: C.slateBg, stroke: C.slate, accent: C.slate, title: "Work — tasks / PRs", titleColor: C.slate, titleSize: 13.5, sub: ["small batches that", "implement the decision"], subSize: 10 });
  // connect decision -> both
  b += arrow(cx - 110, by - 28, x + 102, by - 2, { color: C.arrow });
  b += arrow(cx + 110, by - 28, x + 337, by - 2, { color: C.arrow });
  y = by + 66 + 28;

  b += card(x, y, w, 66, { fill: C.greenBg, stroke: C.green, accent: C.green, title: "Verification", titleColor: C.green, titleSize: 15, sub: ["tests + fitness + telemetry prove it's done & honored"], subSize: 11 });
  b += arrow(x + 102, by + 66, x + 150, y - 2, { color: C.arrow });
  b += arrow(x + 337, by + 66, x + 290, y - 2, { color: C.arrow });
  const vy = y;
  y += 66 + 28;
  b += arrow(cx, vy + 66, cx, y - 2, { color: C.arrow });

  b += card(x, y, w, 66, { fill: C.white, stroke: C.ink, accent: C.ink, title: "Outcome / metrics", titleColor: C.ink, titleSize: 15, sub: ["DORA + flow feed back into forecast & retro"], subSize: 11 });
  const oy = y;

  // feedback loop curve (right side, bottom -> top)
  const rx = x + w;
  b += pathArrow(`M ${rx} ${oy + 33} C ${rx + 150} ${oy + 33}, ${rx + 150} ${ys[0] + 35}, ${rx + 2} ${ys[0] + 35}`, { color: C.green, w: 2.4 });
  b += text(rx + 138, (oy + ys[0]) / 2 + 35, "verification", { size: 12, weight: "bold", fill: C.green, anchor: "middle" });
  b += text(rx + 138, (oy + ys[0]) / 2 + 51, "& learning", { size: 12, weight: "bold", fill: C.green, anchor: "middle" });

  render("intent-spine", W, H, b);
}

/* ----------------------------------------------------------------------- */
/* 3. Personas                                                              */
/* ----------------------------------------------------------------------- */
function personas() {
  const W = 1060, H = 580;
  let b = frame(W, H, "Who Canopy is for", "reads open to all · writes gated by role");

  const cards = [
    ["Architect", C.greenDk, C.greenBg, "Primary persona", "Owns coherence + the irreversible decisions. Plans, schedules, maps architecture, leads on risk."],
    ["Engineering Manager", C.teal, C.tealBg, "Planner", "Sequences work, manages capacity & allocations, proposes and shepherds decisions, runs retros."],
    ["Engineer", C.blue, C.blueBg, "Contributor", "/me work + Today focus. Flags blockers, updates own tasks, proposes & comments on decisions."],
    ["Viewer", C.slate, C.slateBg, "Stakeholder / exec", "Read-only across portfolio, initiatives, risk, roadmap & decisions. Visibility without edit."],
    ["Admin", C.amber, C.amberBg, "Architect + keys", "Everything an architect can do, plus invite users, change roles, deactivate / reactivate."],
    ["Claude (AI)", C.violet, C.violetBg, "Agentic teammate", "Plans, syncs Jira, assesses risk, detects drift, nudges decisions — inside the same guardrails."],
  ];
  const cw = 318, ch = 196, gx = 22, gy = 24, x0 = 28, y0 = 88;
  cards.forEach((c, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = x0 + col * (cw + gx), y = y0 + row * (ch + gy);
    const [name, col1, bg, role, desc] = c;
    b += box(x, y, cw, ch, { fill: bg, stroke: col1, sw: 1.8, rx: 14 });
    b += `<circle cx="${x + 34}" cy="${y + 36}" r="16" fill="${col1}"/>`;
    b += text(x + 34, y + 41, name[0], { size: 16, weight: "bold", fill: "#ffffff" });
    b += text(x + 60, y + 32, name, { size: 17, weight: "bold", fill: col1, anchor: "start" });
    b += text(x + 60, y + 50, role, { size: 11.5, fill: C.muted, anchor: "start" });
    // wrapped description
    const words = desc.split(" ");
    let line = "", ly = y + 86;
    const maxw = cw - 44;
    for (const word of words) {
      const test = line ? line + " " + word : word;
      if (test.length * 7.0 > maxw && line) { b += text(x + 22, ly, line, { size: 12.5, fill: C.ink, anchor: "start" }); line = word; ly += 19; }
      else line = test;
    }
    if (line) b += text(x + 22, ly, line, { size: 12.5, fill: C.ink, anchor: "start" });
  });
  render("personas", W, H, b);
}

/* ----------------------------------------------------------------------- */
/* 4. ADR decision lifecycle                                                */
/* ----------------------------------------------------------------------- */
function adrLifecycle() {
  const W = 1060, H = 540;
  let b = frame(W, H, "Decision (ADR) lifecycle", "illegal jumps rejected · 409");

  const node = (x, y, t, col, bg, sub) => card(x, y, 168, 58, { fill: bg, stroke: col, title: t, titleColor: col, titleSize: 14.5, sub: sub ? [sub] : [], subSize: 10 });

  const xs = [40, 268, 520, 800];
  // column 1
  b += node(xs[0], 150, "Proposed", C.blue, C.blueBg);
  // column 2
  b += node(xs[1], 150, "Under discussion", C.teal, C.tealBg);
  b += node(xs[1], 300, "Deferred", C.amber, C.amberBg, "requires decide_by");
  // column 3
  b += node(xs[2], 90, "Accepted", C.green, C.greenBg);
  b += node(xs[2], 230, "Rejected", C.red, C.redBg);
  // column 4
  b += node(xs[3], 60, "Superseded", C.slate, C.slateBg);
  b += node(xs[3], 150, "Deprecated", C.slate, C.slateBg);

  // arrows
  b += arrow(xs[0] + 168, 179, xs[1] - 2, 179, { color: C.arrow });
  b += arrow(xs[1] + 84, 208, xs[1] + 84, 298, { color: C.amber, dash: "5 4" });
  b += text(xs[1] + 92, 256, "defer", { size: 10.5, fill: C.amber, anchor: "start" });
  // under discussion -> accepted / rejected
  b += pathArrow(`M ${xs[1] + 168} ${172} C ${xs[2] - 40} ${150}, ${xs[2] - 40} ${119}, ${xs[2] - 2} ${119}`, { color: C.green });
  b += pathArrow(`M ${xs[1] + 168} ${186} C ${xs[2] - 40} ${210}, ${xs[2] - 40} ${259}, ${xs[2] - 2} ${259}`, { color: C.red });
  // deferred re-enters discussion
  b += pathArrow(`M ${xs[1] + 168} ${320} C ${xs[2] - 60} ${330}, ${xs[2] - 60} ${300}, ${xs[1] + 170} ${198}`, { color: C.amber, dash: "5 4" });
  // accepted -> superseded / deprecated
  b += pathArrow(`M ${xs[2] + 168} ${108} C ${xs[3] - 40} ${100}, ${xs[3] - 40} ${89}, ${xs[3] - 2} ${89}`, { color: C.slate });
  b += pathArrow(`M ${xs[2] + 168} ${122} C ${xs[3] - 40} ${140}, ${xs[3] - 40} ${179}, ${xs[3] - 2} ${179}`, { color: C.slate });

  // legend
  b += text(40, 430, "Lifecycle:", { size: 12.5, weight: "bold", fill: C.muted, anchor: "start" });
  b += text(40, 452, "proposed → under_discussion → accepted | rejected → superseded | deprecated   (plus deferred, which requires a decide_by date)", { size: 12.5, fill: C.ink, anchor: "start" });
  b += text(40, 480, "Engineers may propose & comment; only planners (admin / architect / eng-manager) can change status.", { size: 12, fill: C.muted, anchor: "start" });
  render("adr-lifecycle", W, H, b);
}

/* ----------------------------------------------------------------------- */
/* 5. Source-of-truth boundaries                                            */
/* ----------------------------------------------------------------------- */
function sourceOfTruth() {
  const W = 1020, H = 470;
  let b = frame(W, H, "Source-of-truth boundaries", "Canopy mirrors & schedules — it does not own");

  // center
  b += card(390, 190, 240, 92, { fill: C.greenDk, stroke: C.greenDk, title: "Canopy", titleColor: "#fff", titleSize: 20, sub: ["architecture + delivery layer"], subColor: "#cdeadd", subSize: 11.5 });

  // Jira (left)
  b += card(60, 130, 230, 80, { fill: C.blueBg, stroke: C.blue, title: "Jira", titleColor: C.blue, titleSize: 16, sub: ["owns epics · stories · status"], subSize: 11 });
  b += pathArrow(`M 290 165 C 340 165, 350 210, 388 220`, { color: C.green, w: 2.4 });
  b += chip(345, 150, "sync FROM", { size: 11, fill: C.green, weight: "bold" });
  // blocked write-back
  b += pathArrow(`M 388 252 C 350 270, 340 300, 292 300`, { color: C.red, w: 2.2, dash: "6 5" });
  b += chip(345, 318, "never writes status", { size: 11, fill: C.red, weight: "bold" });
  b += `<line x1="338" y1="278" x2="352" y2="292" stroke="${C.red}" stroke-width="2.4"/><line x1="352" y1="278" x2="338" y2="292" stroke="${C.red}" stroke-width="2.4"/>`;

  // GitHub (right top)
  b += card(730, 110, 230, 76, { fill: C.white, stroke: C.ink, title: "GitHub", titleColor: C.ink, titleSize: 16, sub: ["owns code · PRs · some docs"], subSize: 11 });
  b += pathArrow(`M 730 150 C 680 160, 660 210, 632 222`, { color: C.arrow, w: 2.2, dash: "5 4" });
  b += chip(672, 150, "reads on demand", { size: 11, fill: C.muted });

  // Drive (right bottom)
  b += card(730, 250, 230, 76, { fill: C.greenBg, stroke: C.green, title: "Google Drive", titleColor: C.green, titleSize: 16, sub: ["owns design docs"], subSize: 11 });
  b += pathArrow(`M 730 286 C 680 280, 660 250, 632 248`, { color: C.arrow, w: 2.2, dash: "5 4" });
  b += chip(672, 300, "reads docs", { size: 11, fill: C.muted });

  b += text(W / 2, 410, "Canopy adds the architecture + delivery layer on top of your existing tools — no migration into a new silo.", { size: 12.5, fill: C.muted });
  render("source-of-truth", W, H, b);
}

/* ----------------------------------------------------------------------- */
/* 6. Project cockpit map                                                   */
/* ----------------------------------------------------------------------- */
function cockpit() {
  const W = 1060, H = 560;
  let b = frame(W, H, "The project cockpit", "/projects/:id  ·  deep-link any tab with ?tab=");

  const groups = [
    ["Plan & schedule", C.blue, C.blueBg, ["Gantt", "Board", "Dependencies", "Roadmap", "Burndown"]],
    ["Architecture & decisions", C.violet, C.violetBg, ["Architecture", "Decisions", "Drift"]],
    ["Team", C.teal, C.tealBg, ["Capacity"]],
    ["Health & history", C.amber, C.amberBg, ["Risk", "Retros", "Activity"]],
  ];
  // layout: 2 x 2 group panels
  const gw = 498, gh = 196, gx = 28, gy = 22, x0 = 28, y0 = 92;
  groups.forEach((g, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = x0 + col * (gw + gx), y = y0 + row * (gh + gy);
    const [name, colr, bg, tabs] = g;
    b += box(x, y, gw, gh, { fill: bg, stroke: colr, sw: 1.8, rx: 14 });
    b += text(x + 22, y + 32, name, { size: 16, weight: "bold", fill: colr, anchor: "start" });
    // tab chips
    const chipW = 150, chipH = 46, cgx = 14, cgy = 14, cx0 = x + 22, cy0 = y + 52;
    tabs.forEach((t, j) => {
      const cc = j % 3, cr = Math.floor(j / 3);
      const tx = cx0 + cc * (chipW + cgx), ty = cy0 + cr * (chipH + cgy);
      b += box(tx, ty, chipW, chipH, { fill: C.white, stroke: colr, sw: 1.4, rx: 9 });
      b += text(tx + chipW / 2, ty + chipH / 2 + 5, t, { size: 13.5, weight: "bold", fill: C.ink });
    });
  });
  render("cockpit", W, H, b);
}

architecture();
intentSpine();
personas();
adrLifecycle();
sourceOfTruth();
cockpit();
console.log("done");
