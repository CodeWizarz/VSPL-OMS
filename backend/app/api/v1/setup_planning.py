"""Setup planning and scheduling API (docs/setup-planning-architecture.md).

Everything except /config and /wo/{wo}/plan-info is PPC / admin only (and only while the switch
SETUP_PLANNING_ENABLED is on). Plan-info is read-only and open to every signed-in role: it is what
the shop floor sees next to a work order.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status as http_status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.core.roles import PPC_PLANNING_ROLES
from app.models.user import User
from app.schemas.setup_planning import (
    HeatsUpdate, ImportApply, PlanUpdate, SetupCreate, SetupMapRequest, SetupMoveRequest, SetupUpdate,
)
from app.services import plan_excel_service as excel
from app.services.setup_planning_service import SetupPlanningService, find_wo, require_enabled

router = APIRouter(prefix="/api/v1/planning", tags=["setup-planning"])

_ppc = require_roles(*PPC_PLANNING_ROLES)


def _ppc_enabled(user: User = Depends(_ppc)) -> User:
    require_enabled()
    return user


@router.get("/config")
def planning_config(user: User = Depends(get_current_user)):
    """Whether setup planning is switched on (the screens use this to show the menu and the release fields)."""
    return {"setup_planning_enabled": bool(settings.SETUP_PLANNING_ENABLED), "at_risk_days": settings.SETUP_PLANNING_AT_RISK_DAYS}


@router.get("/wo/{wo_number}/plan-info")
def plan_info(wo_number: str, stage: Optional[str] = Query(None), db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Plan facts for one work order (setup, heats, commitment, gate dates and state). Read-only, any signed-in role."""
    return SetupPlanningService.plan_info(db, wo_number, stage)


# ---------------------------------------------------------------------------- setups
@router.get("/setups")
def list_setups(status: Optional[str] = Query(None), db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return SetupPlanningService.list_setups(db, status)


@router.post("/setups")
def create_setup(payload: SetupCreate, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    s = SetupPlanningService.create_setup(db, payload.setup_number, payload.setup_date, payload.remarks, user)
    db.commit()
    return SetupPlanningService.setup_detail(db, s.setup_number)


@router.get("/setups/{setup_number}")
def setup_detail(setup_number: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return SetupPlanningService.setup_detail(db, setup_number)


@router.patch("/setups/{setup_number}")
def update_setup(setup_number: str, payload: SetupUpdate, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    s = SetupPlanningService.update_setup(db, setup_number, payload.setup_date, payload.remarks, payload.status, user,
                                          date_given="setup_date" in payload.model_fields_set)
    db.commit()
    return SetupPlanningService.setup_detail(db, s.setup_number)


@router.post("/setups/{setup_number}/work-orders")
def map_work_orders(setup_number: str, payload: SetupMapRequest, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = SetupPlanningService.map_work_orders(db, setup_number, payload.wo_numbers, payload.reason, user)
    db.commit()
    return out


@router.post("/work-orders/{wo_number}/move")
def move_work_order(wo_number: str, payload: SetupMoveRequest, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = SetupPlanningService.move_work_order(db, wo_number, payload.to_setup_number, payload.reason, user)
    db.commit()
    return out


@router.put("/work-orders/{wo_number}/heats")
def set_heats(wo_number: str, payload: HeatsUpdate, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    wo = find_wo(db, wo_number, lock=True)
    heats = SetupPlanningService.set_heats(db, wo, payload.heat_numbers, payload.reason, user)
    db.commit()
    return {"wo_number": wo.wo_number, "heat_numbers": heats, "plan_version": wo.plan_version or 0}


@router.patch("/work-orders/{wo_number}/plan")
def update_plan(wo_number: str, payload: PlanUpdate, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = SetupPlanningService.update_plan(
        db, wo_number, [g.model_dump() for g in payload.gates], payload.heat_numbers, payload.reason,
        payload.expected_plan_version, user)
    db.commit()
    return out


@router.get("/unassigned")
def unassigned(db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return {"work_orders": SetupPlanningService.unassigned(db)}


@router.get("/delays")
def delays(setup: Optional[str] = Query(None), status: Optional[str] = Query(None, description="Comma separated: DELAYED,AT_RISK,NO_PLAN"),
           db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    statuses = [s.strip() for s in status.split(",")] if status else None
    return SetupPlanningService.delay_board(db, setup, statuses)


# ---------------------------------------------------------------------------- digest
@router.get("/digest")
def digest_preview(db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    """The delayed / at-risk list PPC gets every morning (preview; sends nothing)."""
    return SetupPlanningService.delay_digest(db)


@router.post("/digest/send")
def digest_send(db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = SetupPlanningService.send_digest(db, user)
    db.commit()
    return out


@router.post("/digest/run")
def digest_run(x_planning_digest_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """For a scheduler: sends the digest when the shared token matches PLANNING_DIGEST_TOKEN (off when it is empty)."""
    import hmac

    require_enabled()
    token = settings.PLANNING_DIGEST_TOKEN
    if not token or not x_planning_digest_token or not hmac.compare_digest(token, x_planning_digest_token):
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Not authorised.")
    out = SetupPlanningService.send_digest(db, None)
    db.commit()
    return {"counts": out["counts"], "email_sent": out["email_sent"], "recipients": len(out["recipients"])}


# ----------------------------------------------------------------------------- Excel
@router.get("/setups/{setup_number}/export.xlsx")
def export_setup(setup_number: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    content, name = excel.export_setup(db, setup_number, user)
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export-all.xlsx")
def export_all(status: Optional[str] = Query("OPEN", description="OPEN, CLOSED or ALL"),
               db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    """One sheet for the work orders of several setups (default: all open setups)."""
    content, name = excel.export_setups(db, status, user)
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/imports")
async def upload_import(file: UploadFile = File(...), setup_number: Optional[str] = Form(None),
                        db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    """Check an uploaded sheet. Saves the result for review; changes nothing on any work order."""
    content = await file.read()
    out = excel.check_upload(db, content, file.filename or "", user, setup_number)
    db.commit()
    return out


@router.get("/imports/{import_id}")
def get_import(import_id: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return excel.import_to_dict(db, excel.get_import(db, import_id))


@router.post("/imports/{import_id}/apply")
def apply_import(import_id: str, payload: ImportApply, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = excel.apply_import(db, import_id, user, payload.overwrite_stale)
    db.commit()
    return out


@router.delete("/imports/{import_id}")
def discard_import(import_id: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = excel.discard_import(db, import_id, user)
    db.commit()
    return out


@router.post("/imports/{import_id}/undo")
def undo_import(import_id: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = excel.undo_import(db, import_id, user)
    db.commit()
    return out


# ----------------------------------------------------------------------------- calendar, capacity, splits
from datetime import date as _date, timedelta as _td  # noqa: E402

from app.schemas.setup_planning import CalendarDayIn, CapacityIn, SplitUpdate  # noqa: E402
from app.services import planning_extras_service as extras  # noqa: E402


@router.get("/calendar")
def calendar_list(start: Optional[_date] = None, end: Optional[_date] = None,
                  db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    s = start or _date.today().replace(day=1)
    return extras.list_calendar(db, s, end or s + _td(days=400))


@router.put("/calendar/{day}")
def calendar_set(day: _date, body: CalendarDayIn, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = extras.set_calendar_day(db, day, body.kind, body.note, user)
    db.commit()
    return out


@router.delete("/calendar/{day}")
def calendar_delete(day: _date, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = extras.delete_calendar_day(db, day, user)
    db.commit()
    return out


@router.get("/capacity")
def capacity_list(db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return extras.list_capacity(db)


@router.put("/capacity/{stage}")
def capacity_set(stage: str, body: CapacityIn, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = extras.set_capacity(db, stage, body.daily_qty, body.note, user)
    db.commit()
    return out


@router.delete("/capacity/{stage}")
def capacity_delete(stage: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = extras.delete_capacity(db, stage, user)
    db.commit()
    return out


@router.get("/capacity-view")
def capacity_view(start: Optional[_date] = None, days: int = 14,
                  db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return extras.capacity_view(db, start or _date.today(), days)


@router.get("/work-orders/{wo_number}/splits")
def splits_get(wo_number: str, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    return extras.get_splits(db, wo_number)


@router.put("/work-orders/{wo_number}/splits")
def splits_set(wo_number: str, body: SplitUpdate, db: Session = Depends(get_db), user: User = Depends(_ppc_enabled)):
    out = extras.set_splits(db, wo_number, [p.model_dump() for p in body.parts], body.reason, user)
    db.commit()
    return out
