"""Stage plan dates: when each stage of a Work Order should be worked on.

On release, every route stage gets a planned_start / planned_end. They are scheduled
BACKWARDS from the OAR delivery date using standard lead times per stage (so the last
production stage finishes just before dispatch), or FORWARDS from the release date when
the order has no delivery date. PPC can then adjust any stage's dates via WO edit.

These dates drive the shop-floor work queue ("what should I process today and in the
next two days"). They are planning information only -- nothing in production entry,
movement or dispatch validation reads them.

STAGE_LEAD_DAYS is the plant's standard calendar days per stage. It's a first default,
meant to be tuned by PPC/production (see Phase 2 decision #6).
"""
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

STAGE_LEAD_DAYS: Dict[str, int] = {
    "F1": 3,
    "F2": 2,
    "F3": 2,
    "SP": 5,   # subcontract incl. transit
    "FI": 1,
    "PACKING": 1,
    "BSR": 1,
    "PACKING / BSR": 1,
    "PACKING/BSR": 1,
    "DISPATCH": 0,
}
DEFAULT_LEAD_DAYS = 1

Plan = Dict[str, Tuple[date, date]]


# Stages PPC can set on the Lead Times screen (aliases share the PACKING value).
EDITABLE_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR"]
_PACKING_ALIASES = ("PACKING / BSR", "PACKING/BSR")


def load_lead_days(db: Session) -> Dict[str, int]:
    """Code defaults overlaid with the values PPC saved (stage_lead_times table)."""
    from app.models.planning import StageLeadTime  # local import: avoid model import cycles

    merged = dict(STAGE_LEAD_DAYS)
    for row in db.query(StageLeadTime).all():
        merged[row.stage.upper()] = int(row.days)
    if "PACKING" in merged:
        for alias in _PACKING_ALIASES:
            merged[alias] = merged["PACKING"]
    return merged


def lead_days(stage: str, lead_days_map: Optional[Dict[str, int]] = None) -> int:
    table = lead_days_map if lead_days_map is not None else STAGE_LEAD_DAYS
    return table.get((stage or "").strip().upper(), DEFAULT_LEAD_DAYS)


def compute_stage_plan(
    stages: Iterable[str],
    delivery_date: Optional[date],
    start_date: Optional[date] = None,
    lead_days_map: Optional[Dict[str, int]] = None,
) -> Plan:
    """Planned (start, end) for each stage in route order.

    A stage with N lead days occupies N calendar days; a 0-day stage (DISPATCH) starts
    and ends on the day the previous stage ends. With a delivery date, DISPATCH ends on
    the delivery date and earlier stages are packed back-to-back before it."""
    ordered: List[str] = [s for s in stages if s]
    plan: Plan = {}
    if not ordered:
        return plan

    if delivery_date is not None:
        cursor = delivery_date  # the day the current stage must END
        for stage in reversed(ordered):
            n = lead_days(stage, lead_days_map)
            end = cursor
            start = end - timedelta(days=max(n - 1, 0))
            plan[stage] = (start, end)
            cursor = start - timedelta(days=1) if n > 0 else start
        return plan

    cursor = start_date or date.today()  # the day the current stage STARTS
    for stage in ordered:
        n = lead_days(stage, lead_days_map)
        start = cursor
        end = start + timedelta(days=max(n - 1, 0))
        plan[stage] = (start, end)
        cursor = end + timedelta(days=1) if n > 0 else end
    return plan


def order_due_date(order) -> Optional[date]:
    """The date the customer is promised: revised commitment, else commitment, else
    the original delivery date."""
    if order is None:
        return None
    return (
        getattr(order, "revised_commitment_date", None)
        or getattr(order, "commitment_date", None)
        or getattr(order, "delivery_date", None)
    )


def apply_stage_plan(db: Session, wo, overwrite: bool = True) -> None:
    """Set planned_start / planned_end on every route stage of `wo`, scheduled back
    from the order's due date (forward from today if it has none)."""
    from app.models.work_order import WORoute  # local import: avoid model import cycles

    db.flush()
    routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
    if not routes:
        return
    plan = compute_stage_plan(
        [r.stage for r in routes],
        delivery_date=order_due_date(wo.order),
        start_date=date.today(),
        lead_days_map=load_lead_days(db),
    )
    for r in routes:
        if overwrite or r.planned_end is None:
            r.planned_start, r.planned_end = plan.get(r.stage, (None, None))
