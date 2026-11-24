"""Gate scoping for F1..FI stage SUPERVISORS: they may only see their own gate and the
work orders that currently have material at it.

Applied in the API layer only (read endpoints in work_orders.py / production.py /
dashboard.py). It never changes what a query computes for anyone else -- if the caller is
not a pure F1..FI Supervisor, every function here is a no-op. Stage Managers and all
other roles are unaffected.
"""
from typing import Iterable, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.departments import STAGES_OF_ROLE, normalize_stage
from app.models.user import User, UserRole

GATE_SUPERVISOR_ROLES = (
    UserRole.F1_SUPERVISOR, UserRole.F2_SUPERVISOR, UserRole.F3_SUPERVISOR,
    UserRole.SP_SUPERVISOR, UserRole.FI_SUPERVISOR,
)


def supervisor_gate(user: User) -> Optional[str]:
    """The single gate an F1..FI Supervisor is limited to, or None for everyone else.

    Only when EVERY role the user holds (primary + secondary) is an F1..FI Supervisor
    role -- a user who also holds any other role sees what that role allows."""
    roles = [r for r in (user.role, getattr(user, "secondary_role", None)) if r is not None]
    if not roles or any(r not in GATE_SUPERVISOR_ROLES for r in roles):
        return None
    gates = {g for r in roles for g in STAGES_OF_ROLE[r]}
    return next(iter(gates)) if len(gates) == 1 else None


def wo_ids_at_gate(db: Session, gate: str) -> Set[str]:
    """IDs (as strings) of work orders with material currently at `gate`."""
    from app.models.production_movement import StageWIP  # local import: avoid model cycles

    rows = db.query(StageWIP.work_order_id, StageWIP.stage, StageWIP.available_wip,
                    StageWIP.inproc_qty, StageWIP.onhand_qty).all()
    return {
        str(wo_id)
        for wo_id, stage, avail, inproc, onhand in rows
        if normalize_stage(stage) == gate and ((avail or 0) > 0 or (inproc or 0) > 0 or (onhand or 0) > 0)
    }


def _forbidden(gate: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"As {gate} Supervisor you can only view your own gate ({gate}) and its work orders.",
    )


def deny_if_supervisor(user: User) -> None:
    """Plant-wide views (WIP matrix, dashboards, summaries) are not for gate supervisors."""
    gate = supervisor_gate(user)
    if gate:
        raise _forbidden(gate)


def require_own_stage(user: User, stage: Optional[str]) -> None:
    gate = supervisor_gate(user)
    if gate and normalize_stage(stage) != gate:
        raise _forbidden(gate)


def require_wo_at_gate(db: Session, user: User, wo_identifier: str) -> None:
    """A supervisor may open a work order only while it has material at their gate."""
    gate = supervisor_gate(user)
    if not gate:
        return
    from app.models.work_order import WorkOrder  # local import: avoid model cycles

    ident = (wo_identifier or "").strip()
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == ident).first()
    if wo is None:
        # Identifier may be a UUID; compare as strings against the gate set.
        allowed = ident in wo_ids_at_gate(db, gate)
    else:
        allowed = str(wo.id) in wo_ids_at_gate(db, gate)
    if not allowed:
        raise _forbidden(gate)


def filter_to_gate(items: Iterable, allowed_ids: Set[str]):
    return [i for i in items if str(getattr(i, "id", "")) in allowed_ids]
