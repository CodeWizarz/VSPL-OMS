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


def lead_days(stage: str) -> int:
    return STAGE_LEAD_DAYS.get((stage or "").strip().upper(), DEFAULT_LEAD_DAYS)


def compute_stage_plan(
    stages: Iterable[str],
    delivery_date: Optional[date],
    start_date: Optional[date] = None,
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
            n = lead_days(stage)
            end = cursor
            start = end - timedelta(days=max(n - 1, 0))
            plan[stage] = (start, end)
            cursor = start - timedelta(days=1) if n > 0 else start
        return plan

    cursor = start_date or date.today()  # the day the current stage STARTS
    for stage in ordered:
        n = lead_days(stage)
        start = cursor
        end = start + timedelta(days=max(n - 1, 0))
        plan[stage] = (start, end)
        cursor = end + timedelta(days=1) if n > 0 else end
    return plan
