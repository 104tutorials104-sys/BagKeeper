/* "Place a pin on the map" - full-screen map picker.
   Open-source stack: MapLibre GL JS (BSD-3) + OpenFreeMap tiles (OpenStreetMap data, ODbL).
   Store points come from our own /static/data/<mall>.geojson (OSM extract) plus the places the
   admin has mapped. The library is loaded lazily, only when someone opens the picker.
   Never blocks the form: if anything fails the shopper just uses the list instead. */
(function () {
  var VER = "5.24.0";   // 5.x still ships the plain-script build; 6.x is ES-module only
  var JS = "https://cdn.jsdelivr.net/npm/maplibre-gl@" + VER + "/dist/maplibre-gl.js";
  var CSS = "https://cdn.jsdelivr.net/npm/maplibre-gl@" + VER + "/dist/maplibre-gl.css";
  var STYLE = "https://tiles.openfreemap.org/styles/liberty";
  var loading = null;

  function loadLib() {
    if (window.maplibregl) return Promise.resolve();
    if (loading) return loading;
    loading = new Promise(function (ok, fail) {
      var l = document.createElement("link"); l.rel = "stylesheet"; l.href = CSS;
      document.head.appendChild(l);
      var s = document.createElement("script"); s.src = JS; s.onload = ok;
      s.onerror = function () { loading = null; fail(new Error("map library")); };
      document.head.appendChild(s);
    });
    return loading;
  }

  function json(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); });
  }

  function openPicker(opts) {
    var ov = document.createElement("div");
    ov.className = "mp";
    ov.setAttribute("role", "dialog");
    ov.innerHTML =
      '<div class="mp-bar"><b>Place your pin</b><button type="button" class="link" data-x>Close</button></div>' +
      '<div class="mp-map"></div>' +
      '<div class="mp-foot"><p class="muted" data-m>Loading the map...</p>' +
      '<button type="button" class="btn" data-ok disabled>Use this spot</button></div>';
    document.body.appendChild(ov);
    document.body.style.overflow = "hidden";
    var msg = ov.querySelector("[data-m]"), ok = ov.querySelector("[data-ok]");
    var map = null, marker = null, chosen = null;

    function close() { if (map) map.remove(); ov.remove(); document.body.style.overflow = ""; }
    function fail(t) { msg.textContent = t; msg.style.color = "var(--bad)"; }
    ov.querySelector("[data-x]").onclick = close;
    ov.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

    function place(lng, lat, name) {
      chosen = { lat: lat, lon: lng, name: name || null };
      marker.setLngLat([lng, lat]).addTo(map);
      ok.disabled = false;
      msg.style.color = "";
      msg.textContent = name ? "Selected: " + name + ". Drag the pin to adjust."
                             : "Pin placed. Drag it to fine-tune, then tap Use this spot.";
    }

    Promise.all([loadLib(), json("/api/malls/" + opts.mallId + "/map")]).then(function (res) {
      var data = res[1];
      var center = opts.start || data.center || [-80.3217, 26.1505];
      map = new maplibregl.Map({
        container: ov.querySelector(".mp-map"), style: STYLE, center: center,
        zoom: opts.start ? 18 : 16.5, maxZoom: 20,
        attributionControl: { compact: true, customAttribution: "Stores &copy; OpenStreetMap contributors" }
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
      marker = new maplibregl.Marker({ draggable: true, color: "#0F766E" });
      marker.on("dragend", function () { var p = marker.getLngLat(); place(p.lng, p.lat, null); });
      msg.textContent = "Tap the map or a store to drop your pin.";

      var loaded = false;
      map.on("error", function () { if (!loaded) fail("The map could not load. Close this and choose from the list instead."); });
      map.on("load", function () {
        loaded = true;
        var zoneFeatures = data.zones.map(function (z) {
          return { type: "Feature", properties: { name: z.name, kind: "zone" },
                   geometry: { type: "Point", coordinates: [z.lon, z.lat] } };
        });
        map.addSource("places", { type: "geojson", data: { type: "FeatureCollection", features: zoneFeatures } });
        map.addLayer({ id: "places-dot", type: "circle", source: "places", paint: {
          "circle-radius": ["case", ["==", ["get", "kind"], "zone"], 8, 5],
          "circle-color": ["case", ["==", ["get", "kind"], "zone"], "#F2A541", "#0F766E"],
          "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff" } });
        map.addLayer({ id: "places-label", type: "symbol", source: "places", minzoom: 16.5, layout: {
          "text-field": ["get", "name"], "text-size": 12, "text-font": ["Noto Sans Regular"],
          "text-anchor": "top", "text-offset": [0, 0.8], "text-optional": true },
          paint: { "text-color": "#14302D", "text-halo-color": "#ffffff", "text-halo-width": 1.6 } });
        if (data.places_url) {
          json(data.places_url).then(function (gj) {
            map.getSource("places").setData({ type: "FeatureCollection",
              features: zoneFeatures.concat(gj.features) });
          }).catch(function () { /* base map still works without the store layer */ });
        }
        map.on("click", function (e) {
          var pad = 12, box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
          var hit = map.queryRenderedFeatures(box, { layers: ["places-dot"] })[0];
          if (hit) { var c = hit.geometry.coordinates; place(c[0], c[1], hit.properties.name); }
          else place(e.lngLat.lng, e.lngLat.lat, null);
        });
        map.on("mouseenter", "places-dot", function () { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "places-dot", function () { map.getCanvas().style.cursor = ""; });
        if (opts.start) place(opts.start[0], opts.start[1], null);
      });
    }).catch(function () { fail("The map could not load. Close this and choose from the list instead."); });

    ok.onclick = function () { if (chosen) { var c = chosen; close(); opts.onConfirm(c); } };
  }

  document.querySelectorAll("[data-map-btn]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var box = btn.closest("[data-loc]");
      var q = function (n) { return box.querySelector("input[name=" + n + "]"); };
      var msg = box.querySelector("[data-loc-msg]");
      var mallId = box.dataset.mall;
      if (!mallId && box.dataset.mallSelect) {
        var sel = document.querySelector(box.dataset.mallSelect);
        mallId = sel && sel.value;
      }
      if (!mallId) { msg.textContent = "Choose the mall first."; return; }
      var lat = parseFloat(q("lat").value), lon = parseFloat(q("lon").value);
      openPicker({
        mallId: mallId,
        start: (isFinite(lat) && isFinite(lon)) ? [lon, lat] : null,
        onConfirm: function (p) {
          q("lat").value = p.lat; q("lon").value = p.lon; q("acc").value = "0"; q("src").value = "map";
          msg.style.color = "var(--ok)";
          msg.textContent = "Pin placed on the map" + (p.name ? " at " + p.name : "") + ".";
          var d = box.dataset.details ? document.querySelector(box.dataset.details) : null;
          if (d && !d.value && p.name) d.value = "At " + p.name;
          box.dispatchEvent(new CustomEvent("bk-pin", { detail: p }));
        }
      });
    });
  });
})();
