from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.subcontract_service import SubcontractService

router = APIRouter(prefix="/api/v1/subcontract", tags=["subcontract"])


@router.get("/summary")
def subcontract_summary(
    days: int = Query(2, ge=0, le=14),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Read-only SP view: material at SP ready to send, open DCs at the vendor, and DCs
    expected back today / within `days` (from the DC software, when linked)."""
    return SubcontractService.summary(db, days=days)
