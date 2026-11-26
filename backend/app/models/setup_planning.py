"""Setup planning (docs/setup-planning-architecture.md).

A setup is one production day with several work orders, planned by PPC. Every released work
order belongs to one setup. Gate dates stay on wo_routes (planned_start / planned_end); the
tables here hold the setups, the heat numbers of each work order, and the history of Excel
plan imports. Planning is information only: nothing here is read by production entry, moves,
MRB or dispatch validation.
"""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base, GUID


class PlanningSetup(Base):
    __tablename__ = "planning_setups"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    setup_number = Column(String(60), unique=True, nullable=False, index=True)
    setup_date = Column(Date, nullable=True)                       # the production day
    status = Column(String(20), nullable=False, default="OPEN")    # OPEN / CLOSED
    remarks = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


class WOHeat(Base):
    """A heat number used by a work order. A work order can have several, and one heat can serve
    several work orders of the same setup."""
    __tablename__ = "wo_heats"
    __table_args__ = (UniqueConstraint("work_order_id", "heat_number", name="uq_wo_heat"),)

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    setup_id = Column(GUID, ForeignKey("planning_setups.id"), nullable=True, index=True)
    heat_number = Column(String(100), nullable=False, index=True)
    added_by = Column(String, nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanImport(Base):
    """One uploaded Excel plan. Nothing is applied until PPC confirms (status REVIEW -> APPLIED)."""
    __tablename__ = "plan_imports"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    setup_id = Column(GUID, ForeignKey("planning_setups.id"), nullable=True, index=True)
    setup_number = Column(String(60), nullable=True)
    file_name = Column(String, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    uploaded_by = Column(String, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), nullable=False, default="REVIEW")  # REVIEW / APPLIED / DISCARDED / UNDONE
    total_wos = Column(Integer, default=0)
    ok_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    applied_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_by = Column(String, nullable=True)
    file_errors = Column(Text, nullable=True)                      # JSON list of file-level messages


class PlanImportRow(Base):
    __tablename__ = "plan_import_rows"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    import_id = Column(GUID, ForeignKey("plan_imports.id"), nullable=False, index=True)
    row_no = Column(Integer, nullable=True)
    wo_number = Column(String(60), nullable=True)
    stage = Column(String(40), nullable=True)                      # a gate, or HEATS
    old_start = Column(Date, nullable=True)
    old_end = Column(Date, nullable=True)
    new_start = Column(Date, nullable=True)
    new_end = Column(Date, nullable=True)
    old_text = Column(String, nullable=True)                       # heats
    new_text = Column(String, nullable=True)
    result = Column(String(12), nullable=False, default="OK")      # OK / WARNING / ERROR / UNCHANGED
    message = Column(String, nullable=True)
    applied = Column(Boolean, default=False)


class WOSetupSplit(Base):
    """A share of a work order's quantity planned in an ADDITIONAL setup. The work order's primary
    setup (work_orders.setup_id) keeps the rest. Planning information only: quantities on the
    floor (WIP, moves, MRB) never read this."""
    __tablename__ = "wo_setup_splits"
    __table_args__ = (UniqueConstraint("work_order_id", "setup_id", name="uq_wo_setup_split"),)

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    setup_id = Column(GUID, ForeignKey("planning_setups.id"), nullable=False, index=True)
    qty = Column(Integer, nullable=False)
    note = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanningCalendarDay(Base):
    """An exception to the weekly pattern: HOLIDAY (plant closed) or WORKING (a normally-off day worked)."""
    __tablename__ = "planning_calendar_days"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    day = Column(Date, nullable=False, unique=True, index=True)
    kind = Column(String(20), nullable=False, default="HOLIDAY")   # HOLIDAY / WORKING
    note = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlanningCapacity(Base):
    """How many pieces a gate can finish per working day. A gate with no row is not checked."""
    __tablename__ = "planning_capacity"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    stage = Column(String(40), nullable=False, unique=True, index=True)
    daily_qty = Column(Integer, nullable=False)
    note = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
