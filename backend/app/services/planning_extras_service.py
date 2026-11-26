"""Working calendar, gate capacity and split work orders for setup planning.

All three are planning information only. They produce warnings next to PPC's dates and a view of
the load; nothing here blocks a save, and nothing in production entry, moves, MRB or dispatch reads it.
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.departments import normalize_stage
from app.models.setup_planning import PlanningCalendarDay, PlanningCapacity, PlanningSetup, WOSetupSplit
from app.models.user import User
from app.models.work_order import WORoute, WorkOrder
from app.services import plan_delay_service as delay
from app.services.setup_planning_service import _audit, _bad, _is_active, _released, find_setup, find_wo


# ------------------------------------------------------------------------------ calendar
def weekly_off() -> set:
    out = set()
    for p in (settings.PLANNING_WEEKLY_OFF or "").split(","):
        p = p.strip()
        if p.isdigit() and 0 <= int(p) <= 6:
            out.add(int(p))
    return out


def calendar_map(db: Session, start: date, end: date) -> Dict[date, str]:
    rows = db.query(PlanningCalendarDay).filter(PlanningCalendarDay.day >= start, PlanningCalendarDay.day <= end).all()
    return {r.day: r.kind for r in rows}


def non_working_reason(d: date, cal: Dict[date, str], off: Optional[set] = None) -> Optional[str]:
    """None when d is a working day, else why not."""
    off = weekly_off() if off is None else off
    kind = cal.get(d)
    if kind == "HOLIDAY":
        return "a holiday"
    if kind == "WORKING":
        return None
    if d.weekday() in off:
        return d.strftime("a weekly off (%A)")
    return None


def next_working_day(db: Session, d: date) -> date:
    off = weekly_off()
    cal = calendar_map(db, d, d + timedelta(days=60))
    for i in range(0, 60):
        c = d + timedelta(days=i)
        if non_working_reason(c, cal, off) is None:
            return c
    return d


def list_calendar(db: Session, start: date, end: date) -> Dict:
    cal = db.query(PlanningCalendarDay).filter(PlanningCalendarDay.day >= start, PlanningCalendarDay.day <= end) \
        .order_by(PlanningCalendarDay.day).all()
    return {
        "weekly_off": sorted(weekly_off()),
        "days": [{"day": r.day.isoformat(), "kind": r.kind, "note": r.note, "created_by": r.created_by} for r in cal],
    }


def set_calendar_day(db: Session, day: date, kind: str, note: Optional[str], user: Optional[User]) -> Dict:
    kind = (kind or "HOLIDAY").upper()
    if kind not in ("HOLIDAY", "WORKING"):
        raise _bad("Kind must be HOLIDAY or WORKING.")
    row = db.query(PlanningCalendarDay).filter(PlanningCalendarDay.day == day).first()
    old = row.kind if row else "normal"
    if row is None:
        row = PlanningCalendarDay(day=day, kind=kind, note=(note or "").strip() or None, created_by=user.full_name if user else None)
        db.add(row)
    else:
        row.kind, row.note = kind, (note or "").strip() or None
    _audit(db, user, "PLAN_CALENDAR_SET", day.isoformat(), old, kind, (note or "").strip())
    db.flush()
    return {"day": day.isoformat(), "kind": kind, "note": row.note}


def delete_calendar_day(db: Session, day: date, user: Optional[User]) -> Dict:
    row = db.query(PlanningCalendarDay).filter(PlanningCalendarDay.day == day).first()
    if row is None:
        raise _bad("No exception is set for that day.", status.HTTP_404_NOT_FOUND)
    _audit(db, user, "PLAN_CALENDAR_REMOVED", day.isoformat(), row.kind, "normal", "")
    db.delete(row)
    db.flush()
    return {"day": day.isoformat(), "removed": True}


# ------------------------------------------------------------------------------ capacity
def list_capacity(db: Session) -> List[Dict]:
    return [{"stage": r.stage, "daily_qty": r.daily_qty, "note": r.note}
            for r in db.query(PlanningCapacity).order_by(PlanningCapacity.stage).all()]


def capacity_map(db: Session) -> Dict[str, int]:
    return {normalize_stage(r.stage): r.daily_qty for r in db.query(PlanningCapacity).all()}


def set_capacity(db: Session, stage: str, daily_qty: int, note: Optional[str], user: Optional[User]) -> Dict:
    key = normalize_stage(stage or "")
    if not key:
        raise _bad("Gate is required.")
    if daily_qty is None or int(daily_qty) < 1:
        raise _bad("Daily capacity must be at least 1 piece.")
    row = db.query(PlanningCapacity).filter(PlanningCapacity.stage == key).first()
    old = str(row.daily_qty) if row else "not set"
    if row is None:
        row = PlanningCapacity(stage=key, daily_qty=int(daily_qty), note=(note or "").strip() or None, updated_by=user.full_name if user else None)
        db.add(row)
    else:
        row.daily_qty, row.note = int(daily_qty), (note or "").strip() or None
        row.updated_by = user.full_name if user else None
    _audit(db, user, "PLAN_CAPACITY_SET", key, old, str(int(daily_qty)), (note or "").strip())
    db.flush()
    return {"stage": key, "daily_qty": row.daily_qty, "note": row.note}


def delete_capacity(db: Session, stage: str, user: Optional[User]) -> Dict:
    key = normalize_stage(stage or "")
    row = db.query(PlanningCapacity).filter(PlanningCapacity.stage == key).first()
    if row is None:
        raise _bad("No capacity is set for that gate.", status.HTTP_404_NOT_FOUND)
    _audit(db, user, "PLAN_CAPACITY_REMOVED", key, str(row.daily_qty), "not set", "")
    db.delete(row)
    db.flush()
    return {"stage": key, "removed": True}


def _open_work_orders(db: Session) -> List[WorkOrder]:
    return [w for w in db.query(WorkOrder).filter(WorkOrder.release_date.isnot(None)).all() if _is_active(w)]


def gate_load(db: Session, start: date, end: date, exclude_wo_id=None) -> Dict[Tuple[str, date], int]:
    """Pieces whose gate is planned to END on each day, per gate. Finished gates are not counted."""
    wos = [w for w in _open_work_orders(db) if exclude_wo_id is None or w.id != exclude_wo_id]
    if not wos:
        return {}
    evs = delay.evaluate_work_orders(db, wos)
    qty = {str(w.id): (w.physical_wo_qty or 0) for w in wos}
    load: Dict[Tuple[str, date], int] = {}
    for w in wos:
        for g in evs[str(w.id)]["gates"]:
            if g["state"] == delay.DONE or not g["planned_end"]:
                continue
            d = date.fromisoformat(g["planned_end"])
            if start <= d <= end:
                k = (normalize_stage(g["stage"]), d)
                load[k] = load.get(k, 0) + qty[str(w.id)]
    return load


def capacity_view(db: Session, start: date, days: int) -> Dict:
    days = max(1, min(days, 60))
    end = start + timedelta(days=days - 1)
    caps = capacity_map(db)
    load = gate_load(db, start, end)
    cal = calendar_map(db, start, end)
    off = weekly_off()
    stages = sorted(set(caps) | {k[0] for k in load})
    day_list = []
    for i in range(days):
        d = start + timedelta(days=i)
        day_list.append({"day": d.isoformat(), "non_working": non_working_reason(d, cal, off)})
    rows = []
    for s in stages:
        cells = []
        for i in range(days):
            d = start + timedelta(days=i)
            q = load.get((s, d), 0)
            cap = caps.get(s)
            cells.append({"day": d.isoformat(), "load": q, "over": bool(cap and q > cap)})
        rows.append({"stage": s, "daily_qty": caps.get(s), "cells": cells})
    return {"start": start.isoformat(), "days": day_list, "stages": rows}


# ------------------------------------------------------------------------------ warnings for a plan change
def plan_warnings(db: Session, wo: WorkOrder, merged_ends: Dict[str, Tuple[Optional[date], Optional[date]]],
                  changed_keys: set) -> List[Dict]:
    """Warnings for the gate dates PPC is setting: non-working day and over capacity. Never errors."""
    out: List[Dict] = []
    dates = [d for k in changed_keys for d in merged_ends.get(k, (None, None)) if d]
    if not dates:
        return out
    lo, hi = min(dates), max(dates)
    cal = calendar_map(db, lo, hi)
    off = weekly_off()
    caps = capacity_map(db)
    load = gate_load(db, lo, hi, exclude_wo_id=wo.id) if caps else {}
    qty = wo.physical_wo_qty or 0
    for k in sorted(changed_keys):
        start, end = merged_ends.get(k, (None, None))
        for label, d in (("starts", start), ("ends", end)):
            if d:
                why = non_working_reason(d, cal, off)
                if why:
                    out.append({"stage": k, "level": "WARNING", "message": f"{k} {label} {d.strftime('%d %b')}, which is {why}."})
        cap = caps.get(k)
        if cap and end:
            total = load.get((k, end), 0) + qty
            if total > cap:
                out.append({"stage": k, "level": "WARNING",
                            "message": f"{k} on {end.strftime('%d %b')}: {total} pcs planned against a capacity of {cap}."})
    return out


# ------------------------------------------------------------------------------ split work orders
def splits_of(db: Session, wo_ids: List) -> Dict[str, List[WOSetupSplit]]:
    out: Dict[str, List[WOSetupSplit]] = {}
    if not wo_ids:
        return out
    for s in db.query(WOSetupSplit).filter(WOSetupSplit.work_order_id.in_(wo_ids)).all():
        out.setdefault(str(s.work_order_id), []).append(s)
    return out


def get_splits(db: Session, wo_number: str) -> Dict:
    wo = find_wo(db, wo_number)
    names = {str(s.id): s.setup_number for s in db.query(PlanningSetup).all()}
    rows = splits_of(db, [wo.id]).get(str(wo.id), [])
    other = sum(r.qty for r in rows)
    return {
        "wo_number": wo.wo_number, "total_qty": wo.physical_wo_qty or 0,
        "primary_setup": names.get(str(wo.setup_id)) if wo.setup_id else None,
        "primary_qty": (wo.physical_wo_qty or 0) - other,
        "splits": [{"setup_number": names.get(str(r.setup_id)), "qty": r.qty, "note": r.note} for r in rows],
    }


def set_splits(db: Session, wo_number: str, parts: List[Dict], reason: str, user: Optional[User]) -> Dict:
    """Replace the extra-setup shares of a work order. parts = [{setup_number, qty}]. The primary
    setup keeps the remainder, which must stay at least 1 piece."""
    wo = find_wo(db, wo_number, lock=True)
    if len((reason or "").strip()) < 3:
        raise _bad("A reason is required.")
    if not _released(wo) or not _is_active(wo):
        raise _bad("Only released, open work orders can be split.")
    if wo.setup_id is None:
        raise _bad("Map the work order to its main setup first.")
    primary = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first()
    if primary and primary.status == "CLOSED":
        raise _bad(f"Setup '{primary.setup_number}' is closed. Reopen it first.", status.HTTP_409_CONFLICT)
    total = wo.physical_wo_qty or 0
    seen, clean = set(), []
    for p in parts or []:
        s = find_setup(db, p.get("setup_number") or "")
        q = int(p.get("qty") or 0)
        if s.id == wo.setup_id:
            raise _bad(f"{s.setup_number} is already the main setup of {wo.wo_number}.")
        if s.id in seen:
            raise _bad(f"{s.setup_number} is listed twice.")
        if s.status == "CLOSED":
            raise _bad(f"Setup '{s.setup_number}' is closed.", status.HTTP_409_CONFLICT)
        if q < 1:
            raise _bad(f"Quantity for {s.setup_number} must be at least 1.")
        seen.add(s.id)
        clean.append((s, q))
    if sum(q for _, q in clean) >= total and clean:
        raise _bad(f"The shares add up to {sum(q for _, q in clean)} of {total} pieces; the main setup must keep at least 1.")
    before = get_splits(db, wo.wo_number)
    for r in db.query(WOSetupSplit).filter(WOSetupSplit.work_order_id == wo.id).all():
        db.delete(r)
    db.flush()
    for s, q in clean:
        db.add(WOSetupSplit(work_order_id=wo.id, setup_id=s.id, qty=q, created_by=user.full_name if user else None))
    db.flush()
    fmt = lambda parts_: ", ".join(f"{x['setup_number']} {x['qty']}" for x in parts_) or "none"
    _audit(db, user, "WO_SPLIT_SET", wo.wo_number, fmt(before["splits"]), fmt([{"setup_number": s.setup_number, "qty": q} for s, q in clean]), reason.strip())
    return get_splits(db, wo.wo_number)
