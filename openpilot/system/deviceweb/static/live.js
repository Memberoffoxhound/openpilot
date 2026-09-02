/* S3XYPilot LAN WebRTC viewer */
(function () {
  const FEEDS = [
    { id: "fcam", label: "Fcam", cameras: ["road"] },
    { id: "ecam", label: "Ecam", cameras: ["wideRoad"] },
    { id: "dcam", label: "Dcam", cameras: ["driver"] },
    { id: "combo", label: "Combo", cameras: ["road", "driver"] },
  ];

  const LV = {
    feed: "combo",
    status: { fcam: "off", ecam: "off", dcam: "off", combo: "off" },
    conn: "idle",
    live: { speedMs: 0, engaged: false, metric: false, lat: null, lon: null, bearing: null, livestream: false, webrtc: false, mic: false },
    rotate: false,
    mic: false,
    pc: null,
    dc: null,
    streams: [],
    map: null,
    marker: null,
    audio: { ctx: null, source: null, next: 0, es: null },
    poll: null,
    mounted: false,
  };

  function stripMdns(sdp) {
    return sdp.split(/\r\n|\n/).filter((line) => {
      if (!line.startsWith("a=candidate:")) return true;
      return !line.split(" ")[4]?.endsWith(".local");
    }).join("\r\n");
  }

  function speedNum(ms, metric) {
    const v = metric ? (ms || 0) * 3.6 : (ms || 0) * 2.236936;
    return Math.max(0, Math.round(v));
  }

  function html() {
    const metric = !!LV.live.metric;
    const spd = speedNum(LV.live.speedMs, metric);
    const engaged = !!LV.live.engaged;
    const feed = FEEDS.find((f) => f.id === LV.feed) || FEEDS[3];
    return `<div class="live" id="liveRoot">
      <div class="live-stage${LV.rotate ? " rot90" : ""}" id="liveStage">
        <div class="live-video" id="liveMainWrap">
          <video id="liveMain" playsinline autoplay muted></video>
        </div>
        <div class="live-pip" id="livePip" ${feed.id === "combo" ? "" : "hidden"}>
          <video id="livePipVid" playsinline autoplay muted></video>
          <span class="pip-lab">DCAM</span>
        </div>
        <div class="live-empty" id="liveEmpty">
          <b>SEXYPILOT</b>
          <p id="liveMsg">Connecting cameras…</p>
        </div>
        <div class="live-hud">
          <div class="live-speed">
            <span class="n" id="liveSpeed">${spd}</span>
            <span class="u" id="liveUnit">${metric ? "KM/H" : "MPH"}</span>
          </div>
          <div class="live-map" id="liveMap" aria-label="Map"></div>
          <div class="live-mark">
            <div class="wm">SEXYPILOT</div>
            <div class="st${engaged ? " on" : ""}" id="liveEng">${engaged ? "Engaged" : "Disengaged"}</div>
          </div>
        </div>
      </div>
      <div class="live-dock">
        <div class="live-feeds">
          ${FEEDS.map((f) => {
            const st = LV.status[f.id] || "off";
            const lab = st === "live" ? "live" : st === "wait" ? "connecting" : "idle";
            return `<button type="button" class="feed${f.id === LV.feed ? " on" : ""}" data-feed="${f.id}">
              <div class="fn">${f.label}</div>
              <div class="fs"><span class="dot ${st}"></span>${lab}</div>
            </button>`;
          }).join("")}
        </div>
        <div class="live-tools">
          <button type="button" class="btn" id="liveMenu">Menu</button>
          <button type="button" class="btn${LV.mic ? " on" : ""}" id="liveMic">Mic ${LV.mic ? "on" : "off"}</button>
          <button type="button" class="btn${LV.rotate ? " on" : ""}" id="liveRot">Rotate</button>
          <button type="button" class="btn" id="liveFs">Full</button>
        </div>
      </div>
    </div>`;
  }

  function setMsg(t) {
    const el = document.getElementById("liveMsg");
    if (el) el.textContent = t;
  }

  function paintHud() {
    const metric = !!LV.live.metric;
    const n = document.getElementById("liveSpeed");
    const u = document.getElementById("liveUnit");
    const e = document.getElementById("liveEng");
    if (n) n.textContent = String(speedNum(LV.live.speedMs, metric));
    if (u) u.textContent = metric ? "KM/H" : "MPH";
    if (e) {
      e.textContent = LV.live.engaged ? "Engaged" : "Disengaged";
      e.classList.toggle("on", !!LV.live.engaged);
    }
    paintMap();
  }

  function paintMap() {
    const el = document.getElementById("liveMap");
    if (!el) return;
    const lat = LV.live.lat, lon = LV.live.lon;
    if (typeof window.L === "undefined") {
      el.innerHTML = `<div class="live-map-fallback">${lat != null ? lat.toFixed(5) + ", " + lon.toFixed(5) : "NO GPS"}</div>`;
      return;
    }
    const LL = window.L;
    if (!lat || !lon || Math.abs(lat) < 1e-4) {
      if (!LV.map) el.innerHTML = `<div class="live-map-fallback">WAITING FOR GPS</div>`;
      return;
    }
    if (!LV.map) {
      el.innerHTML = "";
      LV.map = LL.map(el, { zoomControl: false, attributionControl: false, dragging: true });
      LL.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 20, subdomains: "abcd",
      }).addTo(LV.map);
      const pane = LV.map.getPane("tilePane");
      if (pane) pane.style.filter = "grayscale(1) contrast(1.05) brightness(1.08)";
      LV.marker = LL.circleMarker([lat, lon], {
        radius: 6, color: "#3e8ceb", weight: 2, fillColor: "#3e8ceb", fillOpacity: .95,
      }).addTo(LV.map);
      LV.map.setView([lat, lon], 15);
    } else {
      LV.marker.setLatLng([lat, lon]);
      const c = LV.map.getCenter();
      if (LL.latLng(lat, lon).distanceTo(c) > 40) LV.map.panTo([lat, lon], { animate: true });
    }
  }

  function killMap() {
    if (LV.map) {
      try { LV.map.remove(); } catch (e) {}
      LV.map = null;
      LV.marker = null;
    }
  }

  function attachTracks(streams) {
    LV.streams = streams;
    const main = document.getElementById("liveMain");
    const pip = document.getElementById("livePipVid");
    const empty = document.getElementById("liveEmpty");
    const wrapPip = document.getElementById("livePip");
    if (!main) return;
    const videos = streams.filter(Boolean);
    if (videos[0]) { main.srcObject = videos[0]; main.play().catch(() => {}); }
    if (wrapPip) wrapPip.hidden = LV.feed !== "combo";
    if (pip && videos[1] && LV.feed === "combo") { pip.srcObject = videos[1]; pip.play().catch(() => {}); }
    if (empty) empty.hidden = videos.length > 0;
  }

  async function startMic() {
    stopMic();
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      LV.audio.ctx = ctx;
      LV.audio.next = ctx.currentTime + 0.08;
      const es = new EventSource("/api/audio");
      LV.audio.es = es;
      es.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          const raw = atob(msg.pcm);
          const buf = new ArrayBuffer(raw.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
          const i16 = new Int16Array(buf);
          const f32 = new Float32Array(i16.length);
          for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
          const rate = msg.rate || 16000;
          const ab = ctx.createBuffer(1, f32.length, rate);
          ab.copyToChannel(f32, 0);
          const src = ctx.createBufferSource();
          src.buffer = ab;
          src.connect(ctx.destination);
          const t = Math.max(ctx.currentTime + 0.02, LV.audio.next);
          src.start(t);
          LV.audio.next = t + ab.duration;
        } catch (e) {}
      };
      es.onerror = () => { if (window.say) say("mic stream dropped"); };
    } catch (e) {
      if (window.say) say(e.message || "mic failed");
      LV.mic = false;
    }
  }

  function stopMic() {
    if (LV.audio.es) { try { LV.audio.es.close(); } catch (e) {} LV.audio.es = null; }
    if (LV.audio.ctx) { try { LV.audio.ctx.close(); } catch (e) {} LV.audio.ctx = null; }
  }

  async function teardownPc() {
    if (LV.dc) { try { LV.dc.close(); } catch (e) {} LV.dc = null; }
    if (LV.pc) {
      try { LV.pc.getReceivers().forEach((r) => r.track && r.track.stop()); } catch (e) {}
      try { LV.pc.close(); } catch (e) {}
      LV.pc = null;
    }
    LV.streams = [];
  }

  async function connect() {
    const spec = FEEDS.find((f) => f.id === LV.feed) || FEEDS[3];
    FEEDS.forEach((f) => { LV.status[f.id] = f.id === spec.id ? "wait" : "off"; });
    LV.conn = "connecting";
    setMsg("Starting livestream…");
    rerenderDock();
    try {
      const warm = await api("/api/live/start", { method: "POST" });
      if (!warm.ready) throw new Error(warm.error || "livestream not ready");
    } catch (e) {
      LV.status[spec.id] = "off";
      LV.conn = "failed";
      setMsg(e.message || "Could not start livestream");
      rerenderDock();
      return;
    }
    await teardownPc();
    const tracks = [];
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      bundlePolicy: "max-bundle",
    });
    LV.pc = pc;
    spec.cameras.forEach(() => pc.addTransceiver("video", { direction: "recvonly" }));
    const dc = pc.createDataChannel("data", { ordered: true });
    LV.dc = dc;
    dc.onopen = () => {
      dc.send(JSON.stringify({ type: "livestreamVideoEnable", data: { enabled: true } }));
    };
    dc.onmessage = (evt) => {
      try {
        const msg = JSON.parse(typeof evt.data === "string" ? evt.data : new TextDecoder().decode(evt.data));
        if (msg.type === "carState" && msg.data) {
          LV.live.speedMs = msg.data.vEgo || 0;
          paintHud();
        }
        if (msg.type === "selfdriveState" && msg.data) {
          LV.live.engaged = !!(msg.data.enabled || msg.data.active);
          paintHud();
        }
        if (msg.type === "gpsLocation" || msg.type === "gpsLocationExternal") {
          const d = msg.data || {};
          if (d.latitude) {
            LV.live.lat = d.latitude;
            LV.live.lon = d.longitude;
            LV.live.bearing = d.bearingDeg;
            paintHud();
          }
        }
        if (msg.type === "disconnect") {
          setMsg(msg.data || "stream closed");
          LV.status[spec.id] = "off";
          rerenderDock();
        }
      } catch (e) {}
    };
    pc.addEventListener("track", (ev) => {
      if (ev.track.kind !== "video") return;
      const stream = ev.streams && ev.streams[0] ? ev.streams[0] : new MediaStream([ev.track]);
      tracks.push(stream);
      attachTracks(tracks);
      LV.status[spec.id] = "live";
      LV.conn = "connected";
      const empty = document.getElementById("liveEmpty");
      if (empty) empty.hidden = true;
      rerenderDock();
    });
    pc.addEventListener("connectionstatechange", () => {
      if (!LV.pc) return;
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
        LV.status[spec.id] = "off";
        LV.conn = pc.connectionState;
        setMsg("Peer connection " + pc.connectionState);
        rerenderDock();
      }
    });
    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitIce(pc, 2500);
      const sdp = stripMdns(pc.localDescription.sdp);
      const resp = await api("/api/webrtc/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sdp,
          cameras: spec.cameras,
          enabled: true,
          bridge_services_in: [],
          bridge_services_out: ["carState", "selfdriveState", "deviceState", "gpsLocation", "gpsLocationExternal"],
        }),
      });
      if (resp.error) throw new Error(resp.message || resp.error);
      await pc.setRemoteDescription({ type: "answer", sdp: resp.sdp });
      setMsg("Waiting for video…");
    } catch (e) {
      LV.status[spec.id] = "off";
      LV.conn = "failed";
      setMsg(e.message || "WebRTC failed");
      rerenderDock();
    }
  }

  function waitIce(pc, ms) {
    return new Promise((resolve) => {
      if (pc.iceGatheringState === "complete") return resolve();
      const t = setTimeout(resolve, ms);
      pc.addEventListener("icegatheringstatechange", () => {
        if (pc.iceGatheringState === "complete") { clearTimeout(t); resolve(); }
      });
    });
  }

  function rerenderDock() {
    const root = document.getElementById("liveRoot");
    if (!root || !LV.mounted) return;
    root.querySelectorAll("[data-feed]").forEach((b) => {
      const id = b.dataset.feed;
      b.classList.toggle("on", id === LV.feed);
      const st = LV.status[id] || "off";
      const lab = st === "live" ? "live" : st === "wait" ? "connecting" : "idle";
      const fs = b.querySelector(".fs");
      if (fs) fs.innerHTML = `<span class="dot ${st}"></span>${lab}`;
    });
    const mic = document.getElementById("liveMic");
    if (mic) {
      mic.classList.toggle("on", LV.mic);
      mic.textContent = LV.mic ? "Mic on" : "Mic off";
    }
    const rot = document.getElementById("liveRot");
    if (rot) rot.classList.toggle("on", LV.rotate);
  }

  function bind() {
    const menu = document.getElementById("liveMenu");
    if (menu) menu.onclick = () => { if (typeof openMenu === "function") openMenu(); };
    document.querySelectorAll("[data-feed]").forEach((b) => {
      b.onclick = () => {
        if (LV.feed === b.dataset.feed && LV.conn === "connected") return;
        LV.feed = b.dataset.feed;
        connect();
      };
    });
    const mic = document.getElementById("liveMic");
    if (mic) mic.onclick = () => {
      LV.mic = !LV.mic;
      localStorage.setItem("sexypilot.mic", LV.mic ? "1" : "0");
      if (LV.mic) startMic(); else stopMic();
      rerenderDock();
    };
    const rot = document.getElementById("liveRot");
    if (rot) rot.onclick = () => {
      LV.rotate = !LV.rotate;
      const stage = document.getElementById("liveStage");
      if (stage) stage.classList.toggle("rot90", LV.rotate);
      rerenderDock();
      if (LV.map) setTimeout(() => { try { LV.map.invalidateSize(); } catch (e) {} }, 80);
    };
    const fs = document.getElementById("liveFs");
    if (fs) fs.onclick = () => {
      const root = document.getElementById("liveRoot");
      if (!root) return;
      if (!document.fullscreenElement) root.requestFullscreen?.() || root.webkitRequestFullscreen?.();
      else document.exitFullscreen?.();
    };
  }

  async function pollLive() {
    try {
      const r = await api("/api/live");
      LV.live = Object.assign(LV.live, r);
      paintHud();
    } catch (e) {}
  }

  function mount() {
    if (LV.mounted) return;
    LV.mounted = true;
    const saved = localStorage.getItem("sexypilot.mic");
    LV.mic = saved === "1" || (saved === null && !!LV.live.mic);
    bind();
    paintHud();
    connect();
    if (LV.mic) startMic();
    if (LV.poll) clearInterval(LV.poll);
    LV.poll = setInterval(pollLive, 1000);
    pollLive();
  }

  function unmount() {
    LV.mounted = false;
    if (LV.poll) { clearInterval(LV.poll); LV.poll = null; }
    stopMic();
    teardownPc();
    killMap();
  }

  window.LiveView = { html, mount, unmount };
})();
