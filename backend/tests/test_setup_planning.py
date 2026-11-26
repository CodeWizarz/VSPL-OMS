"""Setup planning (docs/setup-planning-architecture.md): setups, heats, mandatory setup at release,
gate dates, Excel round trip, delay engine, read-only floor facts and access.

Service tests run on an in-memory database with the app's real no-autoflush session setting.
"""
import io
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401
from app.models.audit import AuditLog
from app.models.order import Customer, Order, OrderStatus, Part
from app.models.production_movement import StageWIP
from app.models.setup_planning import PlanImport, PlanImportRow, PlanningSetup, WOHeat
from app.models.user import User, UserRole
from app.models.vendor import VendorDispatch
from app.models.work_order import WORoute, WOStatus, WorkOrder
from app.schemas.operations import WOReleaseCreate
from app.services import plan_delay_service as delay
from app.services import plan_excel_service as excel
from app.services.operations_service import OperationsService
from app.services.setup_planning_service import SetupPlanningService as SP
from app.services.work_queue_service import WorkQueueService

T = date.today()
ROUTE = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]


def d(n):
    return T + timedelta(days=n)


class Env:
    pass


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(settings, "SETUP_PLANNING_ENABLED", True)
    monkeypatch.setattr(settings, "PLANNING_WEEKLY_OFF", "")        # calendar warnings have their own tests
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    e = Env()
    e.db, e.mp = db, monkeypatch
    e.n = 0

    def mk(name, role):
        u = User(full_name=name, email=f"{name}@vspl.test", hashed_password="x", role=role)
        db.add(u)
        return u
    e.ppc = mk("ppc", UserRole.PLANNER)
    e.admin = mk("admin", UserRole.ADMIN)
    e.sup = mk("sup", UserRole.F1_SUPERVISOR)
    e.cust = Customer(name="Cust", customer_code="C1")
    e.part = Part(part_number="P-1", description="Flanged liner")
    db.add_all([e.cust, e.part])
    db.commit()
    yield e
    db.close()


def mkwo(e, number=None, qty=10, stages=None, planned=None, commitment=None, setup=None, wip=None,
         released=True, status=WOStatus.IN_PRODUCTION, heats=None):
    """A work order with a route, planned dates {stage: (start, end)}, WIP {stage: (ent, ok, rej, inproc, onhand)}."""
    e.n += 1
    number = number or f"WO-T{e.n}"
    stages = stages or ROUTE
    order = Order(oar_number=f"OAR-{number}", customer_id=e.cust.id, part_id=e.part.id, customer_po=f"PO-{number}",
                  po_qty=qty, status=OrderStatus.ACCEPT, commitment_date=commitment)
    e.db.add(order)
    e.db.flush()
    wo = WorkOrder(wo_number=number, order_id=order.id, physical_wo_qty=qty, current_stage=stages[0], status=status,
                   release_date=datetime.now() if released else None, setup_id=setup.id if setup else None)
    e.db.add(wo)
    e.db.flush()
    if released:
        for i, s in enumerate(stages, 1):
            ps, pe = (planned or {}).get(s, (None, None))
            e.db.add(WORoute(work_order_id=wo.id, stage=s, sequence=i, stage_target_qty=qty, planned_start=ps, planned_end=pe))
        for s, (ent, ok, rej, inproc, onhand) in (wip or {}).items():
            e.db.add(StageWIP(work_order_id=wo.id, stage=s, ent_qty=ent, ok_qty=ok, rejected_qty=rej, inproc_qty=inproc,
                              onhand_qty=onhand, available_wip=inproc + onhand))
    for h in heats or []:
        e.db.add(WOHeat(work_order_id=wo.id, setup_id=setup.id if setup else None, heat_number=h))
    e.db.commit()
    return wo


def mksetup(e, number="S-1", day=None):
    s = SP.create_setup(e.db, number, day or T, None, e.ppc)
    e.db.commit()
    return s


def refused(code=None, text=None):
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, et, ev, tb):
            assert et is HTTPException, f"expected HTTPException, got {et}: {ev}"
            if code:
                assert ev.status_code == code, ev.detail
            if text:
                assert text.lower() in str(ev.detail).lower(), ev.detail
            return True
    return _Ctx()


def full_plan(start=0):
    """Dates for every gate of ROUTE, one gate per 2 days from `start`."""
    return {s: (d(start + 2 * i), d(start + 2 * i + 1)) for i, s in enumerate(ROUTE)}


# ================================================================================ setups
def test_setup_numbers_are_unique_ignoring_case_and_cleaned(env):
    s = SP.create_setup(env.db, "  S-2026   0142 ", d(0), "first", env.ppc)
    env.db.commit()
    assert s.setup_number == "S-2026 0142"
    with refused(409, "already exists"):
        SP.create_setup(env.db, "s-2026 0142", d(0), None, env.ppc)
    with refused(text="required"):
        SP.create_setup(env.db, "   ", d(0), None, env.ppc)
    with refused(text="too long"):
        SP.create_setup(env.db, "X" * 61, d(0), None, env.ppc)


def test_map_unassigned_work_orders_and_the_refusals(env):
    s1, s2 = mksetup(env, "S-1"), mksetup(env, "S-2")
    free = mkwo(env)
    other = mkwo(env, setup=s2)
    unreleased = mkwo(env, released=False)
    closed = mkwo(env, status=WOStatus.CLOSED)
    out = SP.map_work_orders(env.db, "S-1", [free.wo_number, other.wo_number, unreleased.wo_number, closed.wo_number, "WO-NOPE"], "plan day", env.ppc)
    env.db.commit()
    assert out["mapped"] == [free.wo_number]
    msgs = {x["wo_number"]: x["message"] for x in out["errors"]}
    assert "Use Move" in msgs[other.wo_number] and "Not released" in msgs[unreleased.wo_number]
    assert "Closed" in msgs[closed.wo_number] and "not found" in msgs["WO-NOPE"]
    with refused(text="reason"):
        SP.map_work_orders(env.db, "S-1", [free.wo_number], "", env.ppc)
    s1.status = "CLOSED"
    env.db.commit()
    with refused(409, "closed"):
        SP.map_work_orders(env.db, "S-1", [mkwo(env).wo_number], "x1x", env.ppc)
    assert env.db.query(AuditLog).filter(AuditLog.action == "WO_SETUP_MAPPED").count() == 1


def test_move_between_setups_keeps_heats_and_is_logged(env):
    s1, s2 = mksetup(env, "S-1"), mksetup(env, "S-2")
    wo = mkwo(env, setup=s1, heats=["H-1"])
    SP.move_work_order(env.db, wo.wo_number, "S-2", "re-planned", env.ppc)
    env.db.commit()
    env.db.expire_all()
    assert env.db.query(WorkOrder).filter(WorkOrder.id == wo.id).one().setup_id == s2.id
    assert env.db.query(WOHeat).one().setup_id == s2.id
    with refused(text="already in that setup"):
        SP.move_work_order(env.db, wo.wo_number, "S-2", "again", env.ppc)
    s1.status = "CLOSED"
    env.db.commit()
    with refused(409, "closed"):
        SP.move_work_order(env.db, wo.wo_number, "S-1", "back", env.ppc)


def test_heats_are_cleaned_deduplicated_and_required_for_f1(env):
    s = mksetup(env)
    wo = mkwo(env, setup=s, heats=["H-1"])
    assert SP.set_heats(env.db, wo, ["h-2, H-3;h-2\nH-1", "H-1"], "update", env.ppc) == ["h-2", "H-3", "H-1"]
    env.db.commit()
    assert wo.heat_number == "h-2" and wo.plan_version == 1
    with refused(text="At least one heat"):
        SP.set_heats(env.db, wo, [" , "], "clear", env.ppc)
    no_f1 = mkwo(env, stages=["F2", "FI", "DISPATCH"], setup=s)
    assert SP.set_heats(env.db, no_f1, [], "no heat needed", env.ppc) == []


def test_one_heat_can_serve_several_work_orders_of_a_setup(env):
    s = mksetup(env)
    a, b = mkwo(env, setup=s, heats=["H-9"]), mkwo(env, setup=s, heats=["H-9"])
    assert env.db.query(WOHeat).filter(WOHeat.heat_number == "H-9").count() == 2
    assert SP.setup_detail(env.db, "S-1")["rollup"]["heat_count"] == 1


# ================================================================================ release
def _release(env, wo, **kw):
    return OperationsService.release_work_order(env.db, WOReleaseCreate(
        wo_number=wo.wo_number, physical_wo_qty=10, route_stages=kw.pop("route", ["F1", "F2", "FI"]), **kw), current_user=kw.pop("user", env.ppc) if False else env.ppc)


def test_release_unchanged_when_setup_planning_is_off(env):
    env.mp.setattr(settings, "SETUP_PLANNING_ENABLED", False)
    wo = mkwo(env, released=False)
    r = _release(env, wo)
    assert r.success and r.setup_number is None and wo.setup_id is None


def test_release_requires_a_setup_and_heats_for_f1(env):
    s = mksetup(env, "S-7")
    wo = mkwo(env, released=False)
    with refused(text="setup number is required"):
        _release(env, wo)
    with refused(text="heat number"):
        _release(env, wo, setup_number="S-7")
    r = _release(env, wo, setup_number="s-7", heat_numbers=["H-1", "H-2"])
    env.db.commit()
    assert r.setup_number == "S-7" and wo.setup_id == s.id and wo.heat_number == "H-1"
    assert sorted(h.heat_number for h in env.db.query(WOHeat).all()) == ["H-1", "H-2"]
    assert wo.plan_version >= 1


def test_release_without_f1_needs_no_heat(env):
    mksetup(env, "S-7")
    wo = mkwo(env, released=False)
    r = _release(env, wo, route=["F2", "FI"], setup_number="S-7")
    assert r.setup_number == "S-7"


def test_release_can_create_a_setup_only_for_ppc(env):
    wo = mkwo(env, released=False)
    with refused(text="production day"):
        _release(env, wo, setup_number="S-NEW", heat_numbers=["H-1"])
    r = _release(env, wo, setup_number="S-NEW", new_setup_date=d(1), heat_numbers=["H-1"])
    assert r.setup_number == "S-NEW"
    other = mkwo(env, released=False)
    with pytest.raises(HTTPException) as e:
        OperationsService.release_work_order(env.db, WOReleaseCreate(
            wo_number=other.wo_number, physical_wo_qty=10, route_stages=["F1", "FI"], setup_number="S-FOREIGN",
            new_setup_date=d(1), heat_numbers=["H"]), current_user=env.sup)
    assert e.value.status_code == 403 and "only PPC" in e.value.detail


def test_release_into_a_closed_setup_is_refused_and_leaves_the_work_order_untouched(env):
    s = mksetup(env, "S-C")
    s.status = "CLOSED"
    env.db.commit()
    wo = mkwo(env, released=False)
    with refused(409, "closed"):
        _release(env, wo, setup_number="S-C", heat_numbers=["H"])
    assert wo.release_date is None and wo.setup_id is None


def test_re_release_replaces_the_heat_list(env):
    mksetup(env, "S-7")
    wo = mkwo(env, released=False)
    _release(env, wo, setup_number="S-7", heat_numbers=["H-1"])
    env.db.commit()
    _release(env, wo, setup_number="S-7", heat_numbers=["H-2"])
    env.db.commit()
    assert [h.heat_number for h in env.db.query(WOHeat).all()] == ["H-2"]


# ========================================================================== delay engine
def ev(routes_dates, wips=None, commitment=None, vendor=None, status="in_production", risk=2):
    routes = [type("R", (), {"stage": s, "sequence": i, "planned_start": ps, "planned_end": pe, "plan_source": None})
              for i, (s, (ps, pe)) in enumerate(routes_dates, 1)]
    w = {s: dict(zip(("ent", "ok", "rej", "inproc", "onhand"), v)) for s, v in (wips or {}).items()}
    return delay.evaluate_work_order(routes, w, vendor or {}, commitment, T, risk, status)


def test_delay_states_on_track_at_risk_delayed_no_plan_complete():
    on = ev([("F1", (d(1), d(5))), ("FI", (d(6), d(9)))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(20))
    assert on["status"] == delay.ON_TRACK
    soon = ev([("F1", (d(-1), d(1))), ("FI", (d(2), d(4)))], {}, commitment=d(20))
    assert soon["status"] == delay.AT_RISK
    late = ev([("F1", (d(-5), d(-2))), ("FI", (d(3), d(5)))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(20))
    assert late["status"] == delay.DELAYED and late["late_gate"] == "F1" and late["late_days"] == 2
    assert late["text"].startswith("Delayed · F1 +2 days")
    over = ev([("F1", (d(1), d(5))), ("FI", (d(6), d(12)))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(9))
    assert over["status"] == delay.DELAYED and "commitment" in over["text"]
    passed = ev([("F1", (d(-9), d(-8)))], {"F1": (10, 10, 0, 0, 0)}, commitment=d(-1))
    assert passed["status"] == delay.COMPLETE
    passed2 = ev([("F1", (None, None))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(-1))
    assert passed2["status"] == delay.DELAYED and "Commitment date passed" in passed2["text"]
    later = ev([("F1", (d(1), d(5))), ("FI", (d(6), d(7)))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(-1))
    assert later["status"] == delay.DELAYED and "Plan ends" in later["text"]
    nop = ev([("F1", (d(1), d(5))), ("FI", (None, None))], {"F1": (10, 0, 0, 10, 0)}, commitment=d(20))
    assert nop["status"] == delay.NO_PLAN and nop["missing_dates"] == ["FI"]


def test_finished_gates_are_never_late_and_skipped_gates_are_done():
    r = ev([("F1", (d(-9), d(-8))), ("F2", (d(-7), d(-6))), ("FI", (d(-5), d(-4)))],
           {"F1": (10, 10, 0, 0, 0), "FI": (10, 0, 0, 10, 0)}, commitment=d(30))
    states = {g["stage"]: g["state"] for g in r["gates"]}
    assert states == {"F1": delay.DONE, "F2": delay.DONE, "FI": delay.IN_PROGRESS}      # F2 skipped (vendor straight to FI)
    assert r["late_gate"] == "FI"


def test_pieces_at_a_vendor_keep_the_gate_in_progress_and_late_when_overdue():
    r = ev([("F1", (d(-9), d(-3)))], {"F1": (10, 10, 0, 0, 0)}, vendor={"F1": 4}, commitment=d(30))
    assert r["gates"][0]["state"] == delay.IN_PROGRESS and r["status"] == delay.DELAYED


def test_dispatched_work_order_is_complete():
    r = ev([("F1", (d(-9), d(-8)))], {}, commitment=d(-5), status="dispatched")
    assert r["status"] == delay.COMPLETE


# ====================================================================== gate date edits
def test_update_plan_sets_dates_source_version_and_audit(env):
    s = mksetup(env)
    wo = mkwo(env, setup=s, planned=full_plan(1), commitment=d(30))
    out = SP.update_plan(env.db, wo.wo_number, [{"stage": "F2", "planned_start": d(20), "planned_end": d(22)}], None, "pour moved", 0, env.ppc)
    env.db.commit()
    env.db.expire_all()
    f2 = env.db.query(WORoute).filter(WORoute.work_order_id == wo.id, WORoute.stage == "F2").one()
    assert (f2.planned_start, f2.planned_end, f2.plan_source) == (d(20), d(22), "MANUAL")
    assert out["changed_gates"] == ["F2"] and out["plan_version"] == 1
    assert env.db.query(AuditLog).filter(AuditLog.action == "WO_PLAN_CHANGED").one().details == "pour moved"


def test_update_plan_refusals_and_warnings(env):
    s = mksetup(env)
    wo = mkwo(env, setup=s, planned=full_plan(1), commitment=d(9), wip={"F1": (10, 10, 0, 0, 0)})
    with refused(text="reason"):
        SP.update_plan(env.db, wo.wo_number, [], None, "", None, env.ppc)
    with pytest.raises(HTTPException) as e:
        SP.update_plan(env.db, wo.wo_number, [{"stage": "F2", "planned_start": d(9), "planned_end": d(3)}], None, "bad order", None, env.ppc)
    assert "start date is after" in str(e.value.detail)
    with pytest.raises(HTTPException) as e:
        SP.update_plan(env.db, wo.wo_number, [{"stage": "XX", "planned_end": d(3)}], None, "no gate", None, env.ppc)
    assert "not a gate" in str(e.value.detail)
    with pytest.raises(HTTPException) as e:
        SP.update_plan(env.db, wo.wo_number, [{"stage": "F1", "planned_end": d(7)}], None, "finished", None, env.ppc)
    assert "already finished" in str(e.value.detail)
    out = SP.update_plan(env.db, wo.wo_number, [{"stage": "DISPATCH", "planned_start": d(12), "planned_end": d(14)}], None, "late plan", None, env.ppc)
    assert any("after the commitment date" in w["message"] for w in out["warnings"])


def test_update_plan_detects_a_stale_editor_and_a_closed_setup(env):
    s = mksetup(env)
    wo = mkwo(env, setup=s, planned=full_plan(1))
    SP.update_plan(env.db, wo.wo_number, [{"stage": "F2", "planned_end": d(40)}], None, "first", 0, env.ppc)
    env.db.commit()
    with refused(409, "changed by someone else"):
        SP.update_plan(env.db, wo.wo_number, [{"stage": "F3", "planned_end": d(41)}], None, "second", 0, env.ppc)
    s.status = "CLOSED"
    env.db.commit()
    with refused(409, "closed"):
        SP.update_plan(env.db, wo.wo_number, [{"stage": "F3", "planned_end": d(41)}], None, "third", None, env.ppc)


# ============================================================================== Excel
def _sheet(content):
    return load_workbook(io.BytesIO(content))


def _save(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _setup_with_two(env):
    s = mksetup(env, "S-X")
    a = mkwo(env, "WO-A", setup=s, planned=full_plan(1), commitment=d(40), heats=["H-1"],
             wip={"F1": (10, 0, 0, 10, 0)})
    b = mkwo(env, "WO-B", setup=s, planned=full_plan(2), commitment=d(40), heats=["H-2"],
             stages=["F2", "SP", "FI", "DISPATCH"])
    return s, a, b


def _col(ws, name):
    return [c.value for c in ws[1]].index(name) + 1


def _row(ws, wo):
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, _col(ws, "WO No")).value == wo:
            return r
    raise AssertionError(wo)


def test_export_layout_keys_and_locked_columns(env):
    _setup_with_two(env)
    content, name = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    assert name == "setup-S-X-plan.xlsx" and wb.sheetnames == ["PLAN", "META", "README"]
    assert wb["META"].sheet_state == "hidden"
    ws = wb["PLAN"]
    headers = [c.value for c in ws[1]]
    assert headers[:3] == ["Setup No", "WO No", "OAR"] and "F1 Start" in headers and "DISPATCH End" in headers
    assert ws.cell(_row(ws, "WO-A"), _col(ws, "Heat Numbers")).value == "H-1"
    # WO-B has no F1/F3/PACKING: those cells are empty
    rb = _row(ws, "WO-B")
    assert ws.cell(rb, _col(ws, "F1 End")).value is None and ws.cell(rb, _col(ws, "F2 End")).value is not None
    meta = {r[0]: r[1] for r in wb["META"].iter_rows(values_only=True) if r and r[0]}
    assert meta["template_version"] == "1" and meta["setup_number"] == "S-X" and meta["WO-A"] == 0


def test_round_trip_check_apply_log_and_stale_versions(env):
    s, a, b = _setup_with_two(env)
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ra, rb = _row(ws, "WO-A"), _row(ws, "WO-B")
    ws.cell(ra, _col(ws, "F2 Start")).value = d(30)
    ws.cell(ra, _col(ws, "F2 End")).value = d(31)
    ws.cell(rb, _col(ws, "SP End")).value = "26-12-2030"          # text date, dd-mm-yyyy
    ws.cell(rb, _col(ws, "Heat Numbers")).value = "H-2, H-5"
    out = excel.check_upload(env.db, _save(wb), "plan.xlsx", env.ppc)
    env.db.commit()
    assert out["counts"]["total_wos"] == 2 and out["counts"]["error"] == 0
    assert any(r["wo_number"] == "WO-B" and r["stage"] == "HEATS" and r["new_text"] == "H-2, H-5" for r in out["rows"])
    # nothing changed yet
    env.db.expire_all()
    assert env.db.query(WORoute).filter(WORoute.work_order_id == a.id, WORoute.stage == "F2").one().planned_end != d(31)
    res = excel.apply_import(env.db, out["id"], env.ppc)
    env.db.commit()
    env.db.expire_all()
    f2 = env.db.query(WORoute).filter(WORoute.work_order_id == a.id, WORoute.stage == "F2").one()
    sp = env.db.query(WORoute).filter(WORoute.work_order_id == b.id, WORoute.stage == "SP").one()
    assert (f2.planned_start, f2.planned_end, f2.plan_source) == (d(30), d(31), "EXCEL")
    assert sp.planned_end == date(2030, 12, 26)
    assert res["counts"]["applied"] == 2 and res["status"] == "APPLIED"
    assert sorted(h.heat_number for h in env.db.query(WOHeat).filter(WOHeat.work_order_id == b.id).all()) == ["H-2", "H-5"]
    assert env.db.query(WorkOrder).filter(WorkOrder.id == a.id).one().plan_version == 1
    assert env.db.query(AuditLog).filter(AuditLog.action == "PLAN_IMPORT_APPLIED").count() == 1
    with refused(409, "already applied"):
        excel.apply_import(env.db, out["id"], env.ppc)


def test_checks_errors_for_every_bad_row_and_blank_means_no_change(env):
    s, a, b = _setup_with_two(env)
    other = mksetup(env, "S-Y")
    foreign = mkwo(env, "WO-F", setup=other, planned=full_plan(1))
    done = mkwo(env, "WO-D", setup=s, planned=full_plan(1), wip={"F1": (10, 10, 0, 0, 0)})
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ra, rb, rd = _row(ws, "WO-A"), _row(ws, "WO-B"), _row(ws, "WO-D")
    ws.cell(ra, _col(ws, "F1 End")).value = None                    # blank: no change
    ws.cell(ra, _col(ws, "F2 End")).value = "not a date"            # unreadable
    ws.cell(rb, _col(ws, "F1 End")).value = d(5)                    # gate not on WO-B's route
    ws.cell(rd, _col(ws, "F1 End")).value = d(50)                   # finished gate
    ws.append(["S-X", "WO-NOPE"])                                   # unknown work order
    ws.append(["S-X", "WO-F", None, None, None, None, None, None, None, None, None, d(3), d(4)])   # other setup's WO
    ws.append(["S-X", "WO-A"])                                      # duplicate
    out = excel.check_upload(env.db, _save(wb), "bad.xlsx", env.ppc)
    msgs = {(r["wo_number"], r["stage"]): r["message"] for r in out["rows"] if r["result"] == "ERROR"}
    assert "not a readable date" in msgs[("WO-A", "F2")]
    assert "not a gate" in msgs[("WO-B", "F1")]
    assert "already finished" in msgs[("WO-D", "F1")]
    assert "not found" in msgs[("WO-NOPE", None)]
    assert "not in this setup" in msgs[("WO-F", None)]
    assert any(r["wo_number"] == "WO-A" and "twice" in (r["message"] or "") for r in out["rows"])
    assert not any(r["wo_number"] == "WO-A" and r["stage"] == "F1" for r in out["rows"])     # blank cell ignored


def test_gate_dates_apply_together_or_not_at_all_per_work_order(env):
    s, a, b = _setup_with_two(env)
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ra, rb = _row(ws, "WO-A"), _row(ws, "WO-B")
    ws.cell(ra, _col(ws, "F2 End")).value = d(33)                   # fine
    ws.cell(ra, _col(ws, "F3 End")).value = "garbage"               # bad: whole WO-A is skipped
    ws.cell(rb, _col(ws, "FI End")).value = d(34)                   # fine
    ws.cell(rb, _col(ws, "DISPATCH End")).value = d(36)             # keeps the gate order, so no warning
    out = excel.check_upload(env.db, _save(wb), "mix.xlsx", env.ppc)
    env.db.commit()
    assert (out["counts"]["error"], out["counts"]["ready"]) == (1, 1)
    res = excel.apply_import(env.db, out["id"], env.ppc)
    env.db.commit()
    env.db.expire_all()
    assert res["counts"]["applied"] == 1 and res["counts"]["skipped"] == 1
    assert env.db.query(WORoute).filter(WORoute.work_order_id == a.id, WORoute.stage == "F2").one().planned_end != d(33)
    assert env.db.query(WORoute).filter(WORoute.work_order_id == b.id, WORoute.stage == "FI").one().planned_end == d(34)


def test_sequence_and_commitment_warnings_still_apply(env):
    s, a, b = _setup_with_two(env)
    a.order.commitment_date = d(10)
    env.db.commit()
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ws.cell(_row(ws, "WO-A"), _col(ws, "DISPATCH End")).value = d(60)
    out = excel.check_upload(env.db, _save(wb), "late.xlsx", env.ppc)
    assert out["counts"]["warning"] == 1 and out["counts"]["error"] == 0
    assert any("after the commitment date" in (r["message"] or "") for r in out["rows"])
    res = excel.apply_import(env.db, out["id"], env.ppc)
    assert res["counts"]["applied"] == 1


def test_same_file_twice_unchanged_and_noted(env):
    s, a, b = _setup_with_two(env)
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ws.cell(_row(ws, "WO-A"), _col(ws, "F2 End")).value = d(33)
    data = _save(wb)
    one = excel.check_upload(env.db, data, "p.xlsx", env.ppc)
    excel.apply_import(env.db, one["id"], env.ppc)
    env.db.commit()
    two = excel.check_upload(env.db, data, "p.xlsx", env.ppc)
    assert two["counts"]["unchanged"] == 2 and two["counts"]["ready"] == 0
    assert any("already applied" in n for n in two["notes"])


def test_stale_sheet_is_warned_and_skipped_unless_overwritten(env):
    s, a, b = _setup_with_two(env)
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ws.cell(_row(ws, "WO-A"), _col(ws, "F2 End")).value = d(33)
    data = _save(wb)
    SP.update_plan(env.db, "WO-A", [{"stage": "F3", "planned_end": d(45)}], None, "someone else", 0, env.ppc)
    env.db.commit()
    out = excel.check_upload(env.db, data, "stale.xlsx", env.ppc)
    assert any(r["stage"] == "PLAN" and r["result"] == "WARNING" for r in out["rows"])
    skipped = excel.apply_import(env.db, out["id"], env.ppc)
    assert skipped["counts"]["applied"] == 0 and skipped["skipped"][0]["wo_number"] == "WO-A"
    out2 = excel.check_upload(env.db, data, "stale.xlsx", env.ppc)
    env.db.commit()
    done = excel.apply_import(env.db, out2["id"], env.ppc, overwrite_stale=True)
    assert done["counts"]["applied"] == 1


def test_file_level_rejections(env):
    _setup_with_two(env)
    with refused(text=".xlsx"):
        excel.check_upload(env.db, b"x", "plan.csv", env.ppc)
    with refused(text="not a readable"):
        excel.check_upload(env.db, b"not excel at all", "plan.xlsx", env.ppc)
    with refused(text="too large"):
        excel.check_upload(env.db, b"0" * (excel.MAX_BYTES + 1), "plan.xlsx", env.ppc)
    wb = _sheet(excel.export_setup(env.db, "S-X", env.ppc)[0])
    wb["META"]["B1"] = "9"
    with refused(text="template version"):
        excel.check_upload(env.db, _save(wb), "plan.xlsx", env.ppc)
    wb = _sheet(excel.export_setup(env.db, "S-X", env.ppc)[0])
    with refused(text="not S-OTHER"):
        excel.check_upload(env.db, _save(wb), "plan.xlsx", env.ppc, "S-OTHER")
    del wb["META"]
    with refused(text="not an OMS setup plan"):
        excel.check_upload(env.db, _save(wb), "plan.xlsx", env.ppc)


def test_excel_date_serials_and_formats_are_read():
    assert excel.parse_date_cell(45000)[0] == date(2023, 3, 15)
    assert excel.parse_date_cell(datetime(2026, 11, 26, 9, 0))[0] == date(2026, 11, 26)
    for text in ("26-11-2026", "26/11/2026", "2026-11-26", "26-Nov-2026", "26 Nov 2026", "26.11.2026"):
        assert excel.parse_date_cell(text)[0] == date(2026, 11, 26), text
    assert excel.parse_date_cell("")[0] is None and excel.parse_date_cell(None)[1] is None
    assert excel.parse_date_cell("31-31-2026")[1] and excel.parse_date_cell(5)[1]


def test_undo_restores_unchanged_gates_and_leaves_later_edits(env):
    s, a, b = _setup_with_two(env)
    before = {r.stage: (r.planned_start, r.planned_end) for r in env.db.query(WORoute).filter(WORoute.work_order_id == a.id)}
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ra = _row(ws, "WO-A")
    ws.cell(ra, _col(ws, "F2 End")).value = d(33)
    ws.cell(ra, _col(ws, "F3 End")).value = d(34)
    ws.cell(ra, _col(ws, "Heat Numbers")).value = "H-1, H-8"
    out = excel.check_upload(env.db, _save(wb), "u.xlsx", env.ppc)
    excel.apply_import(env.db, out["id"], env.ppc)
    env.db.commit()
    SP.update_plan(env.db, "WO-A", [{"stage": "F3", "planned_end": d(44)}], None, "edited after", None, env.ppc)
    env.db.commit()
    res = excel.undo_import(env.db, out["id"], env.ppc)
    env.db.commit()
    env.db.expire_all()
    now = {r.stage: (r.planned_start, r.planned_end) for r in env.db.query(WORoute).filter(WORoute.work_order_id == a.id)}
    assert now["F2"] == before["F2"]                                   # restored
    assert now["F3"][1] == d(44)                                       # edited later: left as it is
    assert any("F3 was changed after" in x["message"] for x in res["skipped"])
    assert [h.heat_number for h in env.db.query(WOHeat).filter(WOHeat.work_order_id == a.id).all()] == ["H-1"]
    assert res["status"] == "UNDONE"
    with refused(409):
        excel.undo_import(env.db, out["id"], env.ppc)


def test_discard_and_closed_setup_block_apply(env):
    s, a, b = _setup_with_two(env)
    content, _ = excel.export_setup(env.db, "S-X", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ws.cell(_row(ws, "WO-A"), _col(ws, "F2 End")).value = d(33)
    data = _save(wb)
    one = excel.check_upload(env.db, data, "d.xlsx", env.ppc)
    assert excel.discard_import(env.db, one["id"], env.ppc)["status"] == "DISCARDED"
    with refused(409):
        excel.apply_import(env.db, one["id"], env.ppc)
    two = excel.check_upload(env.db, data, "d.xlsx", env.ppc)
    s.status = "CLOSED"
    env.db.commit()
    with refused(409, "closed"):
        excel.apply_import(env.db, two["id"], env.ppc)


# =========================================================================== boards
def test_setup_list_rollups_detail_order_and_unassigned(env):
    s = mksetup(env, "S-L")
    ok = mkwo(env, "WO-OK", setup=s, planned=full_plan(2), commitment=d(60), heats=["H-1"], wip={"F1": (10, 0, 0, 10, 0)})
    late = mkwo(env, "WO-LATE", setup=s, planned={**full_plan(2), "F1": (d(-6), d(-2))}, commitment=d(60), heats=["H-1", "H-2"], wip={"F1": (10, 0, 0, 10, 0)})
    nop = mkwo(env, "WO-NOPLAN", setup=s, commitment=d(60))
    mkwo(env, "WO-FREE", commitment=d(5))
    mkwo(env, "WO-DONE", setup=s, status=WOStatus.DISPATCHED)
    lst = SP.list_setups(env.db)
    row = next(x for x in lst if x["setup_number"] == "S-L")
    assert (row["wo_count"], row["delayed"], row["no_plan"], row["heat_count"], row["total_qty"]) == (3, 1, 1, 2, 30)
    assert row["gates_dated"] < row["gates_total"]
    det = SP.setup_detail(env.db, "S-L")
    assert [r["wo_number"] for r in det["work_orders"]][0] == "WO-LATE"            # delayed first
    assert det["gate_columns"] == ROUTE and det["finished_work_orders"] == 1
    assert [r["wo_number"] for r in SP.unassigned(env.db)] == ["WO-FREE"]
    board = SP.delay_board(env.db)
    assert [r["wo_number"] for r in board["work_orders"]][:1] == ["WO-LATE"]
    assert all(r["plan_status"] in ("DELAYED", "AT_RISK") for r in board["work_orders"])
    only = SP.delay_board(env.db, "S-L", ["NO_PLAN"])
    assert [r["wo_number"] for r in only["work_orders"]] == ["WO-NOPLAN"]


def test_plan_info_for_the_floor_and_switch_off(env):
    s = mksetup(env, "S-F")
    mkwo(env, "WO-I", setup=s, planned=full_plan(1), commitment=d(30), heats=["H-5"], wip={"F2": (10, 0, 0, 10, 0)})
    info = SP.plan_info(env.db, "WO-I", "F2")
    assert info["enabled"] and info["setup_number"] == "S-F" and info["heat_numbers"] == ["H-5"]
    assert info["this_gate"]["stage"] == "F2" and info["next_gate"]["stage"] == "F3" and info["days_to_commitment"] == 30
    env.mp.setattr(settings, "SETUP_PLANNING_ENABLED", False)
    assert SP.plan_info(env.db, "WO-I", "F2") == {"enabled": False}


def test_work_queue_shows_setup_heats_commitment_and_state_only_when_on(env):
    s = mksetup(env, "S-Q")
    mkwo(env, "WO-Q", setup=s, planned=full_plan(1), commitment=d(30), heats=["H-7"], wip={"F1": (10, 0, 0, 10, 0)})
    item = WorkQueueService.get_stage_queue(env.db, "F1")["items"][0]
    assert item["setup_number"] == "S-Q" and item["heat_numbers"] == ["H-7"] and item["plan_status"] in ("ON_TRACK", "AT_RISK")
    env.mp.setattr(settings, "SETUP_PLANNING_ENABLED", False)
    assert "setup_number" not in WorkQueueService.get_stage_queue(env.db, "F1")["items"][0]


def test_existing_stage_plan_edit_bumps_the_plan_version(env):
    from fastapi.testclient import TestClient  # noqa: F401  (documented: the API path is covered in the API tests below)
    s = mksetup(env, "S-V")
    wo = mkwo(env, "WO-V", setup=s, planned=full_plan(1))
    from app.services.operations_service import OperationsService as OS
    from app.schemas.operations import WOEditRequest, StagePlanEdit
    OS.edit_work_order(env.db, "WO-V", WOEditRequest(stage_plan=[StagePlanEdit(stage="F2", planned_end=d(44))], reason="manager edit"), current_user=env.ppc)
    env.db.expire_all()
    assert env.db.query(WorkOrder).filter(WorkOrder.id == wo.id).one().plan_version == 1
    assert env.db.query(WORoute).filter(WORoute.work_order_id == wo.id, WORoute.stage == "F2").one().plan_source == "MANUAL"


# ------------------------------------------------------------------ phase 5: clear a date
def test_clear_a_gate_date_on_screen_logs_and_bumps_version(env):
    s, a, b = _setup_with_two(env)
    before = env.db.query(WORoute).filter(WORoute.work_order_id == b.id, WORoute.stage == "SP").one().planned_end
    assert before is not None
    res = SP.update_plan(env.db, "WO-B", [{"stage": "SP", "clear": True}], None, "not needed yet", 0, env.ppc)
    env.db.commit()
    env.db.expire_all()
    r = env.db.query(WORoute).filter(WORoute.work_order_id == b.id, WORoute.stage == "SP").one()
    assert r.planned_start is None and r.planned_end is None
    assert res["plan_version"] == 1 and "SP" in res["changed_gates"]
    assert env.db.query(WorkOrder).filter(WorkOrder.id == b.id).one().plan_version == 1


def test_clear_refused_for_finished_gate_and_for_change_plus_clear(env):
    s, a, b = _setup_with_two(env)
    mkwo(env, "WO-D", setup=s, planned=full_plan(3), wip={"F1": (10, 10, 0, 0, 0)})
    with refused(400):
        SP.update_plan(env.db, "WO-D", [{"stage": "F1", "clear": True}], None, "try", 0, env.ppc)
    with refused(400):
        SP.update_plan(env.db, "WO-B", [{"stage": "SP", "clear": True}, {"stage": "SP", "planned_end": d(30)}],
                       None, "both", 0, env.ppc)
    env.db.rollback()
    env.db.expire_all()
    sp = env.db.query(WORoute).filter(WORoute.work_order_id == b.id, WORoute.stage == "SP").one()
    assert sp.planned_end is not None


# ------------------------------------------------------------------ phase 5: multi-setup sheet
def _two_setups(env):
    s1, a, b = _setup_with_two(env)
    s2 = mksetup(env, "S-Y", d(1))
    c = mkwo(env, "WO-C", setup=s2, planned=full_plan(3), commitment=d(40), heats=["H-9"])
    return s1, s2, a, b, c


def test_multi_export_has_all_open_setups_and_skips_closed(env):
    s1, s2, a, b, c = _two_setups(env)
    s3 = mksetup(env, "S-Z", d(2))
    mkwo(env, "WO-Z", setup=s3, planned=full_plan(1))
    s3.status = "CLOSED"
    env.db.commit()
    content, name = excel.export_setups(env.db, "OPEN", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    sheet_wos = {ws.cell(r, _col(ws, "WO No")).value: ws.cell(r, _col(ws, "Setup No")).value for r in range(2, ws.max_row + 1)}
    assert sheet_wos["WO-A"] == "S-X" and sheet_wos["WO-C"] == "S-Y"
    meta = {r[0]: r[1] for r in wb["META"].iter_rows(values_only=True) if r and r[0]}
    assert meta["setup_number"] == "*" and name.endswith(".xlsx")


def test_multi_upload_applies_across_setups_and_undo(env):
    s1, s2, a, b, c = _two_setups(env)
    content, _ = excel.export_setups(env.db, "ALL", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ws.cell(_row(ws, "WO-A"), _col(ws, "F2 End")).value = d(33)
    ws.cell(_row(ws, "WO-C"), _col(ws, "F2 End")).value = d(34)
    out = excel.check_upload(env.db, _save(wb), "multi.xlsx", env.ppc)
    env.db.commit()
    assert out["setup_number"] == "*" and out["counts"]["error"] == 0
    res = excel.apply_import(env.db, out["id"], env.ppc)
    env.db.commit()
    env.db.expire_all()
    assert res["counts"]["applied"] == 2
    for wo, dt in ((a, d(33)), (c, d(34))):
        assert env.db.query(WORoute).filter(WORoute.work_order_id == wo.id, WORoute.stage == "F2").one().planned_end == dt
    excel.undo_import(env.db, out["id"], env.ppc)
    env.db.commit()
    env.db.expire_all()
    assert env.db.query(WORoute).filter(WORoute.work_order_id == c.id, WORoute.stage == "F2").one().planned_end != d(34)


def test_multi_upload_rejects_mismatching_setup_no_and_closed_setup(env):
    s1, s2, a, b, c = _two_setups(env)
    content, _ = excel.export_setups(env.db, "OPEN", env.ppc)
    wb = _sheet(content)
    ws = wb["PLAN"]
    ra, rc = _row(ws, "WO-A"), _row(ws, "WO-C")
    ws.cell(ra, _col(ws, "Setup No")).value = "S-Y"                  # wrong setup for WO-A
    ws.cell(ra, _col(ws, "F2 End")).value = d(33)
    ws.cell(rc, _col(ws, "F2 End")).value = d(34)
    data = _save(wb)
    s2.status = "CLOSED"
    env.db.commit()
    out = excel.check_upload(env.db, data, "m.xlsx", env.ppc)
    msgs = {r["wo_number"]: r["message"] for r in out["rows"] if r["result"] == "ERROR"}
    assert "says setup S-Y" in msgs["WO-A"]
    assert "closed" in msgs["WO-C"]


def test_multi_sheet_refused_when_uploaded_into_a_single_setup(env):
    _two_setups(env)
    content, _ = excel.export_setups(env.db, "OPEN", env.ppc)
    with refused(400, "several setups"):
        excel.check_upload(env.db, content, "m.xlsx", env.ppc, setup_number_hint="S-X")


# ------------------------------------------------------------------ phase 5: digest
def test_digest_lists_delayed_and_at_risk_and_send_without_smtp(env):
    s = mksetup(env, "S-D")
    mkwo(env, "WO-LATE", setup=s, planned=full_plan(-5), commitment=d(40), wip={"F1": (10, 0, 0, 10, 0)})
    mkwo(env, "WO-OK", setup=s, planned=full_plan(20), commitment=d(60))
    dg = SP.delay_digest(env.db)
    assert dg["counts"]["delayed"] >= 1
    assert "WO-LATE" in [r["wo_number"] for r in dg["delayed"]]
    assert "WO-OK" not in [r["wo_number"] for r in dg["delayed"] + dg["at_risk"]]
    env.mp.setenv("SMTP_PASSWORD", "")
    env.mp.setenv("GMAIL_APP_PASSWORD", "")
    sent = SP.send_digest(env.db, env.ppc)
    env.db.commit()
    assert sent["email_sent"] is False and "ppc@vspl.test" in sent["recipients"]
    assert env.db.query(AuditLog).filter(AuditLog.action == "PLAN_DIGEST_SENT").count() == 1
