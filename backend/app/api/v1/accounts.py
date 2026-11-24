from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.roles import ACCOUNTS_ROLES, COMMERCIAL_REPORT_ROLES
from app.models.user import User
from app.schemas.accounts import InvoiceAmountUpdate, InvoiceSummary, PaymentCreate, PaymentOut, POCycleRow
from app.services.accounts_service import AccountsService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.get("/invoices", response_model=List[InvoiceSummary])
def list_invoices(
    status_filter: Optional[str] = Query(None, description="NOT_VALUED | UNPAID | PARTIAL | PAID"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*COMMERCIAL_REPORT_ROLES)),
):
    """Every dispatched invoice with its value, money received and what is outstanding."""
    return AccountsService.list_invoices(db, status_filter=status_filter)


@router.put("/invoices/{invoice_number}", response_model=InvoiceSummary)
def set_invoice_amount(
    invoice_number: str,
    payload: InvoiceAmountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ACCOUNTS_ROLES)),
):
    """Accounts sets / corrects an invoice's value (audit-logged)."""
    return AccountsService.set_invoice_amount(db, invoice_number, payload, user)


@router.get("/payments", response_model=List[PaymentOut])
def list_payments(
    invoice_number: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*COMMERCIAL_REPORT_ROLES)),
):
    return AccountsService.list_payments(db, invoice_number=invoice_number)


@router.post("/payments", response_model=PaymentOut)
def record_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ACCOUNTS_ROLES)),
):
    """Record money received against an invoice. Partial payments are allowed; the
    total can never exceed the invoice value."""
    return AccountsService.record_payment(db, payload, user)


@router.get("/po-cycle", response_model=List[POCycleRow])
def po_cycle_report(
    search: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*COMMERCIAL_REPORT_ROLES)),
):
    """Sales report: each customer PO/OAR from order to production, BSR, dispatch,
    invoicing and collection."""
    return AccountsService.po_cycle(db, search=search)
