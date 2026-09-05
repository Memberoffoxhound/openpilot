/* S3XYPilot LAN UI — statistics + vSlam tracker + screenshots */
const PAGES = ["home", "vslam", "shots"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const CHECK = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.2l3.1 3.2L13 4.4" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const COL_NOM = [80, 230, 150];
const COL_SLOW = [255, 59, 48];   // red = slowest slam
const COL_FAST = [255, 204, 0];   // yellow = highest in slam

const S = {
  page: "home",
  vslamId: null,
  home: null,
  shots: [],
  shotView: null,
  shotPick: false,
  shotSel: {},
  confirm: null,
  vslam: { enabled: true, filter_enabled: true, op_long: false, events: [], count: 0 },
  vslamDetail: null,
};
let _map = null;

function parseHash() {
  const raw = (location.hash || "#home").replace(/^#/, "");
  const [page, ...rest] = raw.split("/");
  const id = rest.filter(Boolean).join("/") || null;
  return { page: PAGES.includes(page) ? page : "home", id: page === "vslam" ? id : null };
}
{
  const h = parseHash();
  S.page = h.page;
  S.vslamId = h.id;
}

async function api(url, opt) {
  const r = await fetch(url, opt);
  const t = await r.text();
  try { return JSON.parse(t); } catch { throw new Error(t || r.statusText); }
}
function $(id) { return document.getElementById(id); }
function esc(s) {
  return String(s || "").replace(/[&<>"']/g, c => "&#" + c.charCodeAt(0) + ";");
}
function bytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(0) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(1) + " GB";
}
function say(m) {
  const el = $("toast");
  el.hidden = false;
  el.textContent = m;
  clearTimeout(say._t);
  say._t = setTimeout(() => { el.hidden = true; }, 2800);
}
function hdrVal(v, s) { return (v == null || v === "") ? "\u2014" : v + s; }

function fmtDist(meters, unit, tenths) {
  const v = unit === "km" ? (meters || 0) / 1000 : (meters || 0) / 1609.344;
  if (tenths && v < 100) return v.toFixed(1);
  if (v >= 1000) return Math.round(v).toLocaleString();
  return String(Math.round(v));
}

function tickClock() {
  const d = new Date();
  const days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const mons = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  let h = d.getHours(), ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, "0");
  $("clock").textContent = `${days[d.getDay()]} ${mons[d.getMonth()]} ${d.getDate()}  \u00b7  ${h}:${mm} ${ap}`;
}

function applyTheme(info) {
  const theme = (info && info.theme) || "tesla";
  document.body.dataset.theme = theme;
  if (info && info.accent) {
    document.documentElement.style.setProperty("--accent", `rgb(${info.accent.join(",")})`);
  }
}

function paintHeader() {
  const h = S.home;
  const unit = (h && h.unit) || "mi";
  const i = (h && h.info) || {};
  const st = (h && h.stats) || {};
  applyTheme(i);
  const pct = h ? ((st.pct == null) ? "\u2014" : Math.round(Number(st.pct) || 0) + "%") : "\u2014";
  const streak = h ? `${fmtDist(st.longest_m, unit, true)} ${unit}` : "\u2014";
  $("hdrStats").innerHTML = `
    <span><em>ENGAGED</em>${pct}</span>
    <span><em>STREAK</em>${streak}</span>`;
  $("drawerFoot").textContent = i.branch ? `${i.branch}  ${i.version || ""}` : "";
}

function openMenu() {
  $("drawer").classList.add("open");
  $("scrim").hidden = false;
  $("menuBtn").setAttribute("aria-expanded", "true");
  $("drawerClose").focus();
}
function closeMenu() {
  $("drawer").classList.remove("open");
  $("scrim").hidden = true;
  $("menuBtn").setAttribute("aria-expanded", "false");
}

function setPage(p, id) {
  if (!PAGES.includes(p)) p = "home";
  if (p !== "shots") { S.shotView = null; S.shotPick = false; document.onkeydown = null; }
  if (p !== "vslam") { S.vslamId = null; S.vslamDetail = null; killMap(); }
  S.page = p;
  S.vslamId = p === "vslam" ? (id || null) : null;
  location.hash = S.vslamId ? `vslam/${S.vslamId}` : p;
  document.querySelectorAll("#drawer nav button").forEach(b => b.classList.toggle("on", b.dataset.page === p));
  closeMenu();
  render();
  if (p === "shots") loadShots();
  if (p === "vslam") loadVslam(S.vslamId);
}

function ringSVG(pct) {
  const r = 52, c = 2 * Math.PI * r, gap = c * 0.12, run = c - gap;
  const dash = Math.max(0, Math.min(1, pct / 100)) * run;
  return `<svg viewBox="0 0 120 120" role="img" aria-label="${pct} percent engaged">
    <circle class="track" cx="60" cy="60" r="${r}" stroke-dasharray="${run} ${gap}"/>
    <circle class="fill" cx="60" cy="60" r="${r}" stroke-dasharray="${dash} ${c}"/>
  </svg>`;
}

function niceTop(peakM, unit) {
  const u = unit === "km" ? 1000 : 1609.344;
  const v = Math.max(0, peakM) / u;
  if (v <= 0) return u;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (v <= m * mag) return m * mag * u;
  }
  return 10 * mag * u;
}
function fmtPair(eng, tot, unit) {
  return fmtDist(eng, unit) + " / " + fmtDist(tot, unit) + " " + unit;
}

function hChartHTML(title, right, items, current, labels, unit) {
  const totals = items.map(x => x.m || 0);
  const peak = Math.max(0, ...totals);
  const scale = niceTop(peak, unit);
  return `<section class="widget">
    <div class="h-row"><h2 class="week-title">${esc(title)}</h2><span class="badge">${right}</span></div>
    <div class="hrows" aria-label="${esc(title)}">
      ${items.map((it, i) => {
        const tot = it.m || 0, eng = it.e || 0;
        const tw = scale > 0 ? Math.max(0, 100 * tot / scale) : 0;
        const ew = scale > 0 ? Math.max(0, 100 * eng / scale) : 0;
        const txt = fmtPair(eng, tot, unit);
        const inside = tw >= 28;
        return `<div class="hrow${i === current ? " now" : ""}">
          <div class="hname">${labels[i] || ""}</div>
          <div class="htrack">
            <div class="hfill" style="width:${tw}%"></div>
            <div class="heng" style="width:${ew}%"></div>
            <span class="hval${inside ? " in" : ""}">${txt}</span>
          </div>
        </div>`;
      }).join("")}
    </div>
  </section>`;
}

function homeHTML() {
  const h = S.home;
  const st = (h && h.stats) || {};
  const u = (h && h.unit) || "mi";
  const pct = st.pct || 0;
  const streak = st.streak_days || 0;
  const week = st.week_days || Array.from({ length: 7 }, () => ({ m: 0, e: 0 }));
  const months = st.months || [];
  const monthLabs = months.map(m => {
    try { return MONTHS[Number(String(m.id).split("-")[1]) - 1] || ""; } catch (e) { return ""; }
  });
  const curMonth = months.findIndex(m => m.current);
  const curWeek = (new Date().getDay());
  return `<div class="stack">
    <div class="hero">
      <div class="ring-wrap">
        ${ringSVG(pct)}
        <div class="ring-copy"><div class="pct">${pct}%</div><div class="sub">Engaged</div></div>
      </div>
      <div class="hero-side">
        <div class="metric"><div class="k">Longest streak</div>
          <div class="v ok">${fmtDist(st.longest_m, u, true)} ${u}</div></div>
        <div class="metric"><div class="k">Engaged</div>
          <div class="v">${fmtDist(st.life_e, u)} <span class="of">of ${fmtDist(st.life_m, u)} ${u}</span></div></div>
      </div>
    </div>
    <section>
      <h2 class="week-title">${streak} Day Streak</h2>
      <div class="week-row">
        ${WEEKDAYS.map((d, i) => {
          const on = week[i] && (week[i].e || 0) > 1;
          return `<div><div class="check${on ? " on" : ""}" aria-label="${d}${on ? " engaged" : ""}">${on ? CHECK : ""}</div><div class="dow">${d}</div></div>`;
        }).join("")}
      </div>
    </section>
    ${hChartHTML("Weekly Engaged", fmtPair(st.week_e, st.week_m, u), week, curWeek, WEEKDAYS, u)}
    ${hChartHTML("Monthly Engaged", fmtPair(st.life_e, st.life_m, u), months, Math.max(0, curMonth), monthLabs, u)}
  </div>`;
}

function shotUrl(name) { return "/api/screenshots/raw?name=" + encodeURIComponent(name); }
function shotDay(s) {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(s.name || "");
  return m ? m[1] : (s.mtime ? new Date(s.mtime * 1000).toISOString().slice(0, 10) : "unknown");
}
function shotWhen(s) {
  const m = /^(\d{4}-\d{2}-\d{2})--(\d{2})-(\d{2})-(\d{2})/.exec(s.name || "");
  if (m) return `${m[2]}:${m[3]}:${m[4]}`;
  return s.mtime ? new Date(s.mtime * 1000).toLocaleTimeString() : "";
}
function shotGroups() {
  const g = [], map = {};
  for (const s of S.shots) {
    const d = shotDay(s);
    if (!map[d]) { map[d] = []; g.push([d, map[d]]); }
    map[d].push(s);
  }
  return g;
}
function selectedNames() { return Object.keys(S.shotSel).filter(n => S.shotSel[n]); }

function shotTile(s) {
  const on = !!S.shotSel[s.name];
  return `<button class="shot${on ? " sel" : ""}" data-shot="${esc(s.name)}" type="button" aria-label="${esc(s.name)}">
    ${S.shotPick ? `<span class="mark"></span>` : ""}
    <img src="${shotUrl(s.name)}" alt="" loading="lazy"/>
    <figcaption><b>${shotWhen(s)}</b><em>${bytes(s.size)}</em></figcaption>
  </button>`;
}

function lightboxHTML() {
  const i = S.shots.findIndex(s => s.name === S.shotView);
  const s = i >= 0 ? S.shots[i] : null;
  if (!s) return "";
  return `<div class="lb" id="lightbox" role="dialog" aria-modal="true" aria-label="${esc(s.name)}">
    <div class="lb-bar">
      <button class="btn" id="lbClose" type="button">Close</button>
      <b>${esc(s.name)}</b>
      <button class="btn" id="lbPrev" type="button" ${i <= 0 ? "disabled" : ""} aria-label="Previous">\u25c0</button>
      <button class="btn" id="lbNext" type="button" ${i >= S.shots.length - 1 ? "disabled" : ""} aria-label="Next">\u25b6</button>
      <a class="btn" id="lbDl" href="${shotUrl(s.name)}" download="${esc(s.name)}">Download</a>
      <button class="btn live" id="lbDel" type="button">Delete</button>
    </div>
    <div class="lb-stage"><img src="${shotUrl(s.name)}" alt="${esc(s.name)}"/></div>
  </div>`;
}

function confirmHTML() {
  if (!S.confirm) return "";
  return `<div class="modal" role="dialog" aria-modal="true"><div class="sheet">
    <p>${esc(S.confirm.msg)}</p>
    <div class="row">
      <button class="btn" id="cfNo" type="button">Cancel</button>
      <button class="btn live" id="cfYes" type="button">Delete</button>
    </div>
  </div></div>`;
}

function shotsHTML() {
  const n = S.shots.length;
  const bytesTotal = S.shots.reduce((a, s) => a + (s.size || 0), 0);
  const picked = selectedNames();
  const groups = shotGroups();
  return `<div class="stack">
    <div class="h-row"><p class="h-label">Screenshots</p>
      <span class="badge">${n} \u00b7 ${bytes(bytesTotal)}</span></div>
    <div class="live-tools">
      <button class="btn primary" id="shotCap" type="button">Capture</button>
      <button class="btn" id="shotRefresh" type="button">Refresh</button>
      <button class="btn${S.shotPick ? " on" : ""}" id="shotPick" type="button">${S.shotPick ? "Done" : "Select"}</button>
      ${S.shotPick && picked.length ? `<button class="btn live" id="shotDel" type="button">Delete ${picked.length}</button>` : ""}
    </div>
    <p class="tiny">Hold the C4 display 3s, or Capture here. Raw PNGs in /data/media/0/screenshots.</p>
    ${n ? groups.map(([day, items]) => `
      <p class="h-label day-label">${day}</p>
      <div class="gallery">${items.map(shotTile).join("")}</div>`).join("") :
      `<div class="card"><b>No screenshots yet</b><p class="tiny">Hold the display for 3 seconds, or tap Capture.</p></div>`}
  </div>` + (S.shotView ? lightboxHTML() : "") + confirmHTML();
}

function bindConfirm() {
  if (!S.confirm) return;
  $("cfNo").onclick = () => { S.confirm = null; render(); };
  $("cfYes").onclick = () => { const go = S.confirm.go; S.confirm = null; go(); };
}

function bindLightbox() {
  if (!$("lightbox")) return;
  $("lbClose").onclick = () => { S.shotView = null; render(); };
  $("lbPrev").onclick = () => stepShot(-1);
  $("lbNext").onclick = () => stepShot(1);
  $("lbDel").onclick = () => deleteShots([S.shotView]);
  const stage = document.querySelector(".lb-stage");
  let x0 = null;
  stage.ontouchstart = (e) => { x0 = e.changedTouches[0].clientX; };
  stage.ontouchend = (e) => {
    if (x0 == null) return;
    const dx = e.changedTouches[0].clientX - x0;
    x0 = null;
    if (dx > 50) stepShot(-1);
    if (dx < -50) stepShot(1);
  };
  document.onkeydown = (e) => {
    if (e.key === "Escape") { S.shotView = null; render(); }
    if (e.key === "ArrowLeft") stepShot(-1);
    if (e.key === "ArrowRight") stepShot(1);
  };
}

function stepShot(d) {
  const i = S.shots.findIndex(s => s.name === S.shotView);
  const n = i + d;
  if (n < 0 || n >= S.shots.length) return;
  S.shotView = S.shots[n].name;
  render();
}

function tapShot(name) {
  if (S.shotPick) {
    S.shotSel[name] = !S.shotSel[name];
    render();
    return;
  }
  S.shotView = name;
  render();
}

async function loadShots() {
  try {
    const r = await api("/api/screenshots");
    S.shots = r.items || [];
    if (S.shotView && !S.shots.some(s => s.name === S.shotView)) S.shotView = null;
  } catch (e) { say(e.message || "shots failed"); S.shots = []; }
  if (S.page === "shots") render();
}

async function captureShot() {
  try {
    await api("/api/screenshots/capture", { method: "POST" });
    say("capturing\u2026");
    const before = new Set(S.shots.map(s => s.name));
    for (let i = 0; i < 8; i++) {
      await new Promise(r => setTimeout(r, 400));
      await loadShots();
      const neu = S.shots.find(s => !before.has(s.name));
      if (neu) { say("captured"); return; }
    }
    say("no new shot yet \u2014 try again");
  } catch (e) { say(e.message || "capture failed"); }
}

async function deleteShots(names) {
  if (!names.length) return;
  const go = async () => {
    try {
      await api("/api/screenshots/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ names }),
      });
      names.forEach(n => delete S.shotSel[n]);
      if (names.includes(S.shotView)) S.shotView = null;
      say("deleted " + names.length);
      await loadShots();
    } catch (e) { say(e.message || "delete failed"); }
  };
  S.confirm = { msg: `Delete ${names.length} screenshot${names.length > 1 ? "s" : ""}?`, go };
  render();
}

function rgb(c) { return `rgb(${c[0]},${c[1]},${c[2]})`; }
function lerpColor(a, b, t) {
  t = Math.max(0, Math.min(1, t));
  return [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * t));
}
function slamRange(samples) {
  const slam = (samples || []).filter(s => s.in_slam);
  if (!slam.length) return { lo: 0, hi: 0 };
  const vs = slam.map(s => Number(s.v_cruise_mph) || 0);
  return { lo: Math.min(...vs), hi: Math.max(...vs) };
}
function slamColor(v, lo, hi, inSlam) {
  if (!inSlam) return rgb(COL_NOM);
  if (hi <= lo) return rgb(COL_SLOW);
  return rgb(lerpColor(COL_SLOW, COL_FAST, (v - lo) / (hi - lo)));
}
function mph(n) {
  if (n == null || n === "") return "\u2014";
  return Math.round(Number(n)) + " mph";
}

function sparkMini(pts) {
  const w = 88, h = 22, pad = 1.5;
  const raw = pts || [];
  if (raw.length < 2) {
    return `<svg class="spark-mini" viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg>`;
  }
  const vs = raw.map(s => Number(s.v != null ? s.v : s.v_cruise_mph) || 0);
  const slam = raw.map(s => !!(s.s || s.in_slam));
  let mn = Math.min(...vs), mx = Math.max(...vs);
  if (mx - mn < 4) { mx += 2; mn -= 2; }
  const lo = Math.min(...vs.filter((_, i) => slam[i]).concat([mn]));
  const hi = Math.max(...vs.filter((_, i) => slam[i]).concat([mx]));
  const x = i => pad + (i / (raw.length - 1)) * (w - pad * 2);
  const y = v => pad + (1 - (v - mn) / (mx - mn || 1)) * (h - pad * 2);
  let segs = "";
  for (let i = 1; i < raw.length; i++) {
    const c = slamColor(vs[i], lo, hi, !!(slam[i] || slam[i - 1]));
    segs += `<line x1="${x(i - 1).toFixed(1)}" y1="${y(vs[i - 1]).toFixed(1)}" x2="${x(i).toFixed(1)}" y2="${y(vs[i]).toFixed(1)}" stroke="${c}" stroke-width="1.6" stroke-linecap="round"/>`;
  }
  return `<svg class="spark-mini" viewBox="0 0 ${w} ${h}" aria-hidden="true">${segs}</svg>`;
}

function sparkSVG(samples) {
  const pts = samples || [];
  const w = 280, h = 56, pad = 3;
  if (pts.length < 2) {
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg>`;
  }
  const vs = pts.map(s => Number(s.v_cruise_mph) || 0);
  const ps = pts.map(s => Number(s.v_plan_mph) || 0);
  const all = vs.concat(ps);
  let mn = Math.min(...all), mx = Math.max(...all);
  if (mx - mn < 4) { mx += 2; mn -= 2; }
  const rng = { lo: slamRange(pts).lo, hi: slamRange(pts).hi };
  const x = i => pad + (i / (pts.length - 1)) * (w - pad * 2);
  const y = v => pad + (1 - (v - mn) / (mx - mn || 1)) * (h - pad * 2);
  const plan = pts.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(ps[i]).toFixed(1)}`).join(" ");
  let segs = "";
  for (let i = 1; i < pts.length; i++) {
    const c = slamColor(vs[i], rng.lo, rng.hi, !!(pts[i].in_slam || pts[i - 1].in_slam));
    segs += `<line x1="${x(i - 1).toFixed(1)}" y1="${y(vs[i - 1]).toFixed(1)}" x2="${x(i).toFixed(1)}" y2="${y(vs[i]).toFixed(1)}" stroke="${c}" stroke-width="2" stroke-linecap="round"/>`;
  }
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${plan}" fill="none" stroke="rgba(255,255,255,.28)" stroke-width="1.2" stroke-dasharray="3 3"/>
    ${segs}
  </svg>`;
}

function vslamListHTML() {
  const on = !!S.vslam.enabled;
  const filt = !!S.vslam.filter_enabled;
  const opLong = !!S.vslam.op_long;
  const evs = S.vslam.events || [];
  return `<div class="stack">
    <div class="h-row"><p class="h-label">vSlam Settings</p>
      <span class="badge">${evs.length} event${evs.length === 1 ? "" : "s"}</span></div>
    <div class="live-tools">
      <button class="btn${on ? " primary" : ""}" id="vslamToggle" type="button">${on ? "Logger on" : "Logger off"}</button>
      <button class="btn${filt ? " primary" : ""}" id="vslamFilterToggle" type="button" ${opLong ? "" : "disabled"}>${filt ? "Filter on" : (opLong ? "Filter off" : "Filter locked (TACC)")}</button>
      <button class="btn" id="vslamRefresh" type="button">Refresh</button>
    </div>
    <p class="tiny">Logger = observe-only paper trail. Filter = counters Tesla phantom braking on OP long (locked on TACC). Same as Settings \u2192 vSlam Settings.</p>
    <div class="spark-key"><span class="k nom">nominal</span><span class="k lo">slowest slam</span><span class="k hi">highest in slam</span></div>
    ${evs.length ? `<div class="vslam-list">${evs.map(ev => {
      const title = ev.place || ev.road || ev.local_time || ev.id;
      const sub = [ev.local_time, `${mph(ev.pre_mph)} \u2192 ${mph(ev.slam_mph)}`, ev.recovered ? "recovered" : "open"].filter(Boolean).join(" \u00b7 ");
      return `<button class="vslam-row" type="button" data-vslam="${esc(ev.id)}">
        <div class="vr-text"><b>${esc(title)}</b><em>${esc(sub)}</em></div>
        <div class="vr-side">
          <span class="vr-delta">${Math.round(Number(ev.delta_mph) || 0)} mph</span>
          ${sparkMini(ev.spark)}
        </div>
      </button>`;
    }).join("")}</div>` :
      `<div class="card"><b>No slams logged</b><p class="tiny">Drive onroad with the logger on. Events land in /data/vslam.</p></div>`}
  </div>`;
}

function vslamDetailHTML() {
  const d = S.vslamDetail;
  if (!d || d.error) {
    return `<div class="stack">
      <div class="live-tools"><button class="btn" id="vslamBack" type="button">Back</button></div>
      <div class="card"><b>${esc((d && d.error) || "missing event")}</b></div>
    </div>`;
  }
  const ev = d.event || {};
  const samples = (d.trace && d.trace.samples) || [];
  const title = ev.place || ev.road || ev.local_time || ev.id;
  const gps = samples.some(s => Math.abs(s.lat || 0) > 1e-4);
  return `<div class="stack">
    <div class="h-row"><p class="h-label">vSlam</p>
      <button class="btn" id="vslamBack" type="button">Back</button></div>
    <div class="card">
      <b>${esc(title)}</b>
      <p class="tiny">${esc(ev.local_time || "")} \u00b7 ${mph(ev.pre_mph)} \u2192 ${mph(ev.slam_mph)} \u00b7 ${ev.duration_s || 0}s${ev.recovered ? " \u00b7 recovered" : ""}</p>
      <p class="tiny">${esc(ev.route || "")}</p>
    </div>
    ${sparkSVG(samples)}
    <div class="spark-key"><span class="k nom">vCruise nominal</span><span class="k lo">slowest</span><span class="k hi">highest</span><span class="k plan">vPlan</span></div>
    ${gps ? `<div id="vslamMap" class="vslam-map" role="img" aria-label="slam map"></div>` :
      `<p class="tiny">No GPS on this trace \u2014 map skipped.</p>`}
  </div>`;
}

function killMap() {
  if (_map) {
    try { _map.remove(); } catch (e) { /* ignore */ }
    _map = null;
  }
}

function paintMap() {
  const el = $("vslamMap");
  if (!el || typeof L === "undefined") return;
  killMap();
  const samples = ((S.vslamDetail && S.vslamDetail.trace && S.vslamDetail.trace.samples) || [])
    .filter(s => Math.abs(s.lat || 0) > 1e-4 && Math.abs(s.lon || 0) > 1e-4);
  if (samples.length < 2) {
    el.innerHTML = `<p class="tiny" style="padding:12px">Not enough GPS points.</p>`;
    return;
  }
  const rng = slamRange(samples);
  _map = L.map(el, { zoomControl: true, attributionControl: false });
  // Carto Positron is a clean vector-styled basemap. Grayscale is applied to
  // the tile pane only so the vSlam color line stays saturated.
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 20,
    subdomains: "abcd",
  }).addTo(_map);
  const tilePane = _map.getPane("tilePane");
  if (tilePane) tilePane.style.filter = "grayscale(1) contrast(1.18) brightness(1.04)";
  const latlngs = [];
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i];
    const pair = [[a.lat, a.lon], [b.lat, b.lon]];
    latlngs.push(pair[0], pair[1]);
    L.polyline(pair, {
      color: slamColor(b.v_cruise_mph, rng.lo, rng.hi, !!(a.in_slam || b.in_slam)),
      weight: 5,
      opacity: 0.95,
      lineCap: "round",
    }).addTo(_map);
  }
  try { _map.fitBounds(L.latLngBounds(latlngs), { padding: [16, 16] }); }
  catch (e) { _map.setView(latlngs[0], 16); }
}

async function loadVslam(id) {
  try {
    const list = await api("/api/vslam");
    S.vslam = {
      enabled: !!list.enabled,
      filter_enabled: !!list.filter_enabled,
      op_long: !!list.op_long,
      events: list.events || [],
      count: list.count || 0,
    };
  } catch (e) {
    say(e.message || "vslam list failed");
  }
  if (id) {
    try {
      S.vslamDetail = await api("/api/vslam/event?id=" + encodeURIComponent(id));
    } catch (e) {
      S.vslamDetail = { error: e.message || "event failed" };
    }
  } else {
    S.vslamDetail = null;
  }
  if (S.page === "vslam") {
    render();
    if (S.vslamId) requestAnimationFrame(paintMap);
  }
}

async function toggleVslam() {
  const next = !S.vslam.enabled;
  try {
    const r = await api("/api/vslam/enabled", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: next }),
    });
    S.vslam.enabled = !!r.enabled;
    say(S.vslam.enabled ? "vSlam logger on" : "vSlam logger off");
    render();
  } catch (e) { say(e.message || "toggle failed"); }
}

async function toggleVslamFilter() {
  if (!S.vslam.op_long) {
    say("Filter locked while TACC owns long");
    return;
  }
  const next = !S.vslam.filter_enabled;
  try {
    const r = await api("/api/vslam/filter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filter_enabled: next }),
    });
    S.vslam.filter_enabled = !!r.filter_enabled;
    S.vslam.op_long = !!r.op_long;
    say(S.vslam.filter_enabled ? "vSlam filter on" : "vSlam filter off");
    render();
  } catch (e) { say(e.message || "filter toggle failed"); }
}

function bindPage() {
  if (S.page === "shots") {
    $("shotCap").onclick = () => captureShot();
    $("shotRefresh").onclick = () => loadShots();
    $("shotPick").onclick = () => { S.shotPick = !S.shotPick; if (!S.shotPick) S.shotSel = {}; render(); };
    const del = $("shotDel");
    if (del) del.onclick = () => deleteShots(selectedNames());
    $("page").querySelectorAll("[data-shot]").forEach(b => b.onclick = () => tapShot(b.dataset.shot));
    bindLightbox();
    bindConfirm();
  }
  if (S.page === "vslam") {
    const tog = $("vslamToggle");
    if (tog) tog.onclick = () => toggleVslam();
    const ft = $("vslamFilterToggle");
    if (ft) ft.onclick = () => toggleVslamFilter();
    const ref = $("vslamRefresh");
    if (ref) ref.onclick = () => loadVslam(S.vslamId);
    const back = $("vslamBack");
    if (back) back.onclick = () => setPage("vslam");
    $("page").querySelectorAll("[data-vslam]").forEach(b => b.onclick = () => setPage("vslam", b.dataset.vslam));
  }
}

function pageHTML() {
  if (S.page === "vslam") return S.vslamId ? vslamDetailHTML() : vslamListHTML();
  if (S.page === "shots") return shotsHTML();
  return homeHTML();
}

function render() {
  const root = $("page");
  killMap();
  root.innerHTML = pageHTML();
  bindPage();
}

async function refreshHome() {
  try {
    S.home = await api("/api/home");
    paintHeader();
    if (S.page === "home") render();
  } catch (e) { /* keep last */ }
}

function boot() {
  tickClock();
  setInterval(tickClock, 10000);
  $("menuBtn").onclick = openMenu;
  $("drawerClose").onclick = closeMenu;
  $("scrim").onclick = closeMenu;
  document.querySelectorAll("#drawer nav button").forEach(b => b.onclick = () => setPage(b.dataset.page));
  document.querySelectorAll("#drawer nav button").forEach(b => b.classList.toggle("on", b.dataset.page === S.page));
  window.addEventListener("hashchange", () => {
    const h = parseHash();
    if (h.page !== S.page || h.id !== S.vslamId) setPage(h.page, h.id);
  });
  render();
  api("/api/home").then(home => {
    S.home = home;
    paintHeader();
    render();
    if (S.page === "shots") loadShots();
    if (S.page === "vslam") loadVslam(S.vslamId);
  }).catch(() => say("device unreachable"));
  setInterval(refreshHome, 4000);
}

document.addEventListener("DOMContentLoaded", boot);
