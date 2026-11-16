from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import date, datetime

class SalesOpsDailyItem(BaseModel):
    wo_id: str
    wo_number: str
    customer_name: str
    customer_code: str
    customer_po: str
    part_id: str
    part_number: str  # Internal Part ID (e.g. PMC225)
    customer_part_number: Optional[str] = None
    part_name: Optional[str] = None
    grade: Optional[str] = None
    oar_number: Optional[str] = None
    
    commitment_date: Optional[date] = None
    revised_commitment_date: Optional[date] = None
    effective_commitment_date: Optional[date] = None
    commitment_date_revision_count: int = 0
    delivery_date: Optional[date] = None
    date_status: str = "TODAY"  # OVERDUE, TODAY, TOMORROW, THIS_WEEK, FUTURE, UNDATED
    
    # Quantities: Plan vs Actual
    planned_qty: int = 0
    bsr_actual_qty: int = 0  # In BSR / Packing ready for dispatch
    dispatched_qty: int = 0  # Already dispatched
    total_fulfilled_qty: int = 0  # bsr_actual_qty + dispatched_qty
    gap_qty: int = 0  # Deficit: max(0, planned_qty - total_fulfilled_qty)
    part_bsr_stock: int = 0  # Total free unallocated stock in BSR warehouse for this part
    
    # Floor Location & Bottleneck
    current_stage: str = "F1"
    is_at_vendor: bool = False
    vendor_name: Optional[str] = None
    vendor_dc: Optional[str] = None
    vendor_qty: Optional[int] = None
    vendor_stage: Optional[str] = None
    stage_wip: Dict[str, int] = Field(default_factory=dict)
    
    # Value & Pricing
    unit_price: float = 0.0
    price_source: str = "DEFAULT"
    planned_value: float = 0.0
    fulfilled_value: float = 0.0
    gap_value: float = 0.0
    
    # Status
    fulfillment_status: str = "WIP_IN_HOUSE"  # READY_IN_BSR, DISPATCHED, WIP_IN_HOUSE, AT_VENDOR, OVERDUE_DEFICIT
    wo_status: str = "in_production"
    heat_number: Optional[str] = None

class SalesOpsSummary(BaseModel):
    total_orders: int = 0
    total_planned_qty: int = 0
    total_bsr_actual_qty: int = 0
    total_dispatched_qty: int = 0
    total_fulfilled_qty: int = 0
    total_gap_qty: int = 0
    fulfillment_rate: float = 0.0
    total_planned_value: float = 0.0
    total_fulfilled_value: float = 0.0
    total_gap_value: float = 0.0
    overdue_orders_count: int = 0
    overdue_gap_value: float = 0.0
    today_orders_count: int = 0
    today_gap_value: float = 0.0
    at_vendor_count: int = 0

class SalesOpsDailyReportResponse(BaseModel):
    target_date: Optional[date] = None
    filter_preset: str = "today"
    summary: SalesOpsSummary
    items: List[SalesOpsDailyItem]
