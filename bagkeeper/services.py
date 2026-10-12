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
    _set(order_id, runner_id=runner_id, status=new_status)
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
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(
        f"UPDATE orders SET {cols}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (*fields.values(), order_id),
    )


def get_order(order_id):
    return get_db().execute(
        """SELECT o.*, m.name AS mall, c.name AS customer, c.phone AS customer_phone,
                  r.name AS runner
           FROM orders o JOIN malls m ON m.id=o.mall_id
           JOIN users c ON c.id=o.customer_id
           LEFT JOIN users r ON r.id=o.runner_id WHERE o.id=?""",
        (order_id,),
    ).fetchone()


def list_orders(where="1=1", args=()):
    return get_db().execute(
        f"""SELECT o.*, m.name AS mall, c.name AS customer, r.name AS runner
            FROM orders o JOIN malls m ON m.id=o.mall_id
            JOIN users c ON c.id=o.customer_id
            LEFT JOIN users r ON r.id=o.runner_id
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


def _where(zone, level, details, mall):
    parts = [zone["name"]]
    levels = [x.strip() for x in (mall["levels"] or "").split(",") if x.strip()]
    if level and len(levels) > 1 and level in levels:
        parts.append(level)
    text = ", ".join(parts)
    return f"{text} - {details.strip()}" if details and details.strip() else text


def create_order(customer_id, mall_id, zone_id, bag_count, details="", note="",
                 level="", lat=None, lon=None, acc=None):
    mall = get_mall(mall_id)
    if mall is None:
        raise RuleError("Choose a mall.")
    zone = _zone(zone_id, mall_id, ("area", "entrance", "parking"))
    pickup_spot = _where(zone, level, details, mall)
    plat, plon, pacc = parse_pin(lat, lon, acc)
    bag_count = max(1, min(int(bag_count or 1), 10))
    cfg = current_app.config
    fee = cfg["BASE_FEE_CENTS"] + (bag_count - 1) * cfg["EXTRA_BAG_FEE_CENTS"]
    db = get_db()
    code = "BK-" + secrets.token_hex(2).upper()
    cur = db.execute(
        """INSERT INTO orders (code, customer_id, mall_id, pickup_spot, pickup_zone_id,
               pickup_level, pickup_details, pickup_lat, pickup_lon, pickup_acc,
               bag_count, note, fee_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (code, customer_id, mall_id, pickup_spot, zone["id"], level or None,
         (details or "").strip() or None, plat, plon, pacc, bag_count, note.strip(), fee),
    )
    where = pickup_spot + (f" (GPS +/-{pacc:.0f} m)" if pacc is not None else "")
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


def request_return(order_id, customer_id, zone_id, details="", lat=None, lon=None, acc=None):
    o = get_order(order_id)
    if o["customer_id"] != customer_id:
        raise RuleError("Not your order.")
    if o["status"] not in ("picked_up", "stored"):
        raise RuleError("Bag can't be returned at this stage.")
    mall = get_mall(o["mall_id"])
    zone = _zone(zone_id, o["mall_id"], ("parking", "entrance"))
    dlat, dlon, dacc = parse_pin(lat, lon, acc)
    if not (details or "").strip() and dlat is None:
        raise RuleError("Add a few details (row, bay, car colour) or use your location.")
    dropoff_spot = _where(zone, "", details, mall)
    code = f"{secrets.randbelow(10000):04d}"
    _set(order_id, status="return_requested", dropoff_spot=dropoff_spot,
         dropoff_zone_id=zone["id"], dropoff_details=(details or "").strip() or None,
         dropoff_lat=dlat, dropoff_lon=dlon, dropoff_acc=dacc, handover_code=code)
    where = dropoff_spot + (f" (GPS +/-{dacc:.0f} m)" if dacc is not None else "")
    log(order_id, customer_id, "return_requested", where)
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
    _set(order_id, status="assigned", runner_id=runner_id)
    log(order_id, runner_id, "assigned")
    get_db().commit()


def record_pickup(order_id, runner_id, seal_no, seal_method, bag_photo, sealed_photo):
    o = get_order(order_id)
    if o["status"] != "assigned" or o["runner_id"] != runner_id:
        raise RuleError("This pickup isn't assigned to you.")
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
    if not slot.strip():
        raise RuleError("Enter the storage slot.")
    _set(order_id, status="stored", storage_slot=slot.strip().upper())
    log(order_id, runner_id, "stored", slot.strip().upper())
    get_db().commit()


def start_delivery(order_id, runner_id):
    o = get_order(order_id)
    _check_can_take(get_user(runner_id), o)
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
    if code.strip() != o["handover_code"]:
        raise RuleError("Wrong handover code - ask the customer for the 4-digit code.")
    save_photo(order_id, "delivery", photo)
    _set(order_id, status="delivered", seal_ok=1 if seal_intact else 0)
    log(order_id, runner_id, "delivered",
        "seal intact" if seal_intact else "SEAL BROKEN - flagged")
    get_db().commit()
