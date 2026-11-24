"""Planning settings editable by PPC."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base, GUID


class StageLeadTime(Base):
    """Standard calendar days a stage takes. Overrides the code defaults in
    services/stage_plan_service.STAGE_LEAD_DAYS; used to auto-fill stage plan dates."""
    __tablename__ = "stage_lead_times"

    stage = Column(String, primary_key=True)
    days = Column(Integer, nullable=False)
    updated_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
