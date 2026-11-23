"""Shop-floor work queue: which Work Orders have material waiting at a stage, and when
that stage is due -- "what should I process today and in the next two days".

Read-only. Due dates come from each route stage's planned_end (stage_plan_service),
falling back to an estimate from the OAR delivery date for WOs released before plan
dates existed.
"""
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.departments import normalize_stage
from app.models.production_movement import StageWIP
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.services.oms_integration_service import calculate_delivery_risk
from app.services.stage_plan_service import compute_stage_plan

STANDARD_ROUTE = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
BUCKETS = ("overdue", "today", "next", "later", "no_date")


def _bucket(due: Optional[date], today: date, days: int) -> str:
    if due is None:
        return "no_date"
    delta = (due - today).days
    if delta < 0:
        return "overdue"
    if delta == 0:
        return "today"
    if delta <= days:
        return "next"
    return "later"


class WorkQueueService:
    @staticmethod
    def get_stage_queue(db: Session, stage: str, days: int = 2, today: Optional[date] = None) -> Dict:
        today = today or date.today()
        key = normalize_stage(stage)
        items: List[Dict] = []

        active = (
            db.query(WorkOrder)
            .filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED]))
            .all()
        )
        for wo in active:
            wips = [
                w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
                if normalize_stage(w.stage) == key
            ]
            qty = sum(w.available_wip or 0 for w in wips)
            if qty <= 0:
                continue

            order = wo.order
            delivery = order.delivery_date if order else None
            routes = (
                db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
            )
            route_stages = [r.stage for r in routes] or STANDARD_ROUTE
            row = next((r for r in routes if normalize_stage(r.stage) == key), None)

            planned_start = row.planned_start if row else None
            planned_end = row.planned_end if row else None
            plan_source = "planned"
            if planned_end is None:
                est = compute_stage_plan(route_stages, delivery_date=delivery) if delivery else {}
                match = next((v for s, v in est.items() if normalize_stage(s) == key), None)
                if match:
                    planned_start, planned_end = match
                    plan_source = "estimated"
                else:
                    plan_source = "none"

            status_value = getattr(wo.status, "value", wo.status)
            items.append({
                "wo_number": wo.wo_number,
                "oar_number": order.oar_number if order else None,
                "customer_name": order.customer.name if order and order.customer else None,
                "part_number": order.part.part_number if order and order.part else None,
                "part_name": order.part.description if order and order.part else None,
                "qty_at_stage": qty,
                "inproc_qty": sum(w.inproc_qty or 0 for w in wips),
                "onhand_qty": sum(w.onhand_qty or 0 for w in wips),
                "current_stage": wo.current_stage,
                "status": status_value,
                "delivery_date": delivery.isoformat() if delivery else None,
                "planned_start": planned_start.isoformat() if planned_start else None,
                "planned_end": planned_end.isoformat() if planned_end else None,
                "plan_source": plan_source,
                "days_to_due": (planned_end - today).days if planned_end else None,
                "bucket": _bucket(planned_end, today, days),
                "delivery_risk": calculate_delivery_risk(delivery, wo.current_stage or route_stages[0], status_value, route_stages),
            })

        items.sort(key=lambda i: (i["days_to_due"] is None, i["days_to_due"] if i["days_to_due"] is not None else 0))
        counts = {b: {"wos": 0, "qty": 0} for b in BUCKETS}
        for i in items:
            counts[i["bucket"]]["wos"] += 1
            counts[i["bucket"]]["qty"] += i["qty_at_stage"]

        return {
            "stage": "PACKING / BSR" if key == "PACKING" else key,
            "today": today.isoformat(),
            "days": days,
            "counts": counts,
            "items": items,
        }
