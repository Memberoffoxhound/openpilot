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
  vslam: { enabled: true, events: [], count: 0 },
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
    <span><em>STREAK</em>${streak}</span>
    <span><em>TODAY</em>${h ? fmtDist(st.today_m, unit) : "\u2014"} ${unit}</span>
    <span><em>WEEK</em>${h ? fmtDist(st.week_m, unit) : "\u2014"} ${unit}</span>`;
  $("drawerFoot").textContent = i.branch ? `${i.branch}  ${i.version || ""}` : "";
}
