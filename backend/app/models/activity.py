"""Activity log: one row per data-changing API request (create / edit / delete), with who
did it. Written by app.core.activity_log.ActivityLogMiddleware; read by Admin."""
import uuid

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base, GUID


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id = Column(String, nullable=True, index=True)
    user_name = Column(String, nullable=True)
    user_email = Column(String, nullable=True, index=True)
    user_role = Column(String, nullable=True)
    action = Column(String, nullable=False)        # Create / Update / Delete
    method = Column(String, nullable=False)
    path = Column(String, nullable=False, index=True)
    area = Column(String, nullable=True)           # e.g. "production", "work-orders"
    target = Column(String, nullable=True)         # identifying record(s), e.g. "WO-1001 · F2"
    details = Column(String, nullable=True)        # short key fields from the request (no secrets)
    status_code = Column(Integer, nullable=True)
    outcome = Column(String, nullable=True)        # Success / Refused / Failed
    client_ip = Column(String, nullable=True)
