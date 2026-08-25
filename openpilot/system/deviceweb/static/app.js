/* S3XYPilot LAN console — mobile-first */
const PAGES = ["home", "settings", "live", "grok", "shots"];
const CAMS = [
  { id: "wideRoad", label: "E CAM" },
  { id: "road", label: "F CAM" },
  { id: "driver", label: "D CAM" },
];
const PIP_CORNERS = ["br", "bl", "tl", "tr"];
const GROUPS = [
  { id: "drive", title: "Driving", items: [
    { key: "OpenpilotEnabledToggle", label: "Enable S3XYPilot", type: "bool", desc: "Master switch. Restart required.", restart: true },
    { key: "ExperimentalMode", label: "Experimental mode", type: "bool", desc: "End-to-end longitudinal.", confirm: "Experimental mode uses the model for gas and brake. Stay ready to take over." },
    { key: "AutoLaneChangeEnabled", label: "Auto lane change", type: "bool", desc: "Nudgeless after Tesla stock BSM is clear.", confirm: "Auto lane change uses Tesla stock BSM. You still own the merge." },
    { key: "LongitudinalPersonality", label: "Driving personality", type: "select", desc: "How hard it follows the lead.", options: [["0", "Aggressive"], ["1", "Standard"], ["2", "Relaxed"]] },
    { key: "IsLdwEnabled", label: "Lane departure warnings", type: "bool", desc: "Alert when you drift without a signal." },
    { key: "AlwaysOnDM", label: "Always-on driver monitor", type: "bool", desc: "Keep DM running when not engaged." },
    { key: "IsMetric", label: "Use metric units", type: "bool", desc: "Show km/h instead of mph." },
    { key: "DisengageOnAccelerator", label: "Disengage on accelerator", type: "bool", desc: "Cancel when you press the pedal." },
    { key: "RecordFront", label: "Record cabin camera", type: "bool", desc: "Upload dcam. Restart required.", restart: true },
    { key: "RecordAudio", label: "Record microphone", type: "bool", desc: "Store mic audio. Restart required.", restart: true },
  ]},
  { id: "theme", title: "Theme", items: [
    { key: "CustomOnroadUi", label: "Onroad UI", type: "select", desc: "Stock HUD or custom compass / lanes.", options: [["0", "Stock"], ["1", "Custom"]] },
    { key: "LaneColor", label: "Lane color", type: "select", desc: "Engaged lane lines.", options: [["1", "Tesla blue"], ["0", "comma green"]] },
    { key: "CompassSize", label: "Compass size", type: "select", desc: "Custom onroad compass.", options: [["0", "Small"], ["1", "Large"]] },
    { key: "Delorean", label: "Delorean", type: "bool", desc: "88 mph clip on going onroad." },
  ]},
  { id: "device", title: "Device", items: [
    { key: "SshEnabled", label: "Enable SSH", type: "bool", desc: "Allow SSH from your GitHub keys." },
    { key: "AdbEnabled", label: "Enable ADB", type: "bool", desc: "Android debug bridge on the C4." },
    { key: "DisablePowerDown", label: "Disable power down", type: "bool", desc: "Keep awake after the car is off." },
    { key: "DisableUpdates", label: "Disable updates", type: "bool", desc: "Stop the stock updater from fetching." },
  ]},
  { id: "network", title: "Network", items: [
    { key: "GsmRoaming", label: "Cellular roaming", type: "bool", desc: "Allow the SIM to roam.", deviceOnly: true },
    { key: "GsmMetered", label: "Metered cellular", type: "bool", desc: "Treat the SIM as metered.", deviceOnly: true },
    { key: "NetworkMetered", label: "Metered network", type: "bool", desc: "Limit background uploads.", deviceOnly: true },
  ]},
  { id: "developer", title: "Developer", items: [
    { key: "ShowDebugInfo", label: "Show debug info", type: "bool", desc: "FPS and touch dots." },
    { key: "JoystickDebugMode", label: "Joystick debug", type: "bool", desc: "Replace controls with joystick." },
  ]},
];

const S = {
  page: (location.hash.replace("#", "") || "home"),
  home: null,
  params: {},
  grok: { topics: "npr", suggestions: [], duration: 60, wifi_only: false, every_drive: false, provider: "xai", howto: {} },
  routes: [],
  topicDraft: "",
  toast: "",
  confirm: null,
  map: null,
  mapLine: null,
  mapMark: null,
  player: null,
  route: null,
  seg: 0,
  pc: null,
  liveOn: false,
  webrtc: false,
  layout: "triple",
  pipCorner: "br",
  singleCam: "road",
  shots: [],
  shotView: null,
  shotPick: false,
  shotSel: {},
};

if (!PAGES.includes(S.page)) S.page = "home";

async function api(url, opt) {
  const r = await fetch(url, opt);
  const t = await r.text();
  try { return JSON.parse(t); } catch { throw new Error(t || r.statusText); }
}
function $(id) { return document.getElementById(id); }
function bytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(0) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
  return (n / 1073741824).toFixed(1) + " GB";
}
function say(m) {
  S.toast = m;
  const el = $("toast");
  el.hidden = false;
  el.textContent = m;
  clearTimeout(say._t);
  say._t = setTimeout(() => { S.toast = ""; el.hidden = true; }, 2800);
}
function on(v) { return v === true || v === 1 || v === "1"; }

function tickClock() {
  const d = new Date();
  const days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const mons = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  let h = d.getHours(), ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, "0");
  $("clock").textContent = `${days[d.getDay()]} ${mons[d.getMonth()]} ${d.getDate()}  ·  ${h}:${mm} ${ap}`;
}

function hdrVal(v, s) { return (v == null || v === "") ? "—" : v + s; }
function paintHeader() {
  const h = S.home;
  const unit = (h && h.unit) || "mi";
  const i = (h && h.info) || {};
  $("hdrStats").innerHTML = `
    <span><em>TODAY</em>${h ? h.today.toFixed(1) : "—"} ${unit}</span>
    <span><em>WEEK</em>${h ? h.week.toFixed(1) : "—"} ${unit}</span>
    <span><em>CPU</em>${hdrVal(i.tempC, "°")} · ${hdrVal(i.cpuPct, "%")}</span>
    <span><em>MEM</em>${hdrVal(i.memPct, "%")}</span>`;
  $("drawerFoot").textContent = i.branch ? `${i.branch}  ${i.version || ""}` : "";
}

function setPage(p) {
  if (!PAGES.includes(p)) p = "home";
  if (S.page === "live" && p !== "live") hangup();
  if (S.page === "home" && p !== "home") teardownHome();
  if (p !== "shots") { S.shotView = null; S.shotPick = false; document.onkeydown = null; }
  S.page = p;
  location.hash = p;
  document.querySelectorAll("#drawer nav button").forEach(b => b.classList.toggle("on", b.dataset.page === p));
  closeMenu();
  render();
  if (p === "shots") loadShots();
}

function openMenu() { $("drawer").classList.add("open"); $("scrim").hidden = false; }
function closeMenu() { $("drawer").classList.remove("open"); $("scrim").hidden = true; }

function render() {
  const root = $("page");
  if (S.page === "home") root.innerHTML = homeHTML();
  else if (S.page === "settings") root.innerHTML = settingsHTML();
  else if (S.page === "live") root.innerHTML = liveHTML();
  else if (S.page === "grok") root.innerHTML = grokHTML();
  else root.innerHTML = shotsHTML();
  bindPage();
  if (S.page === "home") setupHome();
  if (S.page === "live") bindVideos();
}

function homeHTML() {
  const h = S.home;
  const u = (h && h.unit) || "mi";
  const net = h && h.info && h.info.network;
  return `<div class="stack">
    <div class="h-row"><p class="h-label">Engagement</p>
      <span class="badge">${h && h.engaged ? "ENGAGED" : (h && h.offroad ? "OFFROAD" : "ONROAD")} · ${net || ""}</span></div>
    <div class="grid">
      <div class="stat"><div class="k">Today</div><div class="v">${h ? h.today.toFixed(1) : "—"} <span class="tiny">${u}</span></div></div>
      <div class="stat"><div class="k">Today engaged</div><div class="v">${h ? h.todayEng.toFixed(1) : "—"} <span class="tiny">${u}</span></div></div>
      <div class="stat"><div class="k">Week</div><div class="v">${h ? h.week.toFixed(1) : "—"} <span class="tiny">${u}</span></div></div>
      <div class="stat"><div class="k">Engaged</div><div class="v">${h ? h.engPct : "—"}<span class="tiny">%</span></div></div>
    </div>
    <div class="card mapwrap">
      <div id="map"></div>
      <button type="button" id="mapGps" class="map-gps" aria-label="Center on GPS" title="Center on GPS">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>
          <path d="M12 2.5v3.2M12 18.3v3.2M2.5 12h3.2M18.3 12h3.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="square"/>
        </svg>
      </button>
    </div>
    <div class="h-row"><p class="h-label">Route player</p><span class="tiny">qcamera.ts on device</span></div>
    <div class="player" id="playerBox" hidden>
      <video id="qcam" playsinline controls></video>
      <div class="bar">
        <button class="btn" id="prevSeg">◀</button>
        <span class="tiny" id="segLabel"></span>
        <button class="btn" id="nextSeg">▶</button>
      </div>
    </div>
    <div class="card list" id="routeList">${routeListHTML()}</div>
  </div>`;
}

function routeListHTML() {
  if (!S.routes.length) return `<div class="set"><div class="meta"><b>No routes yet</b><p>Drives land in /data/media/0/realdata.</p></div></div>`;
  return S.routes.map(r => {
    const when = r.mtime ? new Date(r.mtime * 1000).toLocaleString() : r.name;
    const on = S.route && S.route.name === r.name ? " on" : "";
    return `<button class="file${on}" data-route="${r.name}">
      <b>${r.name}</b>
      <em>${r.segments} seg · ${bytes(r.bytes)} · ${when}</em>
    </button>`;
  }).join("");
}

function settingsHTML() {
  return `<div class="stack">${GROUPS.map(g => `
    <p class="h-label">${g.title}</p>
    <div class="card">${g.items.map(itemHTML).join("")}</div>`).join("")}
    <div class="seg">
      <button class="btn" id="reboot">Reboot</button>
      <button class="btn" id="shutdown">Shutdown</button>
    </div>
  </div>` + (S.confirm ? confirmHTML() : "");
}

function itemHTML(it) {
  const locked = it.deviceOnly;
  const val = S.params[it.key];
  if (it.type === "select") {
    const opts = (it.options || []).map(([k, l]) => `<option value="${k}" ${String(val) === String(k) ? "selected" : ""}>${l}</option>`).join("");
    return `<div class="set${locked ? " locked" : ""}"><div class="meta"><b>${it.label}</b><p>${it.desc}</p></div>
      <select data-key="${it.key}" ${locked ? "disabled" : ""}>${opts}</select></div>`;
  }
  return `<div class="set${locked ? " locked" : ""}"><div class="meta"><b>${it.label}</b><p>${it.desc}${it.restart ? " Restart to apply." : ""}</p></div>
    <button class="tog${on(val) ? " on" : ""}" data-key="${it.key}" ${locked ? "disabled" : ""} aria-pressed="${on(val)}"><i></i></button></div>`;
}

function confirmHTML() {
  const c = S.confirm;
  return `<div class="modal"><div class="sheet">
    <p>${c.msg}</p>
    <div class="seg" style="margin-top:12px">
      <button class="btn primary" id="confirmYes">Confirm</button>
      <button class="btn" id="confirmNo">Cancel</button>
    </div>
  </div></div>`;
}

function liveHTML() {
  const air = S.liveOn;
  return `<div class="stack">
    <div class="h-row">
      <p class="h-label">WebRTC · 720p VBR up to 6 Mb/s</p>
      <span class="badge"><span class="dot${air ? " live" : ""}"></span> ${air ? "ON AIR" : "STANDBY"}</span>
    </div>
    <div class="live-tools">
      <button class="btn${air ? " live" : " primary"}" id="airBtn">${air ? "End" : "Go live"}</button>
      <button class="btn" data-layout="triple">3-up</button>
      <button class="btn" data-layout="one" data-cam="road">F</button>
      <button class="btn" data-layout="one" data-cam="wideRoad">E</button>
      <button class="btn" data-layout="one" data-cam="driver">D</button>
      <button class="btn" data-layout="pip" data-cam="road">F + D</button>
      <button class="btn" data-layout="pip" data-cam="wideRoad">E + D</button>
      <button class="btn" id="fsBtn">Fullscreen</button>
    </div>
    <div id="stage" class="stage ${stageClass()}">
      ${CAMS.map(c => `<div class="tile" data-cam="${c.id}"><video playsinline autoplay muted></video><label>${c.label}</label></div>`).join("")}
    </div>
    <p class="tiny">Three cameras at once (BTTF2). PIP d-cam tap cycles corners. Fullscreen is 16:9 black for Discord / Twitch capture.</p>
  </div>`;
}

function stageClass() {
  if (S.layout === "triple") return "triple";
  if (S.layout === "pip") return `pip pip-${S.pipCorner}`;
  return "one";
}

function grokHTML() {
  const g = S.grok;
  const topics = (g.topics || "npr").split(/\n|,/).map(s => s.trim()).filter(Boolean).slice(0, 6);
  const mode = String(S.params.WeatherNewsMode || "1");
  const howto = g.howto || {};
  const providers = [
    { id: "xai", name: "xAI Grok", masked: g.masked, field: "api_key", ph: "xai-…" },
    { id: "openai", name: "OpenAI", masked: g.openai_masked, field: "openai_key", ph: "sk-…" },
    { id: "groq", name: "Groq", masked: g.groq_masked, field: "groq_key", ph: "gsk_…" },
  ];
  const sug = filterSuggest(S.topicDraft, topics);
  return `<div class="stack">
    <p class="h-label">Weather + news</p>
    <div class="card">
      <div class="set"><div class="meta"><b>Grok voice</b><p>Ara speaks the briefing. Weather is always included.</p></div>
        <button class="tog${g.voice_on ? " on" : ""}" id="voiceOn"><i></i></button></div>
      <div class="set"><div class="meta"><b>Mode</b><p>Unhinged is NSFW through the speaker.</p></div>
        <div class="seg">
          <button class="btn${mode === "1" ? " on" : ""}" data-mode="1">Nice</button>
          <button class="btn${mode === "2" ? " on" : ""}" data-mode="2">Unhinged</button>
          <button class="btn${mode === "0" ? " on" : ""}" data-mode="0">Off</button>
        </div></div>
      <div class="set"><div class="meta"><b>Duration</b><p>Spoken length the device uses.</p></div>
        <div class="seg">${[60, 90, 120].map(s => `<button class="btn${g.duration === s ? " on" : ""}" data-dur="${s}">${s}s</button>`).join("")}</div></div>
      <div class="set"><div class="meta"><b>Wi-Fi only</b><p>Skip LTE for fetch + TTS.</p></div>
        <button class="tog${g.wifi_only ? " on" : ""}" id="wifiOnly"><i></i></button></div>
      <div class="set"><div class="meta"><b>Every drive</b><p>Off = first drive of the day. On = start of every drive. For reliability testing.</p></div>
        <button class="tog${g.every_drive ? " on" : ""}" id="everyDrive"><i></i></button></div>
    </div>
    <p class="h-label">Topics · ${topics.length}/6</p>
    <div class="card" style="padding:12px 14px">
      <div class="chips" id="chips">
        <span class="chip locked">weather</span>
        ${topics.map((t, i) => `<span class="chip">${t}<button data-rm="${i}" aria-label="remove">×</button></span>`).join("")}
      </div>
      <input id="topicIn" placeholder="add topic" value="${esc(S.topicDraft)}" ${topics.length >= 6 ? "disabled" : ""}
        autocomplete="off" style="width:100%;margin-top:10px;height:40px;border-radius:8px;background:var(--panel-2);border:1px solid var(--line);padding:0 10px"/>
      ${sug.length ? `<div class="suggest">${sug.map(s => `<button type="button" data-add="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : ""}
    </div>
    <p class="h-label">AI API · plug and play</p>
    ${providers.map(p => `<div class="card">
      <div class="set"><div class="meta"><b>${p.name}</b><p>${howto[p.id] || ""}</p>
        <p class="tiny">${p.masked ? "saved " + p.masked : "no key"}</p></div>
        <button class="btn${g.provider === p.id ? " primary" : ""}" data-prov="${p.id}">${g.provider === p.id ? "Active" : "Use"}</button></div>
      <div class="field"><label>${p.name} key</label>
        <input data-keyfield="${p.field}" placeholder="${p.ph}" autocomplete="off"/>
        <div class="seg" style="margin-top:8px">
          <button class="btn primary" data-savekey="${p.id}">Save</button>
          <button class="btn" data-test="${p.id}">Test</button>
        </div>
      </div>
    </div>`).join("")}
    <div class="seg">
      <button class="btn" id="previewNice">Preview Nice</button>
      <button class="btn" id="previewUnh">Preview Unhinged</button>
    </div>
  </div>` + (S.confirm ? confirmHTML() : "");
}

function shotUrl(name) { return "/api/screenshots/raw?name=" + encodeURIComponent(name); }
function shotDay(s) {
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(s.name || "");
  if (m) return m[1];
  return s.mtime ? new Date(s.mtime * 1000).toISOString().slice(0, 10) : "unknown";
}
function shotWhen(s) {
  const m = /^(\d{4}-\d{2}-\d{2})--(\d{2})-(\d{2})-(\d{2})/.exec(s.name || "");
  if (m) return `${m[2]}:${m[3]}:${m[4]}`;
  return s.mtime ? new Date(s.mtime * 1000).toLocaleTimeString() : "";
}
function shotGroups() {
  const g = [];
  const map = {};
  for (const s of S.shots) {
    const d = shotDay(s);
    if (!map[d]) { map[d] = []; g.push([d, map[d]]); }
    map[d].push(s);
  }
  return g;
}
function selectedNames() { return Object.keys(S.shotSel).filter(n => S.shotSel[n]); }

function shotsHTML() {
  const n = S.shots.length;
  const bytesTotal = S.shots.reduce((a, s) => a + (s.size || 0), 0);
  const picked = selectedNames();
  const groups = shotGroups();
  return `<div class="stack">
    <div class="h-row"><p class="h-label">Screenshots</p>
      <span class="badge">${n} · ${bytes(bytesTotal)}</span></div>
    <div class="live-tools">
      <button class="btn primary" id="shotCap">Capture</button>
      <button class="btn" id="shotRefresh">Refresh</button>
      <button class="btn${S.shotPick ? " on" : ""}" id="shotPick">${S.shotPick ? "Done" : "Select"}</button>
      ${S.shotPick && picked.length ? `<button class="btn live" id="shotDel">Delete ${picked.length}</button>` : ""}
    </div>
    <p class="tiny">Hold the display 3s, or Capture here. PNGs in /data/media/0/screenshots.</p>
    ${n ? groups.map(([day, items]) => `
      <p class="h-label day-label">${day}</p>
      <div class="gallery">${items.map(shotTile).join("")}</div>`).join("") :
      `<div class="card"><div class="set"><div class="meta"><b>No screenshots yet</b><p>Hold the C4 display for 3 seconds, or tap Capture.</p></div></div></div>`}
  </div>` + (S.shotView ? lightboxHTML() : "") + (S.confirm ? confirmHTML() : "");
}

function shotTile(s) {
  const on = !!S.shotSel[s.name];
  return `<button class="shot${on ? " sel" : ""}" data-shot="${esc(s.name)}">
    ${S.shotPick ? `<span class="mark"></span>` : ""}
    <img src="${shotUrl(s.name)}" alt="" loading="lazy"/>
    <figcaption><b>${shotWhen(s)}</b><em>${bytes(s.size)}</em></figcaption>
  </button>`;
}

function lightboxHTML() {
  const i = S.shots.findIndex(s => s.name === S.shotView);
  const s = i >= 0 ? S.shots[i] : null;
  if (!s) return "";
  return `<div class="lb" id="lightbox">
    <div class="lb-bar">
      <button class="btn" id="lbClose">Close</button>
      <b>${esc(s.name)}</b>
      <button class="btn" id="lbPrev" ${i <= 0 ? "disabled" : ""}>◀</button>
      <button class="btn" id="lbNext" ${i >= S.shots.length - 1 ? "disabled" : ""}>▶</button>
      <a class="btn" id="lbDl" href="${shotUrl(s.name)}" download="${esc(s.name)}">Save</a>
      <button class="btn live" id="lbDel">Delete</button>
    </div>
    <div class="lb-stage"><img src="${shotUrl(s.name)}" alt="${esc(s.name)}"/></div>
  </div>`;
}

function esc(s) { return String(s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

function filterSuggest(q, taken) {
  const all = S.grok.suggestions || [];
  const have = new Set(taken.map(t => t.toLowerCase()));
  const qq = (q || "").toLowerCase();
  return all.filter(s => !have.has(s.toLowerCase()) && (!qq || s.toLowerCase().includes(qq))).slice(0, 6);
}

function bindPage() {
  if (S.page === "home") {
    $("page").querySelectorAll("[data-route]").forEach(b => b.onclick = () => pickRoute(b.dataset.route));
    const prev = $("prevSeg"), next = $("nextSeg"), gpsBtn = $("mapGps");
    if (prev) prev.onclick = () => stepSeg(-1);
    if (next) next.onclick = () => stepSeg(1);
    if (gpsBtn) gpsBtn.onclick = () => centerGps();
  }
  if (S.page === "settings") {
    $("page").querySelectorAll(".tog[data-key]").forEach(b => b.onclick = () => toggleParam(b.dataset.key, !b.classList.contains("on")));
    $("page").querySelectorAll("select[data-key]").forEach(s => s.onchange = () => saveParam(s.dataset.key, s.value));
    $("reboot").onclick = () => act("reboot");
    $("shutdown").onclick = () => act("shutdown");
    bindConfirm();
  }
  if (S.page === "live") {
    $("airBtn").onclick = () => S.liveOn ? hangup() : goLive();
    $("fsBtn").onclick = () => toggleFs();
    $("page").querySelectorAll("[data-layout]").forEach(b => b.onclick = () => {
      S.layout = b.dataset.layout;
      if (b.dataset.cam) S.singleCam = b.dataset.cam;
      applyLayout();
    });
  }
  if (S.page === "grok") {
    $("voiceOn").onclick = () => saveGrok({ voice_on: !S.grok.voice_on });
    $("wifiOnly").onclick = () => saveGrok({ wifi_only: !S.grok.wifi_only });
    $("everyDrive").onclick = () => saveGrok({ every_drive: !S.grok.every_drive });
    $("page").querySelectorAll("[data-mode]").forEach(b => b.onclick = () => setMode(b.dataset.mode));
    $("page").querySelectorAll("[data-dur]").forEach(b => b.onclick = () => saveGrok({ duration: Number(b.dataset.dur) }));
    $("page").querySelectorAll("[data-prov]").forEach(b => b.onclick = () => saveGrok({ provider: b.dataset.prov }));
    $("page").querySelectorAll("[data-rm]").forEach(b => b.onclick = () => rmTopic(Number(b.dataset.rm)));
    $("page").querySelectorAll("[data-add]").forEach(b => b.onclick = () => addTopic(b.dataset.add));
    $("page").querySelectorAll("[data-savekey]").forEach(b => b.onclick = (e) => saveProviderKey(b.dataset.savekey, e));
    $("page").querySelectorAll("[data-test]").forEach(b => b.onclick = (e) => testProvider(b.dataset.test, e));
    const tin = $("topicIn");
    if (tin) {
      tin.oninput = () => {
        S.topicDraft = tin.value;
        const box = tin.parentElement;
        let sug = box.querySelector(".suggest");
        const items = filterSuggest(S.topicDraft, topicsArr());
        if (!items.length) { if (sug) sug.remove(); return; }
        if (!sug) { sug = document.createElement("div"); sug.className = "suggest"; box.appendChild(sug); }
        sug.innerHTML = items.map(s => `<button type="button" data-add="${esc(s)}">${esc(s)}</button>`).join("");
        sug.querySelectorAll("[data-add]").forEach(b => b.onclick = () => addTopic(b.dataset.add));
      };
      tin.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); addTopic(tin.value); }
      };
    }
    $("previewNice").onclick = () => preview("nice");
    $("previewUnh").onclick = () => preview("unhinged");
    bindConfirm();
  }
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
    else if (dx < -50) stepShot(1);
  };
  document.onkeydown = (e) => {
    if (S.page !== "shots" || !S.shotView) return;
    if (e.key === "Escape") { S.shotView = null; render(); }
    if (e.key === "ArrowLeft") stepShot(-1);
    if (e.key === "ArrowRight") stepShot(1);
  };
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

function stepShot(d) {
  const i = S.shots.findIndex(s => s.name === S.shotView);
  const n = i + d;
  if (n < 0 || n >= S.shots.length) return;
  S.shotView = S.shots[n].name;
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
    say("capturing…");
    const before = new Set(S.shots.map(s => s.name));
    for (let i = 0; i < 16; i++) {
      await new Promise(r => setTimeout(r, 400));
      await loadShots();
      const neu = S.shots.find(s => !before.has(s.name));
      if (neu) { say("saved"); S.shotView = neu.name; render(); return; }
    }
    say("no new shot — is the UI running?");
  } catch (e) { say(e.message); }
}

async function deleteShots(names) {
  names = (names || []).filter(Boolean);
  if (!names.length) return;
  const go = async () => {
    S.confirm = null;
    try {
      await api("/api/screenshots/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ names }),
      });
      names.forEach(n => delete S.shotSel[n]);
      if (names.includes(S.shotView)) S.shotView = null;
      say("deleted " + names.length);
      await loadShots();
    } catch (e) { say(e.message); }
  };
  S.confirm = { msg: `Delete ${names.length} screenshot${names.length > 1 ? "s" : ""}?`, go };
  render();
}

function bindConfirm() {
  const y = $("confirmYes"), n = $("confirmNo");
  if (y) y.onclick = () => { const c = S.confirm; S.confirm = null; c.go(); };
  if (n) n.onclick = () => { S.confirm = null; render(); };
}

async function saveParam(k, v) {
  try {
    S.params = await api("/api/params", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [k]: v }) });
    if (k === "IsMetric") refreshHome();
    render();
  } catch (e) { say(e.message); }
}

function toggleParam(k, next) {
  const it = GROUPS.flatMap(g => g.items).find(x => x.key === k);
  if (it && it.confirm && next) {
    S.confirm = { msg: it.confirm, go: () => { S.confirm = null; saveParam(k, "1"); } };
    render();
    return;
  }
  saveParam(k, next ? "1" : "0");
}

async function act(kind) {
  if (!confirm(kind + " device?")) return;
  try { await api("/api/action/" + kind, { method: "POST" }); say(kind + " sent"); }
  catch (e) { say(e.message); }
}

async function saveGrok(body) {
  try {
    S.grok = await api("/api/grok", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    render();
  } catch (e) { say(e.message); }
}

function topicsArr() {
  return (S.grok.topics || "").split(/\n|,/).map(s => s.trim()).filter(Boolean).slice(0, 6);
}
function addTopic(t) {
  t = (t || "").trim();
  if (!t) return;
  const cur = topicsArr();
  if (cur.length >= 6) { say("max 6 topics"); return; }
  if (cur.some(x => x.toLowerCase() === t.toLowerCase())) return;
  S.topicDraft = "";
  saveGrok({ topics: cur.concat(t).join("\n") });
}
function rmTopic(i) {
  const cur = topicsArr();
  cur.splice(i, 1);
  saveGrok({ topics: cur.join("\n") });
}

function setMode(m) {
  if (m === "2") {
    S.confirm = { msg: "NSFW. Explicit language through the speaker. Not for kids.", go: () => { S.confirm = null; saveParam("WeatherNewsMode", "2"); } };
    render();
    return;
  }
  saveParam("WeatherNewsMode", m);
}

async function saveProviderKey(id, e) {
  const card = e.target.closest(".card");
  const inp = card.querySelector("[data-keyfield]");
  const field = inp.dataset.keyfield;
  const val = inp.value.trim();
  const body = { provider: id };
  body[field] = val;
  await saveGrok(body);
  say(val ? "key saved" : "key cleared");
}

async function testProvider(id, e) {
  const card = e.target.closest(".card");
  const inp = card.querySelector("[data-keyfield]");
  try {
    const r = await api("/api/grok/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: id, api_key: inp.value.trim() }),
    });
    say(r.ok ? id + " ok" : (r.status || "failed"));
    S.grok = r;
  } catch (e) { say(e.message); }
}

async function preview(mode) {
  try {
    await api("/api/weather/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
    say("preview queued");
  } catch (e) { say(e.message); }
}

function teardownHome() {
  if (S.player) { try { S.player.destroy(); } catch (e) {} S.player = null; }
  if (S.map) { S.map.remove(); S.map = null; S.mapLine = null; S.mapMark = null; }
}

function gpsLatLon() {
  const g = S.home && S.home.gps;
  if (!g || g.lat == null || g.lon == null) return null;
  return [g.lat, g.lon];
}

function centerGps() {
  const ll = gpsLatLon();
  if (!S.map || !ll) { say("no GPS"); return; }
  if (S.mapMark) S.mapMark.setLatLng(ll);
  else S.mapMark = L.circleMarker(ll, { radius: 6, color: "#fff", weight: 2, fillOpacity: 1 }).addTo(S.map);
  S.map.setView(ll, Math.max(S.map.getZoom(), 13));
}

function setupHome() {
  const el = $("map");
  if (!el || S.map || typeof L === "undefined") return;
  const ll = gpsLatLon();
  const lat = ll ? ll[0] : 38.94, lon = ll ? ll[1] : -90.15;
  S.map = L.map(el, { zoomControl: false, attributionControl: true }).setView([lat, lon], ll ? 12 : 4);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OSM &copy; CARTO", maxZoom: 19,
  }).addTo(S.map);
  if (ll) S.mapMark = L.circleMarker(ll, { radius: 6, color: "#fff", weight: 2, fillOpacity: 1 }).addTo(S.map);
  setTimeout(() => S.map && S.map.invalidateSize(), 80);
}

async function pickRoute(name) {
  S.route = S.routes.find(r => r.name === name) || null;
  S.seg = (S.route && S.route.segs && S.route.segs[0]) || 0;
  const box = $("playerBox");
  if (box) box.hidden = !S.route;
  document.querySelectorAll("[data-route]").forEach(b => b.classList.toggle("on", b.dataset.route === name));
  playSeg();
  try {
    const g = await api("/api/route/gps?route=" + encodeURIComponent(name));
    drawTrack(g.points || []);
  } catch (e) { /* map still shows last GPS */ }
}

function drawTrack(pts) {
  if (!S.map || typeof L === "undefined") return;
  if (S.mapLine) { S.map.removeLayer(S.mapLine); S.mapLine = null; }
  if (pts.length < 2) return;
  S.mapLine = L.polyline(pts, { color: "#7ec8ff", weight: 3, opacity: 0.9 }).addTo(S.map);
  S.map.fitBounds(S.mapLine.getBounds(), { padding: [24, 24] });
}

function playSeg() {
  if (!S.route) return;
  const video = $("qcam");
  const label = $("segLabel");
  if (label) label.textContent = `${S.route.name}  ·  ${S.seg + 1}/${S.route.segments}`;
  if (!video) return;
  if (S.player) { try { S.player.destroy(); } catch (e) {} S.player = null; }
  const url = `/api/qcam?route=${encodeURIComponent(S.route.name)}&seg=${S.seg}`;
  video.onended = () => stepSeg(1);
  if (typeof mpegts !== "undefined" && mpegts.isSupported()) {
    S.player = mpegts.createPlayer({ type: "mpegts", isLive: false, url }, { enableWorker: true, lazyLoad: false });
    S.player.attachMediaElement(video);
    S.player.load();
    S.player.play().catch(() => {});
  } else {
    video.src = url;
    video.play().catch(() => {});
  }
}

function stepSeg(d) {
  if (!S.route) return;
  const segs = S.route.segs && S.route.segs.length ? S.route.segs : [...Array(S.route.segments).keys()];
  const i = Math.max(0, segs.indexOf(S.seg));
  const n = i + d;
  if (n < 0 || n >= segs.length) return;
  S.seg = segs[n];
  playSeg();
}

function applyLayout() {
  const stage = $("stage");
  if (!stage) return;
  stage.className = "stage " + stageClass() + (stage.classList.contains("fs") ? " fs" : "");
  stage.querySelectorAll(".tile").forEach(t => {
    const id = t.dataset.cam;
    t.classList.remove("show", "main", "pipcam");
    if (S.layout === "triple") return;
    if (S.layout === "one" && id === S.singleCam) t.classList.add("show");
    if (S.layout === "pip") {
      if (id === S.singleCam) t.classList.add("main");
      if (id === "driver") t.classList.add("pipcam");
    }
  });
  const pip = stage.querySelector(".pipcam");
  if (pip) pip.onclick = () => {
    S.pipCorner = PIP_CORNERS[(PIP_CORNERS.indexOf(S.pipCorner) + 1) % PIP_CORNERS.length];
    applyLayout();
  };
}

function bindVideos() {
  applyLayout();
}

function iceDone(pc) {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise(res => {
    const t = setTimeout(res, 2200);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") { clearTimeout(t); res(); }
    });
  });
}

async function goLive() {
  try {
    await api("/api/live", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on: true }) });
    S.liveOn = true;
    render();
    say("warming cameras…");
    let ready = false;
    for (let i = 0; i < 12; i++) {
      const st = await api("/api/live");
      if (st.webrtc) { ready = true; break; }
      await new Promise(r => setTimeout(r, 700));
    }
    if (!ready) { say("webrtcd not up yet — retry Go live"); return; }
    hangup(false);
    const pc = new RTCPeerConnection({ iceServers: [] });
    S.pc = pc;
    pc.createDataChannel("data");
    CAMS.forEach(() => pc.addTransceiver("video", { direction: "recvonly" }));
    const videos = [...document.querySelectorAll("#stage video")];
    let i = 0;
    pc.ontrack = (ev) => {
      const v = videos[i++] || videos[0];
      if (v) v.srcObject = new MediaStream([ev.track]);
    };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await iceDone(pc);
    const ans = await api("/api/webrtc/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        cameras: CAMS.map(c => c.id),
        enabled: true,
        bridge_services_in: [],
        bridge_services_out: [],
      }),
    });
    if (ans.error) throw new Error(ans.error + (ans.hint ? " — " + ans.hint : ""));
    await pc.setRemoteDescription({ type: ans.type || "answer", sdp: ans.sdp });
    say("live");
  } catch (e) { say(e.message || String(e)); }
}

function hangup(update = true) {
  if (S.pc) { try { S.pc.close(); } catch (e) {} S.pc = null; }
  document.querySelectorAll("#stage video").forEach(v => { v.srcObject = null; });
  if (update) {
    S.liveOn = false;
    api("/api/live", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ on: false }) }).catch(() => {});
    if (S.page === "live") render();
  }
}

function toggleFs() {
  const stage = $("stage");
  if (!stage) return;
  const go = () => { stage.classList.add("fs"); applyLayout(); };
  const leave = () => { stage.classList.remove("fs"); applyLayout(); };
  if (!document.fullscreenElement) {
    (stage.requestFullscreen || stage.webkitRequestFullscreen).call(stage).then(go).catch(go);
  } else {
    (document.exitFullscreen || document.webkitExitFullscreen).call(document).then(leave).catch(leave);
  }
  document.onfullscreenchange = () => { if (!document.fullscreenElement) leave(); };
}

async function refreshHome() {
  try {
    S.home = await api("/api/home");
    paintHeader();
    if (S.page === "home" && !S.player) {
      const el = document.querySelector(".grid");
      if (el && S.home) {
        const u = S.home.unit;
        const vals = [S.home.today, S.home.todayEng, S.home.week];
        el.querySelectorAll(".stat .v").forEach((n, i) => {
          if (i < 3) n.innerHTML = `${vals[i].toFixed(1)} <span class="tiny">${u}</span>`;
          if (i === 3) n.innerHTML = `${S.home.engPct}<span class="tiny">%</span>`;
        });
      }
    }
  } catch (e) { /* keep last */ }
}

async function boot() {
  tickClock();
  setInterval(tickClock, 10000);
  $("menuBtn").onclick = openMenu;
  $("drawerClose").onclick = closeMenu;
  $("scrim").onclick = closeMenu;
  document.querySelectorAll("#drawer nav button").forEach(b => b.onclick = () => setPage(b.dataset.page));
  window.addEventListener("hashchange", () => {
    const p = location.hash.replace("#", "");
    if (PAGES.includes(p) && p !== S.page) setPage(p);
  });
  render();
  try {
    const [home, params, grok, routes, live] = await Promise.all([
      api("/api/home"), api("/api/params"), api("/api/grok").catch(() => S.grok),
      api("/api/routes").catch(() => ({ routes: [] })), api("/api/live").catch(() => ({})),
    ]);
    S.home = home; S.params = params; S.grok = grok; S.routes = routes.routes || [];
    S.liveOn = !!live.live; S.webrtc = !!live.webrtc;
    paintHeader();
    render();
    if (S.page === "shots") loadShots();
  } catch (e) { say("device unreachable"); }
  setInterval(refreshHome, 3000);
}

boot();
