"""Delay and risk of a work order's plan (docs/setup-planning-architecture.md, "How a delay is decided").

Computed live from the planned dates on wo_routes, the floor's records (StageWIP, pieces at a
vendor) and the order's commitment date. Nothing is stored, so it cannot go stale. Read-only:
nothing here changes a work order, and nothing in production entry, moves, MRB or dispatch reads it.

Gate state:
  DONE         the gate has received material, nothing is unprocessed or waiting to move, and some
               pieces were produced or rejected (or a later gate already has material: the gate was
               skipped, for example pieces received straight at FI from a vendor)
  IN_PROGRESS  pieces are unprocessed, waiting to move, or at a vendor from this gate
  NOT_STARTED  no material has reached the gate

Work order status (first match wins):
  DELAYED   a gate's planned end has passed and it is not finished; or the last gate's planned end is
            after the commitment date; or the commitment date has passed and the work order is not done
  AT_RISK   a gate ends within the at-risk window and has not started, or its start date has passed
            with no material at it
  NO_PLAN   at least one gate has no planned end
  ON_TRACK  otherwise
  COMPLETE  every gate is done (or the work order is dispatched / closed)
"""
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.departments import normalize_stage
from app.models.production_movement import StageWIP
from app.models.vendor import VendorDispatch
from app.models.work_order import WORoute, WOStatus, WorkOrder
from app.services.stage_plan_service import order_due_date

DONE = "DONE"
IN_PROGRESS = "IN_PROGRESS"
NOT_STARTED = "NOT_STARTED"

DELAYED = "DELAYED"
AT_RISK = "AT_RISK"
NO_PLAN = "NO_PLAN"
ON_TRACK = "ON_TRACK"
COMPLETE = "COMPLETE"

# Gate flags
LATE = "LATE"
DUE_TODAY = "DUE_TODAY"
DUE_SOON = "DUE_SOON"
START_MISSED = "START_MISSED"

STATUS_RANK = {DELAYED: 0, AT_RISK: 1, NO_PLAN: 2, ON_TRACK: 3, COMPLETE: 4}


def _fmt(d: Optional[date]) -> str:
    return d.strftime("%d %b") if d else "no date"


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def gate_state(ent: int, ok: int, rej: int, inproc: int, onhand: int, at_vendor: int) -> str:
    if (at_vendor or 0) > 0 or (inproc or 0) > 0 or (onhand or 0) > 0:
        return IN_PROGRESS
    if (ent or 0) > 0 and ((ok or 0) + (rej or 0)) > 0:
        return DONE
    return NOT_STARTED


def evaluate_work_order(
    routes: List,                                   # WORoute-like: stage, sequence, planned_start, planned_end
    wips: Dict[str, Dict[str, int]],                # normalized stage -> {ent, ok, rej, inproc, onhand}
    at_vendor: Dict[str, int],                      # normalized stage -> pieces at a vendor from that gate
    commitment: Optional[date],
    today: date,
    at_risk_days: int = 2,
    wo_status: Optional[str] = None,
) -> Dict:
    routes = sorted(routes, key=lambda r: r.sequence)
    wo_done = wo_status in (WOStatus.DISPATCHED.value, WOStatus.CLOSED.value, "dispatched", "closed")

    states: List[str] = []
    for r in routes:
        w = wips.get(normalize_stage(r.stage)) or {}
        states.append(gate_state(w.get("ent", 0), w.get("ok", 0), w.get("rej", 0), w.get("inproc", 0),
                                 w.get("onhand", 0), at_vendor.get(normalize_stage(r.stage), 0)))
    # A gate nobody entered, with material already at a later gate, was skipped (e.g. a vendor return
    # received straight at FI): treat it as done so it is never flagged late.
    for i, r in enumerate(routes):
        if states[i] == NOT_STARTED and any(
            (wips.get(normalize_stage(l.stage)) or {}).get("ent", 0) > 0 for l in routes[i + 1:]
        ):
            states[i] = DONE
    if wo_done:
        states = [DONE] * len(routes)

    gates: List[Dict] = []
    for r, st in zip(routes, states):
        flag = None
        days_late = 0
        pe, ps = r.planned_end, r.planned_start
        if st != DONE and pe:
            if pe < today:
                flag, days_late = LATE, (today - pe).days
            elif pe == today:
                flag = DUE_TODAY
            elif st == NOT_STARTED and (pe - today).days <= at_risk_days:
                flag = DUE_SOON
        if st == NOT_STARTED and ps and ps < today and flag is None:
            flag = START_MISSED
        gates.append({
            "stage": r.stage,
            "sequence": r.sequence,
            "planned_start": _iso(ps),
            "planned_end": _iso(pe),
            "state": st,
            "flag": flag,
            "days_late": days_late,
            "days_to_end": (pe - today).days if pe else None,
            "plan_source": getattr(r, "plan_source", None),
            "_end": pe, "_start": ps,
        })

    missing = [g["stage"] for g in gates if g["_end"] is None and g["state"] != DONE]
    ends = [g for g in gates if g["_end"] is not None]
    last_end = ends[-1]["_end"] if ends else None
    late = [g for g in gates if g["flag"] == LATE]
    all_done = bool(gates) and all(g["state"] == DONE for g in gates)

    status, text, late_gate, late_days = ON_TRACK, "On track", None, 0
    if all_done:
        status, text = COMPLETE, "All gates done"
    elif late:
        worst = max(late, key=lambda g: (g["days_late"], -g["sequence"]))
        status = DELAYED
        late_gate, late_days = worst["stage"], worst["days_late"]
        text = f"Delayed · {worst['stage']} +{worst['days_late']} day{'s' if worst['days_late'] != 1 else ''} (planned {_fmt(worst['_end'])})"
    elif commitment and last_end and last_end > commitment:
        status, text = DELAYED, f"Plan ends {_fmt(last_end)}, commitment {_fmt(commitment)}"
    elif commitment and commitment < today:
        status, text = DELAYED, f"Commitment date passed ({_fmt(commitment)})"
    else:
        risky = [g for g in gates if g["flag"] in (DUE_SOON, START_MISSED)]
        if risky:
            g = risky[0]
            status = AT_RISK
            text = (f"{g['stage']} due {_fmt(g['_end'])}, not started" if g["flag"] == DUE_SOON
                    else f"{g['stage']} should have started {_fmt(g['_start'])}")
        elif missing:
            status, text = NO_PLAN, "No date for " + ", ".join(missing)

    for g in gates:
        g.pop("_end"); g.pop("_start")
    return {
        "status": status,
        "text": text,
        "late_gate": late_gate,
        "late_days": late_days,
        "missing_dates": missing,
        "commitment_date": _iso(commitment),
        "days_to_commitment": (commitment - today).days if commitment else None,
        "last_planned_end": _iso(last_end),
        "gates": gates,
    }


def evaluate_work_orders(db: Session, wos: Iterable[WorkOrder], today: Optional[date] = None) -> Dict[str, Dict]:
    """Evaluate many work orders with a fixed number of queries. Keyed by str(work_order.id)."""
    wos = list(wos)
    today = today or date.today()
    if not wos:
        return {}
    ids = [w.id for w in wos]
    routes_by: Dict[str, List[WORoute]] = {}
    for r in db.query(WORoute).filter(WORoute.work_order_id.in_(ids)).order_by(WORoute.sequence).all():
        routes_by.setdefault(str(r.work_order_id), []).append(r)
    wips_by: Dict[str, Dict[str, Dict[str, int]]] = {}
    for w in db.query(StageWIP).filter(StageWIP.work_order_id.in_(ids)).all():
        wips_by.setdefault(str(w.work_order_id), {})[normalize_stage(w.stage)] = {
            "ent": w.ent_qty or 0, "ok": w.ok_qty or 0, "rej": w.rejected_qty or 0,
            "inproc": w.inproc_qty or 0, "onhand": w.onhand_qty or 0,
        }
    vend_by: Dict[str, Dict[str, int]] = {}
    for d in db.query(VendorDispatch).filter(
        VendorDispatch.work_order_id.in_(ids), VendorDispatch.status.in_(["AT_VENDOR", "PARTIALLY_RECEIVED"])
    ).all():
        left = max((d.dispatched_qty or 0) - (d.received_qty or 0) - (d.scrap_qty or 0), 0)
        if left:
            m = vend_by.setdefault(str(d.work_order_id), {})
            k = normalize_stage(d.dispatch_stage)
            m[k] = m.get(k, 0) + left
    out: Dict[str, Dict] = {}
    for wo in wos:
        key = str(wo.id)
        status = getattr(wo.status, "value", wo.status)
        out[key] = evaluate_work_order(
            routes_by.get(key, []), wips_by.get(key, {}), vend_by.get(key, {}),
            order_due_date(wo.order), today, settings.SETUP_PLANNING_AT_RISK_DAYS, status,
        )
    return out
