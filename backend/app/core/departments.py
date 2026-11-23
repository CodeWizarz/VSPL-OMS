"""Stage roles: which shop-floor stage a stage Supervisor / Manager may post at, and the
conversion of old generic roles (Operator, Machine Operator, Packing, Dispatch) to
stage roles by department.

Backend stage lock (assert_user_may_post_at) applies ONLY to the stage roles
(F1_SUPERVISOR ... PACKING_MANAGER): the stage is part of the role, so they can only
record production / move material out of their own stage. A user who also holds a
non-stage role (e.g. secondary_role = PRODUCTION_MANAGER) is not locked. Old roles keep
today's behaviour (the frontend's userStage.ts hint only) until an admin converts them.
"""
import re
from typing import FrozenSet, Optional

from fastapi import HTTPException, status

from app.models.user import User, UserRole

PACKING_STAGE_ALIASES = {"PACKING", "PACKING/BSR", "PACKING / BSR"}

# Stage(s) each stage role may post at. Packing covers the BSR hand-off too.
STAGES_OF_ROLE = {
    UserRole.F1_SUPERVISOR: frozenset({"F1"}), UserRole.F1_MANAGER: frozenset({"F1"}),
    UserRole.F2_SUPERVISOR: frozenset({"F2"}), UserRole.F2_MANAGER: frozenset({"F2"}),
    UserRole.F3_SUPERVISOR: frozenset({"F3"}), UserRole.F3_MANAGER: frozenset({"F3"}),
    UserRole.SP_SUPERVISOR: frozenset({"SP"}), UserRole.SP_MANAGER: frozenset({"SP"}),
    UserRole.FI_SUPERVISOR: frozenset({"FI"}), UserRole.FI_MANAGER: frozenset({"FI"}),
    UserRole.PACKING_SUPERVISOR: frozenset({"PACKING", "BSR"}),
    UserRole.PACKING_MANAGER: frozenset({"PACKING", "BSR"}),
    UserRole.DISPATCH_SUPERVISOR: frozenset({"DISPATCH"}),
    UserRole.DISPATCH_MANAGER: frozenset({"DISPATCH"}),
}
# Primary stage per role (used for labels and plan-date ownership).
STAGE_OF_ROLE = {
    r: ("PACKING" if "PACKING" in st else next(iter(st))) for r, st in STAGES_OF_ROLE.items()
}

_SUPERVISOR_FOR_STAGE = {
    "F1": UserRole.F1_SUPERVISOR, "F2": UserRole.F2_SUPERVISOR, "F3": UserRole.F3_SUPERVISOR,
    "SP": UserRole.SP_SUPERVISOR, "FI": UserRole.FI_SUPERVISOR, "PACKING": UserRole.PACKING_SUPERVISOR,
}
LEGACY_ROLES = (UserRole.OPERATOR, UserRole.MACHINE_OPERATOR, UserRole.PACKING, UserRole.DISPATCH)


def department_stage(department: Optional[str]) -> Optional[str]:
    """The stage a free-text department names ("F1".."FI", "PACKING"), or None."""
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


def convert_legacy_role(role: UserRole, department: Optional[str]) -> Optional[UserRole]:
    """Stage role an old-role account should become, or None if its stage can't be
    worked out (it stays on its old role, flagged for an admin)."""
    if role == UserRole.PACKING:
        return UserRole.PACKING_SUPERVISOR
    if role == UserRole.DISPATCH:
        return UserRole.DISPATCH_SUPERVISOR
    if role in (UserRole.OPERATOR, UserRole.MACHINE_OPERATOR):
        return _SUPERVISOR_FOR_STAGE.get(department_stage(department))
    return None


def normalize_stage(stage: Optional[str]) -> str:
    s = (stage or "").strip().upper()
    return "PACKING" if s in PACKING_STAGE_ALIASES else s


def allowed_stages_for(user: User) -> Optional[FrozenSet[str]]:
    """Stages this user may post at, or None if unrestricted. Locked only when every
    role the user holds (primary + secondary) is a stage role."""
    roles = [r for r in (user.role, getattr(user, "secondary_role", None)) if r is not None]
    if not roles or any(r not in STAGES_OF_ROLE for r in roles):
        return None
    allowed: set = set()
    for r in roles:
        allowed |= STAGES_OF_ROLE[r]
    return frozenset(allowed)


def assert_user_may_post_at(user: User, stage: Optional[str], action: str) -> None:
    allowed = allowed_stages_for(user)
    if allowed is None:
        return
    if normalize_stage(stage) not in allowed:
        label = " / ".join(sorted(allowed))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You can only {action} at your own stage ({label}), not at '{stage}'.",
        )
