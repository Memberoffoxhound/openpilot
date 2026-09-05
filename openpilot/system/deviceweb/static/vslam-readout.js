/* Observe-only vSlam readout. Wraps the stock detail renderer. */
(function () {
  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, function (c) {
      return "&#" + c.charCodeAt(0) + ";";
    });
  }
  function pathClass(ev) {
    const p = ev.path || ev.kind || "";
    if (p === "cornering" || p === "ramp") return "corner";
    if (p === "straight" || p === "interstate") return "straight";
    return "unknown";
  }
  function readout(ev) {
    const cls = pathClass(ev);
    const filt = ev.filter || "hold";
    const head = ev.headline || (
      cls === "corner" ? "Cornering \u2014 honor" :
      filt === "honor" ? "Straight road \u2014 honor" :
      filt === "driver" ? "Straight road \u2014 driver" :
      cls === "straight" ? "Straight road \u2014 ignore" :
      "Not enough path \u2014 hold"
    );
    const body = ev.summary || "";
    const why = ev.class_why || (ev.facts || []).join(" \u00b7 ");
    return '<div class="readout ' + cls + '">' +
      '<div class="ro-head"><b>' + esc(head) + '</b><span class="ro-filt">' + esc(filt) + '</span></div>' +
      (body ? "<p>" + esc(body) + "</p>" : "") +
      (why ? '<p class="tiny">' + esc(why) + "</p>" : "") +
      "</div>";
  }
  function patch() {
    if (typeof vslamDetailHTML !== "function") return false;
    if (vslamDetailHTML._vslamReadout) return true;
    const orig = vslamDetailHTML;
    function wrapped() {
      const html = orig();
      const ev = (typeof S !== "undefined" && S.vslamDetail && S.vslamDetail.event) || {};
      if (!ev.id) return html;
      const block = readout(ev);
      if (html.indexOf("spark-key") >= 0) return html.replace('<div class="spark-key">', block + '<div class="spark-key">');
      if (html.indexOf("vslam-map") >= 0) return html.replace('<div id="vslamMap"', block + '<div id="vslamMap"');
      return html + block;
    }
    wrapped._vslamReadout = true;
    vslamDetailHTML = wrapped;
    return true;
  }
  function tick() { if (!patch()) setTimeout(tick, 50); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
  else tick();
})();
