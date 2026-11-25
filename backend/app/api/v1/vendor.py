from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User
from app.schemas.vendor import (
    VendorDispatchItem,
    VendorReceiveRequest,
    VendorReceiveResponse,
    VendorTripCreateRequest,
    VendorTripReturnRequest,
    VendorTripCancelRequest,
    VendorTripResponse,
    VendorConfigResponse,
    VendorSummaryResponse
)
from app.services.vendor_service import VendorService
from app.services.vendor_trip_service import VendorTripService, SCM_ROLES
from app.models.user import UserRole
from app.core.roles import PRODUCTION_ENTRY_ROLES, MATERIAL_MOVEMENT_ROLES

# Who may send pieces to a vendor from Production Entry: the production entry roles for their
# own gate (enforced in the service) plus SCM.
TRIP_SEND_ROLES = tuple(PRODUCTION_ENTRY_ROLES) + (UserRole.SP_MANAGER, UserRole.SP_SUPERVISOR)

router = APIRouter(prefix="/api/v1/vendor", tags=["vendor-tracking"])


@router.get("/dispatches", response_model=List[VendorDispatchItem])
def list_vendor_dispatches(
    status: Optional[str] = Query(None, description="Filter by status: AT_VENDOR, PARTIALLY_RECEIVED, RECEIVED, ALL"),
    search: Optional[str] = Query(None, description="Search by DC#, Vendor Name, WO#, Part, Customer"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Lists all Work Orders dispatched to outside subcontractors / vendors."""
    return VendorService.list_dispatches(
        db, status_filter=status, search=search, limit=limit, offset=offset
    )


@router.get("/summary", response_model=VendorSummaryResponse)
def get_vendor_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Aggregate totals for active vendor dispatches, pieces at vendor, and returns."""
    return VendorService.get_summary(db)


@router.post("/receive", response_model=VendorReceiveResponse)
def receive_from_vendor(
    payload: VendorReceiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MATERIAL_MOVEMENT_ROLES))
):
    """Receives subcontracted parts returned from a vendor and lands them
    into the designated stage (e.g. FI for final QA, or F2 for in-house finishing)."""
    return VendorService.receive_from_vendor(
        db=db,
        dispatch_id=payload.dispatch_id,
        received_qty=payload.received_qty,
        scrap_qty=payload.scrap_qty,
        destination_stage=payload.destination_stage or "FI",
        inward_dc=payload.inward_dc,
        remarks=payload.remarks,
        current_user=user
    )


@router.get("/config", response_model=VendorConfigResponse)
def vendor_config(user: User = Depends(get_current_user)):
    """Whether the vendor trip flow is switched on (screens use this to choose their layout)."""
    return {"trips_enabled": VendorTripService.enabled()}


@router.get("/gate-state")
def vendor_gate_state(
    wo_number: str = Query(...),
    stage: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Unprocessed / completed / at-vendor pieces of a WO at one gate."""
    return VendorTripService.gate_state(db, wo_number, stage)


@router.post("/trips", response_model=VendorTripResponse)
def create_vendor_trip(
    payload: VendorTripCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*TRIP_SEND_ROLES))
):
    """Send pieces from a gate to a vendor. Counts no production."""
    return VendorTripService.send(
        db, wo_number=payload.wo_number, stage=payload.stage, quantity=payload.quantity,
        vendor_name=payload.vendor_name, dc_number=payload.dc_number, source_state=payload.source_state,
        process_name=payload.process_name, remarks=payload.remarks, current_user=user,
    )


@router.post("/trips/{trip_id}/returns", response_model=VendorTripResponse)
def record_vendor_trip_return(
    trip_id: str,
    payload: VendorTripReturnRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SCM_ROLES))
):
    """Record pieces back from a vendor; SCM decides what happens to pieces that left unprocessed."""
    return VendorTripService.record_return(
        db, trip_id, good_qty=payload.good_qty, scrap_qty=payload.scrap_qty,
        destination_stage=payload.destination_stage,
        inward_dc=payload.inward_dc, remarks=payload.remarks, current_user=user,
    )


@router.post("/trips/{trip_id}/cancel", response_model=VendorTripResponse)
def cancel_vendor_trip(
    trip_id: str,
    payload: VendorTripCancelRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SCM_ROLES))
):
    """Cancel a trip that has nothing returned yet; its pieces go back to where they left from."""
    return VendorTripService.cancel(db, trip_id, payload.reason, current_user=user)
