"""JSON API (v1). Today it rides on the browser session cookie; for the mobile
app add token auth here and nothing else in the codebase has to change."""
from flask import Blueprint, g, jsonify, request

from . import services as svc
from .auth import login_required

bp = Blueprint("api", __name__)


def _public(o):
    d = {k: o[k] for k in (
        "id", "code", "status", "mall", "pickup_spot", "dropoff_spot", "bag_count",
        "seal_no", "seal_ok", "storage_slot", "fee_cents", "created_at", "updated_at")}
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
    oid = svc.create_order(g.user["id"], int(data["mall_id"]), data.get("pickup_spot", ""),
                           data.get("bag_count", 1), data.get("note", ""))
    return jsonify(_public(svc.get_order(oid))), 201


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
    svc.request_return(order_id, g.user["id"], (request.get_json(force=True) or {}).get("dropoff_spot", ""))
    return jsonify(_public(svc.get_order(order_id)))


@bp.post("/orders/<int:order_id>/cancel")
@login_required("customer")
def cancel(order_id):
    if _mine(order_id) is None:
        return jsonify(error="not found"), 404
    svc.cancel_order(order_id, g.user["id"])
    return jsonify(_public(svc.get_order(order_id)))
