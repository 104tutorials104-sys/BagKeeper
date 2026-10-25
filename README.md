# BagKeeper

Hands-free mall shopping: call a runner, they seal and store your bags, then deliver them to your car.

## Run it (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python seed.py      # demo malls + demo logins (dev only)
.\.venv\Scripts\python run.py       # http://localhost:5000
```

Seed prints three demo logins (admin / runner / customer). Open the runner in a second
browser profile to play both sides.

## Deploy (bagkeeper.hafizassist.com)

1. Push this folder to a private GitHub repo (`.gitignore` already excludes `.venv` and `instance`).
2. Render -> New -> Blueprint -> pick the repo (`render.yaml` and `Dockerfile` do the rest).
   Enter `BAGKEEPER_ADMIN_PHONE` and `BAGKEEPER_ADMIN_PASSWORD` (8+ chars) when asked.
3. Render service -> Settings -> Custom Domains -> add `bagkeeper.hafizassist.com`.
   Render shows a CNAME target.
4. Cloudflare -> hafizassist.com -> DNS -> add `CNAME`, name `bagkeeper`, target = Render's value,
   proxy status "DNS only" until Render finishes issuing HTTPS, then switch to proxied if you like
   (SSL/TLS mode "Full (strict)").
5. Log in at https://bagkeeper.hafizassist.com with that admin, add your malls and runners
   from the Admin page. Do **not** run `seed.py` in production (it creates demo logins).

Data (database + photos) lives on the `/data` disk. Back it up.

## Live updates and alerts

Every screen watches itself (`static/live.js` polls `/api/live` every 4-6 s while the tab is visible):
the shopper's order page, the shopper's list, the runner board and the admin overview refresh when
something changes, and show an alert banner (plus beep, vibration and an optional system notification)
for events such as "your runner is on the way", "new pickup request" or a safety report. A page where
someone is typing or has the camera/map open shows "Tap to refresh" instead of reloading. While a runner is
on the way, the shopper's order page shows the live map with the runner's dot.
Real push notifications while the app is closed need a service worker and a push service (planned, together with the mobile app).

## Who-is-who check (runner and shopper verify each other)

- **Pickup:** the assigned runner and the shopper both see the same rotating phrase (two words and a
  number, changes every 60 s, derived from a per-order secret). The shopper compares it with the runner's
  screen and taps "It matches"; only then is the shopper's 4-digit PIN revealed, which the runner types in.
  Sealing stays locked until both steps are done. Three wrong PINs lock it and alert the admin.
- **Delivery:** the same phrase check reveals the handover code to the shopper.
- **"This isn't my runner":** puts the job on hold (runner can't continue) and shows in the admin
  overview under Safety reports; the admin clears it or reassigns.
- **Admin override:** for a dead shopper phone, with a required reason that is written to the timeline.
- Runners have a badge number (1000 + id) shown to shoppers. Runner photos are planned for later.
- Orders created before this feature have no PIN and skip the check.

## Map and open-source credits

The "Place a pin on the map" picker is built from open-source parts, no API keys or fees:

| Part | What | License |
|---|---|---|
| [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) 5.x | map engine, loaded from jsDelivr only when the picker opens | BSD-3-Clause |
| [OpenFreeMap](https://github.com/hyperknot/openfreemap) | free hosted vector tiles (public instance, no uptime guarantee) | OpenMapTiles / ODbL data |
| OpenStreetMap | base map and the store points in `bagkeeper/static/data/<mall>.geojson` | ODbL, © OpenStreetMap contributors |

Store points were extracted once from OpenStreetMap (named shops and restaurants within 1.1 km of Sawgrass Mills,
166 features). Coverage is partial - Sawgrass has ~350 stores - so the admin can map more places.
The site also refreshes stores from OpenStreetMap by itself (at most weekly, in the background, trying
several public Overpass servers) and the admin Map page has an **Update now** button. New stores appear only if
someone has mapped them in OpenStreetMap. Set `BAGKEEPER_OSM_REFRESH=0` to switch the automatic refresh off.
Always keep the "© OpenStreetMap contributors" credit visible. For heavy production traffic, host the tiles
yourself (Protomaps PMTiles) instead of relying on the public OpenFreeMap instance.

## Layout

| Path | Purpose |
|---|---|
| `bagkeeper/services.py` | All business rules (status flow, seals, handover code). UI-agnostic. |
| `bagkeeper/web.py` | Server-rendered pages (Jinja). |
| `bagkeeper/api.py` | JSON API `/api/...` - what the mobile app will call. |
| `bagkeeper/db.py` | SQLite schema (swap for Postgres later). |
| `bagkeeper/templates`, `static` | Mobile-first UI, dark-mode aware, PWA manifest. |

See [BLUEPRINT.md](BLUEPRINT.md) for the product plan, ideas, names and roadmap.
