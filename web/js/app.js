// NISAR Earth Pulse — main application.
// Static: everything comes from data/catalog.json + per-site images/cubes made by the pipeline.
import { renderChart, lineChart } from "./charts.js";
import { setupExplore } from "./explore.js";

const TYPES = {   // fixed order; dark-surface steps of the validated categorical palette
  flood:       { label: "Floods & wetlands", color: "#3987e5" },
  wetland:     { label: "Floods & wetlands", color: "#3987e5" },
  disturbance: { label: "Fire & forest loss", color: "#d95926" },
  crop:        { label: "Agriculture",       color: "#199e70" },
  earthquake:  { label: "Earthquakes",       color: "#c98500" },
  subsidence:  { label: "Subsidence",        color: "#d55181" },
  glacier:     { label: "Ice & glaciers",    color: "#9085e9" },
};
const FILTERS = ["all", "flood", "disturbance", "crop", "earthquake", "subsidence", "glacier"];
// change types that share a filter chip with another
const GROUP = { wetland: "flood", deformation: "earthquake" };
const groupOf = s => GROUP[s.change_type] || s.change_type;
const HOME = { center: [10, 20], zoom: 1.6 };

const $ = id => document.getElementById(id);
const state = { catalog: null, site: null, frame: 0, playing: null, filter: "all", compare: false,
  basemap: "dark", globe: false, cube: null, visible: {}, opacity: {}, markers: [] };

// ------------------------------------------------------------------ map setup
const STYLE = {
  version: 8,
  sources: {
    // CARTO basemaps now need an API key; Esri Dark Gray Canvas is keyless.
    dark: { type: "raster", tileSize: 256, maxzoom: 16, attribution: "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"] },
    optical: { type: "raster", tileSize: 256, maxzoom: 15,
      attribution: "Sentinel-2 cloudless 2021 by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2021)",
      tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg"] },
    labels: { type: "raster", tileSize: 256, maxzoom: 16,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"] },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0f1113" } },
    { id: "dark", type: "raster", source: "dark" },
    { id: "optical", type: "raster", source: "optical", layout: { visibility: "none" } },
    { id: "labels", type: "raster", source: "labels" },
  ],
};

const map = new maplibregl.Map({ container: "map", style: structuredClone(STYLE), ...HOME,
  attributionControl: { compact: true }, maxPitch: 0 });
// "load" fires once; isStyleLoaded() flips false while tiles stream, so track readiness ourselves
const ready = new WeakSet();
map.once("load", () => ready.add(map));
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");   // zoom lives in the tool rail
let mapB = null;   // compare map, created on demand

const ui = {
  hideHint: () => { $("hint").hidden = true; },
  showHint: () => { $("hint").hidden = !!state.site; },
  closeSite: () => closeSite(),
  setFlyout: f => setFlyout(f),
  toast(msg, ms = 5000) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(ui._t); ui._t = setTimeout(() => (t.hidden = true), ms); },
};

// ------------------------------------------------------------------ catalog
async function init() {
  try {
    const r = await fetch("data/catalog.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    state.catalog = await r.json();
  } catch (e) {
    ui.toast("Could not load data/catalog.json — run the pipeline (or scripts/make_demo_data.py) first.", 15000);
    state.catalog = { sites: [] };
  }
  renderFilters();
  renderSiteList();
  addMarkers();
  state.explore = setupExplore(map, ui);
  wireControls();
  const want = new URLSearchParams(location.hash.slice(1)).get("site");
  if (want && siteById(want)) selectSite(want, { instant: true });
  else setFlyout("sites");
  // the pipeline rebuilds catalog.json while the app is open: pick up new/updated sites on return to the tab
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && refreshCatalog());
  setInterval(refreshCatalog, 120000);
}

async function refreshCatalog() {
  try {
    const r = await fetch("data/catalog.json", { cache: "no-cache" });
    if (!r.ok) return;
    const cat = await r.json();
    if (cat.generated === state.catalog.generated) return;
    const open = state.site?.id;
    state.catalog = cat;
    renderFilters(); renderSiteList(); addMarkers();
    if (state.compare) state.markers.forEach(mk => (mk.getElement().style.display = "none"));
    const cur = open && siteById(open);
    if (cur && cur !== state.site) {   // the open site was reprocessed: reload it in place
      if (JSON.stringify(cur) !== JSON.stringify(state.site)) selectSite(open, { instant: true });
      else state.site = cur;
    }
    ui.toast(`Site data updated (${cat.sites.filter(s => !s.demo).length} of ${cat.sites.length} sites from NISAR data)`, 4000);
  } catch { /* offline or mid-write: try again next time */ }
}

// ------------------------------------------------------------------ tool rail & flyouts
// one flyout at a time next to the rail: "sites" | "layers" | null
function setFlyout(name) {
  if (name === "layers" && !state.site) name = null;
  state.flyout = name;
  $("sites-panel").hidden = name !== "sites";
  $("layer-panel").hidden = name !== "layers";
  $("btn-sites").classList.toggle("on", name === "sites");
  $("btn-layers").classList.toggle("on", name === "layers");
}
function syncRail() {
  const s = state.site, frames = s?.layers.frames?.items?.length || 0;
  $("btn-layers").disabled = !s;
  $("btn-compare").disabled = frames < 2;
}
const dataTag = s => s.demo
  ? `<span class="tag sim" title="Physics-based simulation made with the same processing chain; replaced when real NISAR data is processed">Simulated</span>`
  : `<span class="tag real" title="Processed from NISAR products downloaded from the ASF DAAC">NISAR data</span>`;
const siteById = id => state.catalog.sites.find(s => s.id === id);
const typeOf = s => TYPES[groupOf(s)] || { label: s.change_type, color: "#8f8e86" };

function renderFilters() {
  const box = $("filters");
  box.innerHTML = "";
  for (const f of FILTERS) {
    const n = f === "all" ? state.catalog.sites.length : state.catalog.sites.filter(s => groupOf(s) === f).length;
    if (!n && f !== "all") continue;
    const b = document.createElement("button");
    b.className = "chip" + (state.filter === f ? " on" : "");
    b.innerHTML = f === "all" ? `All <span class="muted">${n}</span>` : `<span class="dot" style="background:${TYPES[f].color}"></span>${TYPES[f].label}`;
    b.onclick = () => { state.filter = f; renderFilters(); renderSiteList(); addMarkers(); };
    box.appendChild(b);
  }
}
const visibleSites = () => state.catalog.sites.filter(s => state.filter === "all" || groupOf(s) === state.filter);

function renderSiteList() {
  const ul = $("site-list");
  ul.innerHTML = "";
  for (const s of visibleSites()) {
    const li = document.createElement("li");
    li.className = "site" + (state.site?.id === s.id ? " active" : "");
    li.tabIndex = 0;
    li.innerHTML = `<h4>${s.name}</h4><div class="meta"><span class="badge"><span class="dot" style="background:${typeOf(s).color}"></span>${typeOf(s).label}</span><span>${s.continent || ""}</span>${dataTag(s)}</div>
      <div class="headline">${s.story?.headline || ""}</div>`;
    li.onclick = () => selectSite(s.id);
    li.onkeydown = e => e.key === "Enter" && selectSite(s.id);
    ul.appendChild(li);
  }
}

function addMarkers() {
  state.markers.forEach(m => m.remove());
  state.markers = visibleSites().map(s => {
    const el = document.createElement("div");
    el.className = "site-marker";
    el.innerHTML = `<span class="pin" style="background:${typeOf(s).color}"></span><span class="lbl">${s.name}</span>`;
    el.title = s.story?.headline || s.name;
    el.onclick = e => { e.stopPropagation(); selectSite(s.id); };
    return new maplibregl.Marker({ element: el, anchor: "left" }).setLngLat(s.center).addTo(map);
  });
}

// ------------------------------------------------------------------ site layers
const corners = b => [[b[0], b[3]], [b[2], b[3]], [b[2], b[1]], [b[0], b[1]]];
const LAYER_IDS = [];

function clearSiteLayers(m) {
  for (const id of [...LAYER_IDS]) {
    if (m.getLayer(id)) m.removeLayer(id);
    if (m.getSource(id)) m.removeSource(id);
  }
}
function addImage(m, id, url, bounds, { opacity = 0.9, visible = true, nearest = false } = {}) {
  m.addSource(id, { type: "image", url, coordinates: corners(bounds) });
  m.addLayer({ id, type: "raster", source: id, layout: { visibility: visible ? "visible" : "none" },
    paint: { "raster-opacity": opacity, "raster-fade-duration": 0, "raster-resampling": nearest ? "nearest" : "linear" } }, "labels");
  if (!LAYER_IDS.includes(id)) LAYER_IDS.push(id);
}
function preload(urls) { for (const u of urls) { const i = new Image(); i.src = u; } }

function frameUrl(s, i) { return s.layers.frames?.items?.[i]?.url ? "data/" + s.layers.frames.items[i].url : null; }
function overlayUrl(s, o, i) {
  if (o.items?.length) {
    const date = s.layers.frames?.items?.[i]?.date;
    const hit = o.items.find(x => x.date === date) || o.items[Math.min(i, o.items.length - 1)];
    return "data/" + hit.url;
  }
  return "data/" + o.url;
}

function buildSiteLayers(m, s, frameIdx) {
  clearSiteLayers(m);
  const nFrames = s.layers.frames?.items?.length || 0;
  if (nFrames) addImage(m, "frame", frameUrl(s, frameIdx), s.bounds, { opacity: state.opacity.frame ?? 1, visible: state.visible.frame !== false });
  for (const o of s.layers.overlays || []) {
    addImage(m, "ov-" + o.id, overlayUrl(s, o, frameIdx), s.bounds, { opacity: state.opacity["ov-" + o.id] ?? 0.85,
      visible: !!state.visible["ov-" + o.id], nearest: o.legend?.type === "classes" });
  }
  // site outline
  m.addSource("site-box", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon", coordinates: [[...corners(s.bounds), corners(s.bounds)[0]]] } } });
  m.addLayer({ id: "site-box", type: "line", source: "site-box", paint: { "line-color": "#ffffff", "line-opacity": 0.6, "line-width": 1, "line-dasharray": [3, 2] } }, "labels");
  if (!LAYER_IDS.includes("site-box")) LAYER_IDS.push("site-box");
}

function whenStyle(m, fn) { ready.has(m) ? fn() : m.once("load", fn); }

// back to the world view: remove everything a site added
function closeSite() {
  if (!state.site) return;
  stop();
  if (state.compare) setCompare(false);
  state.popup?.remove();
  clearSiteLayers(map);
  if (mapB) clearSiteLayers(mapB);
  state.site = null;
  for (const id of ["timeline", "dashboard"]) $(id).hidden = true;
  history.replaceState(null, "", location.pathname + location.search);
  renderSiteList();
  syncRail();
  setFlyout("sites");
  ui.showHint();
  map.flyTo({ ...HOME, duration: 1500 });
}

async function selectSite(id, { instant = false } = {}) {
  const s = siteById(id);
  if (!s) return;
  state.explore?.close();
  state.popup?.remove();
  stop();
  state.site = s;
  state.cube = null;
  state.frame = 0;
  state.visible = { frame: true };
  state.opacity = {};
  for (const o of s.layers.overlays || []) state.visible["ov-" + o.id] = !!o.default;
  // for floods start on the peak, so the first view already tells the story
  const peak = s.stats?.find(t => /^Peak/.test(t.label))?.note;
  if (peak && s.layers.frames?.items?.length) {
    const idx = s.layers.frames.items.findIndex(f => new Date(f.date + "T00:00:00Z").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }) === peak);
    if (idx >= 0) state.frame = idx;
  }
  // cumulative products (subsidence) tell their story at the end of the series
  if (s.layers.frames?.kind === "diverging") state.frame = s.layers.frames.items.length - 1;
  history.replaceState(null, "", `#site=${id}`);
  renderSiteList();
  state.markers.forEach(mk => (mk.getElement().style.display = ""));
  ui.hideHint();
  whenStyle(map, () => buildSiteLayers(map, s, state.frame));
  preload((s.layers.frames?.items || []).map(f => "data/" + f.url));
  for (const o of s.layers.overlays || []) preload((o.items || []).map(f => "data/" + f.url));
  renderLayerPanel();
  renderTimeline();
  renderDashboard();
  if (state.compare) setCompare(false);
  syncRail();
  setFlyout("layers");
  // fit only after the dashboard has taken its width, or the box ends up under it
  map.resize();
  const b = s.bounds;
  const left = 76 + Math.min(290, $("map").clientWidth * 0.3);   // room for rail + layer flyout without squeezing narrow maps
  map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: { top: 60, bottom: 100, left, right: 40 }, duration: instant ? 0 : 2200, maxZoom: 12 });
}

function setFrame(i) {
  const s = state.site;
  if (!s) return;
  const n = s.layers.frames?.items?.length || 0;
  if (!n) return;
  state.frame = ((i % n) + n) % n;
  map.getSource("frame")?.updateImage({ url: frameUrl(s, state.frame), coordinates: corners(s.bounds) });
  for (const o of s.layers.overlays || []) if (o.items?.length) map.getSource("ov-" + o.id)?.updateImage({ url: overlayUrl(s, o, state.frame), coordinates: corners(s.bounds) });
  $("time-slider").value = state.frame;
  $("time-label").textContent = fmtLong(s.layers.frames.items[state.frame].date);
  if (state.compare) $("swipe-right").textContent = afterLabel(s);
}
// "After" label carries the real interval: a dropped pass makes it 24 or 36 days, not 12
function afterLabel(s) {
  const it = s.layers.frames.items, a = it[0].date, b = it[state.frame].date;
  const days = Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 86400000);
  return `After · ${fmtLong(b)}${days > 0 ? ` · ${days} days later` : ""}`;
}
const fmtLong = d => new Date(d + "T00:00:00Z").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

function play() {
  if (state.playing) return stop();
  const n = state.site?.layers.frames?.items?.length || 0;
  if (n < 2) return;
  $("btn-play").textContent = "❚❚";
  $("btn-play").setAttribute("aria-label", "Pause");
  const tick = () => { setFrame(state.frame + 1); state.playing = setTimeout(tick, +$("speed").value); };
  state.playing = setTimeout(tick, 50);
}
function stop() {
  clearTimeout(state.playing); state.playing = null;
  $("btn-play").textContent = "▶"; $("btn-play").setAttribute("aria-label", "Play time-lapse");
}

// ------------------------------------------------------------------ layer panel & legend
function renderLayerPanel() {
  const s = state.site, list = $("layer-list");
  list.innerHTML = "";
  const rows = [];
  if (s.layers.frames?.items?.length) rows.push({ id: "frame", name: s.layers.frames.title || (s.layers.frames.kind === "rgb" ? "Radar image (HH·HV false colour)" : "Radar time-lapse"), legend: s.layers.frames.legend });
  for (const o of s.layers.overlays || []) rows.push({ id: "ov-" + o.id, name: o.name, legend: o.legend });
  for (const r of rows) {
    const d = document.createElement("div");
    d.className = "layer";
    const on = state.visible[r.id] !== false && (r.id === "frame" || state.visible[r.id]);
    d.innerHTML = `<input type="checkbox" id="chk-${r.id}" ${on ? "checked" : ""}><label for="chk-${r.id}">${r.name}</label>
      <input type="range" min="0" max="1" step="0.05" value="${state.opacity[r.id] ?? (r.id === "frame" ? 1 : 0.85)}" aria-label="Opacity of ${r.name}">`;
    d.querySelector("input[type=checkbox]").onchange = e => {
      state.visible[r.id] = e.target.checked;
      for (const m of [map, mapB]) if (m?.getLayer(r.id)) m.setLayoutProperty(r.id, "visibility", e.target.checked ? "visible" : "none");
      renderLegend(rows);
    };
    d.querySelector("input[type=range]").oninput = e => {
      state.opacity[r.id] = +e.target.value;
      for (const m of [map, mapB]) if (m?.getLayer(r.id)) m.setPaintProperty(r.id, "raster-opacity", +e.target.value);
    };
    list.appendChild(d);
  }
  renderLegend(rows);
}

function legendHTML(lg) {
  if (!lg) return "";
  if (lg.type === "classes" || lg.type === "rgb")
    return lg.items.map(i => `<div class="item"><span class="sw" style="background:${i.color}"></span>${i.label}</div>`).join("");
  // pipelines write either vmin/vmax + named colours, or min/max + items; accept both
  const lo = lg.vmin ?? lg.min, hi = lg.vmax ?? lg.max, unit = lg.unit || "";
  const num = v => (v == null ? "" : `${v} ${unit}`.trim());
  if (lg.type === "diverging") {
    const it = lg.items || [];
    const cols = [lg.neg ?? it[0]?.color ?? "#eb6834", lg.mid ?? it[1]?.color ?? "#d9d8d4", lg.pos ?? it.at(-1)?.color ?? "#2a78d6"];
    return `<div class="bar" style="background:linear-gradient(90deg,${cols.join(",")})"></div>
      <div class="ends"><span>${num(lo)}</span><span>0</span><span>${hi == null ? "" : "+" + num(hi)}</span></div>
      <div class="ends"><span>${lg.neg_label ?? it[0]?.label ?? ""}</span><span>${lg.pos_label ?? it.at(-1)?.label ?? ""}</span></div>`;
  }
  if (lg.type === "sequential") {
    const ramp = lg.ramp || ["#0d366b", "#2a78d6", "#cde2fb"];
    const end = lg.start_date ? `+${hi} d` : num(hi);
    return `<div class="bar" style="background:linear-gradient(90deg,${ramp.join(",")})"></div><div class="ends"><span>${lg.start_date || num(lo)}</span><span>${end}</span></div>`;
  }
  if (lg.type === "gray")
    return `<div class="bar" style="background:linear-gradient(90deg,#000,#fff)"></div><div class="ends"><span>${lo} dB</span><span>${hi} dB</span></div>`;
  if (lg.type === "cyclic")
    return `<div class="bar" style="background:linear-gradient(90deg,#e1d8e1,#9a6fbd,#2f1436,#c06a3e,#e1d8e1)"></div><div class="ends"><span>0</span><span>${lg.period_cm ? lg.period_cm + " cm" : "one full cycle"}</span></div>${lg.note ? `<div class="muted">${lg.note}</div>` : ""}`;
  return "";
}
function renderLegend(rows) {
  $("legend").innerHTML = rows.filter(r => r.id === "frame" ? state.visible.frame !== false : state.visible[r.id])
    .map(r => `<div class="ttl">${r.name}</div>${legendHTML(r.legend)}`).join("");
}

// ------------------------------------------------------------------ timeline & compare
function renderTimeline() {
  const n = state.site.layers.frames?.items?.length || 0;
  $("timeline").hidden = n < 2;
  if (n < 2) return;
  const sl = $("time-slider");
  sl.max = n - 1; sl.value = state.frame;
  $("time-label").textContent = fmtLong(state.site.layers.frames.items[state.frame].date);
}

function setCompare(on) {
  const s = state.site;
  state.compare = on && (s?.layers.frames?.items?.length || 0) >= 2;
  $("btn-compare").classList.toggle("on", state.compare);
  $("btn-compare").setAttribute("aria-pressed", String(state.compare));
  $("map-compare").hidden = !state.compare;
  $("swipe").hidden = !state.compare;
  state.markers.forEach(mk => (mk.getElement().style.display = state.compare ? "none" : ""));   // keep labels off the swipe handle
  if (!state.compare) { setFlyout("layers"); return; }
  if (!mapB) {
    mapB = new maplibregl.Map({ container: "map-compare", style: structuredClone(STYLE), center: map.getCenter(), zoom: map.getZoom(), attributionControl: false, interactive: true });
    const b = mapB;
    b.once("load", () => ready.add(b));
    if (state.globe) b.once("load", () => b.setProjection({ type: "globe" }));
    syncMaps(map, mapB);
  }
  mapB.resize();   // it was display:none; a stale size would drag the synced main map off-centre
  mapB.jumpTo({ center: map.getCenter(), zoom: map.getZoom() });
  whenStyle(mapB, () => {
    setBasemap(mapB, state.basemap);
    buildSiteLayers(mapB, s, 0);   // left = first acquisition (before)
  });
  $("swipe-left").textContent = fmtLong(s.layers.frames.items[0].date) + " · Before";
  $("swipe-right").textContent = afterLabel(s);
  if (state.frame === 0) setFrame(s.layers.frames.items.length - 1);
  // zoom so the site box fills the view; the comparison happens inside it
  state.swipeFrac = 0.5;
  setFlyout(null);
  const b = s.bounds;
  // instant: mapB's async resize would otherwise interrupt an animated fit via the map sync
  map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: { top: 60, bottom: 80, left: 20, right: 20 }, duration: 0 });
  updateSwipe();
}
// site box in map-container pixels, clamped to what is on screen
function siteBoxPx() {
  const [w, so, e, n] = state.site.bounds, a = map.project([w, n]), c = map.project([e, so]);
  const W = $("map").clientWidth, H = $("map").clientHeight;
  return { l: Math.max(0, a.x), r: Math.min(W, c.x), t: Math.max(0, a.y), b: Math.min(H, c.y), W, H };
}
// swipe line and "before" map are confined to the site box
function updateSwipe() {
  if (!state.compare || !state.site) return;
  const k = siteBoxPx(), x = k.l + (k.r - k.l) * state.swipeFrac;
  Object.assign($("swipe").style, { left: x + "px", top: k.t + "px", height: Math.max(0, k.b - k.t) + "px", bottom: "auto" });
  $("map-compare").style.clipPath = `inset(${k.t}px ${k.W - x}px ${k.H - k.b}px ${k.l}px)`;
}
function positionSwipe(x) {
  const k = siteBoxPx();
  state.swipeFrac = Math.max(0, Math.min(1, (x - k.l) / ((k.r - k.l) || 1)));
  updateSwipe();
}
function syncMaps(a, b) {
  let lock = false;
  const sync = (src, dst) => () => { if (lock) return; lock = true; dst.jumpTo({ center: src.getCenter(), zoom: src.getZoom(), bearing: src.getBearing(), pitch: src.getPitch() }); lock = false; };
  a.on("move", sync(a, b)); b.on("move", sync(b, a));
}

// ------------------------------------------------------------------ basemap / projection
function setBasemap(m, mode) {
  if (!m?.getLayer("optical")) return;
  m.setLayoutProperty("optical", "visibility", mode === "optical" ? "visible" : "none");
  m.setLayoutProperty("dark", "visibility", mode === "optical" ? "none" : "visible");
}

// ------------------------------------------------------------------ click -> pixel time series
const mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
async function pixelQuery(e) {
  const s = state.site;
  if (!s?.layers.cube) return;
  const [w, so, ea, n] = s.bounds, { lng, lat } = e.lngLat;
  if (lng < w || lng > ea || lat < so || lat > n) return;
  if (!state.cube) state.cube = await (await fetch("data/" + s.layers.cube)).json();
  const c = state.cube, [cy, cx] = c.shape;
  const col = Math.min(cx - 1, Math.floor((lng - w) / (ea - w) * cx));
  const row = Math.min(cy - 1, Math.floor((mercY(n) - mercY(lat)) / (mercY(n) - mercY(so)) * cy));
  const vals = c.data.map(fr => fr[row][col] == null ? null : fr[row][col] / c.scale);
  const t = Math.min(state.frame, vals.length - 1);
  state.popup?.remove();
  state.popup = new maplibregl.Popup({ closeButton: true, maxWidth: "260px" }).setLngLat(e.lngLat)
    .setHTML(`<b>${c.var}: ${vals[t] == null ? "no data" : vals[t].toFixed(1) + " " + c.unit}</b><br>${lat.toFixed(4)}°, ${lng.toFixed(4)}°<br><span style="color:#52514e">${c.dates[t]}${vals.length > 1 ? " · time series added to dashboard" : ""}</span>`).addTo(map);
  if (vals.length > 1) {
    const box = $("pixel-chart");
    box.innerHTML = "";
    lineChart(box, { title: `Clicked point · ${c.var}`, unit: c.unit, dates: c.dates,
      series: [{ name: `${lat.toFixed(3)}, ${lng.toFixed(3)}`, values: vals, color: "#2a78d6" }] }, { highlightDate: s.event_date?.slice(0, 10) });
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// ------------------------------------------------------------------ dashboard
function renderDashboard() {
  const s = state.site, st = s.story || {}, d = $("dash-body");
  $("dashboard").hidden = false;
  const tiles = (s.stats || []).map(t => `<div class="tile"><div class="v">${typeof t.value === "number" ? t.value.toLocaleString() : t.value}<small>${t.unit || ""}</small></div>
    <div class="l">${t.label}</div>${t.note ? `<div class="n">${t.note}</div>` : ""}</div>`).join("");
  const stk = s.stack || {};
  const prov = s.demo
    ? `<b style="color:#ffd27a">Synthetic demo layer.</b> Generated by <code>scripts/make_demo_data.py</code> with the same processing chain; replace by running <code>python -m nisar_pulse run --site ${s.id}</code>.`
    : `NISAR ${s.band || "L"}-band <code>${s.product}</code> · track ${stk.track ?? "?"} · frame ${stk.frame ?? "?"} · ${stk.direction === "A" ? "ascending" : stk.direction === "D" ? "descending" : "?"} · ${stk.n ?? "?"} products`;
  d.innerHTML = `
    <h2>${st.headline || s.name}</h2>
    <div class="sub">${dataTag(s)}<span class="badge"><span class="dot" style="background:${typeOf(s).color}"></span>${typeOf(s).label}</span>
      <span>${s.name}</span><span>${s.region || ""}</span>${s.date_range ? `<span>${fmtLong(s.date_range[0])} → ${fmtLong(s.date_range[1])}</span>` : ""}</div>
    <div class="tiles">${tiles}</div>
    <h3>Change over time</h3><div id="charts"></div><div id="pixel-chart"><p class="muted">Click anywhere inside the dashed box for that point's radar time series.</p></div>
    <h3>What am I seeing?</h3>
    <div class="story">
      ${st.what ? `<p><b>What changed.</b> ${st.what}</p>` : ""}
      ${st.physics ? `<p><b>Radar physics.</b> ${st.physics}</p>` : ""}
      ${st.drivers ? `<p><b>Likely drivers.</b> ${st.drivers}</p>` : ""}
      ${st.caveats ? `<p><b>Caveats.</b> ${st.caveats}</p>` : ""}
      ${s.s_band ? `<p><b>Dual frequency.</b> NISAR S-band (ISRO Bhoonidhi) covers this area — compare canopy-sensitive S-band with ground-reaching L-band.</p>` : ""}
    </div>
    <h3>Data provenance</h3><p class="prov">${prov}${s.excluded_dates?.length ? `<br>Quality-excluded dates: ${s.excluded_dates.map(e => `${e.date} (${e.reason})`).join("; ")}` : ""}<br>Downloads: ${downloadLinks(s)}</p>
    ${s.sources?.length ? `<details class="prov sources"><summary>NASA source files (${s.sources.length}) — ASF DAAC</summary>
      <ol>${s.sources.map(f => `<li><a href="${f.url}" target="_blank" rel="noopener" title="Official download (Earthdata login)">${f.name}</a></li>`).join("")}</ol></details>` : ""}`;
  const charts = $("charts");
  for (const c of s.charts || []) renderChart(charts, c, { highlightDate: s.event_date?.slice(0, 10) });
}
function downloadLinks(s) {
  const L = [];
  if (s.layers.cube) L.push(`<a href="data/${s.layers.cube}" download>time-series cube (JSON)</a>`);
  for (const o of s.layers.overlays || []) L.push(`<a href="data/${o.url || o.items?.at(-1)?.url}" download>${o.id}</a>`);
  L.push(`<a href="data/sites/${s.id}/site.json" download>metadata</a>`);
  return L.join(" · ");
}

// ------------------------------------------------------------------ wiring
function wireControls() {
  $("btn-play").onclick = play;
  $("time-slider").oninput = e => { stop(); setFrame(+e.target.value); };
  $("btn-compare").onclick = () => setCompare(!state.compare);
  $("dash-close").onclick = closeSite;
  $("toast").onclick = e => { e.currentTarget.hidden = true; };
  $("btn-about").onclick = () => $("about").showModal();
  $("about").onclick = e => { if (e.target === e.currentTarget) e.currentTarget.close(); };   // click outside closes
  // tool rail
  $("btn-zoom-in").onclick = () => map.zoomIn();
  $("btn-zoom-out").onclick = () => map.zoomOut();
  $("btn-sites").onclick = () => setFlyout(state.flyout === "sites" ? null : "sites");
  $("btn-layers").onclick = () => setFlyout(state.flyout === "layers" ? null : "layers");
  $("btn-home").onclick = () => { state.explore?.close(); if (state.site) closeSite(); else { map.flyTo({ ...HOME, duration: 1200 }); setFlyout("sites"); } };
  $("btn-fullscreen").onclick = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.();
  document.addEventListener("fullscreenchange", () => $("btn-fullscreen").classList.toggle("on", !!document.fullscreenElement));
  for (const b of document.querySelectorAll("[data-close]")) b.onclick = () => setFlyout(null);
  $("btn-basemap").onclick = e => {
    state.basemap = state.basemap === "dark" ? "optical" : "dark";
    const other = state.basemap === "dark" ? "optical" : "dark";   // the tile previews what you switch *to*
    e.currentTarget.dataset.to = other;
    e.currentTarget.querySelector(".lbl").textContent = other === "optical" ? "Optical" : "Dark map";
    setBasemap(map, state.basemap); setBasemap(mapB, state.basemap);
  };
  $("btn-globe").onclick = e => {
    state.globe = !state.globe;
    try { for (const m of [map, mapB]) m?.setProjection({ type: state.globe ? "globe" : "mercator" }); e.currentTarget.classList.toggle("on", state.globe); }
    catch { ui.toast("Globe view needs MapLibre GL v5+"); }
  };
  // swipe drag
  let dragging = false;
  $("swipe").addEventListener("pointerdown", e => { dragging = true; e.target.setPointerCapture?.(e.pointerId); });
  window.addEventListener("pointermove", e => { if (dragging) positionSwipe(e.clientX - $("map").getBoundingClientRect().left); });
  window.addEventListener("pointerup", () => (dragging = false));
  window.addEventListener("resize", updateSwipe);
  map.on("move", updateSwipe);   // keep the swipe glued to the site box while panning/zooming
  map.on("click", e => { if (!$("explore-panel").hidden) return; pixelQuery(e); });
  document.addEventListener("keydown", e => {
    // Esc backs out one level: dialog (native) → explore → compare → site
    if (e.key === "Escape") {
      if ($("about").open) return;
      if (state.explore?.isOpen()) state.explore.close();
      else if (state.compare) setCompare(false);
      else if (state.site) closeSite();
      else setFlyout(null);
      return;
    }
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
    if (!state.site) return;
    if (e.code === "Space") { e.preventDefault(); play(); }
    if (e.key === "ArrowRight") { stop(); setFrame(state.frame + 1); }
    if (e.key === "ArrowLeft") { stop(); setFrame(state.frame - 1); }
  });
  window.addEventListener("hashchange", () => {
    const id = new URLSearchParams(location.hash.slice(1)).get("site");
    if (id && id !== state.site?.id) selectSite(id);
    else if (!id) closeSite();
  });
}

init();
