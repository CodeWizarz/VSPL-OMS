"""Request bodies for setup planning (docs/setup-planning-architecture.md). Responses are plain dicts."""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class SetupCreate(BaseModel):
    setup_number: str = Field(..., min_length=1, max_length=60)
    setup_date: Optional[date] = None
    remarks: Optional[str] = Field(None, max_length=1000)


class SetupUpdate(BaseModel):
    setup_date: Optional[date] = None
    remarks: Optional[str] = Field(None, max_length=1000)
    status: Optional[str] = Field(None, description="OPEN or CLOSED")


class SetupMapRequest(BaseModel):
    wo_numbers: List[str] = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=3, max_length=500)


class SetupMoveRequest(BaseModel):
    to_setup_number: str = Field(..., min_length=1, max_length=60)
    reason: str = Field(..., min_length=3, max_length=500)


class HeatsUpdate(BaseModel):
    heat_numbers: List[str] = Field(..., max_length=50)
    reason: str = Field(..., min_length=3, max_length=500)


class GateDates(BaseModel):
    stage: str = Field(..., min_length=1, max_length=40)
    planned_start: Optional[date] = None
    planned_end: Optional[date] = None
    clear: bool = Field(False, description="Remove both dates of this gate (not allowed for a finished gate)")


class PlanUpdate(BaseModel):
    gates: List[GateDates] = Field(default_factory=list, max_length=50)
    heat_numbers: Optional[List[str]] = Field(None, max_length=50)
    reason: str = Field(..., min_length=3, max_length=500)
    expected_plan_version: Optional[int] = Field(None, description="The plan_version the editor opened; a newer one means someone else changed the plan")


class ImportApply(BaseModel):
    overwrite_stale: bool = False


class CalendarDayIn(BaseModel):
    kind: str = "HOLIDAY"                    # HOLIDAY / WORKING
    note: Optional[str] = None


class CapacityIn(BaseModel):
    daily_qty: int
    note: Optional[str] = None


class SplitPart(BaseModel):
    setup_number: str
    qty: int


class SplitUpdate(BaseModel):
    parts: List[SplitPart] = []
    reason: str
