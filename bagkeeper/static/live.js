/* Live updates for every screen. The page declares what it shows in <body data-live='{...}'>:
   {"scope": "order|runner|dashboard|admin", "id": 12, "sig": "...", "after": 345}.
   We poll /api/live every few seconds (only while the tab is visible):
     - new events  -> a banner (plus beep, vibration and a system notification when allowed)
     - signature changed -> the page reloads itself, unless the person is in the middle of
       something (typing, camera or map open), in which case we show "Tap to refresh". */
(function () {
  var cfg = null;
  try { cfg = JSON.parse(document.body.dataset.live || "null"); } catch (e) {}
  if (!cfg || !cfg.scope) return;

  var sig = cfg.sig, after = cfg.after;
  var every = cfg.scope === "order" ? 4000 : 6000;
  var box = document.getElementById("toasts");
  var dirty = false, timer = null, unread = 0, baseTitle = document.title, reloading = false;

  document.addEventListener("input", function (e) {
    if (e.target && e.target.matches && e.target.matches("input,textarea,select")) dirty = true;
  }, true);

  // ---------- alerts ----------
  var audio = null;
  function beep() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === "suspended") return;            // browsers block sound until the person has tapped something
      var o = audio.createOscillator(), g = audio.createGain();
      o.type = "sine"; o.frequency.value = 880; g.gain.value = 0.06;
      o.connect(g); g.connect(audio.destination);
      o.start(); o.stop(audio.currentTime + 0.18);
    } catch (e) {}
  }
  ["click", "touchstart", "keydown"].forEach(function (t) {
    document.addEventListener(t, function once() {
      try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); } catch (e) {}
      document.removeEventListener(t, once, true);
    }, true);
  });

  function toast(ev) {
    if (!box) return;
    var d = document.createElement("div");
    d.className = "toast " + (ev.level === "alert" ? "alert" : "");
    var a = document.createElement("a");
    a.href = ev.link || "#"; a.textContent = ev.text;
    a.style.cssText = "flex:1;color:inherit;font-weight:600";
    var x = document.createElement("button");
    x.className = "x"; x.type = "button"; x.setAttribute("aria-label", "Dismiss"); x.textContent = "✕";
    x.onclick = function () { d.remove(); };
    d.appendChild(a); d.appendChild(x); box.appendChild(d);
    setTimeout(function () { d.remove(); }, ev.level === "alert" ? 20000 : 9000);
    if (ev.level === "alert") {
      beep();
      if (navigator.vibrate) navigator.vibrate([140, 70, 140]);
    }
    if (document.hidden) {
      unread += 1; document.title = "(" + unread + ") " + baseTitle;
      if ("Notification" in window && Notification.permission === "granted") {
        try { new Notification("BagKeeper", { body: ev.text, tag: "bk-" + ev.id }); } catch (e) {}
      }
    }
  }

  // optional: ask once (per session) to allow system notifications
  function offerNotifications() {
    if (!box || !("Notification" in window) || Notification.permission !== "default") return;
    try { if (sessionStorage.getItem("bk-notif-asked")) return; sessionStorage.setItem("bk-notif-asked", "1"); } catch (e) {}
    var d = document.createElement("div");
    d.className = "toast";
    d.innerHTML = '<span style="flex:1">Get alerts even when this tab is in the background?</span>';
    var yes = document.createElement("button"); yes.type = "button"; yes.textContent = "Turn on";
    yes.onclick = function () { Notification.requestPermission(); d.remove(); };
    var no = document.createElement("button"); no.type = "button"; no.className = "x"; no.textContent = "Not now";
    no.onclick = function () { d.remove(); };
    d.appendChild(yes); d.appendChild(no); box.appendChild(d);
  }

  // ---------- refreshing ----------
  function busy() {
    if (dirty) return true;
    if (document.querySelector(".cam-ov, .mp")) return true;                       // camera or map picker open
    var files = document.querySelectorAll("input[type=file]");
    for (var i = 0; i < files.length; i++) if (files[i].files && files[i].files.length) return true;
    return false;
  }
  function refreshNow() { if (!reloading) { reloading = true; location.reload(); } }
  function refreshSoon(delay) {
    if (busy()) {
      if (document.getElementById("bk-stale")) return;
      var d = document.createElement("div");
      d.id = "bk-stale"; d.className = "toast alert";
      d.innerHTML = '<span style="flex:1">This page has new information.</span>';
      var b = document.createElement("button"); b.type = "button"; b.textContent = "Tap to refresh";
      b.onclick = refreshNow; d.appendChild(b);
      if (box) box.appendChild(d);
      return;
    }
    setTimeout(refreshNow, delay);
  }

  // ---------- polling ----------
  function poll() {
    if (document.hidden || reloading) return;
    var q = "scope=" + encodeURIComponent(cfg.scope) + (cfg.id ? "&id=" + cfg.id : "") + "&after=" + after;
    fetch("/api/live?" + q, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        after = j.after;
        j.events.forEach(toast);
        if (j.sig !== sig) { sig = j.sig; refreshSoon(j.events.length ? 1800 : 0); }
      }).catch(function () {});
  }
  function start() { clearInterval(timer); timer = setInterval(poll, every); }
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { unread = 0; document.title = baseTitle; poll(); }
  });
  start();
  setTimeout(offerNotifications, 2500);
})();
