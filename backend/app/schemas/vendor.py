from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime


class VendorReceiveRequest(BaseModel):
    dispatch_id: str = Field(..., description="UUID of the vendor dispatch record")
    received_qty: int = Field(..., ge=1, description="Quantity of good parts received from vendor")
    scrap_qty: int = Field(0, ge=0, description="Quantity of rejected / scrap parts reported from vendor")
    destination_stage: Optional[str] = Field("FI", description="Stage where material lands: 'FI' or 'F2'")
    inward_dc: Optional[str] = Field(None, max_length=100, description="Inward Delivery Challan / Invoice / Gate Pass #")
    remarks: Optional[str] = Field(None, max_length=1000, description="Inward remarks / inspection condition")


class VendorTripCreateRequest(BaseModel):
    """Send pieces of a work order from a gate to a vendor. Counts no production."""
    wo_number: str = Field(..., min_length=1)
    stage: str = Field(..., min_length=1, description="Gate the pieces leave from")
    quantity: int = Field(..., ge=1)
    source_state: Optional[str] = Field(None, description="UNPROCESSED or COMPLETED; may be omitted when the gate has only one")
    vendor_name: str = Field(..., min_length=1, max_length=200)
    dc_number: str = Field(..., min_length=1, max_length=100)
    process_name: Optional[str] = Field(None, max_length=200)
    remarks: Optional[str] = Field(None, max_length=1000)


class VendorTripReturnRequest(BaseModel):
    good_qty: int = Field(0, ge=0)
    scrap_qty: int = Field(0, ge=0)
    destination_stage: Optional[str] = Field(None, description="Receive gate entered by SCM: the gate the trip left from (default) or a later gate of the route")
    inward_dc: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = Field(None, max_length=1000)


class VendorTripCancelRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class VendorTripResponse(BaseModel):
    success: bool
    message: str
    trip_id: str
    wo_number: str
    stage: str
    source_state: Optional[str] = None
    status: str
    at_vendor_qty: int
    gate_unprocessed_qty: int
    gate_completed_qty: int


class VendorConfigResponse(BaseModel):
    trips_enabled: bool


class VendorReceiveResponse(BaseModel):
    success: bool
    message: str
    dispatch_id: str
    wo_number: str
    received_qty: int
    scrap_qty: int
    status: str
    current_stage: str


class VendorDispatchItem(BaseModel):
    id: str
    work_order_id: Optional[str]
    wo_number: str
    oar_number: str
    customer_name: str
    part_number: str
    part_name: str
    dispatch_stage: str
    vendor_name: str
    dc_number: str
    dispatched_qty: int
    received_qty: int
    scrap_qty: int
    pending_qty: int
    status: str
    target_return_stage: Optional[str] = "FI"
    received_stage: Optional[str] = None
    dispatched_at: datetime
    received_at: Optional[datetime]
    inward_dc_number: Optional[str]
    remarks: Optional[str]
    days_at_vendor: int
    gate_planned_end: Optional[str] = None
    source_state: Optional[str] = None
    origin: Optional[str] = None
    process_name: Optional[str] = None
    done_qty: int = 0
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None


class VendorSummaryResponse(BaseModel):
    active_dispatches_count: int
    completed_dispatches_count: int
    total_pieces_at_vendor: int
    total_pieces_received: int
    active_vendor_count: int
