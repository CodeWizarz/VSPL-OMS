"""Sales order status dashboard: Sales department and Admin only. Read-only."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.roles import SALES_DASHBOARD_ROLES
from app.models.user import User
from app.services import sales_report_service as svc

router = APIRouter(prefix="/api/v1/sales", tags=["sales-report"])


def _include(sources: Optional[str]):
    return [s for s in (sources or "").split(",") if s.strip()] or None


@router.get("/order-status")
def order_status(sources: Optional[str] = Query(None, description="OAR,PO_LINE,SCHEDULE (default all)"),
                 db: Session = Depends(get_db), user: User = Depends(require_roles(*SALES_DASHBOARD_ROLES))):
    return svc.build_report(db, _include(sources))


@router.get("/order-status.xlsx")
def order_status_xlsx(sources: Optional[str] = Query(None), db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*SALES_DASHBOARD_ROLES))):
    from datetime import date
    content = svc.export_report(db, _include(sources))
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="sales-order-status-{date.today().isoformat()}.xlsx"'})


@router.get("/schedule-status")
def schedule_status(db: Session = Depends(get_db), user: User = Depends(require_roles(*SALES_DASHBOARD_ROLES))):
    return svc.build_schedule_report(db)


@router.get("/schedule-status.xlsx")
def schedule_status_xlsx(db: Session = Depends(get_db), user: User = Depends(require_roles(*SALES_DASHBOARD_ROLES))):
    from datetime import date
    return Response(content=svc.export_schedule_report(db),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="schedule-status-{date.today().isoformat()}.xlsx"'})
