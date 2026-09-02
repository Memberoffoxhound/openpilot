/* Corner map: MapKit JS (Apple) / Google Maps JS / Leaflet fallback.
   Uses car GPS when present, otherwise the phone/browser Geolocation API. */
(function () {
  const KEYS = { apple: "sexypilot.mapkit", google: "sexypilot.gmaps", prefer: "sexypilot.mapPrefer" };

  const M = {
    kind: null,
    map: null,
    marker: null,
    el: null,
    last: null,
    watch: null,
    device: null,
    loading: false,
  };

  function isiOS() {
    const ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function appleToken() { return (localStorage.getItem(KEYS.apple) || "").trim(); }
  function googleKey() { return (localStorage.getItem(KEYS.google) || "").trim(); }
  function prefer() {
    const p = localStorage.getItem(KEYS.prefer);
    if (p === "apple" || p === "google" || p === "osm") return p;
    if (appleToken() && (isiOS() || !googleKey())) return "apple";
    if (googleKey()) return "google";
    return "osm";
  }

  function loadScript(src, ok) {
    return new Promise((resolve, reject) => {
      if (ok()) return resolve();
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", () => reject(new Error("map script failed")));
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("map script failed"));
      document.head.appendChild(s);
    });
  }

  function fallback(el, pos, msg) {
    const t = pos ? pos.lat.toFixed(5) + ", " + pos.lon.toFixed(5) : (msg || "NO GPS");
    el.innerHTML = `<div class="live-map-fallback">${t}</div>`;
  }

  function badge(el, label) {
    let b = el.querySelector(".live-map-badge");
    if (!b) {
      b = document.createElement("button");
      b.type = "button";
      b.className = "live-map-badge";
      b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openSettings(); });
      el.appendChild(b);
    }
    b.textContent = label;
  }

  async function ensureApple() {
    const token = appleToken();
    if (!token) throw new Error("no mapkit token");
    await loadScript("https://cdn.apple-mapkit.com/mk/5.x.x/mapkit.js", () => typeof window.mapkit !== "undefined");
    if (!window.mapkit._sxyInit) {
      mapkit.init({
        authorizationCallback(done) { done(appleToken()); },
      });
      window.mapkit._sxyInit = true;
    }
  }

  async function ensureGoogle() {
    const key = googleKey();
    if (!key) throw new Error("no google key");
    await loadScript(
      "https://maps.googleapis.com/maps/api/js?v=weekly&key=" + encodeURIComponent(key),
      () => !!(window.google && google.maps && google.maps.Map),
    );
  }

  function appleMap(el, pos) {
    if (M.kind !== "apple" || !M.map) {
      kill();
      el.innerHTML = "";
      M.el = el;
      M.kind = "apple";
      const center = new mapkit.Coordinate(pos.lat, pos.lon);
      M.map = new mapkit.Map(el, {
        center,
        colorScheme: mapkit.Map.ColorSchemes.Light,
        mapType: mapkit.Map.MapTypes.Standard,
        showsMapTypeControl: false,
        showsZoomControl: false,
        showsCompass: mapkit.FeatureVisibility.Hidden,
        showsScale: mapkit.FeatureVisibility.Hidden,
        isRotationEnabled: false,
        isScrollEnabled: true,
        isZoomEnabled: true,
      });
      M.map.region = new mapkit.CoordinateRegion(center, new mapkit.CoordinateSpan(0.012, 0.012));
      M.marker = new mapkit.MarkerAnnotation(center, {
        color: "#3e8ceb",
        glyphText: "●",
        title: "",
      });
      M.map.addAnnotation(M.marker);
    } else {
      const center = new mapkit.Coordinate(pos.lat, pos.lon);
      M.marker.coordinate = center;
      const cur = M.map.center;
      const dlat = Math.abs(cur.latitude - pos.lat);
      const dlon = Math.abs(cur.longitude - pos.lon);
      if (dlat + dlon > 0.0004) M.map.setCenterAnimated(center);
    }
    badge(el, "APPLE MAPS");
  }

  function googleMap(el, pos) {
    if (M.kind !== "google" || !M.map) {
      kill();
      el.innerHTML = "";
      M.el = el;
      M.kind = "google";
      M.map = new google.maps.Map(el, {
        center: { lat: pos.lat, lng: pos.lon },
        zoom: 16,
        disableDefaultUI: true,
        gestureHandling: "greedy",
        backgroundColor: "#ececee",
        styles: [
          { elementType: "geometry", stylers: [{ color: "#f5f5f5" }] },
          { elementType: "labels.icon", stylers: [{ visibility: "off" }] },
          { elementType: "labels.text.fill", stylers: [{ color: "#616161" }] },
          { elementType: "labels.text.stroke", stylers: [{ color: "#f5f5f5" }] },
          { featureType: "poi", stylers: [{ visibility: "off" }] },
          { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
          { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#dadada" }] },
          { featureType: "water", elementType: "geometry", stylers: [{ color: "#c9c9c9" }] },
        ],
      });
      M.marker = new google.maps.Marker({
        position: { lat: pos.lat, lng: pos.lon },
        map: M.map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 7,
          fillColor: "#3e8ceb",
          fillOpacity: 1,
          strokeColor: "#fff",
          strokeWeight: 2,
        },
      });
    } else {
      const ll = { lat: pos.lat, lng: pos.lon };
      M.marker.setPosition(ll);
      const c = M.map.getCenter();
      if (c && google.maps.geometry) {
        /* geometry library optional */
      }
      if (c && (Math.abs(c.lat() - pos.lat) + Math.abs(c.lng() - pos.lon) > 0.0004)) {
        M.map.panTo(ll);
      }
    }
    badge(el, "GOOGLE MAPS");
  }

  function osmMap(el, pos) {
    if (typeof window.L === "undefined") {
      fallback(el, pos, "MAP UNAVAILABLE");
      return;
    }
    const LL = window.L;
    if (M.kind !== "osm" || !M.map) {
      kill();
      el.innerHTML = "";
      M.el = el;
      M.kind = "osm";
      M.map = LL.map(el, { zoomControl: false, attributionControl: false, dragging: true });
      LL.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 20, subdomains: "abcd",
      }).addTo(M.map);
      const pane = M.map.getPane("tilePane");
      if (pane) pane.style.filter = "grayscale(1) contrast(1.05) brightness(1.08)";
      M.marker = LL.circleMarker([pos.lat, pos.lon], {
        radius: 6, color: "#3e8ceb", weight: 2, fillColor: "#3e8ceb", fillOpacity: 0.95,
      }).addTo(M.map);
      M.map.setView([pos.lat, pos.lon], 15);
    } else {
      M.marker.setLatLng([pos.lat, pos.lon]);
      const c = M.map.getCenter();
      if (LL.latLng(pos.lat, pos.lon).distanceTo(c) > 40) M.map.panTo([pos.lat, pos.lon], { animate: true });
    }
    badge(el, "MAP");
  }

  async function paint(el, carPos) {
    if (!el) return;
    const pos = (carPos && Math.abs(carPos.lat) > 1e-4) ? carPos : M.device;
    if (!pos || Math.abs(pos.lat) < 1e-4) {
      if (!M.map) fallback(el, null, M.watch ? "WAITING FOR GPS" : "NO GPS");
      return;
    }
    M.last = pos;
    const want = prefer();
    try {
      if (want === "apple") {
        await ensureApple();
        appleMap(el, pos);
        return;
      }
      if (want === "google") {
        await ensureGoogle();
        googleMap(el, pos);
        return;
      }
    } catch (e) {
      osmMap(el, pos);
      return;
    }
    osmMap(el, pos);
  }

  function kill() {
    if (M.kind === "apple" && M.map) {
      try { M.map.destroy(); } catch (e) {}
    }
    if (M.kind === "google" && M.map) {
      try { google.maps.event.clearInstanceListeners(M.map); } catch (e) {}
    }
    if (M.kind === "osm" && M.map) {
      try { M.map.remove(); } catch (e) {}
    }
    if (M.el) {
      try { M.el.innerHTML = ""; } catch (e) {}
    }
    M.kind = null;
    M.map = null;
    M.marker = null;
    M.el = null;
  }

  function startDeviceGps(onFix) {
    stopDeviceGps();
    if (!navigator.geolocation) return;
    M.watch = navigator.geolocation.watchPosition((fix) => {
      M.device = {
        lat: fix.coords.latitude,
        lon: fix.coords.longitude,
        bearing: fix.coords.heading,
        source: "device",
      };
      if (typeof onFix === "function") onFix(M.device);
    }, () => {}, { enableHighAccuracy: true, maximumAge: 2000, timeout: 8000 });
  }

  function stopDeviceGps() {
    if (M.watch != null && navigator.geolocation) {
      try { navigator.geolocation.clearWatch(M.watch); } catch (e) {}
    }
    M.watch = null;
  }

  function openSettings() {
    const root = document.getElementById("liveRoot");
    if (!root) return;
    let sheet = document.getElementById("liveMapSheet");
    if (sheet) { sheet.remove(); }
    const cur = prefer();
    sheet = document.createElement("div");
    sheet.id = "liveMapSheet";
    sheet.className = "live-map-sheet";
    sheet.innerHTML = `
      <div class="live-map-card">
        <b>Corner map</b>
        <p>Apple MapKit JS and Google Maps JS need a token stored on this phone. The PWA cannot embed the native Maps app. Car GPS is preferred; the browser GPS fills in when the car has no fix.</p>
        <label>Provider
          <select id="mapPrefer">
            <option value="apple"${cur === "apple" ? " selected" : ""}>Apple Maps (MapKit JS)</option>
            <option value="google"${cur === "google" ? " selected" : ""}>Google Maps</option>
            <option value="osm"${cur === "osm" ? " selected" : ""}>Light tiles (no key)</option>
          </select>
        </label>
        <label>MapKit JS token
          <input id="mapApple" type="password" autocomplete="off" placeholder="eyJ…" value="${appleToken().replace(/"/g, """)}"/>
        </label>
        <label>Google Maps API key
          <input id="mapGoogle" type="password" autocomplete="off" placeholder="AIza…" value="${googleKey().replace(/"/g, """)}"/>
        </label>
        <div class="row">
          <button type="button" class="btn" id="mapCancel">Close</button>
          <button type="button" class="btn primary" id="mapSave">Save</button>
        </div>
      </div>`;
    root.appendChild(sheet);
    sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.remove(); });
    sheet.querySelector("#mapCancel").onclick = () => sheet.remove();
    sheet.querySelector("#mapSave").onclick = () => {
      localStorage.setItem(KEYS.prefer, sheet.querySelector("#mapPrefer").value);
      localStorage.setItem(KEYS.apple, sheet.querySelector("#mapApple").value.trim());
      localStorage.setItem(KEYS.google, sheet.querySelector("#mapGoogle").value.trim());
      sheet.remove();
      kill();
      const el = document.getElementById("liveMap");
      if (el) paint(el, M.last);
    };
  }

  window.LiveMap = { paint, kill, startDeviceGps, stopDeviceGps, openSettings, device: () => M.device };
})();
