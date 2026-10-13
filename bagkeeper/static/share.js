/* Runner: "Share my live location" with the customer while on the way.
   Sends the phone's GPS every few seconds to /api/orders/<id>/runner-location.
   A web page can only do this while it stays open, so we keep the screen awake. */
(function () {
  var box = document.getElementById("share");
  if (!box) return;
  var id = box.dataset.order;
  var btn = box.querySelector("[data-share-btn]"), msg = box.querySelector("[data-share-msg]");
  var KEY = "bk-share-" + id, GAP_MS = 4000;
  var watch = null, lastSent = 0, lock = null;

  function say(t, tone) { msg.textContent = t; msg.style.color = tone ? "var(--" + tone + ")" : ""; }
  function store(v) { try { v ? localStorage.setItem(KEY, "1") : localStorage.removeItem(KEY); } catch (e) {} }
  function remembered() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } }

  function keepAwake() {
    if (!("wakeLock" in navigator)) return;
    navigator.wakeLock.request("screen").then(function (l) { lock = l; }).catch(function () {});
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && watch !== null) keepAwake();  // re-acquire after returning
  });

  function send(c) {
    fetch("/api/orders/" + id + "/runner-location", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: c.latitude, lon: c.longitude, accuracy: c.accuracy, heading: c.heading })
    }).then(function (r) {
      if (r.status === 403 || r.status === 404 || r.status === 409) { stop("Sharing stopped: this job is no longer active."); return; }
      if (!r.ok) { say("Couldn't send your location (error " + r.status + "). Still trying.", "warn"); return; }
      say("Sharing live location (±" + Math.round(c.accuracy) + " m). Keep this page open and the screen on.", "ok");
    }).catch(function () { say("No connection. Will retry.", "warn"); });
  }

  function start() {
    if (!navigator.geolocation) { say("This browser can't share location.", "bad"); return; }
    if (!window.isSecureContext) { say("Location needs a secure (https) page.", "bad"); return; }
    store(true);
    btn.textContent = "Stop sharing";
    say("Starting... allow location if asked.");
    watch = navigator.geolocation.watchPosition(function (p) {
      var now = Date.now();
      if (now - lastSent < GAP_MS) return;
      lastSent = now; send(p.coords);
    }, function (e) {
      say(e.code === 1 ? "Location is blocked. Allow it in the browser settings to share."
                       : "Couldn't get a GPS fix yet. Still trying.", e.code === 1 ? "bad" : "warn");
    }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
    keepAwake();
  }

  function stop(text) {
    if (watch !== null) navigator.geolocation.clearWatch(watch);
    watch = null; store(false);
    if (lock) { try { lock.release(); } catch (e) {} lock = null; }
    btn.textContent = "Share my live location";
    fetch("/api/orders/" + id + "/runner-location", { method: "DELETE" }).catch(function () {});
    say(text || "Not sharing. The customer can't see where you are.");
  }

  btn.addEventListener("click", function () { watch === null ? start() : stop(); });
  if (remembered()) start();     // resume after a page reload
})();
