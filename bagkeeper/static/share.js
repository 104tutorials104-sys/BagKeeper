/* Runner location, ON BY DEFAULT while a job is active (assigned / out for delivery).
   The base template renders #share with data-orders="12,15" for the runner's active jobs, on
   every page, so sharing continues as the runner moves around the app.
   A web page can only report while it is open, so we keep the screen awake. The browser
   itself still asks for location permission once; if it is blocked we say so loudly. */
(function () {
  var bar = document.getElementById("share");
  if (!bar) return;
  var orders = bar.dataset.orders.split(",").filter(Boolean);
  var msg = bar.querySelector("[data-share-msg]"), retry = bar.querySelector("[data-share-retry]");
  var GAP_MS = 4000, watch = null, lastSent = 0, lock = null;

  function say(t, tone) {
    msg.textContent = t;
    bar.className = "sharebar" + (tone ? " " + tone : "");
  }

  function keepAwake() {
    if (!("wakeLock" in navigator)) return;
    navigator.wakeLock.request("screen").then(function (l) { lock = l; }).catch(function () {});
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && watch !== null) keepAwake();
  });

  function stopAll(text) {
    if (watch !== null) navigator.geolocation.clearWatch(watch);
    watch = null;
    if (lock) { try { lock.release(); } catch (e) {} lock = null; }
    say(text, "");
  }

  function send(c) {
    orders.slice().forEach(function (id) {
      fetch("/api/orders/" + id + "/runner-location", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: c.latitude, lon: c.longitude, accuracy: c.accuracy, heading: c.heading })
      }).then(function (r) {
        if (r.status === 403 || r.status === 404 || r.status === 409) {      // job finished or reassigned
          orders = orders.filter(function (x) { return x !== id; });
          if (!orders.length) stopAll("No active job. Location sharing has stopped.");
          return;
        }
        if (!r.ok) { say("Couldn't send your location (error " + r.status + "). Still trying.", "warn"); return; }
        say("Sharing your location with the customer (±" + Math.round(c.accuracy) + " m). Keep the screen on.", "on");
      }).catch(function () { say("No connection. Still trying.", "warn"); });
    });
  }

  function start() {
    retry.hidden = true;
    if (!navigator.geolocation) { say("This browser can't share location, so customers can't see you.", "bad"); return; }
    if (!window.isSecureContext) { say("Location needs a secure (https) page.", "bad"); return; }
    say("Starting your location... allow it when your phone asks.", "warn");
    watch = navigator.geolocation.watchPosition(function (p) {
      var now = Date.now();
      if (now - lastSent < GAP_MS) return;
      lastSent = now; send(p.coords);
    }, function (e) {
      if (e.code === 1) {
        if (watch !== null) navigator.geolocation.clearWatch(watch);
        watch = null; retry.hidden = false;
        say("Location is OFF, so the customer can't see you. Turn it on for this site in your browser settings.", "bad");
      } else {
        say("Waiting for a GPS fix...", "warn");
      }
    }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
    keepAwake();
  }

  retry.addEventListener("click", start);
  start();
})();
