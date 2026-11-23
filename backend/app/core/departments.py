"""Department -> shop-floor stage resolution, and stage-scoped posting.

A user's `department` is free text set on the Users screen (e.g. "F1 Foundry",
"Subcontracting (SP)", "Packing / BSR"). The frontend uses the same matching rules in
frontend/lib/workspaces.ts to choose which screens a user sees; the backend uses it here
for one thing only: limiting *floor-level* roles to posting at their own stage.

Who is stage-locked (STAGE_LOCKED_ROLES):
  - SUPERVISOR, MACHINE_OPERATOR, OPERATOR -- only when their department names a stage.
    A blank / non-stage department (e.g. "Manufacturing Operations") leaves them
    unrestricted, exactly as before this change.
  - PACKING -- always limited to the Packing / BSR stages, whatever the department.
Admin, Production Manager and Store are never stage-locked.
"""
import re
from typing import Optional

from fastapi import HTTPException, status

from app.models.user import User, UserRole

PACKING_STAGE_ALIASES = {"PACKING", "BSR", "PACKING/BSR", "PACKING / BSR"}

STAGE_LOCKED_ROLES = (UserRole.SUPERVISOR, UserRole.MACHINE_OPERATOR, UserRole.OPERATOR)


def department_stage(department: Optional[str]) -> Optional[str]:
    """The stage a department works at ("F1".."FI", "PACKING"), or None."""
    if not department:
        return None
    d = department.upper()
    words = set(w for w in re.split(r"[^A-Z0-9]+", d) if w)
    if "F1" in words or "FOUNDRY" in d:
        return "F1"
    if "F2" in words:
        return "F2"
    if "F3" in words:
        return "F3"
    if "SP" in words or "SUBCONTRACT" in d:
        return "SP"
    if "FI" in words or "FINAL INSPECTION" in d:
        return "FI"
    if "PACKING" in d or "BSR" in words:
        return "PACKING"
    return None


def normalize_stage(stage: Optional[str]) -> str:
    s = (stage or "").strip().upper()
    return "PACKING" if s in PACKING_STAGE_ALIASES else s


def allowed_stage_for(user: User) -> Optional[str]:
    """The single stage this user may post at, or None if unrestricted."""
    if user.role == UserRole.PACKING:
        return "PACKING"
    if user.role in STAGE_LOCKED_ROLES:
        return department_stage(user.department)
    return None


def assert_user_may_post_at(user: User, stage: Optional[str], action: str) -> None:
    """403 if a stage-locked user tries to record production / move material at a
    stage other than their own."""
    allowed = allowed_stage_for(user)
    if allowed is None:
        return
    if normalize_stage(stage) != allowed:
        label = "Packing / BSR" if allowed == "PACKING" else allowed
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only {action} at your own stage ({label}), not at '{stage}'.",
        )
