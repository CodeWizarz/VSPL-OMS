import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class VendorDispatch(Base):
    """Tracks Work Order material dispatched to outside subcontracting vendors (e.g. from F2)
    and inward reception directly into Final Inspection (FI)."""
    __tablename__ = "vendor_dispatches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    dispatch_stage = Column(String(50), default="F2", nullable=False)
    vendor_name = Column(String(200), nullable=False, index=True)
    dc_number = Column(String(100), nullable=False, index=True)
    target_return_stage = Column(String(50), default="FI", nullable=True)
    received_stage = Column(String(50), nullable=True)
    dispatched_qty = Column(Integer, nullable=False)
    received_qty = Column(Integer, default=0, nullable=False)
    scrap_qty = Column(Integer, default=0, nullable=False)
    
    # Status: AT_VENDOR, PARTIALLY_RECEIVED, RECEIVED
    status = Column(String(50), default="AT_VENDOR", nullable=False, index=True)
    
    dispatched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=True)
    inward_dc_number = Column(String(100), nullable=True)
    remarks = Column(String, nullable=True)

    # --- Vendor trips (docs/vendor-trips-architecture.md) -----------------------------------
    # source_state: UNPROCESSED / COMPLETED = the state the pieces left from at this gate.
    # NULL = legacy trip (a vendor production entry) which keeps its original accounting.
    source_state = Column(String(20), nullable=True, index=True)
    origin = Column(String(10), nullable=True)            # PE (entered on Production Entry) / DC (later)
    process_name = Column(String(200), nullable=True)     # free text, never used for counting
    done_qty = Column(Integer, default=0, nullable=False) # pieces returned as "gate work done"
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(String(500), nullable=True)
    
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder")


class VendorTripReturn(Base):
    """One return of pieces from a vendor trip. Partial returns of one trip can carry
    different SCM decisions, so each return is its own row."""
    __tablename__ = "vendor_trip_returns"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    trip_id = Column(GUID, ForeignKey("vendor_dispatches.id"), nullable=False, index=True)
    good_qty = Column(Integer, default=0, nullable=False)
    scrap_qty = Column(Integer, default=0, nullable=False)
    # MORE_WORK / GATE_DONE (left unprocessed) / BACK_TO_COMPLETED (left completed) / MOVED_ON (landed at another gate)
    decision = Column(String(30), nullable=True)
    # Gate the good pieces landed at. NULL = the gate the trip left from. Another (later) gate
    # = the pieces went straight there (decision MOVED_ON), like a move that skips the wait.
    destination_stage = Column(String(50), nullable=True)
    production_update_id = Column(GUID, nullable=True)    # set for GATE_DONE
    inward_dc = Column(String(100), nullable=True)
    remarks = Column(Text, nullable=True)
    received_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    trip = relationship("VendorDispatch")
