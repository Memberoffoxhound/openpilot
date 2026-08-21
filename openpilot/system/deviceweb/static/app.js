const GROUPS = [
  {id:"toggles", title:"Toggles", items:[
    {key:"OpenpilotEnabledToggle", label:"Enable openpilot", type:"bool", desc:"Master switch. Restart required.", restart:true, deviceOnly:true},
    {key:"ExperimentalMode", label:"Experimental mode", type:"bool", desc:"End-to-end longitudinal.", confirm:"Experimental mode uses the model for gas and brake. Stay ready to take over.", deviceOnly:true},
    {key:"AutoLaneChangeEnabled", label:"Auto lane change", type:"bool", desc:"Nudgeless after Tesla stock BSM is clear.", confirm:"Auto Lane Change uses Tesla’s stock blind spot monitoring to check the adjacent lane. You are still responsible for ensuring the lane of travel is clear and agree to intervene as necessary.", deviceOnly:true},
    {key:"IsLdwEnabled", label:"Lane departure warnings", type:"bool", desc:"Alert when you drift over a line without a signal."},
    {key:"AlwaysOnDM", label:"Always-on driver monitor", type:"bool", desc:"Keep DM running when not engaged."},
    {key:"IsMetric", label:"Use metric units", type:"bool", desc:"Show km/h instead of mph."},
    {key:"DisengageOnAccelerator", label:"Disengage on accelerator", type:"bool", desc:"Cancel openpilot when you press the pedal."},
    {key:"LongitudinalPersonality", label:"Driving personality", type:"select", desc:"How hard it follows the lead.", options:[["0","Aggressive"],["1","Standard"],["2","Relaxed"]]},
    {key:"RecordFront", label:"Record cabin camera", type:"bool", desc:"Upload dcam to help DM.", restart:true},
    {key:"RecordAudio", label:"Record microphone", type:"bool", desc:"Store mic audio in the dashcam.", restart:true},
  ]},
  {id:"theme", title:"Theme", items:[
    {key:"LaneColor", label:"Lane color", type:"select", desc:"Engaged lane lines.", options:[["1","Tesla Autopilot blue"],["0","comma green"]]},
  ]},
  {id:"livestream", title:"Livestream", items:[
    {key:"LivestreamEnabled", label:"On-Air", type:"bool", desc:"Local Wi-Fi viewer. Not on comma Prime LTE."},
  ]},
  {id:"device", title:"Device", items:[
    {key:"SshEnabled", label:"Enable SSH", type:"bool", desc:"Allow SSH from your GitHub keys."},
    {key:"AdbEnabled", label:"Enable ADB", type:"bool", desc:"Android debug bridge on the C4.", deviceOnly:true},
    {key:"DisablePowerDown", label:"Disable power down", type:"bool", desc:"Keep the device awake after the car is off."},
    {key:"DisableUpdates", label:"Disable updates", type:"bool", desc:"Stop the stock updater from fetching."},
  ]},
  {id:"network", title:"Network", items:[
    {key:"GsmRoaming", label:"Cellular roaming", type:"bool", desc:"Allow the SIM to roam.", deviceOnly:true},
    {key:"GsmMetered", label:"Metered cellular", type:"bool", desc:"Treat the SIM as a metered connection.", deviceOnly:true},
    {key:"NetworkMetered", label:"Metered network", type:"bool", desc:"Limit background uploads.", deviceOnly:true},
  ]},
  {id:"developer", title:"Developer", items:[
    {key:"ShowDebugInfo", label:"Show debug info", type:"bool", desc:"FPS and touch dots."},
    {key:"JoystickDebugMode", label:"Joystick debug", type:"bool", desc:"Replace controls with joystick.", deviceOnly:true},
  ]},
];
const TABS = [["status","Status"],["settings","Settings"],["files","Files"],["clips","Clips"],["stats","Stats"],["updates","Updates"]];
let tab = "status", info = {}, params = {}, toast = null, path = "", files = [], q = "", confirmItem = null, busy = false;
let routes = [], clipJob = {state:"idle"}, clipTimer = null;
let statsMonth = new Date();
let statsFrom = null, statsTo = null, statsJob = {state:"idle"}, statsTimer = null, statsMap = null, statsQcam = true;
function pad2(n){ return String(n).padStart(2,"0"); }
function isoDay(d){ return d.getFullYear()+"-"+pad2(d.getMonth()+1)+"-"+pad2(d.getDate()); }
if (!statsFrom) {
  const t = new Date();
  statsFrom = t.getFullYear()+"-"+pad2(t.getMonth()+1)+"-01";
  statsTo = isoDay(t);
}


async function api(url, opt) {
  const r = await fetch(url, opt);
  const t = await r.text();
  try { return JSON.parse(t); } catch { throw new Error(t || r.statusText); }
}
function bytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n/1024).toFixed(0) + " KB";
  if (n < 1073741824) return (n/1048576).toFixed(1) + " MB";
  return (n/1073741824).toFixed(1) + " GB";
}
function say(m) { toast = m; render(); setTimeout(() => { toast = null; render(); }, 3200); }
async function load() {
  render();
  try {
    info = await api("/api/info");
    params = await api("/api/params");
  } catch (e) { toast = (e && e.message) || "device unreachable"; }
  render();
}
async function save(k, v) {
  params[k] = v;
  render();
  await api("/api/params", { method:"PUT", headers:{"content-type":"application/json"}, body: JSON.stringify({[k]: v}) });
  info = await api("/api/info");
  render();
}
async function loadFiles() {
  const j = await api("/api/files?path=" + encodeURIComponent(path));
  files = j.items || [];
  render();
}
function render() {
  const app = document.getElementById("app");
  const title = {status:"Device", settings:"Settings", files:"Files", clips:"Clips", stats:"Stats", updates:"Updates"}[tab];
  app.innerHTML = `
    <aside>
      <div class="brand"><b>DELAMAIN</b><p>LAN console · no lock</p></div>
      <nav>${TABS.map(([id,l]) => `<button class="${tab===id?"on":""}" data-tab="${id}">${l}</button>`).join("")}</nav>
      <div class="ver">${info.version || "0.11.2.1"} · ${info.branch || "Highland"}</div>
    </aside>
    <div class="col">
      <header class="top">
        <div class="lg-hide"><div class="brand" style="padding:0"><b>DELAMAIN</b><p>LAN · no lock</p></div></div>
        <div class="lg-show" style="display:none"></div>
        <h1 class="lg-title">${title}</h1>
        <div style="margin-left:auto;display:flex;gap:8px">
          <span class="pill ${info.offroad===false?"ok":""}">${info.offroad===false?"onroad":"offroad"}</span>
          ${info.onAir ? `<span class="pill live">on air</span>` : ""}
        </div>
      </header>
      <main>${view()}</main>
    </div>
    <nav class="dock">${TABS.map(([id,l]) => `<button class="${tab===id?"on":""}" data-tab="${id}">${l}</button>`).join("")}</nav>
    ${toast ? `<div class="toast">${esc(toast)}</div>` : ""}
    ${confirmItem ? modal() : ""}
  `;
  app.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => {
    tab = b.dataset.tab;
    if (tab==="files") loadFiles();
    else if (tab==="clips") loadClips();
    else if (tab==="stats") loadStats(false);
    else render();
  });
  bind();
}
function esc(s){ s = String(s == null ? "" : s); return s.replace(/&/g,"&#38;").replace(/</g,"&#60;").replace(/>/g,"&#62;").replace(/"/g,"&#34;"); }
function view() {
  if (tab==="status") return statusView();
  if (tab==="settings") return settingsView();
  if (tab==="files") return filesView();
  if (tab==="clips") return clipsView();
  if (tab==="stats") return statsView();
  return updatesView();
}
function statusView() {
  const bars = "▂▄▆█".slice(0, Math.max(1, info.wifiBars|0)) + "·".repeat(4-Math.max(1, info.wifiBars|0));
  const pers = ["Aggressive","Standard","Relaxed"][Number(params.LongitudinalPersonality)||1];
  return `<div class="wrap">
    <div class="warn">This console has no password. Anyone on this Wi-Fi can read files and change settings. Keep it on your LAN.</div>
    <div class="grid">
      ${stat("Temp", info.tempC!=null?info.tempC+"°":"—")}
      ${stat("Memory", info.memPct!=null?info.memPct+"%":"—")}
      ${stat("Disk", info.diskFreeGb!=null?info.diskFreeGb+" GB":"—")}
      ${stat("Network", (info.network||"net").toUpperCase(), bars)}
    </div>
    <div class="card">
      ${row("Device", info.name||"DELAMAIN")}
      ${row("Version", info.version||"—")}
      ${row("Branch", info.branch||"—")}
      ${row("Commit", (info.commit||"").slice(0,12), true)}
      ${row("Dongle", info.dongle||"—", true)}
      ${row("Serial", info.serial||"—", true)}
      ${row("Personality", pers)}
      ${row("Lane color", params.LaneColor==="0"?"comma green":"Tesla blue")}
    </div>
    <div class="btns">
      <button class="btn" id="openLive">Open livestream</button>
    </div>
  </div>`;
}
function stat(k,v,h=""){ return `<div class="stat"><div class="k"><span>${k}</span></div><div class="v">${esc(v)}</div>${h?`<div class="tiny" style="margin-top:4px;font-family:var(--mono)">${esc(h)}</div>`:""}</div>`; }
function row(k,v,mono){ return `<div class="row"><span>${k}</span><span class="${mono?"mono":""}">${esc(v)}</span></div>`; }
function settingsView() {
  const query = q.trim().toLowerCase();
  const groups = GROUPS.map(g => ({...g, items:g.items.filter(it => !query || it.label.toLowerCase().includes(query) || it.key.toLowerCase().includes(query))})).filter(g => g.items.length);
  return `<div class="wrap">
    <label class="search"><input id="q" placeholder="Search settings" value="${esc(q)}"/></label>
    ${groups.map(g => `<section><p class="ghead">${g.title}</p><div class="card">${g.items.map(it => setRow(it)).join("")}</div></section>`).join("")}
  </div>`;
}
function setRow(it) {
  const val = params[it.key] ?? (it.type==="select" ? it.options[0][0] : "0");
  const locked = !!it.deviceOnly;
  const ctl = it.type==="bool"
    ? `<button class="tog ${val==="1"?"on":""}" data-k="${it.key}" data-n="${val==="1"?"0":"1"}" ${locked?"disabled":""}><i></i></button>`
    : `<select data-k="${it.key}" ${locked?"disabled":""}>${it.options.map(([v,l]) => `<option value="${v}" ${v===val?"selected":""}>${l}</option>`).join("")}</select>`;
  const extra = locked ? `<p class="lock">Can only be changed on device.</p>` : "";
  return `<div class="set ${locked?"locked":""}"><div class="meta"><b>${esc(it.label)}</b><p>${esc(it.desc)}</p>${extra}</div>${ctl}</div>`;
}
function filesView() {
  const parts = path.split("/").filter(Boolean);
  let acc = "";
  const crumbs = [`<button data-p="">data</button>`].concat(parts.map((p,i) => {
    acc += "/" + p;
    return `<span>›</span><button data-p="${esc(acc)}">${esc(p)}</button>`;
  }));
  return `<div class="wrap">
    <div class="crumb">${crumbs.join("")}</div>
    <div class="card">${files.length? files.map(n => `<button class="file" data-open="${esc(n.path)}" data-dir="${n.dir?1:0}"><b>${esc(n.name)}</b><em>${n.dir?"folder":bytes(n.size)}</em></button>`).join("") : `<p class="muted" style="padding:40px;text-align:center">Empty folder.</p>`}</div>
    <p class="tiny">Real disk under /data. Tokens and SSH keys are hidden.</p>
  </div>`;
}
function clipsView() {
  const sel = clipJob.route || (routes[0] && routes[0].name) || "";
  const r = routes.find(x => x.name === sel) || routes[0];
  const maxS = r ? r.seconds : 60;
  const start = clipJob.start || 0;
  const end = clipJob.end || Math.min(15, maxS);
  const running = clipJob.state === "running";
  return `<div class="wrap">
    <div class="warn">Clipper HUD on-device. Nelson’s GPU clipper won’t run on a C4 — this is openpilot’s clip tool: same overlay, local routes only, max 30s, offroad only. Turn Off-Air off first.</div>
    <div class="card">
      <div class="field"><label>Route</label>
        <select id="cRoute">${routes.map(x => `<option value="${esc(x.name)}" ${x.name===sel?"selected":""}>${esc(x.name)} · ${x.seconds}s</option>`).join("") || "<option>No routes on disk</option>"}</select>
      </div>
      <div class="field"><label>Start (s)</label><input id="cStart" type="number" min="0" value="${start}"/></div>
      <div class="field"><label>End (s)</label><input id="cEnd" type="number" min="3" max="30" value="${end}"/></div>
      <div class="field"><label>Title</label><input id="cTitle" type="text" maxlength="40" value="${esc(clipJob.title || "DELAMAIN")}"/></div>
      <div class="set"><div class="meta"><b>Use qcamera</b><p>Smaller file, faster. Uncheck for full fcamera.</p></div>
        <button class="tog ${clipJob.qcam!==false?"on":""}" id="cQcam"><i></i></button></div>
    </div>
    ${running ? `<div class="card pad"><p class="muted">Rendering HUD… keep the car offroad.</p><div class="bar" style="margin-top:12px"><i></i></div></div>` : ""}
    ${clipJob.state==="done" ? `<div class="card pad"><p class="muted">Ready${clipJob.size? " · "+Math.round(clipJob.size/1e6)+" MB":""}</p></div>` : ""}
    ${clipJob.state==="error" ? `<div class="warn">${esc(clipJob.error||"failed")}</div>` : ""}
    <div class="btns">
      <button class="btn primary" id="cGo" ${running||!routes.length?"disabled":""}>Render clip</button>
      ${running ? `<button class="btn" id="cStop">Cancel</button>` : ""}
      ${clipJob.state==="done" ? `<a class="btn" href="/api/clip/file">Download</a>` : ""}
    </div>
    <p class="tiny">Uses tools/clip (pyray HUD + RECORD). Does not talk to comma Connect.</p>
  </div>`;
}

function statsView() {
  const d = new Date(statsMonth.getFullYear(), statsMonth.getMonth(), 1);
  const startW = (d.getDay() + 6) % 7;
  const daysIn = new Date(d.getFullYear(), d.getMonth()+1, 0).getDate();
  const label = d.toLocaleString("en-US", {month:"long", year:"numeric"});
  let cells = "";
  for (let i=0;i<startW;i++) cells += `<div class="cell empty"></div>`;
  for (let day=1; day<=daysIn; day++) {
    const iso = d.getFullYear()+"-"+pad2(d.getMonth()+1)+"-"+pad2(day);
    let cls = "cell";
    if (statsFrom && statsTo && iso >= statsFrom && iso <= statsTo) cls += " in";
    if (iso === statsFrom || iso === statsTo) cls += " end";
    cells += `<button class="${cls}" data-day="${iso}">${day}</button>`;
  }
  const r = (statsJob && statsJob.result) || null;
  const running = statsJob.state === "running";
  const metric = params.IsMetric === "1";
  const dist = r ? (metric ? r.km+" km" : r.miles+" mi") : "—";
  return `<div class="wrap">
    <div class="card pad">
      <div class="calhead">
        <button class="btn" id="calPrev">Prev</button>
        <b>${label}</b>
        <button class="btn" id="calNext">Next</button>
      </div>
      <div class="caldows"><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span></div>
      <div class="cal">${cells}</div>
      <p class="muted" style="margin-top:12px">${esc(statsFrom||"—")} → ${esc(statsTo||"—")}</p>
      <div class="btns" style="margin-top:12px">
        <button class="btn primary" id="statsGo" ${running?"disabled":""}>${running?"Generating…":"Generate report"}</button>
      </div>
    </div>
    ${running ? `<div class="card pad"><p class="muted">Reading qlogs… stay offroad.</p><div class="bar" style="margin-top:12px"><i></i></div></div>` : ""}
    ${statsJob.state==="error" ? `<div class="warn">${esc(statsJob.error||"failed")}</div>` : ""}
    ${r ? `<div class="grid">
      ${stat("Distance", dist)}
      ${stat("Engaged", (r.engagedPct??0)+"%")}
      ${stat("Hours", r.hours ?? "—")}
      ${stat("Routes", r.routes ?? "—")}
    </div>
    <div class="card">
      ${row("Engaged hours", r.engagedHours)}
      ${row("Disengages", r.disengages)}
      ${row("Points", (r.points||[]).length)}
    </div>
    <div class="card mapwrap"><div id="statsMap"></div>
      <p class="tiny" style="padding:10px 14px">Trace from onboard GPS. Tiles are OSM, not comma. Scaled to this range.</p>
    </div>` : `<p class="tiny">Pick a start and end day, then generate. Uses local qlogs only.</p>`}
  </div>`;
}
function updatesView() {
  return `<div class="wrap">
    <div class="card pad">
      <p class="ghead">Installed</p>
      <h2>${esc(info.version||"0.11.2.1")}</h2>
      <p class="muted" style="margin-top:8px;font-family:var(--mono)">${esc(info.branch||"Highland")} · ${esc((info.commit||"").slice(0,12))}</p>
      <p class="muted" style="margin-top:16px">${esc(info.updaterNotes||"Check for a newer Highland commit.")}</p>
      <div class="btns" style="margin-top:20px">
        <button class="btn primary" id="chk" ${busy?"disabled":""}>${busy?"Working…":"Check for updates"}</button>
        <button class="btn" id="ins" ${busy||!info.updateAvailable?"disabled":""}>Install</button>
      </div>
    </div>
    <div class="card pad">
      <h2 style="font-size:20px">Power</h2>
      <p class="muted">Offroad only on the real device.</p>
      <div class="btns" style="margin-top:16px">
        <button class="btn" id="reb">Reboot</button>
        <button class="btn" id="shut">Shutdown</button>
      </div>
    </div>
  </div>`;
}
function modal() {
  return `<div class="modal"><div class="sheet"><b style="font-family:var(--display);font-size:20px">${esc(confirmItem.label)}</b><p class="muted" style="margin-top:12px">${esc(confirmItem.confirm)}</p><div class="btns" style="margin-top:20px;justify-content:flex-end"><button class="btn" id="no">Cancel</button><button class="btn primary" id="yes">Enable</button></div></div></div>`;
}
function bind() {
  const qi = document.getElementById("q");
  if (qi) qi.oninput = (e) => { q = e.target.value; render(); qi.focus(); qi.setSelectionRange(q.length,q.length); };
  document.querySelectorAll(".tog").forEach(b => b.onclick = () => {
    const k = b.dataset.k, n = b.dataset.n;
    const item = GROUPS.flatMap(g => g.items).find(x => x.key===k);
    if (item && item.confirm && n==="1") { confirmItem = item; render(); return; }
    save(k, n); if (item && item.restart) say("Saved. Restart the C4 for this to apply.");
  });
  document.querySelectorAll("select[data-k]").forEach(s => s.onchange = () => save(s.dataset.k, s.value));
  document.querySelectorAll("[data-p]").forEach(b => b.onclick = () => { path = b.dataset.p; loadFiles(); });
  document.querySelectorAll("[data-open]").forEach(b => b.onclick = () => {
    if (b.dataset.dir==="1") { path = b.dataset.open; loadFiles(); }
    else { location.href = "/api/files/raw?path=" + encodeURIComponent(b.dataset.open); }
  });
  const live = document.getElementById("openLive");
  if (live) live.onclick = () => window.open(`http://${location.hostname}:5001`, "_blank");
  const chk = document.getElementById("chk");
  if (chk) chk.onclick = async () => {
    busy = true; render();
    try {
      const j = await api("/api/updates/check", {method:"POST"});
      if (!j.ok) say(j.error || "check failed");
      else { info.updateAvailable = j.available; info.updaterNotes = j.available ? "A newer commit is on origin/"+j.branch : "Already current."; say(j.available ? "Update available" : "Up to date"); }
    } catch(e) { say(e.message); }
    busy = false; info = Object.assign(info, await api("/api/info")); render();
  };
  const ins = document.getElementById("ins");
  if (ins) ins.onclick = async () => {
    busy = true; render();
    try {
      const j = await api("/api/updates/apply", {method:"POST"});
      say(j.ok ? "Installing. Device will reboot." : (j.error || "failed"));
    } catch(e) { say(e.message); }
    busy = false; render();
  };
  const reb = document.getElementById("reb");
  if (reb) reb.onclick = async () => { await api("/api/action/reboot", {method:"POST"}); say("Reboot requested."); };
  const shut = document.getElementById("shut");
  if (shut) shut.onclick = async () => { await api("/api/action/shutdown", {method:"POST"}); say("Shutdown requested."); };
  const no = document.getElementById("no");
  if (no) no.onclick = () => { confirmItem = null; render(); };
  const yes = document.getElementById("yes");
  if (yes) yes.onclick = () => { const k = confirmItem.key; confirmItem = null; save(k, "1"); };
  const cGo = document.getElementById("cGo");
  if (cGo) cGo.onclick = startClip;
  const cStop = document.getElementById("cStop");
  if (cStop) cStop.onclick = async () => { clipJob = await api("/api/clip/cancel", {method:"POST"}); say("Cancelled"); render(); };
  const cQ = document.getElementById("cQcam");
  if (cQ) cQ.onclick = () => { clipJob.qcam = clipJob.qcam===false; render(); };

  const calPrev = document.getElementById("calPrev");
  if (calPrev) calPrev.onclick = () => { statsMonth = new Date(statsMonth.getFullYear(), statsMonth.getMonth()-1, 1); render(); };
  const calNext = document.getElementById("calNext");
  if (calNext) calNext.onclick = () => { statsMonth = new Date(statsMonth.getFullYear(), statsMonth.getMonth()+1, 1); render(); };
  document.querySelectorAll("[data-day]").forEach(b => b.onclick = () => pickDay(b.dataset.day));
  const statsGo = document.getElementById("statsGo");
  if (statsGo) statsGo.onclick = () => loadStats(true);
  if (tab==="stats") mountStatsMap();

}
async function loadClips() {
  try {
    const j = await api("/api/routes");
    routes = j.routes || [];
    clipJob = await api("/api/clip");
  } catch (e) { say(e.message); }
  render();
  if (clipJob.state === "running" && !clipTimer) {
    clipTimer = setInterval(async () => {
      try { clipJob = await api("/api/clip"); } catch {}
      if (clipJob.state !== "running") { clearInterval(clipTimer); clipTimer = null; }
      if (tab==="clips") render();
    }, 2000);
  }
}
async function startClip() {
  const route = document.getElementById("cRoute").value;
  const start = Number(document.getElementById("cStart").value);
  const end = Number(document.getElementById("cEnd").value);
  const title = document.getElementById("cTitle").value;
  const qcam = clipJob.qcam !== false;
  const j = await api("/api/clip", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({route, start, end, title, qcam})});
  if (!j.ok) { say(j.error || "could not start"); return; }
  clipJob = j.job || j;
  say("Rendering…");
  loadClips();
}
if ("serviceWorker" in navigator) navigator.serviceWorker.getRegistrations().then(function(rs){ rs.forEach(function(r){ r.unregister(); }); });
load();

window.onerror = function (msg) {
  var el = document.getElementById("app");
  if (el) el.insertAdjacentHTML("afterbegin", "<div class=\"warn\">"+String(msg)+"</div>");
};

function pickDay(iso) {
  if (!statsFrom || (statsFrom && statsTo && statsFrom !== statsTo)) {
    statsFrom = iso; statsTo = iso;
  } else if (iso < statsFrom) {
    statsTo = statsFrom; statsFrom = iso;
  } else {
    statsTo = iso;
  }
  render();
}
async function loadStats(generate) {
  if (generate) {
    const j = await api("/api/stats", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({from: statsFrom, to: statsTo})});
    if (!j.ok) { say(j.error || "could not generate"); return; }
    statsJob = j.job || j;
  } else {
    try { statsJob = await api("/api/stats"); } catch (e) { say(e.message); }
  }
  render();
  if (statsJob.state === "running" && !statsTimer) {
    statsTimer = setInterval(async () => {
      try { statsJob = await api("/api/stats"); } catch {}
      if (statsJob.state !== "running") { clearInterval(statsTimer); statsTimer = null; }
      if (tab==="stats") render();
    }, 1500);
  }
}
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  return new Promise((res, rej) => {
    const c = document.createElement("link");
    c.rel = "stylesheet";
    c.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(c);
    const s = document.createElement("script");
    s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    s.onload = res; s.onerror = rej;
    document.body.appendChild(s);
  });
}
async function mountStatsMap() {
  const el = document.getElementById("statsMap");
  const pts = (statsJob.result && statsJob.result.points) || [];
  if (!el || pts.length < 2) return;
  try { await loadLeaflet(); } catch { el.innerHTML = "<p class=muted style=padding:16px>Map tiles need internet.</p>"; return; }
  if (statsMap) { try { statsMap.remove(); } catch(e) {} statsMap = null; }
  const map = window.L.map(el, { zoomControl: true, attributionControl: true });
  window.L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OSM &copy; CARTO", maxZoom: 19
  }).addTo(map);
  const line = window.L.polyline(pts, { color: "#3ea7ff", weight: 3, opacity: 0.9 }).addTo(map);
  map.fitBounds(line.getBounds(), { padding: [24, 24] });
  statsMap = map;
  setTimeout(() => map.invalidateSize(), 80);
}
