from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.roles import PLANNING_ROLES
from app.models.audit import AuditLog
from app.models.planning import StageLeadTime
from app.models.user import User
from app.services.stage_plan_service import EDITABLE_STAGES, STAGE_LEAD_DAYS, load_lead_days

router = APIRouter(prefix="/api/v1/planning", tags=["planning"])


class LeadTimesUpdate(BaseModel):
    days: Dict[str, int] = Field(..., description="Stage -> standard calendar days, e.g. {'F1': 3}")


def _current(db: Session) -> dict:
    merged = load_lead_days(db)
    saved = {r.stage.upper() for r in db.query(StageLeadTime).all()}
    return {
        "stages": [
            {"stage": s, "days": merged[s], "default_days": STAGE_LEAD_DAYS.get(s), "customised": s in saved}
            for s in EDITABLE_STAGES
        ]
    }


@router.get("/lead-times")
def get_lead_times(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Standard days per stage used to auto-fill stage plan dates on release."""
    return _current(db)


@router.put("/lead-times")
def update_lead_times(
    payload: LeadTimesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES)),
):
    """PPC sets standard days per stage. Applies to WOs released/edited from now on;
    existing plan dates are not changed."""
    before = load_lead_days(db)
    changes = []
    for raw_stage, days in payload.days.items():
        stage = raw_stage.strip().upper()
        if stage not in EDITABLE_STAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown stage '{raw_stage}'.")
        if not 0 <= days <= 60:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{stage}: days must be between 0 and 60.")
        if before.get(stage) == days:
            continue
        row = db.query(StageLeadTime).filter(StageLeadTime.stage == stage).first()
        if row is None:
            db.add(StageLeadTime(stage=stage, days=days, updated_by=user.id))
        else:
            row.days, row.updated_by = days, user.id
        changes.append(f"{stage}: {before.get(stage)} -> {days}")
    if changes:
        db.add(AuditLog(
            user_id=user.id, user_name=user.full_name, action="LEAD_TIMES_UPDATED",
            entity="StageLeadTime", entity_id="lead-times", new_value="; ".join(changes),
        ))
        db.commit()
    return _current(db)
