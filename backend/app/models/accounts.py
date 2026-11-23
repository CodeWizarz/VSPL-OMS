"""Customer invoices and the payments received against them (PO-to-receipt cycle).

An invoice is identified by the invoice number entered at dispatch. One invoice can
cover several dispatch lines (several WOs); its amount is the sum of the line values
entered at dispatch, and Accounts can correct it. Payments are recorded per invoice and
may be partial.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.sql import func

from app.core.database import Base, GUID


class CustomerInvoice(Base):
    __tablename__ = "customer_invoices"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_number = Column(String, unique=True, nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=True)  # None = value not entered yet
    invoice_date = Column(Date, nullable=True)
    updated_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class InvoicePayment(Base):
    __tablename__ = "invoice_payments"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_number = Column(String, nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    received_date = Column(Date, nullable=False)
    mode = Column(String, nullable=True)        # NEFT / RTGS / Cheque / ...
    reference = Column(String, nullable=True)   # UTR / cheque number
    remarks = Column(String, nullable=True)
    recorded_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    recorded_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
