/* BlackBox web UI — vanilla JS, hand-drawn SVG charts. */
"use strict";

// ---------------------------------------------------------------- utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nf = new Intl.NumberFormat("tr-TR");
const num = (v, d = 0) => (v == null || Number.isNaN(v) ? "–" : new Intl.NumberFormat("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v));
const ratio = (k, d) => (k == null ? "–" : d ? num(k / d, 2) : `${k}/0`);
const pct = (a, b) => (b ? `%${Math.round((100 * a) / b)}` : "–");
const mmss = (s) => (s == null ? "–" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);
const dt = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "–");
const day = (iso) => {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" }) + " " + iso.slice(11, 16);
};
const resultTag = (r) => (r === "win" ? '<span class="tag win">Zafer</span>' : r === "loss" ? '<span class="tag loss">Yenilgi</span>' : '<span class="tag none">Bilinmiyor</span>');
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

async function api(path, params) {
  // several player profiles: every request names the selected one
  if (state.players && state.players.length > 1) params = { ...(params || {}), player: state.player };
  const q = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString() : "";
  const r = await fetch(`/api/${path}${q}`);
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}

// tooltip
const tip = $("#tip");
function showTip(html, e) {
  tip.innerHTML = html;
  tip.classList.add("on");
  const x = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8);
  const y = e.clientY + 16 + tip.offsetHeight > innerHeight ? e.clientY - tip.offsetHeight - 10 : e.clientY + 16;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
const hideTip = () => tip.classList.remove("on");
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest("[data-tip]");
  if (t) showTip(t.dataset.tip, e); else if (!e.target.closest("[data-tip-live]")) hideTip();
});

// ---------------------------------------------------------------- state
const state = { filters: store.get("bb-filters", { type: "air" }), player: "" };

function setTheme(name) {
  document.documentElement.dataset.theme = name;
  try { localStorage.setItem("bb-theme", name); } catch { /* ignore */ }
  $$(".themes button").forEach((b) => b.classList.toggle("on", b.dataset.themeSet === name));
}

// ---------------------------------------------------------------- filters UI
async function loadFilterOptions() {
  const f = state.filters;
  const o = await api("filters", { type: f.type });
  const sv = $("#fVehicle"), sm = $("#fMap");
  sv.innerHTML = '<option value="">Tüm araçlar</option>' + o.vehicles.map((v) => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join("");
  sm.innerHTML = '<option value="">Tüm haritalar</option>' + o.maps.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
  if (f.vehicle && !o.vehicles.some((v) => v.id === f.vehicle)) delete f.vehicle;
  if (f.map && !o.maps.includes(f.map)) delete f.map;
  sv.value = f.vehicle || "";
  sm.value = f.map || "";
  $("#fLast").value = f.last || "";
  $("#fSince").value = f.since || "";
  $$("#typeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.type === (f.type || "air")));
}

function bindFilters() {
  const changed = async (refreshOptions) => {
    store.set("bb-filters", state.filters);
    if (refreshOptions) await loadFilterOptions();
    route();
  };
  $$("#typeSeg button").forEach((b) => b.addEventListener("click", () => {
    state.filters = { ...state.filters, type: b.dataset.type };
    delete state.filters.vehicle; delete state.filters.map;
    changed(true);
  }));
  $("#fVehicle").addEventListener("change", (e) => { state.filters.vehicle = e.target.value || undefined; changed(); });
  $("#fMap").addEventListener("change", (e) => { state.filters.map = e.target.value || undefined; changed(); });
  $("#fLast").addEventListener("change", (e) => { state.filters.last = e.target.value || undefined; changed(); });
  $("#fSince").addEventListener("change", (e) => { state.filters.since = e.target.value || undefined; changed(); });
  $("#fReset").addEventListener("click", () => { state.filters = { type: "air" }; changed(true); });
}

// ---------------------------------------------------------------- building blocks
let panelIdx = 0;
function panel(title, body, { cls = "c12", aside = "", flush = false } = {}) {
  panelIdx += 1;
  return `<section class="panel ${cls}">
    <header class="panel-h"><span class="idx">${String(panelIdx).padStart(2, "0")}</span><h2>${esc(title)}</h2>${aside ? `<span class="aside">${aside}</span>` : ""}</header>
    <div class="panel-b${flush ? " flush" : ""}">${body}</div></section>`;
}

function kpis(items) {
  return `<div class="kpis">${items.map((k) => `<div class="kpi${k.hl ? " hl" : ""}">
    <div class="kpi-label">${esc(k.label)}</div>
    <div class="kpi-value">${k.unit === "%" && k.value !== "–" ? `<small>%</small>` : ""}${k.value}${k.unit && k.unit !== "%" ? `<small>${esc(k.unit)}</small>` : ""}</div>
    ${k.sub ? `<div class="kpi-sub">${k.sub}</div>` : ""}</div>`).join("")}</div>`;
}

function barList(items, { cls = "", fmt = (it, total) => `<b>${it.n}</b> · ${pct(it.n, total)}`, max } = {}) {
  if (!items.length) return '<div class="dim">Veri yok.</div>';
  const total = items.reduce((a, b) => a + b.n, 0);
  const top = max ?? Math.max(...items.map((i) => i.n));
  return `<div class="bars">${items.map((it) => `
    <div class="lab" title="${esc(it.name)}">${esc(it.name)}</div>
    <div class="track"><div class="fill ${it.cls || cls}" style="width:${top ? (100 * it.n) / top : 0}%"></div></div>
    <div class="val">${fmt(it, total)}</div>`).join("")}</div>`;
}

function empty(title, text) {
  return `<div class="empty"><strong>${esc(title)}</strong>${text}</div>`;
}

// vertical bar chart (svg)
function columnChart(data, { h = 170, cls = "", valueFmt = (v) => v, labelEvery = 1 } = {}) {
  const W = 600, pad = { l: 28, r: 6, t: 10, b: 24 };
  const max = Math.max(1, ...data.map((d) => d.v));
  const iw = W - pad.l - pad.r, ih = h - pad.t - pad.b;
  const bw = iw / data.length;
  const ticks = niceTicks(max, 4);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img">`;
  for (const t of ticks) {
    const y = pad.t + ih - (ih * t) / ticks[ticks.length - 1];
    s += `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}"/><text x="${pad.l - 6}" y="${y + 3}" text-anchor="end">${t}</text>`;
  }
  const top = ticks[ticks.length - 1];
  data.forEach((d, i) => {
    const bh = (ih * d.v) / top;
    const x = pad.l + i * bw + bw * 0.18;
    s += `<rect class="bar ${d.cls || cls}" x="${x}" y="${pad.t + ih - bh}" width="${bw * 0.64}" height="${Math.max(bh, d.v ? 1 : 0)}" data-tip="${esc(d.tip || `${d.label}: ${valueFmt(d.v)}`)}"/>`;
    if (i % labelEvery === 0) s += `<text x="${pad.l + i * bw + bw / 2}" y="${h - 8}" text-anchor="middle">${esc(d.label)}</text>`;
  });
  s += `<line class="axis" x1="${pad.l}" x2="${W - pad.r}" y1="${pad.t + ih}" y2="${pad.t + ih}"/></svg>`;
  return s;
}

function niceTicks(max, n) {
  const raw = max / n;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag;
  const out = [];
  for (let v = 0; v <= max + step * 0.999; v += step) out.push(Math.round(v * 100) / 100);
  return out.length > 1 ? out : [0, 1];
}

function formStrip(form) {
  if (!form.length) return "";
  const bars = form.map((b) => {
    const lp = b.lobby == null ? 0.5 : b.lobby;
    const h = 12 + 52 * (1 - lp);
    const cls = b.result === "win" ? "win" : b.result === "loss" ? "loss" : "";
    const t = `${day(b.started)} · ${b.result === "win" ? "zafer" : b.result === "loss" ? "yenilgi" : "sonuç ?"}<br>K ${b.kills ?? "–"} / Ö ${b.deaths ?? "–"} · skor ${b.score ?? "–"}<br>lobi dilimi %${Math.round(100 * lp)}`;
    return `<a href="#/mac/${b.session_id}" class="${cls}" style="height:${h}px" data-tip="${esc(t)}"></a>`;
  }).join("");
  return `<div class="form-strip">${bars}</div>
    <div class="form-legend"><span>Yükseklik = lobideki sıralaman (uzun = üst sıralar)</span>
    <span><i class="sw" style="background:var(--win)"></i>Zafer</span><span><i class="sw" style="background:var(--loss)"></i>Yenilgi</span>
    <span><i class="sw" style="background:var(--neutral)"></i>Sonuç metni yok</span></div>`;
}

function compareTable(lob, kind = "air") {
  const rows = [["Sen", lob.me, "me"], ["Lobi ortalaması", lob.lobby, ""], ["Her maçın ilk 3'ü", lob.top3, ""]];
  const metrics = [
    ["Ort. skor", (r) => r.score, (v) => num(v)],
    ["K/D", (r) => (r.k == null ? null : r.d ? r.k / r.d : r.k), (v) => num(v, 2)],
    kind === "ground" ? ["Kill / maç", (r) => r.kpm, (v) => num(v, 2)] : ["Füzeden kaçış / maç", (r) => r.ev, (v) => num(v, 2)],
    ["Asist / maç", (r) => r.a, (v) => num(v, 2)],
  ];
  let s = `<table class="compare"><thead><tr><th></th>${metrics.map((m) => `<th>${m[0]}</th>`).join("")}</tr></thead><tbody>`;
  for (const [label, r, cls] of rows) {
    s += `<tr class="${cls}"><td class="who">${label}</td>`;
    for (const [, get, f] of metrics) {
      const max = Math.max(...rows.map((x) => get(x[1]) || 0)) || 1;
      const v = get(r);
      s += `<td><div class="cbar"><div class="track"><div class="fill" style="width:${(100 * (v || 0)) / max}%"></div></div><span class="v">${f(v)}</span></div></td>`;
    }
    s += "</tr>";
  }
  return s + "</tbody></table>";
}

// sortable table
function dataTable(cols, rows, { key, onRow, sortKey, desc = true, id = "t" } = {}) {
  const sorted = sortKey ? [...rows].sort((a, b) => cmp(a[sortKey], b[sortKey]) * (desc ? -1 : 1)) : rows;
  const head = cols.map((c) => `<th class="${c.n ? "n " : ""}${c.sort !== false ? "sortable " : ""}${sortKey === c.k ? "sorted" + (desc ? "" : " asc") : ""}" data-k="${c.k}">${esc(c.h)}</th>`).join("");
  const body = sorted.map((r) => `<tr class="${onRow ? "link " : ""}${r._cls || ""}" ${key ? `data-key="${esc(r[key])}"` : ""}>${cols.map((c) => `<td class="${c.n ? "n " : ""}${c.cls || ""}">${c.f ? c.f(r) : esc(r[c.k] ?? "–")}</td>`).join("")}</tr>`).join("");
  return `<div class="tbl-wrap"><table class="data" data-table="${id}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
const cmp = (a, b) => (a == null && b == null ? 0 : a == null ? -1 : b == null ? 1 : typeof a === "string" ? a.localeCompare(b, "tr") : a - b);

function mountTable(container, cols, rows, opts) {
  const st = { sortKey: opts.sortKey, desc: opts.desc ?? true };
  const draw = () => {
    container.innerHTML = dataTable(cols, rows, { ...opts, ...st });
    $$("th.sortable", container).forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      st.desc = st.sortKey === k ? !st.desc : true;
      st.sortKey = k;
      draw();
    }));
    if (opts.onRow) $$("tbody tr", container).forEach((tr) => tr.addEventListener("click", () => opts.onRow(tr.dataset.key)));
  };
  draw();
}

// ---------------------------------------------------------------- pages
async function pageSummary(view) {
  const [s, sk] = await Promise.all([api("summary", state.filters), api("skills", state.filters).catch(() => null)]);
  const t = s.totals;
  const ground = s.kind === "ground";
  const known = (t.w || 0) + (t.l || 0);
  $("#fCount").textContent = `${t.n} maç`;
  if (!t.n) {
    view.innerHTML = `<div class="grid">${panel("Veri yok", empty("Bu filtreyle maç bulunamadı.", "Filtreleri sıfırla ya da sağ üstten <b>İçe aktar</b>'a bas."))}</div>`;
    return;
  }
  const lobbyPct = t.lobby == null ? "–" : `%${Math.round(100 * t.lobby)}`;
  const tel = s.telemetry;
  view.innerHTML = `
  <div class="page-title"><h1>Özet</h1><span class="meta">${t.n} maç · ${t.nres || 0} sonuç metni · ${tel.n || 0} telemetrili uçuş</span></div>
  <div class="grid">
    <section class="panel c12">${kpis([
      { label: "Maç", value: num(t.n), sub: `${t.w || 0} Z · ${t.l || 0} Y · ${t.n - known} ?` },
      { label: "Kazanma oranı", value: known ? Math.round((100 * t.w) / known) : "–", unit: known ? "%" : "", sub: `${known} sonucu bilinen maçta` },
      { label: "K/D", value: ratio(t.k || 0, t.d), sub: `${t.k || 0} kill · ${t.d || 0} ölüm`, hl: true },
      ...(ground || !t.nbases ? [] : [{ label: "Üs / maç", value: num((t.bases || 0) / t.nbases, 1), sub: `${t.bases || 0} üs · ${t.nbase_battles || 0} maçta`, hl: true }]),
      { label: "Ortalama skor", value: num(t.score), sub: `asist ${t.a || 0}` },
      { label: "Lobi dilimi", value: lobbyPct, sub: "0 = lobinin en iyisi" },
      ground
        ? { label: "Kill / maç", value: num((t.k || 0) / t.n, 1), sub: `kara ${t.gk || 0} · hava ${(t.k || 0) - (t.gk || 0)}` }
        : { label: "Füzeden kaçış", value: num((t.ev || 0) / t.n, 1), unit: "/maç", sub: `toplam ${t.ev || 0}` },
      { label: "SL / maç", value: num(t.sl), sub: t.nres ? `${num(t.sl_min)} SL/dk · ${t.nres} maçtan` : "sonuç metni yok" },
      { label: "RP / maç", value: num(t.rp), sub: t.nres ? `${num(t.rp_min)} RP/dk · ${t.nres} maçtan` : "sonuç metni yok" },
    ])}</section>
    ${panel("Son maçlar", formStrip(s.form), { cls: "c12", aside: `son ${s.form.length}`, flush: true })}
    ${sk ? panel("Güçlü ve zayıf yönler", findingList(topFindings(sk.findings), { compact: true }), { cls: "c12", aside: `<a href="#/beceri">tüm analiz →</a>` }) : ""}
    ${panel("Lobiyle kıyas", compareTable(s.lobby, s.kind) + `<p class="note">Aynı maçlardaki diğer ${Math.round(s.lobby.others || 0)} oyuncuya göre (maç başına ortalama). Lobi ortalaması iki takımı da kapsar.${ground ? " Kill = kara + hava." : ""}</p>`, { cls: "c7" })}
    ${panel("Ne zaman ölüyorsun", columnChart(s.death_timing.map((d) => ({ label: d.label, v: d.n, tip: `${d.label}. dakika: ${d.n} ölüm` })), { cls: "acc" }) + '<p class="note">Maç başından itibaren dakika. Replay verisinden.</p>', { cls: "c5" })}
    ${panel("Seni düşüren silahlar", barList(s.death_weapons, { cls: "loss" }), { cls: "c6", aside: '<a href="#/silahlar">tümü →</a>' })}
    ${panel("Kill aldığın silahlar", barList(s.kill_weapons, { cls: "acc" }), { cls: "c6", aside: "oyuncular + AI hedefler" })}
    ${tel.n ? panel("Uçuş verisi", kpis([
      { label: "Ort. irtifa", value: num(tel.alt), unit: " m" },
      { label: "Ort. hız", value: num(tel.tas), unit: " km/h" },
      { label: "Ort. maks G", value: num(tel.max_g, 1) },
      { label: "300 m altı", value: num((tel.low || 0) * 100), unit: "%" },
      { label: "İsabet anı irtifa", value: num(tel.death_alt), unit: " m" },
      { label: "En yakın düşman", value: num(tel.death_enemy_km, 1), unit: " km", sub: "ilk isabet anında, minimapte" },
    ]), { cls: "c12", aside: `${tel.n} telemetrili yaşam`, flush: true }) : ""}
    ${panel("Son 10 maç", '<div id="recentT"></div>', { cls: "c12", flush: true, aside: '<a href="#/maclar">tümü →</a>' })}
  </div>`;
  mountTable($("#recentT", view), battleCols(), s.recent, { key: "session_id", onRow: (k) => (location.hash = `#/mac/${k}`) });
}

// main page: the two most important weak points and the two most important strengths (notes fill gaps)
function topFindings(fs) {
  const weak = fs.filter((f) => f.kind === "weak").slice(0, 2);
  const good = fs.filter((f) => f.kind !== "weak").slice(0, 4 - weak.length);
  return [...weak, ...good].slice(0, 4);
}

function basesCell(r) {
  if (r.bases_est == null) return '<span class="dim">–</span>';
  return r.has_result ? `${r.bases_est}` : `<span class="dim" title="Sonuç metni yok: üs hasarından tahmin">≈</span>${r.bases_est}`;
}

function battleCols() {
  const ground = state.filters.type === "ground";
  return [
    { h: "Tarih", k: "started", f: (r) => `<span class="num">${dt(r.started)}</span>` },
    { h: "Harita", k: "map" },
    { h: "Araç", k: "vehicle_name" },
    { h: "Sonuç", k: "result", f: (r) => resultTag(r.result) },
    { h: "K", k: "kills", n: true, f: (r) => r.kills ?? "–" },
    { h: "Ö", k: "deaths", n: true, f: (r) => r.deaths ?? "–" },
    ...(ground ? [] : [{ h: "Üs", k: "bases_est", n: true, f: basesCell }]),
    { h: "Skor", k: "score", n: true, f: (r) => num(r.score) },
    { h: "Lobi", k: "lobby_pos", n: true, f: (r) => (r.lobby_pos ? `${r.lobby_pos}<span class="dim">/${r.n_players}</span>` : "–") },
    ...(ground ? [] : [{ h: "Kaçış", k: "missile_evades", n: true, f: (r) => r.missile_evades ?? "–" }]),
    { h: "SL", k: "total_sl", n: true, f: (r) => num(r.total_sl) },
    { h: "RP", k: "total_rp", n: true, f: (r) => num(r.total_rp) },
    { h: "Veri", k: "has_replay", sort: false, f: (r) => `<span class="src">${r.has_replay ? "<b>R</b>" : "·"}${r.has_result ? "<b>S</b>" : "·"}${r.has_telemetry ? "<b>T</b>" : "·"}</span>` },
  ];
}

async function pageBattles(view) {
  const rows = await api("battles", state.filters);
  $("#fCount").textContent = `${rows.length} maç`;
  view.innerHTML = `<div class="page-title"><h1>Maçlar</h1><span class="meta">${rows.length} maç · satıra tıkla: detay · Veri: <b>R</b> replay, <b>S</b> sonuç metni, <b>T</b> telemetri</span></div>
    <div class="grid">${panel("Maç listesi", '<div id="bt"></div>', { flush: true })}</div>`;
  mountTable($("#bt", view), battleCols(), rows, { key: "session_id", onRow: (k) => (location.hash = `#/mac/${k}`), sortKey: "started" });
}

async function pageWeapons(view) {
  const w = await api("weapons", state.filters);
  const nk = w.kills.reduce((a, b) => a + b.n, 0), nd = w.deaths.reduce((a, b) => a + b.n, 0);
  $("#fCount").textContent = `${nk} kill · ${nd} ölüm`;
  view.innerHTML = `<div class="page-title"><h1>Silahlar</h1><span class="meta">Replay kill raporlarından · ${nk} kill · ${nd} ölüm</span></div>
  <div class="grid">
    ${panel("Seni düşüren silahlar", barList(w.deaths, { cls: "loss" }), { cls: "c6", aside: `${nd} ölüm` })}
    ${panel("Kill aldığın silahlar", barList(w.kills, { cls: "acc" }), { cls: "c6", aside: `${nk} kill · AI dahil` })}
    ${panel("Seni düşüren araçlar", barList(w.killers, { cls: "loss" }), { cls: "c6" })}
    ${panel("Düşürdüğün araçlar", barList(w.victims, { cls: "acc" }), { cls: "c6" })}
    ${w.intercepts.length ? panel("Vurduğun füzeler", barList(w.intercepts), { cls: "c6", aside: "mühimmat etkisizleştirme" }) : ""}
  </div>`;
}

// ---------------------------------------------------------------- skills
const KIND = { weak: ["Zayıf", "loss"], strong: ["Güçlü", "win"], note: ["Not", "none"] };
const CLS_SHORT = { radar: "Radar", ir: "IR", gun: "Top", sam: "SAM", none: "Kaza", other: "Diğer", unknown: "?" };
const VERDICT = { good: ["Savunma var", "win"], weak: ["Zayıf", "loss"], none: ["Savunma yok", "loss"], "n/a": ["–", "none"] };

function findingList(items, { compact = false } = {}) {
  if (!items.length) return empty("Henüz belirgin bir güçlü ya da zayıf yön yok.", "Daha fazla maç biriktikçe burası dolacak.");
  return `<ol class="findings${compact ? " compact" : ""}">${items.map((f) => {
    const [label, cls] = KIND[f.kind];
    return `<li class="finding ${f.kind}${f.low_data ? " low" : ""}">
      <span class="tag ${cls}">${label}</span>
      <div><h3>${esc(f.title)}</h3><p>${esc(f.detail)}</p>
      ${f.hint ? `<p class="hint"><b>Ne yapabilirsin</b>${esc(f.hint)}</p>` : ""}</div>
      <span class="n" data-tip="${f.low_data ? "Örnek az; sonuç değişebilir" : "Dayandığı örnek sayısı"}">n=${f.n}${f.low_data ? " · az veri" : ""}</span></li>`;
  }).join("")}</ol>`;
}

// side-by-side share bars: you vs lobby, per weapon class
function pairBars(classes, mineKey, lobbyKey) {
  const mt = classes.reduce((a, c) => a + c[mineKey], 0), lt = classes.reduce((a, c) => a + c[lobbyKey], 0);
  const rows = classes.filter((c) => c[mineKey] || c[lobbyKey]);
  if (!mt) return '<div class="dim">Veri yok.</div>';
  const max = Math.max(...rows.map((c) => Math.max(c[mineKey] / mt, lt ? c[lobbyKey] / lt : 0)));
  return `<div class="pairs">${rows.map((c) => {
    const a = c[mineKey] / mt, b = lt ? c[lobbyKey] / lt : 0;
    const d = Math.round(100 * (a - b));
    const t = `Sen: ${c[mineKey]} (%${Math.round(100 * a)})<br>Lobi: ${c[lobbyKey]} (%${Math.round(100 * b)})`;
    return `<div class="pair-lab">${esc(c.name)}</div>
      <div class="pair-bars" data-tip="${esc(t)}"><div class="pb me" style="width:${(100 * a) / max}%"></div><div class="pb lob" style="width:${(100 * b) / max}%"></div></div>
      <div class="pair-val"><b>%${Math.round(100 * a)}</b> <span class="dim">/ %${Math.round(100 * b)}</span><span class="delta">${d > 0 ? "+" : ""}${d}</span></div>`;
  }).join("")}</div>
  <div class="form-legend"><span><i class="sw" style="background:var(--accent)"></i>Sen (${mt})</span><span><i class="sw" style="background:var(--ink-3)"></i>Aynı maçlardaki lobi (${lt})</span><span>sağdaki sayı: fark (puan)</span></div>`;
}

// share of the pre-hit window spent hot / beaming / cold relative to the nearest spotted enemy
function aspectStack(r) {
  if (r.def_hot == null) return '<span class="dim">görünür düşman yok</span>';
  const seg = (v, cls) => (v ? `<i class="${cls}" style="width:${100 * v}%"></i>` : "");
  const t = `Tehdide doğru %${Math.round(100 * r.def_hot)} · Notch %${Math.round(100 * r.def_notch)} · Soğuk %${Math.round(100 * r.def_cold)}<br>En yakın görünen düşman ~${num(r.def_threat_km, 1)} km`;
  return `<span class="astack" data-tip="${esc(t)}">${seg(r.def_hot, "hot")}${seg(r.def_notch, "notch")}${seg(r.def_cold, "cold")}</span>`;
}

async function pageSkills(view) {
  const [s, tr] = await Promise.all([api("skills", state.filters), api("trend", state.filters).catch(() => null)]);
  s.trend = tr;
  if (s.kind === "ground") return pageSkillsGround(view, s);
  const e = s.energy, lob = s.lobby, fd = s.first_death;
  const nDeaths = s.classes.reduce((a, c) => a + c.my_deaths, 0);
  $("#fCount").textContent = `${lob.n || 0} maç · ${s.defense.length} ölüm analizi`;
  const mins = (ms) => (ms == null ? "–" : num(ms / 60000, 1));
  const share = (v) => (v == null ? "–" : num(100 * v));
  view.innerHTML = `<div class="page-title"><h1>Beceri</h1><span class="meta">Tahmini analiz · ${lob.n || 0} replay · ${e.n} telemetrili uçuş</span></div>
  <div class="grid">
    ${panel("Güçlü ve zayıf yönler", findingList(s.findings), { cls: "c12", aside: "lobiyle kıyas + uçuş verisi" })}
    ${basesPanel(s.bases)}
    ${trendPanel(s.trend, false)}
    <section class="panel c12">${kpis([
      { label: "Füzeden kaçış / maç", value: num(lob.my_ev, 2), sub: `lobi ${num(lob.l_ev, 2)}`, hl: lob.my_ev > lob.l_ev },
      { label: "K/D", value: lob.my_d ? num(lob.my_k / lob.my_d, 2) : "–", sub: `lobi ${lob.l_d ? num(lob.l_k / lob.l_d, 2) : "–"}` },
      { label: "İlk ölüm (ortanca)", value: mins(fd.me), unit: " dk", sub: `lobi ${mins(fd.lobby)} dk` },
      { label: "Ort. enerji yüksekliği", value: num(e.energy_m), unit: " m", sub: "irtifa + hız²/2g" },
      { label: "600 km/h altı", value: share(e.low_energy), unit: "%", sub: "300 m üstünde" },
      { label: "Art yakıcı", value: share(e.ab), unit: "%", sub: "uçuş süresinin" },
      { label: "Takımın önünde", value: share(e.front), unit: "%", sub: "düşmana en yakın dost" },
      { label: "300 m altı", value: share(e.low_alt), unit: "%", sub: "uçuş süresinin" },
    ])}</section>
    ${panel("Seni ne düşürüyor", pairBars(s.classes, "my_deaths", "lobby_deaths"), { cls: "c6", aside: `${nDeaths} ölüm · replay` })}
    ${panel("Neyle düşürüyorsun", pairBars(s.classes, "my_kills", "lobby_kills"), { cls: "c6", aside: "oyuncu kill'leri · replay" })}
    ${panel("Vurulmadan önceki 15 saniye", '<div id="dt"></div>', { cls: "c12", flush: true, aside: "telemetrili ölümler · satıra tıkla: maç" })}
  </div>
  <p class="note">Oyun füze atışını ve RWR'ı dışarı vermediği için yön analizi <b>en yakın görünen düşman uçağına</b> göre yapılır; atan uçak o olmayabilir.
  Notch: düşmana göre 65–115°. Multipath: radar irtifası 60 m altı. Değerlendirme füzenin türüne göre yapılır: radar için notch / multipath / soğuk kaçış, IR ve top için sert manevra (6 G+) ya da kaçış aranır.</p>`;
  const box = $("#dt", view);
  if (!s.defense.length) {
    box.innerHTML = empty("Telemetrili ölüm yok.", "Kaydedici açıkken oynadığın maçlarda burada her ölümün son 15 saniyesi görünür.");
    return;
  }
  mountTable(box, [
    { h: "Tarih", k: "started", f: (r) => `<span class="num">${dt(r.started)}</span>` },
    { h: "Harita", k: "map" },
    { h: "Silah", k: "weapon", f: (r) => esc(r.weapon || "–") },
    { h: "Tür", k: "cls", f: (r) => `<span class="cls-chip">${CLS_SHORT[r.cls] || esc(r.cls)}</span>` },
    { h: "Yön: sıcak · notch · soğuk", k: "def_notch", f: aspectStack },
    { h: "60 m altı", k: "def_low", n: true, f: (r) => (r.def_low == null ? "–" : `%${Math.round(100 * r.def_low)}`) },
    { h: "Maks G", k: "def_max_g", n: true, f: (r) => num(r.def_max_g, 1) },
    { h: "Hız km/h", k: "def_tas1", n: true, f: (r) => (r.def_tas0 == null ? "–" : `${num(r.def_tas0)}<span class="dim"> → </span>${num(r.def_tas1)}`) },
    { h: "İrtifa m", k: "def_alt1", n: true, f: (r) => (r.def_alt0 == null ? "–" : `${num(r.def_alt0)}<span class="dim"> → </span>${num(r.def_alt1)}`) },
    { h: "Görülen", k: "style", cls: "dim wrap" },
    { h: "Değerlendirme", k: "verdict", f: (r) => `<span class="tag ${VERDICT[r.verdict][1]}">${VERDICT[r.verdict][0]}</span>` },
  ], s.defense, { key: "session_id", sortKey: "started", onRow: (k) => (location.hash = `#/mac/${k}`) });
}

// small rolling-average line chart; better = "up" or "down" colours the change
function trendChart(points, key, { label, fmt = (v) => num(v, 2), better = "up" } = {}) {
  const pts = points.map((p, i) => ({ i, v: p[key], t: p.started })).filter((p) => p.v != null);
  if (pts.length < 2) return `<div class="trend"><div class="trend-h">${esc(label)}</div><div class="dim">Yeterli veri yok.</div></div>`;
  const W = 300, H = 80, pad = 6;
  const vs = pts.map((p) => p.v), lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
  const n = points.length - 1 || 1;
  const x = (i) => pad + ((W - 2 * pad) * i) / n, y = (v) => H - pad - ((H - 2 * pad) * (v - lo)) / span;
  const d = pts.map((p, j) => `${j ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const first = pts[0].v, last = pts[pts.length - 1].v;
  const up = last > first, flat = Math.abs(last - first) < span * 0.05;
  const good = flat ? "" : (up === (better === "up") ? "win" : "loss");
  const arrow = flat ? "→" : up ? "↗" : "↘";
  const tip = (p) => `${day(p.t)}: ${fmt(p.v)}`;
  return `<div class="trend"><div class="trend-h">${esc(label)}<span class="trend-v ${good}">${fmt(first)} ${arrow} <b>${fmt(last)}</b></span></div>
    <svg viewBox="0 0 ${W} ${H}" class="trend-svg"><path d="${d}" class="trend-line"/>
    ${pts.map((p) => `<circle cx="${x(p.i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="7" fill="transparent" data-tip="${esc(tip(p))}"/>`).join("")}
    <circle cx="${x(pts[pts.length - 1].i).toFixed(1)}" cy="${y(last).toFixed(1)}" r="3" class="trend-dot"/></svg></div>`;
}

function trendPanel(t, ground) {
  if (!t || t.points.length < 2) return "";
  const pctf = (v) => `%${Math.round(100 * v)}`;
  const charts = ground
    ? [trendChart(t.points, "kd", { label: "K/D" }), trendChart(t.points, "kpm", { label: "Kill / maç" }),
       trendChart(t.points, "cz", { label: "Bölge / maç" }), trendChart(t.points, "score", { label: "Skor", fmt: (v) => num(v) })]
    : [trendChart(t.points, "kd", { label: "K/D" }), trendChart(t.points, "bases", { label: "Üs / maç" }),
       trendChart(t.points, "rp_min", { label: "RP / dakika", fmt: (v) => num(v) }),
       trendChart(t.points, "ir", { label: "IR füzesiyle ölüm payı", fmt: pctf, better: "down" })];
  return panel("Gelişim", `<div class="trends">${charts.join("")}</div><p class="note">Her nokta son ${t.window} maçın ortalaması (hareketli ortalama), soldan sağa eskiden yeniye. Yeşil: iyiye gidiyor, kırmızı: kötüye.</p>`, { cls: "c12", aside: `${t.n} maç` });
}

function basesPanel(b) {
  if (!b || !b.n) return "";
  const w = b.split.with, wo = b.split.without;
  const row = (label, r) => (r ? `<tr><td>${label}</td><td class="n">${r.n}</td><td class="n">${num(r.rp)}</td><td class="n">${num(r.rp_min)}</td><td class="n">${num(r.sl)}</td><td class="n">${num(r.sl_min)}</td><td class="n">${num(r.score)}</td><td class="n">${num(r.kills, 2)}</td></tr>` : "");
  return panel("Üs bombalama", kpis([
    { label: "Üs / maç", value: num(b.per_match, 2), sub: `toplam ${b.bases || 0} üs`, hl: true },
    { label: "Üs aldığın maç", value: num(100 * (b.share || 0)), unit: "%", sub: `${b.with_bases || 0} / ${b.n} maç` },
    { label: "En çok üs", value: b.best ?? "–", sub: "tek maçta" },
    { label: "Etki / maç", value: num(b.impact, 2), sub: "hava kill + üs" },
    ...(b.timing && b.timing.n ? [
      { label: "İlk üs (ortanca)", value: b.timing.first_base_s == null ? "–" : mmss(b.timing.first_base_s), sub: "maç başından" },
      { label: "Üsler arası", value: b.timing.gap_s == null ? "–" : `${b.timing.gap_s}`, unit: b.timing.gap_s == null ? "" : " sn", sub: "aynı maçta, ortanca" },
      { label: "Üs almadan düştüğün", value: b.timing.died ? num((100 * b.timing.died_before_base) / b.timing.died) : "–", unit: b.timing.died ? "%" : "", sub: `düştüğün ${b.timing.died} maçta` },
    ] : []),
  ]) + (b.weapons && b.weapons.length ? `<div style="padding:12px var(--pad) 0"><div class="kpi-label" style="margin-bottom:8px">Üs aldığın silahlar</div>${barList(b.weapons, { cls: "acc", fmt: (it) => `<b>${it.n}</b> üs` })}</div>` : "") + (w || wo ? `<table class="data"><thead><tr><th>Sonuç metni olan maçlar</th><th class="n">Maç</th><th class="n">RP/maç</th><th class="n">RP/dk</th><th class="n">SL/maç</th><th class="n">SL/dk</th><th class="n">Skor</th><th class="n">Kill</th></tr></thead><tbody>
      ${row("Üs aldığın", w)}${row("Üs almadığın", wo)}</tbody></table>` : "") +
    `<p class="note">Üs, ton hasarına göre değil <b>alınan üs sayısına</b> göre sayılır. Sayı sonuç metnindeki "Yok edilen üsler" satırlarından gelir.
    Sonuç metni olmayan maçlarda (≈) o uçakla verdiğin üs hasarının sonuç metinli maçlardaki üs başına ortalamasıyla tahmin edilir. Hiç sonuç metni olmayan uçaklar tahmin edilmez.
    Lobideki diğer oyuncuların üs sayısı replay'de kayıtlı değil; bu yüzden lobi kıyası yapılmaz.</p>`, { cls: "c12", aside: `${b.exact || 0} kesin · ${(b.n || 0) - (b.exact || 0)} tahmini maç` });
}

function pageSkillsGround(view, s) {
  const lob = s.lobby, fd = s.first_death, cov = s.coverage;
  $("#fCount").textContent = `${lob.n || 0} maç`;
  const mins = (ms) => (ms == null ? "–" : num(ms / 60000, 1));
  const covTxt = cov.total ? `${cov.mapped}/${cov.total} ölüm eşleşti` : `${cov.mapped} ölüm`;
  view.innerHTML = `<div class="page-title"><h1>Beceri</h1><span class="meta">Kara muharebeleri · ${lob.n || 0} replay · lobiyle kıyas</span></div>
  <div class="grid">
    ${panel("Güçlü ve zayıf yönler", findingList(s.findings), { cls: "c12", aside: "aynı maçlardaki lobiyle kıyas" })}
    <section class="panel c12">${kpis([
      { label: "K/D", value: lob.my_d ? num(lob.my_k / lob.my_d, 2) : "–", sub: `lobi ${lob.l_d ? num(lob.l_k / lob.l_d, 2) : "–"} · kara + hava`, hl: true },
      { label: "Kill / maç", value: num(lob.my_kpm, 2), sub: `lobi ${num(lob.l_kpm, 2)}` },
      { label: "Ölüm / maç", value: num(lob.my_dpm, 2), sub: `lobi ${num(lob.l_dpm, 2)}` },
      { label: "Asist / maç", value: num(lob.my_a, 2), sub: `lobi ${num(lob.l_a, 2)}` },
      { label: "İlk ölüm (ortanca)", value: mins(fd.me), unit: " dk", sub: `lobi ${mins(fd.lobby)} dk` },
      { label: "Bölge / maç", value: num(lob.my_cz, 2), sub: `lobi ${num(lob.l_cz, 2)}`, hl: lob.my_cz > lob.l_cz },
    ])}</section>
    ${trendPanel(s.trend, true)}
    ${s.vehicles && s.vehicles.length ? panel("Araçlarına göre", '<div id="gvt"></div>', { cls: "c12", flush: true, aside: "replay kill kayıtlarından" }) : ""}
    ${panel("Seni ne düşürüyor", pairBars(s.classes, "my_deaths", "lobby_deaths"), { cls: "c6", aside: `düşmanın araç türü · ${covTxt}` })}
    ${panel("Neyi düşürüyorsun", pairBars(s.classes.filter((c) => c.id !== "none"), "my_kills", "lobby_kills"), { cls: "c6", aside: `hedefin araç türü · ${s.classes.reduce((a, c) => a + c.my_kills, 0)}/${lob.my_k || 0} kill eşleşti` })}
    ${panel("Seni vuran mühimmat", pairBars(s.ammo, "my_deaths", "lobby_deaths"), { cls: "c6", aside: "tank / SPAA atışları · tahmini" })}
    ${panel("Kullandığın mühimmat", pairBars(s.ammo, "my_kills", "lobby_kills"), { cls: "c6", aside: "tank / SPAA atışları · tahmini" })}
  </div>
  <p class="note">Kara maçlarında yeniden doğan araçlar replay'de yeni kimlik alır; bir ölüm ancak o araç daha önce bir şey vurduysa ya da ilk araçsa oyuncuya eşlenebilir.
  Bu yüzden türe göre dağılım ölümlerin bir kısmından hesaplanır (${covTxt}). K/D, kill, ölüm ve asist sayıları maç sonu tablosundan geldiği için tamdır.
  Mühimmat türü silah adından tahmin edilir. Araçlarına göre tablosunda kill'ler kesin, ölümler eşleşebildiği kadarıyla sayılır.</p>`;
  const vt = $("#gvt", view);
  if (vt) {
    s.vehicles.forEach((v) => { v.kd = v.d ? v.k / v.d : v.k; });
    const maxKd = Math.max(...s.vehicles.map((v) => v.kd || 0), 0.01);
    mountTable(vt, [
      { h: "Araç", k: "vehicle_name" }, { h: "Tür", k: "type", cls: "dim" },
      { h: "Maç", k: "n", n: true }, { h: "Kill", k: "k", n: true }, { h: "Ölüm", k: "d", n: true },
      { h: "K/D", k: "kd", n: true, f: (r) => rateBar(r.kd, maxKd, "acc") },
    ], s.vehicles, { sortKey: "k" });
  }
}

function rateBar(v, max = 1, cls = "", digits = 2) {
  return v == null ? "–" : `<span class="num">${num(v, digits)}</span><span class="inline-bar ${cls}" style="width:${Math.min(60, (60 * v) / (max || 1))}px"></span>`;
}

async function pageMaps(view) {
  const rows = await api("maps", state.filters);
  $("#fCount").textContent = `${rows.length} harita`;
  const maxKd = Math.max(...rows.map((r) => (r.d ? r.k / r.d : r.k || 0)), 0.01);
  rows.forEach((r) => { r.kd = r.k == null ? null : r.d ? r.k / r.d : r.k; r.wr = (r.w || 0) + (r.l || 0) ? r.w / (r.w + r.l) : null; r.top = r.lobby == null ? null : 1 - r.lobby; });
  const ground = state.filters.type === "ground";
  rows.forEach((r) => { r.bpm = r.nb ? r.bases / r.nb : null; });
  const maxBpm = Math.max(...rows.map((r) => r.bpm || 0), 0.01);
  const maxRpm = Math.max(...rows.map((r) => r.rp_min || 0), 1);
  view.innerHTML = `<div class="page-title"><h1>Haritalar</h1><span class="meta">Hangi haritada iyisin, hangisinde zorlanıyorsun</span></div>
    <div class="grid">${ground ? "" : mapBaseHighlights(rows)}${panel("Harita performansı", '<div id="mt"></div>', { flush: true, aside: "başlığa tıkla: sırala" })}</div>
    <p class="note">Lobi dilimi: maçın kaçta kaçındasın (0 = en iyi). Kazanma oranı ve RP/dk yalnızca sonuç metni olan maçlardan.
    ${ground ? "" : "Üs/maç sonuç metni olan maçlarda kesin, olmayanlarda tahmini (≈). İlk üs: sonuç metnindeki ilk yok edilen üssün dakikası. İlk ölüm: replay'deki ilk ölümün dakikası."}</p>`;
  mountTable($("#mt", view), [
    { h: "Harita", k: "map" },
    { h: "Maç", k: "n", n: true },
    { h: "Kazanma", k: "wr", n: true, f: (r) => (r.wr == null ? '<span class="dim">–</span>' : `%${Math.round(100 * r.wr)} <span class="dim">(${r.w}/${r.w + r.l})</span>`) },
    { h: "Kill", k: "k", n: true },
    { h: "Ölüm", k: "d", n: true },
    { h: "K/D", k: "kd", n: true, f: (r) => rateBar(r.kd, maxKd, "acc") },
    { h: "Ort. skor", k: "score", n: true, f: (r) => num(r.score) },
    { h: "Lobi dilimi", k: "top", n: true, f: (r) => (r.lobby == null ? "–" : `%${Math.round(100 * r.lobby)}`) },
    ...(ground ? [{ h: "Bölge/maç", k: "cz", n: true, f: (r) => num(r.cz, 2) }] : [
      { h: "Üs/maç", k: "bpm", n: true, f: (r) => (r.bpm == null ? '<span class="dim">–</span>' : rateBar(r.bpm, maxBpm, "acc")) },
      { h: "İlk üs", k: "first_base_s", n: true, f: (r) => (r.first_base_s == null ? '<span class="dim">–</span>' : mmss(r.first_base_s)) },
      { h: "İlk ölüm", k: "first_death_s", n: true, f: (r) => (r.first_death_s == null ? '<span class="dim">–</span>' : mmss(r.first_death_s)) },
      { h: "Kaçış", k: "ev", n: true },
    ]),
    { h: "RP/dk", k: "rp_min", n: true, f: (r) => (r.rp_min == null ? '<span class="dim">–</span>' : rateBar(r.rp_min, maxRpm, "s2", 0)) },
    { h: "SL/dk", k: "sl_min", n: true, f: (r) => (r.sl_min == null ? '<span class="dim">–</span>' : num(r.sl_min)) },
  ], rows, { sortKey: "n" });
}

// best and worst maps for base bombing (needs at least 3 battles with a known base count)
function mapBaseHighlights(rows) {
  const ok = rows.filter((r) => r.nb >= 3).sort((a, b) => b.bpm - a.bpm);
  if (ok.length < 2) return "";
  const line = (r) => `<li><b>${esc(r.map)}</b> <span class="dim">· ${num(r.bpm, 1)} üs/maç · ${r.base_matches}/${r.nb} maçta üs${r.rp_min ? ` · ${num(r.rp_min)} RP/dk` : ""}${r.first_base_s != null ? ` · ilk üs ${mmss(r.first_base_s)}` : ""}</span></li>`;
  const best = ok.slice(0, 3), worst = ok.slice(-3).reverse().filter((r) => !best.includes(r));
  return panel("Üs bombalamaya en uygun haritalar", `<ul class="map-hl">${best.map(line).join("")}</ul>`, { cls: "c6", aside: "en az 3 maç" }) +
    (worst.length ? panel("Üs almakta zorlandığın haritalar", `<ul class="map-hl">${worst.map(line).join("")}</ul>`, { cls: "c6", aside: "en az 3 maç" }) : "");
}

async function pageVehicles(view) {
  const rows = await api("vehicles", state.filters);
  $("#fCount").textContent = `${rows.length} araç`;
  const maxKd = Math.max(...rows.map((r) => (r.d ? r.k / r.d : r.k || 0)), 0.01);
  rows.forEach((r) => { r.kd = r.d ? r.k / r.d : r.k; r.wr = (r.w || 0) + (r.l || 0) ? r.w / (r.w + r.l) : null; });
  view.innerHTML = `<div class="page-title"><h1>Araçlar</h1><span class="meta">Araçlarını yan yana karşılaştır · satıra tıkla: o araçla filtrele</span></div>
    <div class="grid">${panel("Araç performansı", '<div id="vt"></div>', { flush: true, aside: "başlığa tıkla: sırala" })}</div>
    <p class="note">İlk ölüm: replay'deki ilk ölümün ortalama dakikası (düştüğün maçlarda). Ölmeden biten: hiç düşmeden bitirdiğin maç oranı. RP/dk ve SL/dk yalnızca sonuç metni olan maçlardan.</p>`;
  mountTable($("#vt", view), [
    { h: "Araç", k: "vehicle_name" },
    { h: "Tür", k: "vehicle_type", cls: "dim" },
    { h: "Maç", k: "n", n: true },
    { h: "Kazanma", k: "wr", n: true, f: (r) => (r.wr == null ? '<span class="dim">–</span>' : `%${Math.round(100 * r.wr)}`) },
    { h: "Kill", k: "k", n: true }, { h: "Ölüm", k: "d", n: true },
    { h: "K/D", k: "kd", n: true, f: (r) => rateBar(r.kd, maxKd, "acc") },
    { h: "Ort. skor", k: "score", n: true, f: (r) => num(r.score) },
    { h: "Lobi dilimi", k: "lobby", n: true, f: (r) => (r.lobby == null ? "–" : `%${Math.round(100 * r.lobby)}`) },
    { h: "İlk ölüm", k: "first_death_s", n: true, f: (r) => (r.first_death_s == null ? '<span class="dim">–</span>' : mmss(r.first_death_s)) },
    { h: "Ölmeden biten", k: "survived", n: true, f: (r) => (r.n ? `%${Math.round((100 * (r.survived || 0)) / r.n)}` : "–") },
    ...(state.filters.type === "ground" ? [{ h: "Bölge/maç", k: "cz", n: true, f: (r) => num(r.cz, 2) }] : []),
    ...(state.filters.type === "ground" ? [] : [{ h: "Üs/maç", k: "bases", n: true, f: (r) => (r.nb ? num(r.bases / r.nb, 2) + (r.nb < r.n ? ` <span class="dim" title="Üs sayısı bilinen maç">(${r.nb} maç)</span>` : "") : '<span class="dim">–</span>') }]),
    { h: "SL/maç", k: "sl", n: true, f: (r) => num(r.sl) },
    { h: "RP/maç", k: "rp", n: true, f: (r) => num(r.rp) },
    { h: "RP/dk", k: "rp_min", n: true, f: (r) => num(r.rp_min) },
    { h: "SL/dk", k: "sl_min", n: true, f: (r) => num(r.sl_min) },
  ], rows, { sortKey: "n", key: "vehicle", onRow: (k) => { state.filters.vehicle = k; store.set("bb-filters", state.filters); $("#fVehicle").value = k; location.hash = "#/ozet"; } });
}

async function pageGrind(view) {
  const [g, miss] = await Promise.all([api("grind", state.filters), api("missing", state.filters)]);
  const t = g.totals;
  $("#fCount").textContent = `${t.n} sonuç metni`;
  if (!t.n) {
    view.innerHTML = `<div class="page-title"><h1>Grind</h1></div><div class="grid">${panel("Sonuç metni yok", empty("Henüz SL/RP verisi yok.", "Recorder açıkken hangardaki savaş sonucu bildiriminde <b>kopyala</b>'ya bas; metin otomatik kaydedilir. Sonra <b>İçe aktar</b>."))}</div>`;
    return;
  }
  const mins = (t.played || 0) / 60;
  view.innerHTML = `<div class="page-title"><h1>Grind</h1><span class="meta">${t.n} maçın savaş sonucu metninden · toplam ${num(t.sum_sl)} SL, ${num(t.sum_rp)} RP</span></div>
  <div class="grid">
    <section class="panel c12">${kpis([
      { label: "Net SL / maç", value: num(t.sl), hl: true, sub: `tamir ort. ${num(t.repair)}` },
      { label: "RP / maç", value: num(t.rp) },
      { label: "SL / dakika", value: mins ? num(t.sum_sl / mins) : "–", sub: "oynanan süreye göre" },
      { label: "RP / dakika", value: mins ? num(t.sum_rp / mins) : "–" },
      { label: "Zaferde", value: num(t.win_sl), unit: " SL", sub: `${num(t.win_rp)} RP` },
      { label: "Yenilgide", value: num(t.loss_sl), unit: " SL", sub: `${num(t.loss_rp)} RP` },
      { label: "Ort. aktivite", value: num(t.activity), unit: "%" },
    ])}</section>
    ${panel("Maç başı kazanç", grindChart(g.battles), { cls: "c12", aside: "net SL ve RP" })}
    ${panel("Araca göre", '<div id="gv"></div>', { cls: "c12", flush: true })}
    ${panel("Sonuç metni eksik maçlar", '<div id="gm"></div>', { cls: "c12", flush: true, aside: "hangarda bildirimden kopyala" })}
  </div>
  <p class="note">Sonuç metni eksik maçlarda SL/RP, kesin üs sayısı ve kazanma bilgisi yok. Hangardaki bildirimlerde
  savaş sonucu bildiriminde <b>kopyala</b>ya bas; BlackBox açıkken (BlackBox.bat) metin otomatik kaydedilir ve birkaç saniye içinde içe aktarılır.</p>`;
  const box = $("#gm", view);
  if (!miss.length) box.innerHTML = empty("Eksik yok.", "Her maçın sonuç metni kayıtlı.");
  else mountTable(box, [
      { h: "Tarih", k: "started", f: (r) => `<span class="num">${dt(r.started)}</span>` },
      { h: "Harita", k: "map" }, { h: "Araç", k: "vehicle_name" },
      { h: "K", k: "kills", n: true }, { h: "Ö", k: "deaths", n: true }, { h: "Skor", k: "score", n: true, f: (r) => num(r.score) },
      { h: "Süre", k: "end_s", n: true, f: (r) => mmss(r.end_s) },
    ], miss, { key: "session_id", sortKey: "started", onRow: (k) => (location.hash = `#/mac/${k}`) });
  mountTable($("#gv", view), [
    { h: "Araç", k: "vehicle_name" }, { h: "Maç", k: "n", n: true },
    { h: "SL/maç", k: "sl", n: true, f: (r) => num(r.sl) }, { h: "RP/maç", k: "rp", n: true, f: (r) => num(r.rp) },
    { h: "Tamir/maç", k: "repair", n: true, f: (r) => num(r.repair) },
    { h: "SL/dk", k: "sum_sl", n: true, f: (r) => (r.played ? num(r.sum_sl / (r.played / 60)) : "–") },
    { h: "RP/dk", k: "sum_rp", n: true, f: (r) => (r.played ? num(r.sum_rp / (r.played / 60)) : "–") },
  ], g.by_vehicle, { sortKey: "n" });
}

function grindChart(rows) {
  const W = 1000, H = 220, pad = { l: 56, r: 56, t: 14, b: 28 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const maxSl = Math.max(1, ...rows.map((r) => r.total_sl || 0)), maxRp = Math.max(1, ...rows.map((r) => r.total_rp || 0));
  const tSl = niceTicks(maxSl, 4), tRp = niceTicks(maxRp, 4);
  const topSl = tSl[tSl.length - 1], topRp = tRp[tRp.length - 1];
  const gw = iw / rows.length;
  let s = `<div class="chart-legend"><span><i class="sw" style="background:var(--ink)"></i>Net SL (sol eksen)</span><span><i class="sw" style="background:var(--series-2)"></i>RP (sağ eksen)</span></div><svg class="chart" viewBox="0 0 ${W} ${H}">`;
  tSl.forEach((v, i) => {
    const y = pad.t + ih - (ih * v) / topSl;
    s += `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}"/><text x="${pad.l - 6}" y="${y + 3}" text-anchor="end">${nf.format(v)}</text>`;
    const rv = tRp[Math.min(i, tRp.length - 1)];
    if (i < tRp.length) s += `<text x="${W - pad.r + 6}" y="${pad.t + ih - (ih * rv) / topRp + 3}">${nf.format(rv)}</text>`;
  });
  rows.forEach((r, i) => {
    const x = pad.l + i * gw;
    const bw = Math.min(18, gw * 0.34);
    const hs = (ih * Math.max(0, r.total_sl || 0)) / topSl, hr = (ih * (r.total_rp || 0)) / topRp;
    const tipTxt = `${day(r.started)} · ${r.map}<br>${r.vehicle_name || ""} · ${r.result === "win" ? "zafer" : "yenilgi"}<br>${num(r.total_sl)} SL net · ${num(r.total_rp)} RP`;
    s += `<g data-tip="${esc(tipTxt)}" style="cursor:pointer" onclick="location.hash='#/mac/${r.session_id}'"><rect x="${x}" y="${pad.t}" width="${gw}" height="${ih}" fill="transparent"/>
      <rect class="bar" x="${x + gw / 2 - bw - 1}" y="${pad.t + ih - hs}" width="${bw}" height="${hs}"/>
      <rect class="bar s2" x="${x + gw / 2 + 1}" y="${pad.t + ih - hr}" width="${bw}" height="${hr}"/>
      <rect x="${x + gw / 2 - bw - 1}" y="${pad.t + ih + 4}" width="${bw * 2 + 2}" height="3" fill="var(--${r.result === "win" ? "win" : "loss"})"/></g>`;
  });
  s += `<line class="axis" x1="${pad.l}" x2="${W - pad.r}" y1="${pad.t + ih}" y2="${pad.t + ih}"/></svg>`;
  return s + '<p class="note">Çubuğun altındaki şerit: yeşil zafer, kırmızı yenilgi. Tıkla: maç detayı.</p>';
}

// ---------------------------------------------------------------- battle detail
async function pageBattle(view, sid) {
  const d = await api(`battle/${encodeURIComponent(sid)}`);
  const b = d.battle;
  const me = d.players.find((p) => p.is_me);
  const myTeam = me ? me.team : null;
  const mine = d.kills.filter((k) => k.me_killer || k.me_victim);
  $("#fCount").textContent = "";
  const end = (b.end_s || Math.max(0, ...d.kills.map((k) => k.ms / 1000))) || 1;

  const evList = mine.length ? `<ul class="events">${mine.map((k) => {
    if (k.me_killer && k.destroyed_weapon) return `<li><span class="t">${mmss(k.ms / 1000)}</span><span class="k icpt">◇</span><span>${esc(k.destroyed_name)} füzesini vurdun <span class="w">${esc(k.weapon_name || "?")}</span></span></li>`;
    if (k.me_killer) return `<li><span class="t">${mmss(k.ms / 1000)}</span><span class="k kill">▲</span><span><b>${esc(k.victim_name || "AI hedef")}</b> <span class="dim">${esc(k.victim_vehicle_name || "")}</span> <span class="w">${esc(k.weapon_name || "silahsız")}</span></span></li>`;
    return `<li><span class="t">${mmss(k.ms / 1000)}</span><span class="k death">✕</span><span>Düşürüldün: <b>${esc(k.killer_name || "kaza")}</b> <span class="dim">${esc(k.killer_vehicle_name || "")}</span> <span class="w">${esc(k.weapon_name || "silahsız")}</span></span></li>`;
  }).join("")}</ul>` : '<div class="dim">Bu maçta senin kill veya ölüm kaydın yok.</div>';

  const teamTables = [myTeam, myTeam === 1 ? 2 : 1].filter((t) => t != null).map((team) => {
    const ps = d.players.filter((p) => p.team === team).map((p) => ({ ...p, _cls: p.is_me ? "me" : "" }));
    const label = team === myTeam ? "Senin takımın" : "Rakip takım";
    const color = team === myTeam ? "var(--win)" : "var(--loss)";
    return `<div class="c6 panel"><div class="team-h"><span class="bar" style="background:${color}"></span>${label}<span class="dim" style="margin-left:auto">${ps.reduce((a, p) => a + (p.kills || 0), 0)} kill</span></div>
      ${dataTable([
        { h: "Oyuncu", k: "name", f: (p) => `${esc(p.name)} <span class="dim">${esc(p.clan || "")}</span>` },
        { h: "Araç", k: "vehicle_name", cls: "muted" },
        { h: "K", k: "kills", n: true }, { h: "Ö", k: "deaths", n: true }, { h: "A", k: "assists", n: true },
        { h: "Skor", k: "score", n: true }, { h: "Kaçış", k: "missile_evades", n: true },
      ], ps, { sortKey: null })}</div>`;
  }).join("");

  const rewards = () => {
    if (!d.result) return "";
    const cats = Object.entries(d.result.categories || {});
    return panel("Ödüller", `<table class="rewards"><tbody>${cats.map(([k, v]) => `<tr><td>${esc(k)}${v.count ? ` <span class="dim">×${v.count}</span>` : ""}</td><td class="n">${v.sl != null ? num(v.sl) + " SL" : ""}</td><td class="n">${v.rp != null ? num(v.rp) + " RP" : ""}</td></tr>`).join("")}
      <tr><td>Otomatik tamir</td><td class="n">${num(d.result.repair_sl)} SL</td><td></td></tr>
      <tr class="total"><td>Toplam (net)</td><td class="n">${num(d.result.total_sl)} SL</td><td class="n">${num(d.result.total_rp)} RP</td></tr></tbody></table>
      <p class="note">Aktivite %${d.result.activity ?? "–"} · oynanan ${mmss(d.result.played_s)} · araştırma: ${esc(d.result.research_vehicle || "–")}</p>`, { cls: "c5" });
  };

  view.innerHTML = `
  <a class="back" href="#/maclar">← Maçlar</a>
  <div class="detail-head"><div>
    <h1>${esc(b.map || "?")}</h1>
    <div class="meta">${resultTag(b.result)}<span>${esc(b.mode || b.battle_class || "")}</span><span class="num">${dt(b.started)}</span><span>${esc(b.vehicle_name || "")}</span><span class="num">${mmss(end)}</span><span class="src">oturum ${esc(b.session_id)}</span></div>
  </div></div>
  <div class="grid">
    <section class="panel c12">${kpis([
      { label: "Kill", value: b.kills ?? "–", hl: true }, { label: "Ölüm", value: b.deaths ?? "–" }, { label: "Asist", value: b.assists ?? "–" },
      { label: "Skor", value: num(b.score) }, { label: "Lobi sırası", value: b.lobby_pos ?? "–", unit: b.n_players ? `/${b.n_players}` : "" },
      { label: "Takım sırası", value: b.team_pos ?? "–" },
      ...(b.kind === "ground" ? [] : [{ label: "Üs", value: b.bases_est ?? "–", unit: b.bases_est != null && !b.has_result ? " ≈" : "", sub: b.has_result ? `${b.base_hits || 0} üs isabeti` : "üs hasarından tahmin" },
        { label: "Füzeden kaçış", value: b.missile_evades ?? "–" }]),
      { label: "Net SL", value: num(b.total_sl) }, { label: "RP", value: num(b.total_rp) },
    ])}</section>
    ${panel("Maç akışı", timeline(d.kills, end, myTeam, d.players), { cls: "c12", aside: "tüm lobideki kill'ler" })}
    ${panel("Seninle ilgili olaylar", evList, { cls: d.result ? "c7" : "c12" })}
    ${rewards()}
    <div class="c12" id="flight"></div>
    ${teamTables}
  </div>`;

  if (b.match_id) view._afterMount = () => loadFlight(b.match_id);
}

function timeline(kills, end, myTeam, players) {
  const W = 1000, H = 150, pad = { l: 92, r: 14, t: 12, b: 26 };
  const iw = W - pad.l - pad.r;
  const x = (ms) => pad.l + (iw * Math.min(ms / 1000, end)) / end;
  const lanes = { me: 30, own: 70, enemy: 104 };
  const teamOf = (idx) => players.find((p) => p.idx === idx)?.team;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
  for (let m = 0; m <= end / 60; m++) {
    const xx = pad.l + (iw * m * 60) / end;
    s += `<line class="grid-line" x1="${xx}" x2="${xx}" y1="${pad.t}" y2="${H - pad.b}"/><text x="${xx}" y="${H - 8}" text-anchor="middle">${m}:00</text>`;
  }
  for (const [k, y] of Object.entries(lanes)) {
    s += `<line class="axis" x1="${pad.l}" x2="${W - pad.r}" y1="${y}" y2="${y}" style="stroke:var(--rule)"/>`;
    s += `<text class="lane-label" x="0" y="${y + 4}">${{ me: "Sen", own: "Takımın", enemy: "Rakip" }[k]}</text>`;
  }
  for (const k of kills) {
    const xx = x(k.ms);
    const who = `${mmss(k.ms / 1000)} · ${esc(k.killer_name || "kaza")} (${esc(k.killer_vehicle_name || "?")})${k.destroyed_weapon ? ` → ${esc(k.destroyed_name)} füzesi` : ` → ${esc(k.victim_name || "AI")} (${esc(k.victim_vehicle_name || "?")})`}<br>${esc(k.weapon_name || "silahsız")}`;
    if (k.me_killer) {
      s += `<path class="mk-kill" d="M${xx} ${lanes.me - 8} L${xx + 6} ${lanes.me + 4} L${xx - 6} ${lanes.me + 4}Z" data-tip="${who}"/>`;
    } else if (k.me_victim) {
      s += `<g data-tip="${who}"><rect x="${xx - 8}" y="${lanes.me - 8}" width="16" height="16" fill="transparent"/><path class="mk-death" d="M${xx - 6} ${lanes.me - 6} L${xx + 6} ${lanes.me + 6} M${xx + 6} ${lanes.me - 6} L${xx - 6} ${lanes.me + 6}"/></g>`;
    }
    if (k.killer_idx == null && !k.me_victim) continue;
    const team = k.killer_idx != null ? teamOf(k.killer_idx) : null;
    if (team == null || k.me_killer) continue;
    const y = team === myTeam ? lanes.own : lanes.enemy;
    s += `<g data-tip="${who}"><rect x="${xx - 4}" y="${y - 10}" width="8" height="20" fill="transparent"/><line class="${team === myTeam ? "tick-own" : "tick-enemy"}" x1="${xx}" x2="${xx}" y1="${y - 8}" y2="${y + 8}"/></g>`;
  }
  return s + "</svg>";
}

async function loadFlight(matchId) {
  const box = $("#flight");
  box.innerHTML = '<div class="loading">Uçuş verisi yükleniyor</div>';
  let t;
  try { t = await api(`telemetry/${encodeURIComponent(matchId)}`); } catch { box.innerHTML = ""; return; }
  if (!t.series.length) { box.innerHTML = ""; return; }
  const life = t.lives[0] || {};
  box.className = "c12 grid";
  box.style.gap = "var(--gap)";
  panelIdx = $$(".panel-h .idx").length;
  box.innerHTML = `${panel("Uçuş profili", `<div class="chart-legend"><span><i class="sw" style="background:var(--accent-soft);outline:1px solid var(--accent)"></i>İrtifa (m, sol)</span><span><i class="sw" style="background:var(--ink)"></i>Gerçek hava hızı (km/h, sağ)</span><span><i class="sw" style="background:var(--accent)"></i>Kill</span><span><i class="sw" style="background:var(--loss)"></i>Hasar / ölüm</span></div>${flightChart(t)}<div class="readout" id="readout">Grafiğin üzerinde gezin.</div>`, { cls: "c8", aside: "8111 telemetrisi" })}
    ${panel("Rota", trackChart(t), { cls: "c4", aside: life.distance_km ? `${num(life.distance_km)} km` : "" })}`;
  bindFlightHover(t);
}

function flightChart(t) {
  const W = 1000, H = 260, pad = { l: 50, r: 54, t: 10, b: 24 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const s0 = t.series;
  const t0 = s0[0][0], t1 = s0[s0.length - 1][0];
  const maxH = niceTicks(Math.max(...s0.map((r) => r[1] || 0)), 4), maxV = niceTicks(Math.max(...s0.map((r) => r[2] || 0)), 4);
  const topH = maxH[maxH.length - 1], topV = maxV[maxV.length - 1];
  const X = (tt) => pad.l + (iw * (tt - t0)) / Math.max(1, t1 - t0);
  const YH = (h) => pad.t + ih - (ih * (h || 0)) / topH, YV = (v) => pad.t + ih - (ih * (v || 0)) / topV;
  let s = `<svg class="chart" id="flightSvg" viewBox="0 0 ${W} ${H}" data-tip-live>`;
  maxH.forEach((v) => { s += `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${YH(v)}" y2="${YH(v)}"/><text x="${pad.l - 6}" y="${YH(v) + 3}" text-anchor="end">${nf.format(v)}</text>`; });
  maxV.forEach((v) => { s += `<text x="${W - pad.r + 6}" y="${YV(v) + 3}">${nf.format(v)}</text>`; });
  for (let m = Math.ceil(t0 / 60); m <= t1 / 60; m++) s += `<text x="${X(m * 60)}" y="${H - 6}" text-anchor="middle">${m}:00</text>`;
  const area = `M${X(t0)} ${YH(0)} ` + s0.map((r) => `L${X(r[0]).toFixed(1)} ${YH(r[1]).toFixed(1)}`).join(" ") + ` L${X(t1)} ${YH(0)}Z`;
  const alt = s0.map((r, i) => `${i ? "L" : "M"}${X(r[0]).toFixed(1)} ${YH(r[1]).toFixed(1)}`).join(" ");
  const spd = s0.map((r, i) => `${i ? "L" : "M"}${X(r[0]).toFixed(1)} ${YV(r[2]).toFixed(1)}`).join(" ");
  s += `<path class="area" d="${area}"/><path class="line acc" d="${alt}"/><path class="line" d="${spd}"/>`;
  for (const e of t.events) {
    if (e.t < t0 || e.t > t1) continue;
    const xx = X(e.t);
    if (e.me_actor && (e.kind === "kill" || e.kind === "destroy")) s += `<line x1="${xx}" x2="${xx}" y1="${pad.t}" y2="${pad.t + ih}" stroke="var(--accent)" stroke-width="2"/>`;
    else if (e.me_target && (e.kind === "kill" || e.kind === "destroy")) s += `<line x1="${xx}" x2="${xx}" y1="${pad.t}" y2="${pad.t + ih}" stroke="var(--loss)" stroke-width="2"/>`;
    else if (e.me_target) s += `<line x1="${xx}" x2="${xx}" y1="${pad.t}" y2="${pad.t + ih}" stroke="var(--loss)" stroke-width="1" stroke-dasharray="3 3"/>`;
  }
  s += `<line class="axis" x1="${pad.l}" x2="${W - pad.r}" y1="${pad.t + ih}" y2="${pad.t + ih}"/>`;
  s += `<line class="cross" id="crossX" x1="-10" x2="-10" y1="${pad.t}" y2="${pad.t + ih}"/><rect id="hoverRect" x="${pad.l}" y="${pad.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
  t._geom = { W, pad, iw, t0, t1 };
  return s;
}

function bindFlightHover(t) {
  const svg = $("#flightSvg"), cross = $("#crossX"), out = $("#readout");
  if (!svg) return;
  const { W, pad, iw, t0, t1 } = t._geom;
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    const tt = t0 + ((vx - pad.l) / iw) * (t1 - t0);
    if (tt < t0 || tt > t1) return;
    let best = t.series[0];
    for (const row of t.series) { if (row[0] > tt) break; best = row; }
    cross.setAttribute("x1", vx); cross.setAttribute("x2", vx);
    out.innerHTML = `t <b>${mmss(best[0])}</b> · irtifa <b>${num(best[1])} m</b> · hız <b>${num(best[2])} km/h</b> · Mach <b>${num(best[3], 2)}</b> · G <b>${num(best[4], 1)}</b>`;
    const dot = $("#trackDot");
    if (dot && t.track.length) {
      let p = t.track[0];
      for (const q of t.track) { if (q[0] > best[0]) break; p = q; }
      dot.setAttribute("cx", p[1] * 300); dot.setAttribute("cy", p[2] * 300); dot.style.display = "";
    }
  });
}

function trackChart(t) {
  if (!t.track.length) return '<div class="dim">Konum verisi yok.</div>';
  const S = 300;
  const xs = t.track.map((p) => p[1]), ys = t.track.map((p) => p[2]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY, 0.05) * 1.25;
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const vb = [cx - span / 2, cy - span / 2, span, span].map((v) => v * S);
  let s = `<svg class="chart" viewBox="${vb.join(" ")}" style="aspect-ratio:1;overflow:hidden">`;
  const step = S / 8;
  const letters = "ABCDEFGH";
  for (let i = 0; i <= 8; i++) {
    s += `<line class="grid-line" x1="${i * step}" x2="${i * step}" y1="0" y2="${S}" vector-effect="non-scaling-stroke"/><line class="grid-line" y1="${i * step}" y2="${i * step}" x1="0" x2="${S}" vector-effect="non-scaling-stroke"/>`;
  }
  const fs = span * S * 0.035;
  for (let i = 0; i < 8; i++) {
    s += `<text class="grid-label" x="${i * step + step / 2}" y="${vb[1] + fs * 1.2}" text-anchor="middle" style="font-size:${fs}px">${i + 1}</text>`;
    s += `<text class="grid-label" x="${vb[0] + fs * 0.4}" y="${i * step + step / 2}" style="font-size:${fs}px">${letters[i]}</text>`;
  }
  const d = t.track.map((p, i) => `${i ? "L" : "M"}${(p[1] * S).toFixed(2)} ${(p[2] * S).toFixed(2)}`).join(" ");
  const sw = span * S * 0.006;
  const last = t.track[t.track.length - 1], first = t.track[0];
  s += `<path class="track-path" d="${d}" style="stroke-width:${sw}"/>`;
  s += `<circle class="track-start" cx="${first[1] * S}" cy="${first[2] * S}" r="${sw * 2.2}" style="stroke-width:${sw}"/>`;
  s += `<path d="M${last[1] * S - sw * 2.5} ${last[2] * S - sw * 2.5} L${last[1] * S + sw * 2.5} ${last[2] * S + sw * 2.5} M${last[1] * S + sw * 2.5} ${last[2] * S - sw * 2.5} L${last[1] * S - sw * 2.5} ${last[2] * S + sw * 2.5}" stroke="var(--loss)" stroke-width="${sw * 1.4}"/>`;
  s += `<circle id="trackDot" r="${sw * 2.2}" fill="var(--accent)" style="display:none"/></svg>`;
  return s + '<p class="note">○ başlangıç · ✕ son konum · harita ızgarası oyundaki kare koordinatları</p>';
}

// ---------------------------------------------------------------- import
async function runImport() {
  const btn = $("#importBtn");
  btn.disabled = true;
  btn.textContent = "Aktarılıyor…";
  try {
    await fetch("/api/import", { method: "POST", headers: { "X-BlackBox": "1" } });
    let st;
    do {
      await new Promise((r) => setTimeout(r, 700));
      st = await api("import");
      const lastLine = st.log[st.log.length - 1];
      if (lastLine) btn.textContent = lastLine.trim().slice(0, 28) + "…";
    } while (st.running);
    if (st.error) toast(`Hata: ${st.error}`);
    else if (st.last) toast(`Telemetri ${st.last.telemetry} · replay ${st.last.replays} · sonuç ${st.last.results} yeni. Toplam ${st.last.battles} maç.`);
    await loadFilterOptions();
    route();
  } catch (e) {
    toast(`Hata: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "İçe aktar";
  }
}

// the server imports by itself when started with "start"; refresh the page when a new import finishes
let importSeq = null;
async function watchImports() {
  try {
    const st = await api("import");
    if (!st.auto) return;
    if (importSeq !== null && st.seq !== importSeq && !st.running && !$("#importBtn").disabled) {
      if (st.last && (st.last.telemetry || st.last.replays || st.last.results)) {
        toast(`Otomatik içe aktarıldı: telemetri ${st.last.telemetry} · replay ${st.last.replays} · sonuç ${st.last.results} yeni.`);
        await loadFilterOptions();
        route();
      }
    }
    if (!st.running) importSeq = st.seq;
  } catch (e) { /* server restarting */ }
  setTimeout(watchImports, 8000);
}

async function quitApp() {
  if (!confirm("BlackBox kapatılsın mı? Telemetri kaydı ve otomatik içe aktarma da durur.")) return;
  try { await fetch("/api/quit", { method: "POST", headers: { "X-BlackBox": "1" } }); } catch { /* already down */ }
  document.body.innerHTML = `<div class="closed"><span class="brand-mark"></span><h1>BlackBox kapatıldı</h1>
    <p>Kayıt durdu. Yeniden başlatmak için masaüstündeki BlackBox kısayoluna ya da BlackBox.bat'a çift tıkla.</p>
    <p class="dim">Bu sekmeyi kapatabilirsin.</p></div>`;
}

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ---------------------------------------------------------------- router
const routes = { ozet: pageSummary, maclar: pageBattles, beceri: pageSkills, silahlar: pageWeapons, haritalar: pageMaps, araclar: pageVehicles, grind: pageGrind };
let routeSeq = 0;
async function route() {
  const seq = ++routeSeq;
  hideTip();
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const page = parts[0] || "ozet";
  const arg = parts[1];
  $$("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === page || (page === "mac" && a.dataset.tab === "maclar")));
  $("#filterbar").style.display = page === "mac" ? "none" : "";
  const view = $("#view");
  view.innerHTML = '<div class="loading">Yükleniyor</div>';
  panelIdx = 0;
  try {
    const tmp = document.createElement("div");
    if (page === "mac") await pageBattle(tmp, decodeURIComponent(arg || ""));
    else await (routes[page] || pageSummary)(tmp);
    if (seq !== routeSeq) return;
    view.replaceChildren(...tmp.childNodes);
    if (tmp._afterMount) tmp._afterMount();
  } catch (e) {
    if (seq !== routeSeq) return;
    view.innerHTML = `<div class="grid">${panel("Hata", empty("Veri yüklenemedi.", esc(e.message)))}</div>`;
  }
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- boot
(async function boot() {
  setTheme(document.documentElement.dataset.theme || "paper");
  $$(".themes button").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeSet)));
  $("#importBtn").addEventListener("click", runImport);
  $("#quitBtn").addEventListener("click", quitApp);
  bindFilters();
  try {
    const me = await api("me");
    state.players = me.players || [me.player];
    const saved = store.get("bb-player", null);
    state.player = state.players.includes(saved) ? saved : me.player;
    const pilot = $("#pilot");
    if (state.players.length > 1) {
      pilot.innerHTML = `<select id="playerSel" class="player-sel" title="Oyuncu profili">${state.players.map((p) => `<option${p === state.player ? " selected" : ""}>${esc(p)}</option>`).join("")}</select>`;
      $("#playerSel").addEventListener("change", async (e) => {
        state.player = e.target.value;
        store.set("bb-player", state.player);
        state.filters.vehicle = ""; state.filters.map = "";
        await loadFilterOptions();
        route();
      });
    } else pilot.textContent = state.player;
  } catch { /* ignore */ }
  await loadFilterOptions();
  addEventListener("hashchange", route);
  route();
  watchImports();
})();
