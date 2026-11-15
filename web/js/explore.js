// "Explore anywhere": drag a box anywhere on Earth -> live query of the ASF archive for NISAR
// products -> footprints on the map, stacks grouped by viewing geometry, and the exact
// command that processes the box with the same pipeline as the showcase sites.

const ASF_API = "https://api.daac.asf.alaska.edu/services/search/param";
const TS = /^\d{8}T\d{6}$/;

export function parseGranule(name) {
  const t = name.replace(/\.(h5|zip)$/, "").split("_");
  if (t[0] !== "NISAR" || t.length < 10) return null;
  const times = t.filter(x => TS.test(x)).map(x => `${x.slice(0, 4)}-${x.slice(4, 6)}-${x.slice(6, 8)}`);
  return { name: t.join("_"), band: t[1][0] === "S" ? "S" : "L", product: t[3], track: +t[5], direction: t[6], frame: +t[7], pol: t[9], times };
}

const wkt = ([w, s, e, n]) => `POLYGON((${w} ${s},${e} ${s},${e} ${n},${w} ${n},${w} ${s}))`;
const r3 = v => Math.round(v * 1000) / 1000;

export function setupExplore(map, ui) {
  const panel = document.getElementById("explore-panel");
  const out = document.getElementById("ex-result");
  const endInput = document.getElementById("ex-end");
  endInput.value = new Date().toISOString().slice(0, 10);
  let drawing = false, start = null, bbox = null;

  const ensureLayers = () => {
    if (map.getSource("draw-box")) return;
    map.addSource("draw-box", { type: "geojson", data: empty() });
    map.addLayer({ id: "draw-box", type: "line", source: "draw-box", paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [2, 1] } });
    map.addSource("footprints", { type: "geojson", data: empty() });
    map.addLayer({ id: "footprints-fill", type: "fill", source: "footprints", paint: { "fill-color": "#3987e5", "fill-opacity": 0.06 } });
    map.addLayer({ id: "footprints-line", type: "line", source: "footprints", paint: { "line-color": "#86b6ef", "line-width": 1 } });
  };
  const empty = () => ({ type: "FeatureCollection", features: [] });
  const boxFeature = b => ({ type: "Feature", geometry: { type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } });

  const btn = document.getElementById("btn-explore");
  const redraw = document.getElementById("ex-redraw");
  function startDrawing() {
    ensureLayers();
    drawing = true; start = null; bbox = null;
    map.getCanvas().style.cursor = "crosshair";
    map.dragPan.disable();
    redraw.hidden = true;
    map.getSource("draw-box").setData(empty()); map.getSource("footprints").setData(empty());
    out.innerHTML = `<p class="muted">Drag a rectangle on the map… (Esc to cancel)</p>`;
  }
  function open() {
    ui.closeSite?.();   // explore is its own mode: leave any open site first
    ui.setFlyout?.(null);
    panel.hidden = false;
    btn.classList.add("on"); btn.setAttribute("aria-pressed", "true");
    startDrawing();
    ui.hideHint();
  }
  function close() {
    if (panel.hidden) return;
    panel.hidden = true; drawing = false; start = null;
    btn.classList.remove("on"); btn.setAttribute("aria-pressed", "false");
    map.getCanvas().style.cursor = ""; map.dragPan.enable();
    if (map.getSource("draw-box")) { map.getSource("draw-box").setData(empty()); map.getSource("footprints").setData(empty()); }
    ui.showHint?.();
  }
  btn.onclick = () => (panel.hidden ? open() : close());
  document.getElementById("ex-close").onclick = close;
  document.getElementById("ex-x").onclick = close;
  redraw.onclick = startDrawing;
  for (const id of ["ex-start", "ex-end", "ex-product", "ex-maturity"]) document.getElementById(id).onchange = () => bbox && run();

  map.on("mousedown", e => { if (!drawing) return; start = e.lngLat; });
  map.on("mousemove", e => {
    if (!drawing || !start) return;
    bbox = [Math.min(start.lng, e.lngLat.lng), Math.min(start.lat, e.lngLat.lat), Math.max(start.lng, e.lngLat.lng), Math.max(start.lat, e.lngLat.lat)].map(r3);
    map.getSource("draw-box").setData({ type: "FeatureCollection", features: [boxFeature(bbox)] });
  });
  map.on("mouseup", () => {
    if (!drawing || !start) return;
    start = null; drawing = false;
    map.dragPan.enable(); map.getCanvas().style.cursor = "";
    redraw.hidden = false;
    if (bbox && (bbox[2] - bbox[0]) > 0.01) run();
    else out.innerHTML = `<p class="muted">That box was too small. Press <b>Draw another box</b> and drag a larger area.</p>`;
  });

  async function run() {
    const product = document.getElementById("ex-product").value;
    const maturity = document.getElementById("ex-maturity").value;
    const s = document.getElementById("ex-start").value, e = endInput.value;
    const type = { GCOV: "flood", GUNW: "subsidence", GOFF: "glacier" }[product];
    const cmd = `python -m nisar_pulse search --bbox ${bbox.join(" ")} --start ${s} --end ${e} --product ${product}\n` +
      `python -m nisar_pulse adhoc --bbox ${bbox.join(" ")} --type ${type} --start ${s} --end ${e}   # flood|wetland|disturbance|crop|earthquake|subsidence|glacier`;
    const vertex = `https://search.asf.alaska.edu/#/?dataset=NISAR&polygon=${encodeURIComponent(wkt(bbox))}&start=${s}T00:00:00Z&end=${e}T23:59:59Z&productTypes=${product}`;
    out.innerHTML = `<p>Box <b>${bbox.join(", ")}</b> — searching ASF…</p>`;
    const params = new URLSearchParams({ dataset: "NISAR", processingLevel: product, intersectsWith: wkt(bbox),
      start: `${s}T00:00:00Z`, end: `${e}T23:59:59Z`, output: "geojson", maxResults: "300" });
    if (maturity) params.set("dataMaturity", maturity);
    let feats = null, err = null;
    try {
      let r = await fetch(`${ASF_API}?${params}`);
      if (!r.ok && maturity) { params.delete("dataMaturity"); r = await fetch(`${ASF_API}?${params}`); }
      if (!r.ok) throw new Error(`ASF API HTTP ${r.status}`);
      feats = (await r.json()).features || [];
    } catch (ex) { err = ex; }
    const tail = `<h4>Process this box</h4><pre>${cmd}</pre><p><a href="${vertex}" target="_blank" rel="noopener">Open in ASF Vertex ↗</a>` +
      ` · S-band over India & science sites: <a href="https://bhoonidhi.nrsc.gov.in" target="_blank" rel="noopener">Bhoonidhi ↗</a></p>`;
    if (err) { out.innerHTML = `<p class="muted">Live search unavailable from this browser (${err.message}). Use Vertex or the CLI:</p>` + tail; return; }
    map.getSource("footprints").setData({ type: "FeatureCollection", features: feats.filter(f => f.geometry) });
    const stacks = {};
    for (const f of feats) {
      const p = f.properties || {};
      const g = parseGranule(p.fileID || p.sceneName || p.fileName || "");
      if (!g) continue;
      const k = `${g.band}-band ${g.product} · track ${g.track} · frame ${g.frame} · ${g.direction === "A" ? "ascending" : "descending"}`;
      (stacks[k] ||= new Set()).add(g.product === "GCOV" ? g.times[0] : `${g.times[0]}→${g.times[2] || g.times[1]}`);
    }
    const keys = Object.keys(stacks).sort((a, b) => stacks[b].size - stacks[a].size);
    out.innerHTML = (keys.length ? `<p><b>${feats.length}</b> products in <b>${keys.length}</b> viewing geometries. Only images within one geometry can be compared.</p>` +
      keys.map(k => `<div class="ex-stack"><b>${k}</b> — ${stacks[k].size} dates<div class="ex-dates">${[...stacks[k]].sort().map(d => `<span>${d}</span>`).join("")}</div></div>`).join("")
      : `<p>No ${product} products found. Calibrated L-band data start 2026-06-17; older BETA data are pre-calibration — try maturity “any”.</p>`) + tail;
  }
  return { open, close, isOpen: () => !panel.hidden };
}
