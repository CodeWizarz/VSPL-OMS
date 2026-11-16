from fastapi import APIRouter, Depends, Response, Query
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.report_service import ReportService
from app.schemas.reports import SalesOpsDailyReportResponse

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

@router.get("/sales-ops-daily", response_model=SalesOpsDailyReportResponse)
def get_sales_ops_daily_report(
    target_date: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    preset: str = Query("today", description="Filter preset: today, tomorrow, this_week, overdue_and_today, all_active, custom"),
    status_filter: str = Query("all", description="Status filter: all, gaps_only, ready_only, at_vendor, overdue"),
    search: Optional[str] = Query(None, description="Search term for WO, customer, part, or PO"),
    sort_by: str = Query("priority", description="Sort order: priority, value_desc, date_asc, gap_desc, customer"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Daily Sales-Ops meeting report comparing Planned Commitment vs BSR Actual & Dispatched with financial values."""
    return ReportService.get_sales_ops_daily_report(
        db=db,
        target_date=target_date,
        from_date=from_date,
        to_date=to_date,
        preset=preset,
        status_filter=status_filter,
        search=search,
        sort_by=sort_by
    )

@router.get("/export/sales-ops-csv")
def export_sales_ops_csv(
    target_date: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    preset: str = Query("today"),
    status_filter: str = Query("all"),
    search: Optional[str] = Query(None),
    sort_by: str = Query("priority"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download daily Sales-Ops meeting report as CSV for print or distribution."""
    csv_content = ReportService.generate_sales_ops_csv(
        db=db,
        target_date=target_date,
        from_date=from_date,
        to_date=to_date,
        preset=preset,
        status_filter=status_filter,
        search=search,
        sort_by=sort_by
    )
    dt_str = target_date.strftime("%Y%m%d") if target_date else date.today().strftime("%Y%m%d")
    filename = f"vspl_sales_ops_report_{preset}_{dt_str}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export/wip-csv")
def export_wip_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download current WIP matrix as CSV."""
    csv_content = ReportService.generate_wip_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_wip_report.csv"}
    )

@router.get("/export/movements-csv")
def export_movements_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download full movement history ledger as CSV."""
    csv_content = ReportService.generate_movements_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_movement_ledger.csv"}
    )

@router.get("/export/dispatch-csv")
def export_dispatch_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download dispatch transaction history as CSV."""
    csv_content = ReportService.generate_dispatch_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_dispatch_report.csv"}
    )
