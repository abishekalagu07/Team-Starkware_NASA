// Minimal dependency-free SVG charts: line (crosshair tooltip) and bar (per-mark tooltip).
// Rules followed: one y-axis, thin marks, recessive grid, legend for >=2 series,
// direct end-labels for <=4 series, colour follows the entity (class colour = map colour),
// table view for accessibility.

const NS = "http://www.w3.org/2000/svg";
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const INK = "#0b0b0b", INK2 = "#52514e", GRID = "#e7e6e2", MUTED = "#8a8985";

let tip;
function tooltip() {
  if (!tip) { tip = document.createElement("div"); tip.className = "tooltip"; tip.hidden = true; document.body.appendChild(tip); }
  return tip;
}
function el(name, attrs = {}, parent) {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}
function niceTicks(min, max, n = 4) {
  if (!isFinite(min) || !isFinite(max)) return [0, 1];
  if (min === max) { min -= 1; max += 1; }
  const span = max - min, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || 10 * mag;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}
const fmt = v => (v == null || !isFinite(v)) ? "–" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : (+v.toFixed(Math.abs(v) < 10 ? 2 : 1)).toString();
const fmtDate = s => new Date(s + "T00:00:00Z").toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
const short = s => { const t = s.replace(/\s*\(.*\)/, ""); return t.length > 14 ? t.slice(0, 13) + "…" : t; };

function card(container, title, onTable) {
  const c = document.createElement("div");
  c.className = "chart-card";
  const t = document.createElement("div");
  t.className = "ct";
  t.innerHTML = `<span>${title}</span>`;
  if (onTable) {
    const b = document.createElement("button");
    b.textContent = "Table";
    b.onclick = () => onTable(c, b);
    t.appendChild(b);
  }
  c.appendChild(t);
  container.appendChild(c);
  return c;
}

function toggleTable(c, b, header, rows) {
  const existing = c.querySelector(".chart-table");
  const svg = c.querySelector("svg");
  if (existing) { existing.remove(); svg.style.display = ""; b.textContent = "Table"; return; }
  const tb = document.createElement("table");
  tb.className = "chart-table";
  tb.innerHTML = `<thead><tr>${header.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(r => `<tr>${r.map(v => `<td>${v}</td>`).join("")}</tr>`).join("") + "</tbody>";
  svg.style.display = "none"; b.textContent = "Chart";
  c.appendChild(tb);
}

export function lineChart(container, spec, { highlightDate } = {}) {
  const dates = spec.dates, series = spec.series.map((s, i) => ({ ...s, color: s.color || SERIES[i % SERIES.length] }));
  const c = card(container, `${spec.title}${spec.unit ? ` (${spec.unit})` : ""}`, (cc, b) =>
    toggleTable(cc, b, ["Date", ...series.map(s => short(s.name))], dates.map((d, i) => [fmtDate(d), ...series.map(s => fmt(s.values[i]))])));
  if (series.length >= 2) {
    const lg = document.createElement("div"); lg.className = "chart-legend";
    lg.innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
    c.appendChild(lg);
  }
  const W = 380, H = 190, direct = series.length <= 4 && series.length >= 2;
  const m = { l: 38, r: direct ? 84 : 12, t: 10, b: 24 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.title }, c);
  const ts = dates.map(d => Date.parse(d));
  const t0 = Math.min(...ts), t1 = Math.max(...ts) || t0 + 1;
  const vals = series.flatMap(s => s.values).filter(v => v != null && isFinite(v));
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = t => m.l + (W - m.l - m.r) * ((t - t0) / ((t1 - t0) || 1));
  const Y = v => m.t + (H - m.t - m.b) * (1 - (v - y0) / ((y1 - y0) || 1));
  for (const tv of ticks) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(tv), y2: Y(tv), stroke: GRID, "stroke-width": 1 }, svg);
    el("text", { x: m.l - 6, y: Y(tv) + 3.5, "text-anchor": "end", "font-size": 10, fill: MUTED }, svg).textContent = fmt(tv);
  }
  const nx = Math.min(5, dates.length);
  for (let k = 0; k < nx; k++) {
    const i = Math.round(k * (dates.length - 1) / Math.max(nx - 1, 1));
    el("text", { x: X(ts[i]), y: H - 6, "text-anchor": "middle", "font-size": 10, fill: MUTED }, svg).textContent = fmtDate(dates[i]);
  }
  if (highlightDate) {
    const hx = X(Date.parse(highlightDate));
    if (hx >= m.l && hx <= W - m.r) {
      el("line", { x1: hx, x2: hx, y1: m.t, y2: H - m.b, stroke: INK2, "stroke-dasharray": "3 3", "stroke-width": 1 }, svg);
      el("text", { x: hx + 3, y: m.t + 9, "font-size": 9.5, fill: INK2 }, svg).textContent = "event";
    }
  }
  const ends = [];
  for (const s of series) {
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v == null || !isFinite(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(ts[i]).toFixed(1)},${Y(v).toFixed(1)}`; pen = true;
    });
    el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    const li = s.values.map((v, i) => (v != null && isFinite(v)) ? i : -1).filter(i => i >= 0).pop();
    if (li != null) ends.push({ s, y: Y(s.values[li]), x: X(ts[li]) });
  }
  if (direct) {
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 12) ends[i].y = ends[i - 1].y + 12;
    for (const e of ends) el("text", { x: W - m.r + 6, y: e.y + 3.5, "font-size": 10.5, fill: INK2 }, svg).textContent = short(e.s.name);
  }
  // crosshair + tooltip
  const cross = el("line", { y1: m.t, y2: H - m.b, stroke: INK2, "stroke-width": 1, visibility: "hidden" }, svg);
  const dots = series.map(s => el("circle", { r: 4, fill: s.color, stroke: "#fcfcfb", "stroke-width": 2, visibility: "hidden" }, svg));
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  const tt = tooltip();
  hit.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * W / r.width;
    let bi = 0, bd = Infinity;
    ts.forEach((t, i) => { const dd = Math.abs(X(t) - px); if (dd < bd) { bd = dd; bi = i; } });
    cross.setAttribute("x1", X(ts[bi])); cross.setAttribute("x2", X(ts[bi])); cross.setAttribute("visibility", "visible");
    series.forEach((s, k) => {
      const v = s.values[bi];
      if (v == null || !isFinite(v)) { dots[k].setAttribute("visibility", "hidden"); return; }
      dots[k].setAttribute("cx", X(ts[bi])); dots[k].setAttribute("cy", Y(v)); dots[k].setAttribute("visibility", "visible");
    });
    tt.innerHTML = `<div class="tt-date">${fmtDate(dates[bi])}</div>` + series.map(s =>
      `<div class="tt-row"><span><i style="background:${s.color}"></i>${short(s.name)}</span><b>${fmt(s.values[bi])}${spec.unit ? " " + spec.unit : ""}</b></div>`).join("");
    tt.hidden = false;
    tt.style.left = Math.min(ev.clientX + 14, innerWidth - 200) + "px"; tt.style.top = ev.clientY + 14 + "px";
  });
  hit.addEventListener("mouseleave", () => { tt.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); });
  return c;
}

export function barChart(container, spec) {
  const bars = spec.bars;
  const c = card(container, `${spec.title}${spec.unit ? ` (${spec.unit})` : ""}`, (cc, b) =>
    toggleTable(cc, b, ["Pair", spec.unit || "value", "Spans event"], bars.map(x => [x.label, fmt(x.value), x.event ? "yes" : ""])));
  const lg = document.createElement("div"); lg.className = "chart-legend";
  lg.innerHTML = `<span><i style="background:${SERIES[1]}"></i>Pair spanning the event</span><span><i style="background:${SERIES[0]}"></i>Quiet pair</span>`;
  c.appendChild(lg);
  const W = 380, H = 180, m = { l: 38, r: 8, t: 14, b: 34 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.title }, c);
  const ticks = niceTicks(0, Math.max(...bars.map(b => b.value)));
  const y1 = ticks[ticks.length - 1];
  const Y = v => m.t + (H - m.t - m.b) * (1 - v / (y1 || 1));
  for (const tv of ticks) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(tv), y2: Y(tv), stroke: GRID }, svg);
    el("text", { x: m.l - 6, y: Y(tv) + 3.5, "text-anchor": "end", "font-size": 10, fill: MUTED }, svg).textContent = fmt(tv);
  }
  const bw = (W - m.l - m.r) / bars.length, gap = 2, tt = tooltip();
  bars.forEach((b, i) => {
    const x = m.l + i * bw + gap, w = bw - 2 * gap, y = Y(b.value), h = Y(0) - y, r = Math.min(4, w / 2, h);
    const path = `M${x},${Y(0)} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${Y(0)} Z`;
    const p = el("path", { d: path, fill: b.event ? SERIES[1] : SERIES[0] }, svg);
    el("text", { x: x + w / 2, y: H - 20, "text-anchor": "middle", "font-size": 9.5, fill: MUTED }, svg).textContent = b.label.split("–")[0];
    if (b.event) el("text", { x: x + w / 2, y: y - 4, "text-anchor": "middle", "font-size": 10.5, fill: INK, "font-weight": 600 }, svg).textContent = fmt(b.value);
    const hit = el("rect", { x: m.l + i * bw, y: m.t, width: bw, height: H - m.t - m.b, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", ev => {
      tt.innerHTML = `<div class="tt-date">${b.label}</div><div class="tt-row"><span>${b.event ? "Spans the event" : "Quiet pair"}</span><b>${fmt(b.value)} ${spec.unit}</b></div>`;
      tt.hidden = false; tt.style.left = Math.min(ev.clientX + 14, innerWidth - 200) + "px"; tt.style.top = ev.clientY + 14 + "px";
      p.setAttribute("opacity", .85);
    });
    hit.addEventListener("mouseleave", () => { tt.hidden = true; p.setAttribute("opacity", 1); });
  });
  el("line", { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: INK2 }, svg);
  return c;
}

export function renderChart(container, spec, opts) {
  return spec.kind === "bar" ? barChart(container, spec) : lineChart(container, spec, opts);
}
