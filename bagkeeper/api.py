"""JSON API (v1). Today it rides on the browser session cookie; for the mobile
app add token auth here and nothing else in the codebase has to change."""
from flask import Blueprint, g, jsonify, request

from . import services as svc
from .auth import login_required

bp = Blueprint("api", __name__)


def _public(o):
    d = {k: o[k] for k in (
        "id", "code", "status", "mall", "pickup_spot", "dropoff_spot", "bag_count",
        "seal_no", "seal_ok", "storage_slot", "fee_cents", "created_at", "updated_at",
        "pickup_lat", "pickup_lon", "pickup_acc", "pickup_src",
        "dropoff_lat", "dropoff_lon", "dropoff_acc", "dropoff_src")}
    if o["status"] in ("return_requested", "out_for_delivery"):
        d["handover_code"] = o["handover_code"]
    return d


@bp.errorhandler(svc.RuleError)
def _rule_error(e):
    return jsonify(error=str(e)), 400


@bp.get("/orders")
@login_required("customer")
def orders():
    rows = svc.list_orders("o.customer_id=?", (g.user["id"],))
    return jsonify([_public(o) for o in rows])


@bp.post("/orders")
@login_required("customer")
def create():
    data = request.get_json(force=True)
    oid = svc.create_order(
        g.user["id"], int(data["mall_id"]), data.get("zone_id"), data.get("bag_count", 1),
        details=data.get("details", ""), note=data.get("note", ""),
        level=data.get("level", ""), lat=data.get("lat"), lon=data.get("lon"),
        acc=data.get("accuracy"), src=data.get("source"))   # source: "gps" | "map"
    return jsonify(_public(svc.get_order(oid))), 201


# ---- live runner location ----
@bp.post("/orders/<int:order_id>/runner-location")
@login_required("runner", "admin")
def runner_location_post(order_id):
    o = svc.get_order(order_id)
    if o is None:
        return jsonify(error="not found"), 404
    if o["runner_id"] != g.user["id"]:
        return jsonify(error="not your job", share=False), 403
    if o["status"] not in svc.SHARE_STATUSES:
        return jsonify(error="not tracking right now", share=False), 409
    d = request.get_json(silent=True) or {}
    saved = svc.save_runner_position(order_id, g.user["id"], d.get("lat"), d.get("lon"),
                                     d.get("accuracy"), d.get("heading"))
    return jsonify(ok=True, share=True, saved=saved)


@bp.delete("/orders/<int:order_id>/runner-location")
@login_required("runner", "admin")
def runner_location_stop(order_id):
    o = svc.get_order(order_id)
    if o is None or o["runner_id"] != g.user["id"]:
        return jsonify(error="not your job"), 403
    svc.clear_runner_position(order_id)
    return jsonify(ok=True)


@bp.get("/orders/<int:order_id>/runner")
@login_required("customer", "admin")
def runner_where(order_id):
    o = svc.get_order(order_id)
    if o is None or (g.user["role"] == "customer" and o["customer_id"] != g.user["id"]):
        return jsonify(error="not found"), 404
    resp = jsonify(svc.runner_tracking(o))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/malls/<int:mall_id>/map")
def mall_map(mall_id):
    data = svc.map_data(mall_id)
    if data is None:
        return jsonify(error="not found"), 404
    svc.maybe_refresh_async(mall_id)      # weekly OpenStreetMap update, in the background
    return jsonify(data)


@bp.get("/malls/<int:mall_id>/zones")
def zones(mall_id):
    return jsonify([{"id": z["id"], "name": z["name"], "kind": z["kind"],
                     "lat": z["lat"], "lon": z["lon"]} for z in svc.zones(mall_id)])


def _mine(order_id):
    o = svc.get_order(order_id)
    if o is None or o["customer_id"] != g.user["id"]:
        return None
    return o


@bp.get("/orders/<int:order_id>")
@login_required("customer")
def detail(order_id):
    o = _mine(order_id)
    if o is None:
        return jsonify(error="not found"), 404
    return jsonify(_public(o))


@bp.post("/orders/<int:order_id>/return")
@login_required("customer")
def return_bag(order_id):
    if _mine(order_id) is None:
        return jsonify(error="not found"), 404
    d = request.get_json(force=True) or {}
    svc.request_return(order_id, g.user["id"], d.get("zone_id"), d.get("details", ""),
                       d.get("lat"), d.get("lon"), d.get("accuracy"), d.get("source"))
    return jsonify(_public(svc.get_order(order_id)))


@bp.post("/orders/<int:order_id>/cancel")
@login_required("customer")
def cancel(order_id):
    if _mine(order_id) is None:
        return jsonify(error="not found"), 404
    svc.cancel_order(order_id, g.user["id"])
    return jsonify(_public(svc.get_order(order_id)))
