from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, send_from_directory, session, url_for)

from . import services as svc
from .auth import load_user, login_required
from .db import get_db

bp = Blueprint("web", __name__)
bp.before_app_request(load_user)


def _home_for(user):
    return url_for({"customer": "web.dashboard", "runner": "web.runner",
                    "admin": "web.admin"}[user["role"]])


def _order_or_404(order_id):
    o = svc.get_order(order_id)
    if o is None:
        abort(404)
    if g.user["role"] == "customer" and o["customer_id"] != g.user["id"]:
        abort(404)
    return o


@bp.route("/")
def index():
    if g.user:
        return redirect(_home_for(g.user))
    return render_template("index.html")


@bp.route("/gps-test")
def gps_test():
    """Public field-test page: how good is phone GPS inside a mall?"""
    return render_template("gps_test.html")


# ---------- auth ----------
@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            uid = svc.create_user(request.form["name"], request.form["phone"],
                                  request.form["password"])
        except svc.RuleError as e:
            flash(str(e), "error")
        else:
            session.clear()
            session["uid"] = uid
            return redirect(url_for("web.dashboard"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = svc.authenticate(request.form["phone"], request.form["password"])
        if user:
            session.clear()
            session["uid"] = user["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else _home_for(user))
        flash("Wrong phone or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("web.index"))


# ---------- customer ----------
@bp.route("/app")
@login_required("customer")
def dashboard():
    orders = svc.list_orders("o.customer_id=?", (g.user["id"],))
    active = [o for o in orders if o["status"] in svc.ACTIVE]
    past = [o for o in orders if o["status"] not in svc.ACTIVE]
    return render_template("dashboard.html", active=active, past=past)


@bp.route("/app/new", methods=["GET", "POST"])
@login_required("customer")
def new_order():
    if request.method == "POST":
        f = request.form
        try:
            oid = svc.create_order(
                g.user["id"], int(f["mall_id"]), f.get("zone_id"), f.get("bag_count", 1),
                details=f.get("details", ""), note=f.get("note", ""),
                level=f.get("level", ""), lat=f.get("lat"), lon=f.get("lon"),
                acc=f.get("acc"), src=f.get("src"))
        except (svc.RuleError, ValueError) as e:
            flash(str(e) or "Check the form.", "error")
        else:
            return redirect(url_for("web.order", order_id=oid))
    return render_template("new_order.html", malls=svc.malls(), zones=svc.zones(),
                           cfg=current_app.config)


@bp.route("/order/<int:order_id>")
@login_required()
def order(order_id):
    o = _order_or_404(order_id)
    mall = svc.get_mall(o["mall_id"])
    show_pins = _can_see_pins(o)
    return render_template(
        "order.html", o=o, events=svc.order_events(order_id),
        photos=svc.order_photos(order_id), mall=mall, show_pins=show_pins,
        pickup_in_mall=svc.pin_inside_mall(mall, o["pickup_lat"], o["pickup_lon"]),
        dropoff_in_mall=svc.pin_inside_mall(mall, o["dropoff_lat"], o["dropoff_lon"]),
        return_zones=svc.zones(o["mall_id"], ("parking", "entrance")),
        runners_here=svc.runners(o["mall_id"]) if g.user["role"] == "admin" else [])


def _can_see_pins(o):
    """Exact pins: the customer, admins, and the runner who took the job."""
    return g.user["role"] in ("customer", "admin") or o["runner_id"] == g.user["id"]


@bp.route("/order/<int:order_id>/map")
@login_required()
def order_map(order_id):
    o = _order_or_404(order_id)
    if not _can_see_pins(o):
        flash("Take the job first to see the exact pin.", "error")
        return redirect(url_for("web.order", order_id=order_id))
    # NOTE: the runner who took the job passes _can_see_pins, so they get the pins too
    pins = []
    if o["pickup_lat"] is not None:
        pins.append({"kind": "Pickup", "color": "#0F766E", "lat": o["pickup_lat"],
                     "lon": o["pickup_lon"], "acc": o["pickup_acc"], "src": o["pickup_src"],
                     "label": f"Pickup: {o['pickup_spot']}"})
    if o["dropoff_lat"] is not None:
        pins.append({"kind": "Delivery", "color": "#D97706", "lat": o["dropoff_lat"],
                     "lon": o["dropoff_lon"], "acc": o["dropoff_acc"], "src": o["dropoff_src"],
                     "label": f"Delivery: {o['dropoff_spot']}"})
    # the shopper (and admin) can also watch the runner live while a runner is on the way
    tracking = g.user["role"] in ("customer", "admin") and o["status"] in svc.SHARE_STATUSES
    if not pins and not tracking:
        flash("This order has no map pin - see the written place and details.", "error")
        return redirect(url_for("web.order", order_id=order_id))
    return render_template("order_map.html", o=o, pins=pins, tracking=tracking)


@bp.post("/order/<int:order_id>/cancel")
@login_required("customer")
def cancel(order_id):
    _order_or_404(order_id)
    return _act(order_id, lambda: svc.cancel_order(order_id, g.user["id"]))


@bp.post("/order/<int:order_id>/return")
@login_required("customer")
def return_bag(order_id):
    _order_or_404(order_id)
    f = request.form
    return _act(order_id, lambda: svc.request_return(
        order_id, g.user["id"], f.get("zone_id"), f.get("details", ""),
        f.get("lat"), f.get("lon"), f.get("acc"), f.get("src")))


# ---------- runner ----------
@bp.route("/runner")
@login_required("runner", "admin")
def runner():
    uid, mall = g.user["id"], g.user["mall_id"]
    # runners only see their own mall; admins see every mall
    scope, sargs = ("o.mall_id=?", (mall,)) if g.user["role"] == "runner" else ("1=1", ())
    return render_template(
        "runner.html",
        open_pickups=svc.list_orders(f"o.status='requested' AND {scope}", sargs),
        open_returns=svc.list_orders(
            f"o.status='return_requested' AND (o.runner_id IS NULL OR o.runner_id=?) AND {scope}",
            (uid, *sargs)),
        mine=svc.list_orders(
            "o.runner_id=? AND o.status IN ('assigned','picked_up','out_for_delivery')",
            (uid,)),
        stored=svc.list_orders(f"o.status='stored' AND {scope}", sargs),
        mall_name=(get_db().execute("SELECT name FROM malls WHERE id=?", (mall,)).fetchone()
                   if mall else None),
        stuck_ids={o["id"] for o in svc.list_orders(svc.unclaimed_clause())},
    )


@bp.post("/runner/duty")
@login_required("runner")
def duty():
    svc.set_duty(g.user["id"], request.form.get("on_duty") == "1")
    return redirect(url_for("web.runner"))


@bp.post("/order/<int:order_id>/claim")
@login_required("runner", "admin")
def claim(order_id):
    return _act(order_id, lambda: svc.claim(order_id, g.user["id"]))


@bp.post("/order/<int:order_id>/pickup")
@login_required("runner", "admin")
def pickup(order_id):
    return _act(order_id, lambda: svc.record_pickup(
        order_id, g.user["id"], request.form.get("seal_no", ""),
        request.form.get("seal_method", "tamper_tag"),
        request.files.get("bag_photo"), request.files.get("sealed_photo")))


@bp.post("/order/<int:order_id>/store")
@login_required("runner", "admin")
def store(order_id):
    return _act(order_id, lambda: svc.mark_stored(
        order_id, g.user["id"], request.form.get("slot", "")))


@bp.post("/order/<int:order_id>/deliver/start")
@login_required("runner", "admin")
def deliver_start(order_id):
    return _act(order_id, lambda: svc.start_delivery(order_id, g.user["id"]))


@bp.post("/order/<int:order_id>/deliver/complete")
@login_required("runner", "admin")
def deliver_complete(order_id):
    return _act(order_id, lambda: svc.complete_delivery(
        order_id, g.user["id"], request.form.get("code", ""),
        request.form.get("seal_intact") == "yes", request.files.get("photo")))


def _act(order_id, fn):
    try:
        fn()
    except svc.RuleError as e:
        flash(str(e), "error")
    return redirect(url_for("web.order", order_id=order_id))


# ---------- admin ----------
@bp.route("/admin")
@login_required("admin")
def admin():
    db = get_db()
    stats = db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(status IN ('requested','assigned','picked_up','stored',
                                 'return_requested','out_for_delivery')) AS active,
                  SUM(status='delivered') AS delivered,
                  SUM(seal_ok=0) AS flagged,
                  COALESCE(SUM(CASE WHEN status='delivered' THEN fee_cents END),0) AS revenue
           FROM orders""").fetchone()
    return render_template("admin.html", stats=stats,
                           flagged=svc.list_orders("o.seal_ok=0"),
                           stuck=svc.list_orders(svc.unclaimed_clause()),
                           staff=svc.runners(), malls=svc.malls(),
                           all_zones=svc.zones(include_inactive=True),
                           recent=svc.list_orders()[:25])


@bp.post("/order/<int:order_id>/reassign")
@login_required("admin")
def reassign(order_id):
    try:
        rid = int(request.form["runner_id"])
    except (KeyError, ValueError):
        abort(400)
    return _act(order_id, lambda: svc.reassign(order_id, g.user["id"], rid))


@bp.route("/admin/map")
@login_required("admin")
def admin_map():
    malls = svc.malls()
    if not malls:
        flash("Add a mall first.", "error")
        return redirect(url_for("web.admin"))
    try:
        mall_id = int(request.args.get("mall", malls[0]["id"]))
    except ValueError:
        abort(400)
    mall = svc.get_mall(mall_id)
    if mall is None:
        abort(404)
    return render_template("admin_map.html", malls=malls, mall=mall,
                           added=svc.map_places(mall_id, include_inactive=True),
                           kinds=svc.PLACE_KINDS,
                           focus_lat=request.args.get("lat"), focus_lon=request.args.get("lon"))


@bp.post("/admin/map/places")
@login_required("admin")
def admin_map_add():
    f = request.form
    try:
        mall_id = int(f["mall_id"])
        svc.add_map_place(mall_id, g.user["id"], f.get("name"), f.get("kind"),
                          f.get("lat"), f.get("lon"))
    except (svc.RuleError, ValueError, KeyError) as e:
        flash(str(e) or "Check the form.", "error")
        return redirect(url_for("web.admin_map", mall=f.get("mall_id")))
    flash(f"{f.get('name', '').strip()} added to the map.", "ok")
    return redirect(url_for("web.admin_map", mall=mall_id, lat=f.get("lat"), lon=f.get("lon")))


@bp.post("/admin/map/places/<int:place_id>/toggle")
@login_required("admin")
def admin_map_toggle(place_id):
    row = get_db().execute("SELECT mall_id FROM map_places WHERE id=?", (place_id,)).fetchone()
    if row is None:
        abort(404)
    svc.toggle_map_place(place_id)
    return redirect(url_for("web.admin_map", mall=row["mall_id"]))


@bp.get("/admin/map/export/<int:mall_id>.geojson")
@login_required("admin")
def admin_map_export(mall_id):
    import json
    from flask import Response
    mall = svc.get_mall(mall_id)
    if mall is None:
        abort(404)
    body = json.dumps(svc.export_places_geojson(mall_id), separators=(",", ":"))
    return Response(body, mimetype="application/geo+json", headers={
        "Content-Disposition": f"attachment; filename={svc._slug(mall['name'])}.geojson"})


@bp.post("/admin/zones")
@login_required("admin")
def add_zone():
    f = request.form
    try:
        svc.add_zone(int(f["mall_id"]), f.get("name"), f.get("kind"),
                     f.get("lat"), f.get("lon"))
    except (svc.RuleError, ValueError, KeyError) as e:
        flash(str(e) or "Check the form.", "error")
    else:
        flash("Place added.", "ok")
    return redirect(url_for("web.admin"))


@bp.post("/admin/zones/<int:zone_id>/toggle")
@login_required("admin")
def toggle_zone(zone_id):
    svc.toggle_zone(zone_id)
    return redirect(url_for("web.admin"))


@bp.post("/admin/malls/<int:mall_id>/location")
@login_required("admin")
def mall_location(mall_id):
    f = request.form
    try:
        svc.set_mall_location(mall_id, f.get("lat"), f.get("lon"), f.get("radius_m"))
    except svc.RuleError as e:
        flash(str(e), "error")
    else:
        flash("Mall location saved.", "ok")
    return redirect(url_for("web.admin"))


@bp.post("/admin/malls")
@login_required("admin")
def add_mall():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Enter a mall name.", "error")
    else:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO malls (name) VALUES (?)", (name,))
        db.commit()
        flash(f"Mall '{name}' added.", "ok")
    return redirect(url_for("web.admin"))


@bp.post("/admin/staff")
@login_required("admin")
def add_staff():
    role = request.form.get("role")
    if role not in ("runner", "admin"):
        abort(400)
    try:
        mall_id = int(request.form["mall_id"]) if request.form.get("mall_id") else None
        svc.create_user(request.form["name"], request.form["phone"],
                        request.form["password"], role, mall_id)
    except (svc.RuleError, ValueError) as e:
        flash(str(e), "error")
    else:
        flash(f"{role.title()} account created.", "ok")
    return redirect(url_for("web.admin"))


# ---------- photos (access-controlled) ----------
@bp.route("/photo/<int:photo_id>")
@login_required()
def photo(photo_id):
    p = get_db().execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if p is None:
        abort(404)
    _order_or_404(p["order_id"])
    return send_from_directory(current_app.config["UPLOAD_DIR"], p["filename"])
