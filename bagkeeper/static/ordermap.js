/* Read-only map for one order: pickup / delivery pins on our own map, with store labels,
   GPS accuracy circles, and the viewer's own blue dot. Uses the loader from mappick.js. */
(function () {
  var root = document.getElementById("omap");
  if (!root || !window.BK) return;
  var msg = document.getElementById("omap-msg");
  var pins = JSON.parse(root.dataset.pins);

  function say(t, tone) { msg.textContent = t; msg.style.color = tone ? "var(--" + tone + ")" : ""; }

  // polygon approximating a circle of r metres around a point
  function circle(lon, lat, r) {
    var pts = [], dLat = r / 111320, dLon = r / (111320 * Math.cos(lat * Math.PI / 180));
    for (var i = 0; i <= 48; i++) {
      var a = i / 48 * 2 * Math.PI;
      pts.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
    }
    return { type: "Polygon", coordinates: [pts] };
  }

  Promise.all([
    window.BK.loadMapLib(),
    fetch("/api/malls/" + root.dataset.mall + "/map").then(function (r) { return r.json(); })
  ]).then(function (res) {
    var data = res[1], first = pins[0];
    var map = new maplibregl.Map({
      container: root, style: window.BK.MAP_STYLE, center: [first.lon, first.lat], zoom: 18, maxZoom: 20,
      attributionControl: { compact: true, customAttribution: "Stores &copy; OpenStreetMap contributors" }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
    map.addControl(new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
      trackUserLocation: true, showAccuracyCircle: true, showUserLocation: true }));

    pins.forEach(function (p, i) {
      var m = new maplibregl.Marker({ color: p.color }).setLngLat([p.lon, p.lat])
        .setPopup(new maplibregl.Popup({ offset: 28 }).setText(p.label)).addTo(map);
      if (i === 0) m.togglePopup();
    });
    if (pins.length > 1) {
      var b = new maplibregl.LngLatBounds();
      pins.forEach(function (p) { b.extend([p.lon, p.lat]); });
      map.fitBounds(b, { padding: 90, maxZoom: 18, duration: 0 });
    }

    var loaded = false;
    map.on("error", function () { if (!loaded) say("The map could not load. The written place below still applies.", "bad"); });
    map.on("load", function () {
      loaded = true;
      say("Tap a pin for its label.");
      // GPS accuracy circles (map pins have none)
      var circles = pins.filter(function (p) { return p.src !== "map" && p.acc > 0; }).map(function (p) {
        return { type: "Feature", properties: { color: p.color }, geometry: circle(p.lon, p.lat, p.acc) };
      });
      map.addSource("acc", { type: "geojson", data: { type: "FeatureCollection", features: circles } });
      map.addLayer({ id: "acc-fill", type: "fill", source: "acc", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.15 } });
      map.addLayer({ id: "acc-line", type: "line", source: "acc", paint: { "line-color": ["get", "color"], "line-width": 1.5 } });
      // store labels
      var feats = (data.zones || []).map(function (z) {
        return { type: "Feature", properties: { name: z.name, kind: "zone" }, geometry: { type: "Point", coordinates: [z.lon, z.lat] } };
      }).concat((data.extra_places || []).map(function (p) {
        return { type: "Feature", properties: { name: p.name, kind: p.kind }, geometry: { type: "Point", coordinates: [p.lon, p.lat] } };
      }));
      map.addSource("places", { type: "geojson", data: { type: "FeatureCollection", features: feats } });
      map.addLayer({ id: "places-dot", type: "circle", source: "places", paint: {
        "circle-radius": 4, "circle-color": "#0F766E", "circle-stroke-width": 1.2, "circle-stroke-color": "#fff" } });
      map.addLayer({ id: "places-label", type: "symbol", source: "places", minzoom: 16, layout: {
        "text-field": ["get", "name"], "text-size": 12, "text-font": ["Noto Sans Regular"],
        "text-anchor": "top", "text-offset": [0, 0.8], "text-optional": true },
        paint: { "text-color": "#14302D", "text-halo-color": "#ffffff", "text-halo-width": 1.6 } });
      if (data.places_url) {
        fetch(data.places_url).then(function (r) { return r.json(); }).then(function (gj) {
          map.getSource("places").setData({ type: "FeatureCollection", features: feats.concat(gj.features) });
        }).catch(function () {});
      }
    });
  }).catch(function () { say("The map could not load. The written place below still applies.", "bad"); });
})();
