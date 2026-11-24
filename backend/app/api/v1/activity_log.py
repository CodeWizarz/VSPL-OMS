from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.activity import ActivityLog
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/v1/activity-log", tags=["activity-log"])


@router.get("")
def list_activity(
    search: Optional[str] = Query(None, max_length=200, description="Name, email, record or screen"),
    action: Optional[str] = Query(None, description="Create | Update | Delete"),
    outcome: Optional[str] = Query(None, description="Success | Refused | Failed"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN)),
):
    """Admin: who created / changed / deleted what, newest first."""
    q = db.query(ActivityLog)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            ActivityLog.user_name.ilike(like), ActivityLog.user_email.ilike(like),
            ActivityLog.target.ilike(like), ActivityLog.path.ilike(like), ActivityLog.details.ilike(like),
        ))
    if action:
        q = q.filter(ActivityLog.action == action)
    if outcome:
        q = q.filter(ActivityLog.outcome == outcome)
    if date_from:
        q = q.filter(ActivityLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.filter(ActivityLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = q.count()
    rows = q.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id),
                "at": r.created_at.isoformat() if r.created_at else None,
                "user_name": r.user_name or "Unknown",
                "user_email": r.user_email,
                "user_role": r.user_role,
                "action": r.action,
                "area": r.area,
                "path": r.path,
                "target": r.target,
                "details": r.details,
                "outcome": r.outcome,
                "status_code": r.status_code,
            }
            for r in rows
        ],
    }
