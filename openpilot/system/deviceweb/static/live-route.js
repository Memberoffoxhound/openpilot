/* Route #live without rewriting app.js */
(function () {
  if (typeof PAGES !== "undefined" && !PAGES.includes("live")) PAGES.push("live");

  if (typeof pageHTML === "function") {
    const inner = pageHTML;
    pageHTML = function () {
      if (S.page === "live") {
        return (window.LiveView && LiveView.html()) || '<div class="live-empty"><b>SEXYPILOT</b><p>Live viewer failed to load.</p></div>';
      }
      return inner();
    };
  }

  if (typeof setPage === "function") {
    const inner = setPage;
    setPage = function (p, id) {
      if (p !== "live" && window.LiveView) LiveView.unmount();
      inner(p, id);
    };
  }

  if (typeof render === "function") {
    const inner = render;
    render = function () {
      const prev = document.body.dataset.page;
      if (prev === "live" && S.page !== "live" && window.LiveView) LiveView.unmount();
      document.body.dataset.page = S.page;
      inner();
      if (S.page === "live" && window.LiveView) LiveView.mount();
    };
  }

  const raw = (location.hash || "").replace(/^#/, "").split("/")[0];
  if (raw === "live" && S.page !== "live" && typeof setPage === "function") setPage("live");
})();
