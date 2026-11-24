from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class InvoiceSummary(BaseModel):
    invoice_number: str
    customer_name: Optional[str] = None
    customer_pos: List[str] = []
    wo_numbers: List[str] = []
    dispatched_qty: int = 0
    first_dispatch_date: Optional[datetime] = None
    amount: Optional[float] = None
    paid: float = 0.0
    outstanding: Optional[float] = None
    status: str  # NOT_VALUED | UNPAID | PARTIAL | PAID
    days_since_dispatch: Optional[int] = None


class InvoiceAmountUpdate(BaseModel):
    amount: Decimal = Field(..., ge=0, le=Decimal("9999999999.99"), max_digits=14, decimal_places=2)
    invoice_date: Optional[date] = None


class PaymentCreate(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=200)
    amount: Decimal = Field(..., gt=0, le=Decimal("9999999999.99"), max_digits=14, decimal_places=2)
    received_date: date
    mode: Optional[str] = Field(None, max_length=50)
    reference: Optional[str] = Field(None, max_length=200)
    remarks: Optional[str] = Field(None, max_length=1000)


class PaymentOut(BaseModel):
    id: str
    invoice_number: str
    amount: float
    received_date: date
    mode: Optional[str] = None
    reference: Optional[str] = None
    remarks: Optional[str] = None
    recorded_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class POCycleRow(BaseModel):
    oar_number: Optional[str] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_po: str
    part_number: Optional[str] = None
    po_qty: int
    delivery_date: Optional[date] = None
    wo_count: int
    released_qty: int
    in_bsr_qty: int
    dispatched_qty: int
    pending_qty: int
    invoices: List[str] = []
    invoiced_amount: Optional[float] = None
    paid_amount: float = 0.0
    outstanding_amount: Optional[float] = None
    stage: str  # IN_PRODUCTION | READY_IN_BSR | PART_DISPATCHED | DISPATCHED
    collection_status: str  # NOT_INVOICED | NOT_VALUED | UNPAID | PARTIAL | PAID
