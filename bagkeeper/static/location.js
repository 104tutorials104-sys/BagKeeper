/* "Use my location" buttons + small form helpers. Plain JS, no dependencies.
   Markup contract (see templates/_loc.html):
     <div data-loc [data-zone-select="#id"]>
       <button data-loc-btn> <p data-loc-msg>  <input name=lat|lon|acc type=hidden>
   Fixes worse than 150 m are not kept: the server ignores them too. */
(function () {
  var GOOD = 30, MAX = 150;

  function metres(a, b, c, d) {
    var r = Math.PI / 180, x = Math.sin((c - a) * r / 2), y = Math.sin((d - b) * r / 2);
    var h = x * x + Math.cos(a * r) * Math.cos(c * r) * y * y;
    return 2 * 6371000 * Math.asin(Math.sqrt(h));
  }

  function suggestZone(select, lat, lon) {
    var best = null, bestD = 300;               // only suggest if within 300 m
    Array.prototype.forEach.call(select.options, function (o) {
      if (!o.dataset.lat || o.hidden) return;
      var d = metres(lat, lon, parseFloat(o.dataset.lat), parseFloat(o.dataset.lon));
      if (d < bestD) { best = o; bestD = d; }
    });
    return best;
  }

  document.querySelectorAll("[data-loc]").forEach(function (box) {
    var btn = box.querySelector("[data-loc-btn]");
    var msg = box.querySelector("[data-loc-msg]");
    var f = function (n) { return box.querySelector("input[name=" + n + "]"); };
    var select = box.dataset.zoneSelect ? document.querySelector(box.dataset.zoneSelect) : null;

    function clear() { f("lat").value = f("lon").value = f("acc").value = ""; }
    function say(t, tone) { msg.textContent = t; msg.style.color = tone ? "var(--" + tone + ")" : ""; }

    btn.addEventListener("click", function () {
      clear();
      if (!navigator.geolocation) { say("This browser can't share location. Please choose below.", "warn"); return; }
      if (!window.isSecureContext) { say("Location needs a secure (https) page.", "warn"); return; }
      btn.disabled = true; say("Finding you...");
      navigator.geolocation.getCurrentPosition(function (p) {
        btn.disabled = false;
        var c = p.coords, acc = Math.round(c.accuracy);
        if (acc > MAX) { say("Signal too weak here (±" + acc + " m). Please choose where you are below.", "bad"); return; }
        f("lat").value = c.latitude; f("lon").value = c.longitude; f("acc").value = c.accuracy;
        if (acc <= GOOD) say("Location found (±" + acc + " m).", "ok");
        else say("Approximate location (±" + acc + " m). Please also choose the place below.", "warn");
        if (select && !select.value) {
          var z = suggestZone(select, c.latitude, c.longitude);
          if (z) { select.value = z.value; msg.textContent += " Nearest: " + z.textContent.trim() + "."; }
        }
      }, function (e) {
        btn.disabled = false;
        say(e.code === 1 ? "Location is blocked. Allow it in your browser settings, or choose below."
                         : "Couldn't get a location. Please choose below.", "bad");
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    });
  });

  // <select data-filter-by="mall_id">: show only zone options whose data-mall matches
  document.querySelectorAll("select[data-filter-by]").forEach(function (zoneSel) {
    var driver = document.getElementById(zoneSel.dataset.filterBy);
    if (!driver) return;
    function apply() {
      var keep = driver.value, current = zoneSel.options[zoneSel.selectedIndex];
      Array.prototype.forEach.call(zoneSel.options, function (o) {
        if (!o.dataset.mall) return;
        var hide = o.dataset.mall !== keep;
        o.hidden = hide; o.disabled = hide;
      });
      if (current && current.disabled) zoneSel.value = "";
    }
    driver.addEventListener("change", apply); apply();
  });
})();
