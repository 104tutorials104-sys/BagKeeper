/* Admin "Mark stores on the map": tap to place a pin, name it in the form, save.
   Uses the shared MapLibre loader exposed by mappick.js (window.BK). */
(function () {
  var root = document.getElementById("amap");
  if (!root || !window.BK) return;
  var msg = document.getElementById("amap-msg");
  var latI = document.getElementById("p-lat"), lonI = document.getElementById("p-lon");
  var save = document.getElementById("p-save"), nameI = document.getElementById("p-name");
  var focus = (root.dataset.lat && root.dataset.lon)
    ? [parseFloat(root.dataset.lon), parseFloat(root.dataset.lat)] : null;

  function say(t, tone) { msg.textContent = t; msg.style.color = tone ? "var(--" + tone + ")" : ""; }

  Promise.all([
    window.BK.loadMapLib(),
    fetch("/api/malls/" + root.dataset.mall + "/map").then(function (r) { return r.json(); })
  ]).then(function (res) {
    var data = res[1];
    var center = focus || data.center || [-80.3217, 26.1505];
    var map = new maplibregl.Map({
      container: root, style: window.BK.MAP_STYLE, center: center, zoom: focus ? 18 : 16.5, maxZoom: 20,
      attributionControl: { compact: true, customAttribution: "Stores &copy; OpenStreetMap contributors" }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
    // blue dot: stand at a store, tap it, then tap the map right where you are
    map.addControl(new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
      trackUserLocation: true, showAccuracyCircle: true, showUserLocation: true }));
    var marker = new maplibregl.Marker({ draggable: true, color: "#D97706" });
    var loaded = false;

    function place(lng, lat) {
      marker.setLngLat([lng, lat]).addTo(map);
      latI.value = lat; lonI.value = lng; save.disabled = false;
      say("Spot chosen. Type the store name below and save.", "ok");
      nameI.focus({ preventScroll: true });
    }
    marker.on("dragend", function () { var p = marker.getLngLat(); place(p.lng, p.lat); });

    map.on("error", function () { if (!loaded) say("The map could not load. Try again in a moment.", "bad"); });
    map.on("load", function () {
      loaded = true;
      var extra = (data.extra_places || []).map(function (p) {
        return { type: "Feature", properties: { name: p.name, extra: 1 },
                 geometry: { type: "Point", coordinates: [p.lon, p.lat] } };
      });
      var live = (data.live_places || []).map(function (p) {          // refreshed from OpenStreetMap
        return { type: "Feature", properties: { name: p.name },
                 geometry: { type: "Point", coordinates: [p.lon, p.lat] } };
      });
      map.addSource("base", { type: "geojson", data: { type: "FeatureCollection", features: live } });
      map.addSource("extra", { type: "geojson", data: { type: "FeatureCollection", features: extra } });
      map.addLayer({ id: "base-dot", type: "circle", source: "base", paint: {
        "circle-radius": 5, "circle-color": "#0F766E", "circle-stroke-width": 1.5, "circle-stroke-color": "#fff" } });
      map.addLayer({ id: "extra-dot", type: "circle", source: "extra", paint: {
        "circle-radius": 7, "circle-color": "#F2A541", "circle-stroke-width": 2, "circle-stroke-color": "#fff" } });
      ["base", "extra"].forEach(function (s) {
        map.addLayer({ id: s + "-label", type: "symbol", source: s, minzoom: 16.5, layout: {
          "text-field": ["get", "name"], "text-size": 12, "text-font": ["Noto Sans Regular"],
          "text-anchor": "top", "text-offset": [0, 0.9], "text-optional": true },
          paint: { "text-color": "#14302D", "text-halo-color": "#ffffff", "text-halo-width": 1.6 } });
      });
      if (data.places_url) {
        fetch(data.places_url).then(function (r) { return r.json(); }).then(function (gj) {
          map.getSource("base").setData({ type: "FeatureCollection", features: live.concat(gj.features) });
        }).catch(function () {});
      }
      map.on("click", function (e) {
        var pad = 10, box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
        var hit = map.queryRenderedFeatures(box, { layers: ["base-dot", "extra-dot"] })[0];
        if (hit) { say("Already on the map: " + hit.properties.name + ". Tap an empty spot to add another.", "warn"); return; }
        place(e.lngLat.lng, e.lngLat.lat);
      });
      say(focus ? "Saved. Tap another empty spot to add more." : "Tap an empty spot where the store is.");
    });
  }).catch(function () { say("The map could not load. Try again in a moment.", "bad"); });
})();
