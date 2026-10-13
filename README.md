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

## Map and open-source credits

The "Place a pin on the map" picker is built from open-source parts, no API keys or fees:

| Part | What | License |
|---|---|---|
| [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) 5.x | map engine, loaded from jsDelivr only when the picker opens | BSD-3-Clause |
| [OpenFreeMap](https://github.com/hyperknot/openfreemap) | free hosted vector tiles (public instance, no uptime guarantee) | OpenMapTiles / ODbL data |
| OpenStreetMap | base map and the store points in `bagkeeper/static/data/<mall>.geojson` | ODbL, © OpenStreetMap contributors |

Store points were extracted once from OpenStreetMap (named shops and restaurants within 1.1 km of Sawgrass Mills,
166 features). Coverage is partial - Sawgrass has ~350 stores - so the admin can map more places.
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
