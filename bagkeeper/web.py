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
        try:
            oid = svc.create_order(g.user["id"], int(request.form["mall_id"]),
                                   request.form["pickup_spot"],
                                   request.form.get("bag_count", 1),
                                   request.form.get("note", ""))
        except (svc.RuleError, ValueError) as e:
            flash(str(e) or "Check the form.", "error")
        else:
            return redirect(url_for("web.order", order_id=oid))
    return render_template("new_order.html", malls=svc.malls(),
                           cfg=current_app.config)


@bp.route("/order/<int:order_id>")
@login_required()
def order(order_id):
    o = _order_or_404(order_id)
    return render_template("order.html", o=o, events=svc.order_events(order_id),
                           photos=svc.order_photos(order_id),
                           runners_here=svc.runners(o["mall_id"])
                           if g.user["role"] == "admin" else [])


@bp.post("/order/<int:order_id>/cancel")
@login_required("customer")
def cancel(order_id):
    _order_or_404(order_id)
    return _act(order_id, lambda: svc.cancel_order(order_id, g.user["id"]))


@bp.post("/order/<int:order_id>/return")
@login_required("customer")
def return_bag(order_id):
    _order_or_404(order_id)
    return _act(order_id, lambda: svc.request_return(
        order_id, g.user["id"], request.form.get("dropoff_spot", "")))


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
                           recent=svc.list_orders()[:25])


@bp.post("/order/<int:order_id>/reassign")
@login_required("admin")
def reassign(order_id):
    try:
        rid = int(request.form["runner_id"])
    except (KeyError, ValueError):
        abort(400)
    return _act(order_id, lambda: svc.reassign(order_id, g.user["id"], rid))


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
