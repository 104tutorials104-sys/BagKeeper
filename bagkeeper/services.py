"""Business logic. No Flask request/session code here, so the web UI and the
JSON API (and later a mobile app) all go through the same rules."""
import secrets
import sqlite3
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

# status flow:
# requested -> assigned -> picked_up -> stored -> return_requested
#           -> out_for_delivery -> delivered      (cancelled: only before pickup)
ACTIVE = ("requested", "assigned", "picked_up", "stored", "return_requested", "out_for_delivery")


class RuleError(Exception):
    """A user-facing business rule violation."""


# ---------- users ----------
UNCLAIMED_MINUTES = 5

# ---- live runner tracking ----
SHARE_STATUSES = ("assigned", "out_for_delivery")   # runner heading to pickup / bringing bags
POSITION_STALE_S = 45        # older than this = "paused"
POSITION_MIN_GAP_S = 2       # ignore updates faster than this
MAX_TRACK_ACCURACY_M = 500


def create_user(name, phone, password, role="customer", mall_id=None):
    name, phone = name.strip(), "".join(c for c in phone if c.isdigit() or c == "+")
    if not name or len(phone) < 7:
        raise RuleError("Enter your name and a valid phone number.")
    if len(password) < (8 if role != "customer" else 4):
        raise RuleError(f"Password must be at least {8 if role != 'customer' else 4} characters.")
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
        raise RuleError("That phone number is already registered.")
    if role == "runner" and not mall_id:
        raise RuleError("A runner must be assigned to a mall.")
    cur = db.execute(
        "INSERT INTO users (name, phone, role, pw_hash, mall_id) VALUES (?,?,?,?,?)",
        (name, phone, role, generate_password_hash(password),
         mall_id if role == "runner" else None),
    )
    if role == "runner":
        db.execute("UPDATE users SET badge=? WHERE id=?", (str(1000 + cur.lastrowid), cur.lastrowid))
    db.commit()
    return cur.lastrowid


def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def set_duty(user_id, on_duty):
    get_db().execute("UPDATE users SET on_duty=? WHERE id=?", (1 if on_duty else 0, user_id))
    get_db().commit()


def runners(mall_id=None):
    sql, args = "SELECT * FROM users WHERE role='runner'", ()
    if mall_id:
        sql, args = sql + " AND mall_id=?", (mall_id,)
    return get_db().execute(sql + " ORDER BY on_duty DESC, name", args).fetchall()


def unclaimed_clause():
    """SQL: jobs nobody has taken for UNCLAIMED_MINUTES."""
    return (f"o.status IN ('requested','return_requested') AND "
            f"o.updated_at <= datetime('now','-{UNCLAIMED_MINUTES} minutes')")


def reassign(order_id, admin_id, runner_id):
    o = get_order(order_id)
    if o["status"] not in ("requested", "assigned", "picked_up", "return_requested",
                           "out_for_delivery"):
        raise RuleError("This order can't be reassigned now.")
    r = get_db().execute("SELECT * FROM users WHERE id=? AND role='runner'",
                         (runner_id,)).fetchone()
    if r is None or r["mall_id"] != o["mall_id"]:
        raise RuleError("Pick a runner from the same mall.")
    # keep the status as is: a requested/return_requested job becomes assigned/out_for_delivery
    # only when the runner acts; reassigning just changes who is responsible.
    new_status = {"requested": "assigned"}.get(o["status"], o["status"])
    get_db().execute("DELETE FROM runner_positions WHERE order_id=?", (order_id,))
    # a new runner starts from scratch: verification, PIN tries and any safety report are reset
    _set(order_id, runner_id=runner_id, status=new_status, verified_at=None, pin_ok_at=None,
         pin_fails=0, pin_locked=0, delivery_verified_at=None, safety_flag=None, safety_note=None)
    log(order_id, admin_id, "reassigned", f"to {r['name']}")
    get_db().commit()


def authenticate(phone, password):
    phone = "".join(c for c in phone if c.isdigit() or c == "+")
    row = get_db().execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    if row and check_password_hash(row["pw_hash"], password):
        return row
    return None


# ---------- helpers ----------
def log(order_id, actor_id, event, detail=None):
    get_db().execute(
        "INSERT INTO events (order_id, actor_id, event, detail) VALUES (?,?,?,?)",
        (order_id, actor_id, event, detail),
    )


def _set(order_id, **fields):
    # live tracking only exists while the runner is heading to / bringing the bags
    if fields.get("status") and fields["status"] not in SHARE_STATUSES:
        get_db().execute("DELETE FROM runner_positions WHERE order_id=?", (order_id,))
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(
        f"UPDATE orders SET {cols}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (*fields.values(), order_id),
    )


def get_order(order_id):
    return get_db().execute(
        """SELECT o.*, m.name AS mall, c.name AS customer, c.phone AS customer_phone,
                  r.name AS runner, r.badge AS runner_badge
           FROM orders o JOIN malls m ON m.id=o.mall_id
           JOIN users c ON c.id=o.customer_id
           LEFT JOIN users r ON r.id=o.runner_id WHERE o.id=?""",
        (order_id,),
    ).fetchone()


def list_orders(where="1=1", args=()):
    return get_db().execute(
        f"""SELECT o.*, m.name AS mall, c.name AS customer, r.name AS runner,
                   CASE WHEN rp.ts IS NULL THEN NULL
                        ELSE CAST(strftime('%s','now') AS REAL) - rp.ts END AS pos_age
            FROM orders o JOIN malls m ON m.id=o.mall_id
            JOIN users c ON c.id=o.customer_id
            LEFT JOIN users r ON r.id=o.runner_id
            LEFT JOIN runner_positions rp ON rp.runner_id=o.runner_id AND rp.order_id=o.id
            WHERE {where} ORDER BY o.updated_at DESC""",
        args,
    ).fetchall()


def order_events(order_id):
    return get_db().execute(
        """SELECT e.*, u.name AS actor FROM events e
           LEFT JOIN users u ON u.id=e.actor_id WHERE order_id=? ORDER BY e.id""",
        (order_id,),
    ).fetchall()


def order_photos(order_id):
    return get_db().execute(
        "SELECT * FROM photos WHERE order_id=? ORDER BY id", (order_id,)
    ).fetchall()


def malls():
    return get_db().execute("SELECT * FROM malls ORDER BY name").fetchall()


def save_photo(order_id, kind, file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = Path(file_storage.filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        raise RuleError("Photos must be JPG, PNG, WEBP or HEIC.")
    name = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(Path(current_app.config["UPLOAD_DIR"]) / name)
    get_db().execute(
        "INSERT INTO photos (order_id, kind, filename) VALUES (?,?,?)",
        (order_id, kind, name),
    )
    return name


# ---------- customer actions ----------
# ---------- places: malls, zones, GPS pins ----------
GOOD_ACCURACY_M = 30
MAX_PIN_ACCURACY_M = 150      # worse than this and we ignore the pin


def get_mall(mall_id):
    return get_db().execute("SELECT * FROM malls WHERE id=?", (mall_id,)).fetchone()


PLACE_KINDS = ("shop", "food", "service", "other")


def _slug(name):
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def map_places(mall_id, include_inactive=False):
    sql = "SELECT * FROM map_places WHERE mall_id=?"
    if not include_inactive:
        sql += " AND active=1"
    return get_db().execute(sql + " ORDER BY name", (mall_id,)).fetchall()


def add_map_place(mall_id, admin_id, name, kind, lat, lon):
    mall = get_mall(mall_id)
    name = (name or "").strip()
    if mall is None or not (2 <= len(name) <= 60):
        raise RuleError("Enter the store name (2-60 characters).")
    if kind not in PLACE_KINDS:
        raise RuleError("Choose a type.")
    plat, plon, _ = parse_pin(lat, lon, 0)
    if plat is None:
        raise RuleError("Tap the map to choose where it is.")
    if pin_inside_mall(mall, plat, plon) is False:
        raise RuleError("That spot is outside the mall area. Move the pin, or enlarge the radius in Places and map settings.")
    for p in map_places(mall_id):
        if p["name"].lower() == name.lower() and distance_m(plat, plon, p["lat"], p["lon"]) < 40:
            raise RuleError(f"{p['name']} is already on the map there.")
    get_db().execute(
        "INSERT INTO map_places (mall_id, name, kind, lat, lon, created_by) VALUES (?,?,?,?,?,?)",
        (mall_id, name, kind, plat, plon, admin_id))
    get_db().commit()


def toggle_map_place(place_id):
    get_db().execute("UPDATE map_places SET active = 1 - active WHERE id=?", (place_id,))
    get_db().commit()


# ---------- stores from OpenStreetMap (auto-refreshed) ----------
OSM_TTL_S = 7 * 24 * 3600        # refresh at most weekly
OSM_RETRY_S = 3600               # after a failed try, wait an hour
_refresh_running = set()
_refresh_lock = None
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)


def _kind_for(tags):
    if tags.get("shop"):
        return "shop"
    amenity = tags.get("amenity", "")
    if amenity in ("cinema", "bank", "pharmacy"):
        return "service" if amenity != "cinema" else "other"
    return "food"


def _overpass_fetch(lat, lon, radius_m):
    """Named shops and eateries around a point, from OpenStreetMap (Overpass API)."""
    import json
    import urllib.parse
    import urllib.request
    q = ("[out:json][timeout:60];("
         f'nwr["shop"]["name"](around:{radius_m},{lat},{lon});'
         f'nwr["amenity"~"^(restaurant|cafe|fast_food|food_court|ice_cream|cinema|bank|pharmacy)$"]["name"]'
         f"(around:{radius_m},{lat},{lon});"
         ");out tags center 4000;")
    body = urllib.parse.urlencode({"data": q}).encode()
    data, last_error = None, None
    for endpoint in OVERPASS_ENDPOINTS:            # public servers are often busy: try the next one
        req = urllib.request.Request(endpoint, data=body, headers={
            "User-Agent": "BagKeeper/0.1 (mall bag-holding service)", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
            break
        except Exception as e:                      # 502/429/timeouts, etc.
            last_error = e
    if data is None:
        raise last_error
    out = []
    for e in data.get("elements", []):
        tags = e.get("tags", {})
        name = (tags.get("name") or "").strip()
        pt = e if e.get("type") == "node" else (e.get("center") or {})
        if not name or pt.get("lat") is None or pt.get("lon") is None:
            continue
        out.append({"osm": f"{e['type']}/{e['id']}", "name": name[:80], "kind": _kind_for(tags),
                    "lat": pt["lat"], "lon": pt["lon"]})
    return out


def osm_status(mall_id):
    row = get_db().execute("SELECT * FROM osm_refresh WHERE mall_id=?", (mall_id,)).fetchone()
    n = get_db().execute("SELECT COUNT(*) FROM osm_places WHERE mall_id=?", (mall_id,)).fetchone()[0]
    return {"last_ok": row["last_ok"] if row else None, "count": n,
            "last_try": row["last_try"] if row else None,
            "last_error": row["last_error"] if row else None}


def refresh_osm_places(mall_id, fetch=None):
    """Pull the mall's stores from OpenStreetMap. Returns {"total", "new", "removed"}.
    An empty or failed answer never wipes what we already have."""
    import time
    mall = get_mall(mall_id)
    if mall is None or mall["lat"] is None:
        raise RuleError("Set the mall's centre point first.")
    fetch = fetch or _overpass_fetch
    radius = min(mall["radius_m"] or 1100, 1500)
    db, now = get_db(), time.time()
    db.execute("INSERT INTO osm_refresh (mall_id, last_try) VALUES (?,?) "
               "ON CONFLICT(mall_id) DO UPDATE SET last_try=excluded.last_try", (mall_id, now))
    db.commit()
    try:
        rows = fetch(mall["lat"], mall["lon"], radius)
    except Exception as e:
        why = f"{type(e).__name__}: {e}"[:300]
        current_app.logger.warning("OpenStreetMap refresh failed for mall %s: %s", mall_id, why)
        db.execute("UPDATE osm_refresh SET last_error=? WHERE mall_id=?", (why, mall_id))
        db.commit()
        raise RuleError("OpenStreetMap is busy right now. Try again in a few minutes.")
    if not rows:
        db.execute("UPDATE osm_refresh SET last_error=? WHERE mall_id=?", ("empty answer", mall_id))
        db.commit()
        raise RuleError("OpenStreetMap returned nothing, so nothing was changed.")
    before = {r[0] for r in db.execute("SELECT osm_id FROM osm_places WHERE mall_id=?", (mall_id,))}
    for r in rows:
        db.execute("INSERT OR REPLACE INTO osm_places (mall_id, osm_id, name, kind, lat, lon, seen_at)"
                   " VALUES (?,?,?,?,?,?,?)", (mall_id, r["osm"], r["name"], r["kind"], r["lat"], r["lon"], now))
    db.execute("DELETE FROM osm_places WHERE mall_id=? AND seen_at < ?", (mall_id, now))
    ids = {r["osm"] for r in rows}
    db.execute("UPDATE osm_refresh SET last_ok=?, count=?, last_error=NULL WHERE mall_id=?",
               (now, len(ids), mall_id))
    db.commit()
    return {"total": len(ids), "new": len(ids - before), "removed": len(before - ids)}


def osm_refresh_due(mall_id):
    import time
    row = get_db().execute("SELECT * FROM osm_refresh WHERE mall_id=?", (mall_id,)).fetchone()
    now = time.time()
    if row is None:
        return True
    if row["last_try"] and now - row["last_try"] < OSM_RETRY_S:
        return False
    return not row["last_ok"] or now - row["last_ok"] > OSM_TTL_S


def maybe_refresh_async(mall_id):
    """Called when the map is opened: if the weekly refresh is due, do it in the background
    so nobody waits. Set BAGKEEPER_OSM_REFRESH=0 to turn this off."""
    import os
    import threading
    global _refresh_lock
    if os.environ.get("BAGKEEPER_OSM_REFRESH") == "0" or not osm_refresh_due(mall_id):
        return
    if _refresh_lock is None:
        _refresh_lock = threading.Lock()
    with _refresh_lock:
        if mall_id in _refresh_running:
            return
        _refresh_running.add(mall_id)
    app = current_app._get_current_object()

    def work():
        try:
            with app.app_context():
                refresh_osm_places(mall_id)
        except RuleError:
            pass                              # already logged and recorded in osm_refresh
        except Exception:
            app.logger.exception("background OpenStreetMap refresh crashed (mall %s)", mall_id)
        finally:
            with _refresh_lock:
                _refresh_running.discard(mall_id)

    threading.Thread(target=work, daemon=True).start()


def _static_osm_ids(mall):
    return {f["properties"].get("osm") for f in _static_features(mall)}


def live_places(mall_id):
    """Refreshed OpenStreetMap stores that are not already in the committed file."""
    mall = get_mall(mall_id)
    skip = _static_osm_ids(mall)
    rows = get_db().execute("SELECT * FROM osm_places WHERE mall_id=? ORDER BY name", (mall_id,)).fetchall()
    return [r for r in rows if r["osm_id"] not in skip]


def export_places_geojson(mall_id):
    """Static file points + hand-added places, as one GeoJSON a developer can commit to
    bagkeeper/static/data/<mall>.geojson so they survive hosting resets."""
    import json
    from pathlib import Path
    mall = get_mall(mall_id)
    path = Path(current_app.static_folder) / "data" / f"{_slug(mall['name'])}.geojson"
    try:
        base = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        base = {"type": "FeatureCollection", "features": []}
    feats = list(base.get("features", []))
    for p in live_places(mall_id):
        feats.append({"type": "Feature",
                      "properties": {"name": p["name"], "kind": p["kind"], "osm": p["osm_id"]},
                      "geometry": {"type": "Point",
                                   "coordinates": [round(p["lon"], 6), round(p["lat"], 6)]}})
    for p in map_places(mall_id):
        feats.append({"type": "Feature",
                      "properties": {"name": p["name"], "kind": p["kind"], "osm": "manual"},
                      "geometry": {"type": "Point",
                                   "coordinates": [round(p["lon"], 6), round(p["lat"], 6)]}})
    return {"type": "FeatureCollection",
            "attribution": base.get("attribution", "Data (c) OpenStreetMap contributors, ODbL"),
            "features": feats}


def map_data(mall_id):
    """Everything the map picker needs for one mall."""
    from pathlib import Path
    mall = get_mall(mall_id)
    if mall is None:
        return None
    slug = _slug(mall["name"])
    places = Path(current_app.static_folder) / "data" / f"{slug}.geojson"
    return {
        "name": mall["name"],
        "center": [mall["lon"], mall["lat"]] if mall["lat"] is not None else None,
        "radius_m": mall["radius_m"],
        "places_url": f"/static/data/{slug}.geojson" if places.exists() else None,
        "extra_places": [{"id": p["id"], "name": p["name"], "kind": p["kind"],
                          "lat": p["lat"], "lon": p["lon"]} for p in map_places(mall_id)],
        "live_places": [{"name": p["name"], "kind": p["kind"], "lat": p["lat"], "lon": p["lon"]}
                        for p in live_places(mall_id)],
        "zones": [{"id": z["id"], "name": z["name"], "kind": z["kind"],
                   "lat": z["lat"], "lon": z["lon"]}
                  for z in zones(mall_id) if z["lat"] is not None],
    }


def zones(mall_id=None, kinds=None, include_inactive=False):
    sql, args = "SELECT * FROM zones WHERE 1=1", []
    if mall_id:
        sql += " AND mall_id=?"
        args.append(mall_id)
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += list(kinds)
    if not include_inactive:
        sql += " AND active=1"
    return get_db().execute(sql + " ORDER BY kind, name", args).fetchall()


def _zone(zone_id, mall_id, kinds):
    try:
        zone_id = int(zone_id)
    except (TypeError, ValueError):
        raise RuleError("Choose where you are from the list.")
    z = get_db().execute("SELECT * FROM zones WHERE id=? AND mall_id=? AND active=1",
                         (zone_id, mall_id)).fetchone()
    if z is None or z["kind"] not in kinds:
        raise RuleError("That place isn't available at this mall.")
    return z


def parse_pin(lat, lon, acc):
    """Return (lat, lon, accuracy) or (None, None, None). Bad or very weak pins are dropped."""
    try:
        lat, lon = float(lat), float(lon)
        acc = float(acc) if acc not in (None, "") else None
    except (TypeError, ValueError):
        return None, None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None, None, None
    if acc is None or acc < 0 or acc > MAX_PIN_ACCURACY_M:
        return None, None, None
    return lat, lon, acc


def parse_any_pin(lat, lon, acc, src):
    """Pin from either source. src 'map' = placed by the customer on the map (accuracy 0);
    anything else is treated as a GPS fix and needs a usable accuracy.
    Returns (lat, lon, accuracy, src) or four Nones."""
    if src == "map":
        plat, plon, _ = parse_pin(lat, lon, 0)
        return (plat, plon, 0.0, "map") if plat is not None else (None, None, None, None)
    plat, plon, pacc = parse_pin(lat, lon, acc)
    return (plat, plon, pacc, "gps") if plat is not None else (None, None, None, None)


def distance_m(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def pin_inside_mall(mall, lat, lon):
    """True/False, or None when the mall has no centre set or there is no pin."""
    if lat is None or mall["lat"] is None or not mall["radius_m"]:
        return None
    return distance_m(lat, lon, mall["lat"], mall["lon"]) <= mall["radius_m"]


_places_cache = {}


def _static_features(mall):
    """Features of the committed store file for this mall (cached; [] if there is none)."""
    import json
    from pathlib import Path
    slug = _slug(mall["name"])
    if slug not in _places_cache:
        path = Path(current_app.static_folder) / "data" / f"{slug}.geojson"
        try:
            _places_cache[slug] = json.loads(path.read_text(encoding="utf-8-sig"))["features"]
        except (OSError, ValueError, KeyError):
            _places_cache[slug] = []
    return _places_cache[slug]


def _nearest_place(mall, lat, lon, within_m=150):
    """Name of the closest known store/place for this mall, or None."""
    best, best_d = None, within_m
    candidates = [(f["properties"]["name"], f["geometry"]["coordinates"][1],
                   f["geometry"]["coordinates"][0]) for f in _static_features(mall)]
    candidates += [(p["name"], p["lat"], p["lon"]) for p in map_places(mall["id"])]
    candidates += [(r["name"], r["lat"], r["lon"]) for r in get_db().execute(
        "SELECT name, lat, lon FROM osm_places WHERE mall_id=?", (mall["id"],))]
    for name, lat2, lon2 in candidates:
        d = distance_m(lat, lon, lat2, lon2)
        if d < best_d:
            best, best_d = name, d
    return best


def _pin_stands_alone(acc, src):
    """A pin can replace choosing a place only if it was placed on the map or is a good GPS fix."""
    return src == "map" or (acc is not None and acc <= GOOD_ACCURACY_M)


def _pin_label(mall, lat, lon, details, src="map"):
    near = _nearest_place(mall, lat, lon)
    kind = "Pin on map" if src == "map" else "GPS pin"
    text = f"{kind} near {near}" if near else kind
    return f"{text} - {details.strip()}" if details and details.strip() else text


def _where(zone, level, details, mall):
    parts = [zone["name"]]
    levels = [x.strip() for x in (mall["levels"] or "").split(",") if x.strip()]
    if level and len(levels) > 1 and level in levels:
        parts.append(level)
    text = ", ".join(parts)
    return f"{text} - {details.strip()}" if details and details.strip() else text


def create_order(customer_id, mall_id, zone_id, bag_count, details="", note="",
                 level="", lat=None, lon=None, acc=None, src=None):
    mall = get_mall(mall_id)
    if mall is None:
        raise RuleError("Choose a mall.")
    plat, plon, pacc, psrc = parse_any_pin(lat, lon, acc, src)
    if zone_id in (None, ""):
        if plat is None or not _pin_stands_alone(pacc, psrc):
            raise RuleError("Choose where you are from the list, or drop a pin on the map.")
        zone = None
        pickup_spot = _pin_label(mall, plat, plon, details, psrc)
    else:
        zone = _zone(zone_id, mall_id, ("area", "entrance", "parking"))
        pickup_spot = _where(zone, level, details, mall)
    bag_count = max(1, min(int(bag_count or 1), 10))
    cfg = current_app.config
    fee = cfg["BASE_FEE_CENTS"] + (bag_count - 1) * cfg["EXTRA_BAG_FEE_CENTS"]
    db = get_db()
    code = "BK-" + secrets.token_hex(2).upper()
    cur = db.execute(
        """INSERT INTO orders (code, customer_id, mall_id, pickup_spot, pickup_zone_id,
               pickup_level, pickup_details, pickup_lat, pickup_lon, pickup_acc, pickup_src,
               bag_count, note, fee_cents, pickup_pin, verify_secret)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (code, customer_id, mall_id, pickup_spot, zone["id"] if zone else None, level or None,
         (details or "").strip() or None, plat, plon, pacc, psrc, bag_count, note.strip(), fee,
         f"{secrets.randbelow(10000):04d}", secrets.token_hex(16)),
    )
    where = pickup_spot + _pin_note(pacc, psrc)
    log(cur.lastrowid, customer_id, "requested", f"{bag_count} bag(s) at {where}")
    db.commit()
    return cur.lastrowid


def cancel_order(order_id, customer_id):
    o = get_order(order_id)
    if o["customer_id"] != customer_id:
        raise RuleError("Not your order.")
    if o["status"] not in ("requested", "assigned"):
        raise RuleError("Too late to cancel - your bag is already with us.")
    _set(order_id, status="cancelled")
    log(order_id, customer_id, "cancelled")
    get_db().commit()


def _pin_note(acc, src):
    if src == "map":
        return " (pin placed on map)"
    return f" (GPS +/-{acc:.0f} m)" if acc is not None else ""


def request_return(order_id, customer_id, zone_id, details="", lat=None, lon=None, acc=None,
                   src=None):
    o = get_order(order_id)
    if o["customer_id"] != customer_id:
        raise RuleError("Not your order.")
    if o["status"] not in ("picked_up", "stored"):
        raise RuleError("Bag can't be returned at this stage.")
    mall = get_mall(o["mall_id"])
    dlat, dlon, dacc, dsrc = parse_any_pin(lat, lon, acc, src)
    if zone_id in (None, ""):
        if dlat is None or not _pin_stands_alone(dacc, dsrc):
            raise RuleError("Choose a parking area or exit, or drop a pin on the map.")
        zone = None
        dropoff_spot = _pin_label(mall, dlat, dlon, details, dsrc)
    else:
        zone = _zone(zone_id, o["mall_id"], ("parking", "entrance"))
        if not (details or "").strip() and dlat is None:
            raise RuleError("Add a few details (row, bay, car colour) or use your location.")
        dropoff_spot = _where(zone, "", details, mall)
    code = f"{secrets.randbelow(10000):04d}"
    _set(order_id, status="return_requested", dropoff_spot=dropoff_spot,
         dropoff_zone_id=zone["id"] if zone else None,
         dropoff_details=(details or "").strip() or None,
         dropoff_lat=dlat, dropoff_lon=dlon, dropoff_acc=dacc, dropoff_src=dsrc,
         handover_code=code)
    where = dropoff_spot + _pin_note(dacc, dsrc)
    log(order_id, customer_id, "return_requested", where)
    get_db().commit()


# ---------- live runner position ----------
def runner_may_share(order, user_id):
    return (order is not None and order["runner_id"] == user_id
            and order["status"] in SHARE_STATUSES)


def save_runner_position(order_id, runner_id, lat, lon, acc=None, heading=None):
    """Store the runner's latest position. Returns False when skipped (too frequent)."""
    import time
    try:
        lat, lon = float(lat), float(lon)
        acc = float(acc) if acc not in (None, "") else None
        heading = float(heading) if heading not in (None, "") else None
    except (TypeError, ValueError):
        raise RuleError("Bad location.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        raise RuleError("Bad location.")
    if acc is not None and (acc < 0 or acc > MAX_TRACK_ACCURACY_M):
        raise RuleError("Location too inaccurate right now.")
    if heading is not None and not (0 <= heading <= 360):
        heading = None
    now = time.time()
    db = get_db()
    row = db.execute("SELECT ts, order_id FROM runner_positions WHERE runner_id=?",
                     (runner_id,)).fetchone()
    if row and row["order_id"] == order_id and now - row["ts"] < POSITION_MIN_GAP_S:
        return False
    db.execute("INSERT OR REPLACE INTO runner_positions (runner_id, order_id, lat, lon, acc, heading, ts)"
               " VALUES (?,?,?,?,?,?,?)", (runner_id, order_id, lat, lon, acc, heading, now))
    db.commit()
    return True


def clear_runner_position(order_id):
    get_db().execute("DELETE FROM runner_positions WHERE order_id=?", (order_id,))
    get_db().commit()


def runner_tracking(order):
    """What the customer's map may show about the runner right now."""
    import time
    can_track = order["status"] in SHARE_STATUSES and order["runner_id"] is not None
    out = {"status": order["status"], "can_track": can_track,
           "runner": (order["runner"] or "").split(" ")[0] or None,
           "sharing": False, "age_s": None}
    if not can_track:
        return out
    row = get_db().execute("SELECT * FROM runner_positions WHERE runner_id=? AND order_id=?",
                           (order["runner_id"], order["id"])).fetchone()
    if row is None:
        return out
    age = max(0, time.time() - row["ts"])
    out.update(age_s=round(age), lat=row["lat"], lon=row["lon"], acc=row["acc"],
               heading=row["heading"], sharing=age <= POSITION_STALE_S)
    return out


# ---------- who is who: runner <-> shopper verification ----------
# Pickup: the shopper compares the runner's rotating phrase with their own screen and taps
# "It matches"; only then does the shopper reveal a 4-digit PIN, which the runner types in to
# unlock sealing. Delivery: the same phrase check reveals the handover code. A shopper can also
# report "this isn't my runner", which puts the job on hold for the admin.
PIN_MAX_TRIES = 3
PHRASE_WINDOW_S = 60
ADJECTIVES = (
    "Amber", "Azure", "Bold", "Brave", "Bright", "Calm", "Clever", "Coral", "Cosmic", "Crimson",
    "Dizzy", "Dusty", "Eager", "Fancy", "Frosty", "Fuzzy", "Gentle", "Golden", "Gusty", "Happy",
    "Honest", "Icy", "Jolly", "Keen", "Lemon", "Lucky", "Mellow", "Merry", "Mighty", "Misty",
    "Noble", "Olive", "Orange", "Pearl", "Plum", "Proud", "Quick", "Quiet", "Rapid", "Rosy",
    "Royal", "Ruby", "Sandy", "Shiny", "Silver", "Sleepy", "Smart", "Snowy", "Solar", "Spicy",
    "Steady", "Sunny", "Swift", "Teal", "Tidy", "Tiny", "Velvet", "Violet", "Warm", "Wild",
    "Wise", "Witty", "Young", "Zesty",
)
ANIMALS = (
    "Badger", "Bear", "Beaver", "Bison", "Camel", "Cobra", "Condor", "Coyote", "Crane", "Dingo",
    "Dolphin", "Eagle", "Falcon", "Ferret", "Finch", "Fox", "Gazelle", "Gecko", "Goat", "Hawk",
    "Heron", "Horse", "Ibis", "Jaguar", "Koala", "Lemur", "Lion", "Lizard", "Llama", "Lynx",
    "Moose", "Mouse", "Newt", "Otter", "Owl", "Panda", "Parrot", "Pelican", "Pigeon", "Puma",
    "Quail", "Rabbit", "Raven", "Robin", "Salmon", "Seal", "Shark", "Sloth", "Sparrow", "Squid",
    "Stork", "Swan", "Tiger", "Toucan", "Trout", "Turtle", "Viper", "Walrus", "Whale", "Wolf",
    "Wombat", "Yak",
)


def _utc_text():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _secret(order):
    if order["verify_secret"]:
        return order["verify_secret"]
    s = secrets.token_hex(16)            # orders created before this feature
    get_db().execute("UPDATE orders SET verify_secret=? WHERE id=? AND verify_secret IS NULL",
                     (s, order["id"]))
    get_db().commit()
    return get_db().execute("SELECT verify_secret FROM orders WHERE id=?", (order["id"],)).fetchone()[0]


def phrase_for(order, now=None):
    """The two-word-plus-number phrase both phones show right now, and seconds until it changes.
    Derived from a per-order secret and the current minute, so it can't be guessed or reused."""
    import hashlib
    import hmac
    import time
    now = time.time() if now is None else now
    window = int(now // PHRASE_WINDOW_S)
    digest = hmac.new(_secret(order).encode(), f"{order['id']}:{window}".encode(),
                      hashlib.sha256).digest()
    adj = ADJECTIVES[int.from_bytes(digest[0:2], "big") % len(ADJECTIVES)]
    animal = ANIMALS[int.from_bytes(digest[2:4], "big") % len(ANIMALS)]
    number = int.from_bytes(digest[4:6], "big") % 100
    return f"{adj} {animal} {number:02d}", int(PHRASE_WINDOW_S - (now % PHRASE_WINDOW_S))


def can_see_phrase(order, user):
    """Only the shopper who owns the order and the runner assigned to it."""
    if order is None or order["status"] not in ("assigned", "out_for_delivery") or order["safety_flag"]:
        return False
    return (user["role"] == "customer" and order["customer_id"] == user["id"]) or \
           (user["role"] == "runner" and order["runner_id"] == user["id"])


def _check_not_flagged(o):
    if o["safety_flag"]:
        raise RuleError("This job is on hold after a safety report. Wait for the admin.")


def verification_needed(o):
    """Pickup can't start until the shopper confirmed the phrase and the runner entered the PIN.
    Orders from before this feature (no PIN) are exempt."""
    return o["pickup_pin"] is not None and not (o["verified_at"] and o["pin_ok_at"])


def confirm_runner(order_id, customer_id):
    """Shopper taps 'It matches' (pickup) or confirms the runner again at delivery."""
    o = get_order(order_id)
    if o is None or o["customer_id"] != customer_id:
        raise RuleError("Not your order.")
    _check_not_flagged(o)
    if o["runner_id"] is None or o["status"] not in ("assigned", "out_for_delivery"):
        raise RuleError("Your runner isn't on the way yet.")
    badge = o["runner_badge"] or "-"
    if o["status"] == "assigned":
        if o["verified_at"]:
            return
        _set(order_id, verified_at=_utc_text())
        log(order_id, customer_id, "runner_verified", f"shopper confirmed the phrase (runner badge {badge})")
    else:
        if o["delivery_verified_at"]:
            return
        _set(order_id, delivery_verified_at=_utc_text())
        log(order_id, customer_id, "delivery_runner_verified", f"shopper confirmed the phrase (runner badge {badge})")
    get_db().commit()


def enter_pin(order_id, runner_id, pin):
    """Runner types the shopper's PIN. Three wrong tries lock the step until an admin overrides."""
    import hmac
    o = get_order(order_id)
    if o is None or o["runner_id"] != runner_id or o["status"] != "assigned":
        raise RuleError("This pickup isn't yours.")
    _check_not_flagged(o)
    if o["pin_ok_at"] or o["pickup_pin"] is None:
        return
    if not o["verified_at"]:
        raise RuleError("Wait until the shopper confirms your phrase.")
    if o["pin_locked"]:
        raise RuleError("Locked after 3 wrong PINs. Call the admin.")
    pin = (pin or "").strip()
    if not hmac.compare_digest(pin.encode(), o["pickup_pin"].encode()):
        fails = o["pin_fails"] + 1
        locked = fails >= PIN_MAX_TRIES
        _set(order_id, pin_fails=fails, pin_locked=1 if locked else 0)
        log(order_id, runner_id, "pin_failed", f"wrong PIN, attempt {fails} of {PIN_MAX_TRIES}")
        if locked:
            log(order_id, runner_id, "pin_locked", "3 wrong PINs - an admin must review and override")
        get_db().commit()
        raise RuleError("Locked after 3 wrong PINs. The admin has been alerted." if locked
                        else f"Wrong PIN. {PIN_MAX_TRIES - fails} tries left.")
    _set(order_id, pin_ok_at=_utc_text())
    log(order_id, runner_id, "pin_ok", "shopper PIN accepted")
    get_db().commit()


def override_verification(order_id, admin_id, reason):
    """Admin lets a pickup proceed without the shopper's phone (e.g. it died). Always logged."""
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise RuleError("Give a short reason (at least 5 characters).")
    o = get_order(order_id)
    if o is None or o["status"] != "assigned":
        raise RuleError("There is nothing to override.")
    _set(order_id, verified_at=o["verified_at"] or _utc_text(), pin_ok_at=_utc_text(),
         pin_locked=0, pin_fails=0)
    log(order_id, admin_id, "verification_overridden", reason)
    get_db().commit()


def report_runner(order_id, customer_id, note=""):
    """'This isn't my runner': put the job on hold and alert the admin."""
    o = get_order(order_id)
    if o is None or o["customer_id"] != customer_id:
        raise RuleError("Not your order.")
    if o["runner_id"] is None or o["status"] not in ("assigned", "picked_up", "out_for_delivery"):
        raise RuleError("There is no runner to report right now.")
    if o["safety_flag"]:
        return
    note = (note or "").strip()[:300]
    _set(order_id, safety_flag="runner_reported", safety_note=note or None)
    log(order_id, customer_id, "runner_reported",
        f"shopper says this is NOT their runner (badge {o['runner_badge'] or '-'})" + (f": {note}" if note else ""))
    get_db().commit()


def clear_safety_flag(order_id, admin_id):
    o = get_order(order_id)
    if o is None or not o["safety_flag"]:
        raise RuleError("There is no safety report on this order.")
    _set(order_id, safety_flag=None, safety_note=None)
    log(order_id, admin_id, "safety_flag_cleared", "admin reviewed and cleared the report")
    get_db().commit()


# ---------- admin: places ----------
def add_zone(mall_id, name, kind, lat=None, lon=None):
    name = (name or "").strip()
    if not name or kind not in ("area", "entrance", "parking"):
        raise RuleError("Enter a name and choose a type.")
    plat, plon = None, None
    if lat not in (None, "") and lon not in (None, ""):
        plat, plon, _ = parse_pin(lat, lon, 0)
    db = get_db()
    try:
        db.execute("INSERT INTO zones (mall_id, name, kind, lat, lon) VALUES (?,?,?,?,?)",
                   (mall_id, name, kind, plat, plon))
    except sqlite3.IntegrityError:
        raise RuleError("That place already exists for this mall.")
    db.commit()


def toggle_zone(zone_id):
    get_db().execute("UPDATE zones SET active = 1 - active WHERE id=?", (zone_id,))
    get_db().commit()


def set_mall_location(mall_id, lat, lon, radius_m):
    plat, plon, _ = parse_pin(lat, lon, 0)
    try:
        radius = int(radius_m)
    except (TypeError, ValueError):
        radius = 0
    if plat is None or not (50 <= radius <= 20000):
        raise RuleError("Enter a valid latitude, longitude and a radius of 50-20000 m.")
    get_db().execute("UPDATE malls SET lat=?, lon=?, radius_m=? WHERE id=?",
                     (plat, plon, radius, mall_id))
    get_db().commit()


# ---------- runner actions ----------
def _check_can_take(user, order):
    if user["role"] == "admin":
        return
    if user["mall_id"] != order["mall_id"]:
        raise RuleError("This job is at a different mall.")
    if not user["on_duty"]:
        raise RuleError("Go on duty first to take jobs.")


def claim(order_id, runner_id):
    o = get_order(order_id)
    _check_can_take(get_user(runner_id), o)
    if o["status"] != "requested":
        raise RuleError("Someone already took this pickup.")
    _set(order_id, status="assigned", runner_id=runner_id, verified_at=None, pin_ok_at=None,
         pin_fails=0, pin_locked=0)
    log(order_id, runner_id, "assigned")
    get_db().commit()


def record_pickup(order_id, runner_id, seal_no, seal_method, bag_photo, sealed_photo):
    o = get_order(order_id)
    if o["status"] != "assigned" or o["runner_id"] != runner_id:
        raise RuleError("This pickup isn't assigned to you.")
    _check_not_flagged(o)
    if verification_needed(o):
        raise RuleError("Verify the shopper first: they confirm your phrase, then you enter their PIN.")
    seal_no = seal_no.strip().upper()
    if not seal_no:
        raise RuleError("Enter the seal / tag number.")
    if not (bag_photo and bag_photo.filename):
        raise RuleError("A photo of the bag contents is required.")
    save_photo(order_id, "pickup", bag_photo)
    save_photo(order_id, "sealed", sealed_photo)
    _set(order_id, status="picked_up", seal_no=seal_no, seal_method=seal_method)
    log(order_id, runner_id, "sealed_and_picked_up", f"seal {seal_no} ({seal_method})")
    get_db().commit()


def mark_stored(order_id, runner_id, slot):
    o = get_order(order_id)
    if o["status"] != "picked_up" or o["runner_id"] != runner_id:
        raise RuleError("Can't store this bag now.")
    _check_not_flagged(o)
    if not slot.strip():
        raise RuleError("Enter the storage slot.")
    _set(order_id, status="stored", storage_slot=slot.strip().upper())
    log(order_id, runner_id, "stored", slot.strip().upper())
    get_db().commit()


def start_delivery(order_id, runner_id):
    o = get_order(order_id)
    _check_can_take(get_user(runner_id), o)
    _check_not_flagged(o)
    if o["status"] != "return_requested":
        raise RuleError("No delivery to start.")
    if o["runner_id"] not in (None, runner_id) and get_user(runner_id)["role"] != "admin":
        raise RuleError("This delivery was assigned to another runner.")
    _set(order_id, status="out_for_delivery", runner_id=runner_id)
    log(order_id, runner_id, "out_for_delivery")
    get_db().commit()


def complete_delivery(order_id, runner_id, code, seal_intact, photo):
    o = get_order(order_id)
    if o["status"] != "out_for_delivery" or o["runner_id"] != runner_id:
        raise RuleError("This delivery isn't yours.")
    _check_not_flagged(o)
    if code.strip() != o["handover_code"]:
        raise RuleError("Wrong handover code - ask the customer for the 4-digit code.")
    save_photo(order_id, "delivery", photo)
    _set(order_id, status="delivered", seal_ok=1 if seal_intact else 0)
    log(order_id, runner_id, "delivered",
        "seal intact" if seal_intact else "SEAL BROKEN - flagged")
    get_db().commit()
