/* Who-is-who check, both phones:
   - every [data-phrase] shows the rotating phrase from the server (same on the shopper's and the
     runner's phone) and refreshes itself when the minute rolls over;
   - a [data-wait-verify] block (runner, step 1) watches for the shopper's "It matches" and reloads
     the page into step 2 the moment it happens. */
(function () {
  document.querySelectorAll("[data-phrase]").forEach(function (box) {
    var id = box.dataset.order;
    var left = box.parentNode.querySelector("[data-phrase-left]");
    var timer = null, tick = null, remaining = 0;

    function show() {
      if (left) left.textContent = remaining > 0 ? "Changes in " + remaining + " s. If it just changed, look again." : "";
    }
    function load() {
      fetch("/api/orders/" + id + "/verify/phrase", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (!j) { box.textContent = "-"; if (left) left.textContent = "No phrase right now."; return; }
          box.textContent = j.phrase;
          remaining = j.seconds_left;
          show();
          clearTimeout(timer);
          timer = setTimeout(load, Math.max(2, remaining + 1) * 1000);
        })
        .catch(function () { timer = setTimeout(load, 5000); });
    }
    tick = setInterval(function () { if (remaining > 0) { remaining -= 1; show(); } }, 1000);
    load();
  });

  document.querySelectorAll("[data-wait-verify]").forEach(function (box) {
    var id = box.dataset.order;
    var poll = setInterval(function () {
      fetch("/api/orders/" + id + "/verify/status", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (j && (j.shopper_confirmed || j.flagged)) { clearInterval(poll); location.reload(); }
        }).catch(function () {});
    }, 3000);
  });
})();
