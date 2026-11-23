"""Invoices, payments and the PO -> dispatch -> collection report.

Read models are derived from Dispatch rows (one per WO shipped, carrying the invoice
number), CustomerInvoice (invoice value) and InvoicePayment (money received). Nothing
here changes production or dispatch quantities.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.accounts import CustomerInvoice, InvoicePayment
from app.models.audit import AuditLog
from app.models.dispatch import Dispatch
from app.models.order import Order
from app.models.packing import PackingRecord
from app.models.user import User
from app.models.work_order import WorkOrder
from app.schemas.accounts import (
    InvoiceAmountUpdate, InvoiceSummary, PaymentCreate, PaymentOut, POCycleRow,
)


def _money(v) -> Optional[float]:
    return None if v is None else float(Decimal(v).quantize(Decimal("0.01")))


def _collection_status(amount: Optional[Decimal], paid: Decimal) -> str:
    if amount is None:
        return "NOT_VALUED" if paid == 0 else "PARTIAL"
    if paid <= 0:
        return "UNPAID" if amount > 0 else "PAID"
    return "PAID" if paid >= amount else "PARTIAL"


def _paid_by_invoice(db: Session) -> Dict[str, Decimal]:
    totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for p in db.query(InvoicePayment).all():
        totals[p.invoice_number] += Decimal(p.amount)
    return totals


def record_dispatch_invoice_value(db: Session, invoice_number: str, line_amount: Optional[Decimal], user: Optional[User]) -> None:
    """Called at dispatch: make sure the invoice exists and add this line's value."""
    inv_no = invoice_number.strip()
    inv = db.query(CustomerInvoice).filter(CustomerInvoice.invoice_number == inv_no).first()
    if inv is None:
        inv = CustomerInvoice(invoice_number=inv_no, amount=None, invoice_date=date.today())
        db.add(inv)
    if line_amount is not None:
        inv.amount = (Decimal(inv.amount) if inv.amount is not None else Decimal("0")) + Decimal(line_amount)
        inv.updated_by = user.id if user else None


class AccountsService:
    @staticmethod
    def list_invoices(db: Session, status_filter: Optional[str] = None) -> List[InvoiceSummary]:
        dispatches = db.query(Dispatch).filter(Dispatch.invoice_number.isnot(None)).all()
        invoices = {i.invoice_number: i for i in db.query(CustomerInvoice).all()}
        paid = _paid_by_invoice(db)
        groups: Dict[str, List[Dispatch]] = defaultdict(list)
        for d in dispatches:
            groups[d.invoice_number.strip()].append(d)

        today = date.today()
        out: List[InvoiceSummary] = []
        for inv_no, rows in groups.items():
            inv = invoices.get(inv_no)
            amount = Decimal(inv.amount) if inv and inv.amount is not None else None
            p = paid.get(inv_no, Decimal("0"))
            first = min((d.dispatch_date for d in rows if d.dispatch_date), default=None)
            wos = [d.work_order for d in rows if d.work_order is not None]
            customer = next((w.order.customer.name for w in wos if w.order and w.order.customer), None)
            st = _collection_status(amount, p)
            if status_filter and st != status_filter.upper():
                continue
            out.append(InvoiceSummary(
                invoice_number=inv_no,
                customer_name=customer,
                customer_pos=sorted({d.customer_po for d in rows if d.customer_po}),
                wo_numbers=sorted({w.wo_number for w in wos}),
                dispatched_qty=sum(d.dispatched_qty or 0 for d in rows),
                first_dispatch_date=first,
                amount=_money(amount),
                paid=_money(p) or 0.0,
                outstanding=_money(max(amount - p, Decimal("0"))) if amount is not None else None,
                status=st,
                days_since_dispatch=(today - first.date()).days if first else None,
            ))
        out.sort(key=lambda i: (i.status == "PAID", -(i.days_since_dispatch or 0)))
        return out

    @staticmethod
    def set_invoice_amount(db: Session, invoice_number: str, req: InvoiceAmountUpdate, user: User) -> InvoiceSummary:
        inv_no = invoice_number.strip()
        if not db.query(Dispatch.id).filter(Dispatch.invoice_number == inv_no).first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No dispatch found for invoice '{inv_no}'.")
        inv = db.query(CustomerInvoice).filter(CustomerInvoice.invoice_number == inv_no).first()
        old = inv.amount if inv else None
        if inv is None:
            inv = CustomerInvoice(invoice_number=inv_no)
            db.add(inv)
        paid = _paid_by_invoice(db).get(inv_no, Decimal("0"))
        if req.amount < paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invoice amount cannot be less than the {paid:.2f} already received.",
            )
        inv.amount = req.amount
        if req.invoice_date is not None:
            inv.invoice_date = req.invoice_date
        inv.updated_by = user.id
        db.add(AuditLog(
            user_id=user.id, user_name=user.full_name, action="INVOICE_AMOUNT_SET",
            entity="CustomerInvoice", entity_id=inv_no,
            old_value=str(old) if old is not None else None, new_value=str(req.amount),
        ))
        db.commit()
        return next(i for i in AccountsService.list_invoices(db) if i.invoice_number == inv_no)

    @staticmethod
    def record_payment(db: Session, req: PaymentCreate, user: User) -> PaymentOut:
        inv_no = req.invoice_number.strip()
        if not db.query(Dispatch.id).filter(Dispatch.invoice_number == inv_no).first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No dispatch found for invoice '{inv_no}'.")
        if req.received_date > date.today():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Received date cannot be in the future.")
        inv = db.query(CustomerInvoice).filter(CustomerInvoice.invoice_number == inv_no).first()
        paid = _paid_by_invoice(db).get(inv_no, Decimal("0"))
        if inv is not None and inv.amount is not None and paid + req.amount > Decimal(inv.amount):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Payment of {req.amount:.2f} would exceed the invoice amount "
                    f"({Decimal(inv.amount):.2f}, already received {paid:.2f})."
                ),
            )
        pay = InvoicePayment(
            invoice_number=inv_no, amount=req.amount, received_date=req.received_date,
            mode=req.mode, reference=req.reference, remarks=req.remarks,
            recorded_by=user.id, recorded_by_name=user.full_name,
        )
        db.add(pay)
        db.add(AuditLog(
            user_id=user.id, user_name=user.full_name, action="PAYMENT_RECORDED",
            entity="InvoicePayment", entity_id=inv_no,
            new_value=f"{req.amount} on {req.received_date}", details=req.reference,
        ))
        db.commit()
        db.refresh(pay)
        return AccountsService._payment_out(pay)

    @staticmethod
    def list_payments(db: Session, invoice_number: Optional[str] = None) -> List[PaymentOut]:
        q = db.query(InvoicePayment)
        if invoice_number:
            q = q.filter(InvoicePayment.invoice_number == invoice_number.strip())
        return [AccountsService._payment_out(p) for p in q.order_by(InvoicePayment.received_date.desc()).all()]

    @staticmethod
    def _payment_out(p: InvoicePayment) -> PaymentOut:
        return PaymentOut(
            id=str(p.id), invoice_number=p.invoice_number, amount=_money(p.amount) or 0.0,
            received_date=p.received_date, mode=p.mode, reference=p.reference, remarks=p.remarks,
            recorded_by_name=p.recorded_by_name, created_at=p.created_at,
        )

    @staticmethod
    def po_cycle(db: Session, search: Optional[str] = None) -> List[POCycleRow]:
        invoices = {i.invoice_number: i for i in db.query(CustomerInvoice).all()}
        paid = _paid_by_invoice(db)
        rows: List[POCycleRow] = []
        for order in db.query(Order).order_by(Order.created_at.desc()).all():
            wos = db.query(WorkOrder).filter(WorkOrder.order_id == order.id).all()
            wo_ids = [w.id for w in wos]
            dispatches = db.query(Dispatch).filter(Dispatch.work_order_id.in_(wo_ids)).all() if wo_ids else []
            packing = db.query(PackingRecord).filter(PackingRecord.work_order_id.in_(wo_ids)).all() if wo_ids else []
            customer = order.customer
            part = order.part
            if search:
                hay = " ".join(filter(None, [
                    order.oar_number, order.customer_po, customer.name if customer else None,
                    customer.customer_code if customer else None, part.part_number if part else None,
                ])).lower()
                if search.strip().lower() not in hay:
                    continue

            inv_nos = sorted({d.invoice_number.strip() for d in dispatches if d.invoice_number})
            amounts = [invoices[i].amount for i in inv_nos if i in invoices and invoices[i].amount is not None]
            invoiced = sum((Decimal(a) for a in amounts), Decimal("0")) if len(amounts) == len(inv_nos) and inv_nos else None
            received = sum((paid.get(i, Decimal("0")) for i in inv_nos), Decimal("0"))
            dispatched = sum(d.dispatched_qty or 0 for d in dispatches)
            in_bsr = sum(p.ready_for_dispatch_qty or 0 for p in packing)

            if not inv_nos:
                collection = "NOT_INVOICED"
            elif invoiced is None:
                collection = "NOT_VALUED" if received == 0 else "PARTIAL"
            else:
                collection = _collection_status(invoiced, received)

            if dispatched >= order.po_qty and order.po_qty > 0:
                stage = "DISPATCHED"
            elif dispatched > 0:
                stage = "PART_DISPATCHED"
            elif in_bsr > 0:
                stage = "READY_IN_BSR"
            else:
                stage = "IN_PRODUCTION"

            rows.append(POCycleRow(
                oar_number=order.oar_number,
                customer_code=customer.customer_code if customer else None,
                customer_name=customer.name if customer else None,
                customer_po=order.customer_po,
                part_number=part.part_number if part else None,
                po_qty=order.po_qty,
                delivery_date=order.delivery_date,
                wo_count=len(wos),
                released_qty=sum(w.physical_wo_qty or 0 for w in wos),
                in_bsr_qty=in_bsr,
                dispatched_qty=dispatched,
                pending_qty=max(order.po_qty - dispatched, 0),
                invoices=inv_nos,
                invoiced_amount=_money(invoiced),
                paid_amount=_money(received) or 0.0,
                outstanding_amount=_money(max(invoiced - received, Decimal("0"))) if invoiced is not None else None,
                stage=stage,
                collection_status=collection,
            ))
        return rows
