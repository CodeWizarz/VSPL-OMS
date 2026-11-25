"""Vendor trips (docs/vendor-trips-architecture.md): pieces that leave a gate for a vendor and
come back are counted exactly once, in any order, at any gate.

The rule checked after EVERY step:
    WO quantity = unprocessed + completed (all gates) + rejected + at vendor + vendor scrap
and the reconciliation report balances. A vendor trip moves pieces; only an in-house production
entry or SCM's "gate work done" ever adds to a gate's good count.

Edge cases covered here are listed in docs/vendor-trips-architecture.md section 10 (numbers in
the test docstrings). Cases 5, 15, 16, 17, 18 belong to the DC software link, which is on hold.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401  registers every table
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.vendor import VendorDispatch, VendorTripReturn
from app.models.mrb import MRBReview
from app.models.rejection_type import RejectionType
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.services.production_service import ProductionService
from app.services.vendor_service import VendorService
from app.services.vendor_trip_service import VendorTripService
from app.services.mrb_service import MRBService
from app.services.oms_integration_service import OMSIntegrationService

ROUTE = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
QTY = 10
WO_NO = "WO-TRIP-1"


class Env:
    pass


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(settings, "VENDOR_TRIPS_ENABLED", True)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    e = Env()
    e.db = db
    e.mp = monkeypatch

    def mk(name, role):
        u = User(full_name=name, email=f"{name}@vspl.test", hashed_password="x", role=role)
        db.add(u)
        return u
    e.admin = mk("admin", UserRole.ADMIN)
    e.scm = mk("scm", UserRole.SP_MANAGER)
    e.f1sup = mk("f1sup", UserRole.F1_SUPERVISOR)
    e.f2sup = mk("f2sup", UserRole.F2_SUPERVISOR)
    e.op = mk("op", UserRole.OPERATOR)
    db.add(RejectionType(code="DEF-POROSITY", name="Porosity", is_active=True))
    cust = Customer(name="Customer", customer_code="TRIP")
    part = Part(part_number="P-TRIP")
    db.add_all([cust, part])
    db.flush()
    order = Order(customer_id=cust.id, part_id=part.id, customer_po="PO-TRIP", po_qty=QTY, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    e.wo = WorkOrder(wo_number=WO_NO, order_id=order.id, physical_wo_qty=QTY, current_stage="F1")
    db.add(e.wo)
    db.flush()
    for i, stage in enumerate(ROUTE, 1):
        db.add(WORoute(work_order_id=e.wo.id, stage=stage, sequence=i, stage_target_qty=QTY))
    db.add(StageWIP(work_order_id=e.wo.id, stage="F1", ent_qty=QTY, ok_qty=0, inproc_qty=QTY,
                    onhand_qty=0, rejected_qty=0, available_wip=QTY))
    db.commit()
    yield e
    db.close()


# ------------------------------------------------------------------------------- helpers
def entry(e, stage, good, rej=0, user=None, remarks=None, vendor=False):
    return ProductionService.record_stage_production(e.db, RecordStageProductionRequest(
        wo_number=WO_NO, stage=stage, good_qty=good, rejected_quantity=rej, remarks=remarks,
        production_type="VENDOR" if vendor else "IN_HOUSE",
        vendor_name="Vendor A" if vendor else None, dc_number="LEG-1" if vendor else None,
        defect_code="DEF-POROSITY" if rej else None), current_user=user or e.admin)


def send(e, stage, qty, dc, source=None, user=None, vendor="Vendor A", process=None):
    return VendorTripService.send(e.db, WO_NO, stage, qty, vendor, dc, source_state=source,
                                  process_name=process, current_user=user or e.admin)


def trip(e, dc):
    e.db.expire_all()
    return e.db.query(VendorDispatch).filter(VendorDispatch.dc_number == dc).one()


def ret(e, dc, good=0, scrap=0, user=None, dest=None):
    return VendorTripService.record_return(e.db, str(trip(e, dc).id), good, scrap,
                                           current_user=user or e.scm, destination_stage=dest)


def approve(e, stage):
    MRBService.approve_stage_reviews(e.db, WO_NO, stage, current_user=e.admin)


def move(e, frm, to, qty):
    return ProductionService.move_parts(e.db, MovePartsRequest(
        wo_number=WO_NO, from_stage=frm, to_stage=to, quantity_moved=qty), current_user=e.admin)


def wip(e, stage):
    e.db.expire_all()
    return e.db.query(StageWIP).filter(StageWIP.work_order_id == e.wo.id, StageWIP.stage == stage).one()


def wo_qty(e):
    e.db.expire_all()
    return e.db.query(WorkOrder).filter(WorkOrder.id == e.wo.id).one().physical_wo_qty


def counted_once(e):
    e.db.expire_all()
    wips = e.db.query(StageWIP).filter(StageWIP.work_order_id == e.wo.id).all()
    disps = e.db.query(VendorDispatch).filter(VendorDispatch.work_order_id == e.wo.id).all()
    at_vendor = sum(max(d.dispatched_qty - (d.received_qty or 0) - (d.scrap_qty or 0), 0)
                    for d in disps if d.status in ("AT_VENDOR", "PARTIALLY_RECEIVED"))
    vendor_scrap = sum(d.scrap_qty or 0 for d in disps)
    live = sum((w.inproc_qty or 0) + (w.onhand_qty or 0) for w in wips)
    rejected = sum(w.rejected_qty or 0 for w in wips)
    wo_now = e.db.query(WorkOrder).filter(WorkOrder.id == e.wo.id).one()
    assert live + rejected + at_vendor + vendor_scrap == wo_now.physical_wo_qty == QTY
    rec = OMSIntegrationService.reconcile_work_order(e.db, wo_now)
    assert rec.is_balanced, rec.details


def gate(e, stage):
    return VendorTripService.gate_state(e.db, WO_NO, stage)


def refused(code=None, text=None):
    class _Ctx:
        def __enter__(self):
            return self
        def __exit__(self, et, ev, tb):
            assert et is HTTPException, f"expected HTTPException, got {et}"
            if code:
                assert ev.status_code == code, ev.detail
            if text:
                assert text.lower() in str(ev.detail).lower(), ev.detail
            return True
    return _Ctx()


# ============================================================ the orders of work (any order)
def test_vendor_first_then_in_house(env):
    """F1 vendor first, then in-house: 10 out unprocessed -> back for more work -> entry 10."""
    e = env
    send(e, "F1", 10, "DC-1")
    f1 = wip(e, "F1")
    assert (f1.ok_qty, f1.inproc_qty, f1.onhand_qty) == (0, 0, 0)       # nothing produced, none in stock
    counted_once(e)
    ret(e, "DC-1", good=10)
    assert (wip(e, "F1").inproc_qty, wip(e, "F1").ok_qty) == (10, 0)   # back to unprocessed, not counted
    entry(e, "F1", 10)
    assert (wip(e, "F1").ok_qty, wip(e, "F1").onhand_qty) == (10, 10)  # counted once
    approve(e, "F1")
    move(e, "F1", "F2", 10)
    assert wip(e, "F2").ent_qty == 10 and wo_qty(e) == 10
    counted_once(e)


def test_in_house_first_then_vendor(env):
    """F2 in-house first, then vendor: entry 10 -> send completed -> back; not counted twice."""
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 10, "DC-1")                                           # source resolved to COMPLETED
    assert trip(e, "DC-1").source_state == "COMPLETED"
    f1 = wip(e, "F1")
    assert (f1.ok_qty, f1.onhand_qty) == (10, 0)
    counted_once(e)
    ret(e, "DC-1", good=10)
    f1 = wip(e, "F1")
    assert (f1.ok_qty, f1.onhand_qty) == (10, 10)
    move(e, "F1", "F2", 10)                                              # earlier MRB approval still covers them
    assert wip(e, "F2").ent_qty == 10
    counted_once(e)


def test_vendor_does_the_gates_last_process(env):
    """Vendor does F1's whole job and SCM receives the pieces at F2: counted once at F1, no MRB."""
    e = env
    send(e, "F1", 10, "DC-1", process="Machining")
    r = ret(e, "DC-1", good=10, dest="F2")
    assert "landed at F2" in r["message"]
    f1, f2 = wip(e, "F1"), wip(e, "F2")
    assert (f1.ok_qty, f1.inproc_qty, f1.onhand_qty) == (10, 0, 0)
    assert (f2.ent_qty, f2.inproc_qty) == (10, 10)
    t = e.db.query(MRBReview).one()
    assert t.status == "APPROVED" and t.disposition == "VENDOR_RETURN_DIRECT"   # nothing waiting for review
    counted_once(e)
    entry(e, "F2", 10)
    counted_once(e)


def test_vendor_then_in_house_then_vendor_again(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=10)
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 10, "DC-2", process="Plating")
    counted_once(e)
    ret(e, "DC-2", good=10)
    assert (wip(e, "F1").ok_qty, wip(e, "F1").onhand_qty) == (10, 10)
    counted_once(e)


def test_split_part_vendor_part_in_house(env):
    e = env
    send(e, "F1", 6, "DC-1")
    assert wip(e, "F1").inproc_qty == 4
    entry(e, "F1", 4)
    counted_once(e)
    ret(e, "DC-1", good=6)
    entry(e, "F1", 6)
    assert wip(e, "F1").ok_qty == 10
    counted_once(e)


def test_two_vendors_unprocessed_and_completed_at_the_same_gate(env):
    e = env
    entry(e, "F1", 4)                                                    # 4 completed, 6 unprocessed
    with refused(text="Choose which"):
        send(e, "F1", 2, "DC-X")                                         # 4: both states -> must choose
    send(e, "F1", 6, "DC-A", source="UNPROCESSED", vendor="Vendor A")
    send(e, "F1", 4, "DC-B", source="COMPLETED", vendor="Vendor B")
    g = gate(e, "F1")
    assert (g["unprocessed_qty"], g["completed_qty"], g["at_vendor_from_unprocessed_qty"], g["at_vendor_from_completed_qty"]) == (0, 0, 6, 4)
    counted_once(e)
    ret(e, "DC-B", good=4)
    ret(e, "DC-A", good=6)                                               # back to F1 for more work
    assert wip(e, "F1").inproc_qty == 6
    entry(e, "F1", 6)
    assert (wip(e, "F1").ok_qty, wip(e, "F1").onhand_qty) == (10, 10)
    counted_once(e)


# ======================================================================== scrap at the vendor
def test_scrap_on_a_trip_that_left_unprocessed(env):
    """8 good (more work) + 2 scrap: 8 left to process, the 2 are vendor scrap, total 10."""
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=8, scrap=2)
    f1 = wip(e, "F1")
    assert (f1.inproc_qty, f1.rejected_qty, f1.ok_qty) == (8, 0, 0)
    counted_once(e)
    entry(e, "F1", 8)
    counted_once(e)
    with refused():
        entry(e, "F1", 1)                                                # only 8 existed


def test_scrap_on_a_trip_that_left_completed_reduces_movable(env):
    """14: approved, sent, 8 back + 2 scrap: 8 movable and still covered by the earlier approval."""
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=8, scrap=2)
    assert wip(e, "F1").onhand_qty == 8
    counted_once(e)
    assert ProductionService.get_stage_dashboard(e.db, WO_NO, "F1").mrb_approved_movable_qty == 8
    move(e, "F1", "F2", 8)
    assert wip(e, "F2").ent_qty == 8
    counted_once(e)


def test_scrap_only_return_needs_no_decision(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", scrap=10)
    assert trip(e, "DC-1").status == "RECEIVED"
    f1 = wip(e, "F1")
    assert (f1.inproc_qty, f1.onhand_qty) == (0, 0)
    counted_once(e)


# ==================================================================== sending: validation
def test_send_more_than_available_refused_with_numbers(env):
    """1"""
    e = env
    with refused(text="No pieces"):
        send(e, "F2", 1, "DC-0")                                         # nothing at F2 yet
    entry(e, "F1", 6)                                                    # 6 completed, 4 unprocessed
    with refused(text="Available: 4 unprocessed, 6 completed"):
        send(e, "F1", 7, "DC-1", source="COMPLETED")
    with refused(text="Available: 4 unprocessed, 6 completed"):
        send(e, "F1", 5, "DC-1", source="UNPROCESSED")
    assert e.db.query(VendorDispatch).count() == 0
    counted_once(e)


def test_same_pieces_cannot_be_sent_twice(env):
    """2"""
    e = env
    send(e, "F1", 10, "DC-1")
    with refused(text="already at a vendor"):
        send(e, "F1", 1, "DC-2")
    assert e.db.query(VendorDispatch).count() == 1
    counted_once(e)


def test_same_dc_twice_is_one_trip(env):
    """3: double click or re-entry; case does not matter; a cancelled DC can be reused."""
    e = env
    send(e, "F1", 4, "DC-1")
    with refused(409, "One DC is one trip"):
        send(e, "F1", 4, "DC-1")
    with refused(409):
        send(e, "F1", 2, "dc-1")
    assert e.db.query(VendorDispatch).count() == 1
    VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), "wrong DC", current_user=e.scm)
    send(e, "F1", 4, "DC-1")                                             # reusable after cancel
    counted_once(e)


def test_unknown_gate_wo_and_blocked_gates(env):
    e = env
    with refused(text="not part of the route"):
        send(e, "F9", 1, "DC-1")
    with refused(404):
        VendorTripService.send(e.db, "WO-NOPE", "F1", 1, "V", "DC-1", current_user=e.admin)
    with refused(text="cannot be sent"):
        send(e, "PACKING", 1, "DC-1")
    with refused(text="cannot be sent"):
        send(e, "DISPATCH", 1, "DC-1")


def test_closed_work_order_cannot_send(env):
    """22"""
    e = env
    e.db.query(WorkOrder).filter(WorkOrder.id == e.wo.id).one().status = WOStatus.CLOSED
    e.db.commit()
    with refused(text="completely dispatched"):
        send(e, "F1", 1, "DC-1")


def test_required_fields(env):
    e = env
    with refused(text="required"):
        VendorTripService.send(e.db, WO_NO, "F1", 5, "  ", "DC-1", current_user=e.admin)
    with refused(text="required"):
        VendorTripService.send(e.db, WO_NO, "F1", 5, "V", " ", current_user=e.admin)
    with refused(text="greater than zero"):
        send(e, "F1", 0, "DC-1")
    with refused(text="UNPROCESSED or COMPLETED"):
        send(e, "F1", 1, "DC-1", source="BOGUS")


# ============================================================ in-house work while pieces are out
def test_entry_while_some_pieces_are_out(env):
    """9: only what is still here can be entered, and a larger entry is NOT F1 excess."""
    e = env
    send(e, "F1", 6, "DC-1")
    entry(e, "F1", 4)
    with refused(text="at a vendor"):
        entry(e, "F1", 5)
    counted_once(e)


def test_pieces_at_vendor_never_trigger_f1_excess(env):
    """10: even with a remark (which normally authorises F1 excess), the WO must not grow."""
    e = env
    send(e, "F1", 6, "DC-1")
    with refused(text="at a vendor"):
        entry(e, "F1", 8, remarks="extra mould poured")
    assert wo_qty(e) == 10 and (e.db.query(WorkOrder).one().excess_qty or 0) == 0
    counted_once(e)


def test_all_out_entry_message_names_the_vendor_not_a_finished_gate(env):
    """11"""
    e = env
    send(e, "F1", 10, "DC-1")
    with refused(text="at a vendor"):
        entry(e, "F1", 1)
    counted_once(e)


def test_gate_is_not_complete_while_pieces_are_out(env):
    """11"""
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 10, "DC-1")
    e.db.expire_all()
    r = e.db.query(WORoute).filter(WORoute.work_order_id == e.wo.id, WORoute.stage == "F1").one()
    assert r.stage_status == "At Vendor"
    ret(e, "DC-1", good=10)
    move(e, "F1", "F2", 10)
    e.db.expire_all()
    r = e.db.query(WORoute).filter(WORoute.work_order_id == e.wo.id, WORoute.stage == "F1").one()
    assert r.stage_status == "Completed"


def test_rejection_entry_while_pieces_are_out(env):
    e = env
    send(e, "F1", 5, "DC-1")
    entry(e, "F1", 3, rej=2)
    assert wip(e, "F1").rejected_qty == 2
    counted_once(e)
    ret(e, "DC-1", good=5)
    counted_once(e)


# ================================================================================== moving on
def test_move_only_what_is_in_stock_while_the_rest_is_out(env):
    """12"""
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 4, "DC-1")
    d = ProductionService.get_stage_dashboard(e.db, WO_NO, "F1")
    assert d.remaining_movable_qty == 6 and d.mrb_approved_movable_qty == 6
    with refused():
        move(e, "F1", "F2", 7)
    move(e, "F1", "F2", 6)
    counted_once(e)
    ret(e, "DC-1", good=4)
    move(e, "F1", "F2", 4)
    assert wip(e, "F2").ent_qty == 10 and wip(e, "F1").onhand_qty == 0
    counted_once(e)


def test_completed_pieces_sent_before_mrb_move_freely_after_return(env):
    """No MRB at receipt: the review was approved when the pieces were sent."""
    e = env
    entry(e, "F1", 10)                                                   # MRB pending
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=10)
    move(e, "F1", "F2", 10)
    counted_once(e)


# ================================================================================ returns
def test_partial_returns_can_have_different_receive_gates(env):
    """6: 4 back to F1 for more work, 6 straight to FI: two return rows, counted once."""
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=4)
    assert trip(e, "DC-1").status == "PARTIALLY_RECEIVED"
    counted_once(e)
    ret(e, "DC-1", good=6, dest="FI")
    t = trip(e, "DC-1")
    assert t.status == "RECEIVED" and t.done_qty == 6
    f1 = wip(e, "F1")
    assert (f1.ok_qty, f1.inproc_qty, f1.onhand_qty, wip(e, "FI").ent_qty) == (6, 4, 0, 6)
    rows = e.db.query(VendorTripReturn).filter(VendorTripReturn.trip_id == t.id).all()
    assert sorted((r.decision, r.destination_stage) for r in rows) == [("MORE_WORK", None), ("MOVED_ON", "FI")]
    counted_once(e)


def test_return_more_than_outstanding_or_after_received(env):
    """7"""
    e = env
    send(e, "F1", 5, "DC-1")
    with refused(text="Only 5 pcs"):
        ret(e, "DC-1", good=5, scrap=1)
    ret(e, "DC-1", good=5)
    with refused(text="already been fully received"):
        ret(e, "DC-1", good=1)
    counted_once(e)


def test_no_decision_is_asked_and_scrap_only_needs_none(env):
    e = env
    send(e, "F1", 4, "DC-U")
    ret(e, "DC-U", good=2)                                               # outcome follows from the receive gate
    ret(e, "DC-U", scrap=2)
    assert trip(e, "DC-U").status == "RECEIVED"
    assert [r.decision for r in e.db.query(VendorTripReturn).order_by(VendorTripReturn.received_at).all()] == ["MORE_WORK", None]
    entry(e, "F1", 2 + 0)
    counted_once(e)


def test_cancel_before_any_return_puts_pieces_back(env):
    e = env
    send(e, "F1", 10, "DC-1")
    VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), "vendor not ready", current_user=e.scm)
    assert trip(e, "DC-1").status == "CANCELLED"
    assert wip(e, "F1").inproc_qty == 10
    counted_once(e)
    with refused(text="cancelled"):
        ret(e, "DC-1", good=1)
    with refused(text="already cancelled"):
        VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), "again", current_user=e.scm)


def test_cancel_after_a_return_is_refused(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=3)
    with refused(text="already has returns"):
        VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), "too late", current_user=e.scm)
    with refused(text="reason"):
        VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), " ", current_user=e.scm)
    counted_once(e)


# ================================================================================ who may do what
def test_roles(env):
    e = env
    # a gate supervisor may send from their own gate only
    with refused(403):
        send(e, "F1", 2, "DC-1", user=e.f2sup)
    send(e, "F1", 2, "DC-1", user=e.f1sup)
    # SCM (a stage role locked to SP) may send from any gate
    send(e, "F1", 2, "DC-2", user=e.scm)
    # only SCM / admin record returns, cancel and choose "gate work done"
    for who in (e.f1sup, e.op):
        with refused(403):
            ret(e, "DC-1", good=2, user=who)
        with refused(403):
            VendorTripService.cancel(e.db, str(trip(e, "DC-1").id), "nope", current_user=who)
    ret(e, "DC-1", good=2, user=e.scm)
    counted_once(e)


# ============================================================================ the switch
def test_trips_refused_when_flag_is_off(env):
    e = env
    e.mp.setattr(settings, "VENDOR_TRIPS_ENABLED", False)
    with refused(text="not enabled"):
        send(e, "F1", 1, "DC-1")


def test_old_vendor_entry_and_move_label_refused_when_flag_is_on(env):
    e = env
    with refused(text="vendor trip"):
        entry(e, "F1", 10, vendor=True)
    entry(e, "F1", 10)
    approve(e, "F1")
    with refused(text="cannot be marked"):
        ProductionService.move_parts(e.db, MovePartsRequest(
            wo_number=WO_NO, from_stage="F1", to_stage="F2", quantity_moved=10,
            production_type="VENDOR", vendor_name="V", dc_number="D"), current_user=e.admin)
    assert wip(e, "F1").onhand_qty == 10
    counted_once(e)


# ===================================================================== legacy trips untouched
def test_legacy_open_trip_keeps_its_accounting_after_the_switch(env):
    """19: a trip recorded the old way before the switch is received the old way afterwards."""
    e = env
    e.mp.setattr(settings, "VENDOR_TRIPS_ENABLED", False)
    entry(e, "F1", 10, vendor=True)                                      # old style: counted as OK, auto-approved
    old = e.db.query(VendorDispatch).one()
    assert old.source_state is None
    counted_once(e)
    e.mp.setattr(settings, "VENDOR_TRIPS_ENABLED", True)
    counted_once(e)                                                      # unchanged by the switch
    VendorService.receive_from_vendor(e.db, str(old.id), 10, 0, "F2", current_user=e.admin)
    assert wip(e, "F2").ent_qty == 10
    counted_once(e)
    with refused(text="earlier-style"):
        VendorTripService.record_return(e.db, str(old.id), 1, 0, None, current_user=e.scm)
    with refused(text="earlier-style"):
        VendorTripService.cancel(e.db, str(old.id), "not allowed", current_user=e.scm)


def test_new_trip_and_legacy_trip_at_different_gates_together(env):
    e = env
    e.mp.setattr(settings, "VENDOR_TRIPS_ENABLED", False)
    entry(e, "F1", 10)
    approve(e, "F1")
    move(e, "F1", "F2", 6)                                               # 4 stay completed at F1
    entry(e, "F2", 6, vendor=True)                                       # legacy trip at F2
    e.mp.setattr(settings, "VENDOR_TRIPS_ENABLED", True)
    send(e, "F1", 4, "DC-NEW")                                           # new trip at F1
    counted_once(e)
    ret(e, "DC-NEW", good=4)
    VendorService.receive_from_vendor(e.db, str(e.db.query(VendorDispatch).filter(VendorDispatch.source_state.is_(None)).one().id),
                                      6, 0, "FI", current_user=e.admin)
    counted_once(e)


# ================================================================================== other gates
def test_trips_work_at_a_later_gate_and_at_sp(env):
    """20"""
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    move(e, "F1", "F2", 10)
    entry(e, "F2", 10)
    approve(e, "F2")
    move(e, "F2", "F3", 10)
    entry(e, "F3", 10)
    approve(e, "F3")
    move(e, "F3", "SP", 10)
    send(e, "SP", 10, "DC-SP", process="Painting")                       # SP is just another gate
    assert gate(e, "SP")["at_vendor_from_unprocessed_qty"] == 10
    counted_once(e)
    ret(e, "DC-SP", good=10, dest="FI", user=e.scm)                      # SCM receives them straight at FI
    assert wip(e, "SP").ok_qty == 10 and wip(e, "FI").ent_qty == 10
    counted_once(e)


# ===================================================================== balance and reporting
def test_reconciliation_balanced_at_every_step_of_a_long_story(env):
    """21"""
    e = env
    counted_once(e)
    send(e, "F1", 3, "DC-1"); counted_once(e)
    entry(e, "F1", 4, rej=1); counted_once(e)
    send(e, "F1", 2, "DC-2", source="COMPLETED"); counted_once(e)
    ret(e, "DC-1", good=2, scrap=1); counted_once(e)
    ret(e, "DC-2", good=1, scrap=1); counted_once(e)
    entry(e, "F1", 2); counted_once(e)
    approve(e, "F1")
    move(e, "F1", "F2", 4); counted_once(e)


def test_gate_state_numbers(env):
    e = env
    entry(e, "F1", 4)
    send(e, "F1", 3, "DC-1", source="UNPROCESSED")
    g = gate(e, "F1")
    assert g == {**g, "unprocessed_qty": 3, "completed_qty": 4,
                 "at_vendor_from_unprocessed_qty": 3, "at_vendor_from_completed_qty": 0, "trips_enabled": True}


# ============================================== pieces that land at a LATER gate (e.g. F1 -> FI)
def test_unprocessed_trip_goes_straight_to_fi(env):
    """Vendor did F1's work and the pieces go directly to FI: counted once at F1, landed at FI."""
    e = env
    send(e, "F1", 10, "DC-1")
    r = ret(e, "DC-1", good=10, dest="FI")
    assert "landed at FI" in r["message"]
    f1, fi = wip(e, "F1"), wip(e, "FI")
    assert (f1.ok_qty, f1.inproc_qty, f1.onhand_qty) == (10, 0, 0)      # counted once, nothing left waiting
    assert fi.ent_qty == 10 and fi.inproc_qty == 10
    t = trip(e, "DC-1")
    rows = e.db.query(VendorTripReturn).filter(VendorTripReturn.trip_id == t.id).all()
    assert [(x.decision, x.destination_stage) for x in rows] == [("MOVED_ON", "FI")]
    mrb = e.db.query(MRBReview).one()
    assert mrb.status == "APPROVED" and mrb.disposition == "VENDOR_RETURN_DIRECT"
    counted_once(e)
    entry(e, "FI", 10)                                                   # FI works on them normally
    counted_once(e)


def test_unprocessed_trip_to_the_next_gate(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=10, dest="F2")
    assert (wip(e, "F1").onhand_qty, wip(e, "F2").ent_qty) == (0, 10)
    counted_once(e)


def test_completed_trip_goes_straight_to_a_later_gate(env):
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=10, dest="FI")
    assert (wip(e, "F1").ok_qty, wip(e, "F1").onhand_qty, wip(e, "FI").ent_qty) == (10, 0, 10)
    counted_once(e)


def test_pending_review_of_sent_pieces_is_approved_so_nothing_waits_at_receipt(env):
    e = env
    entry(e, "F1", 10)                                                   # review pending
    assert e.db.query(MRBReview).one().status == "PENDING"
    send(e, "F1", 10, "DC-1")
    t = e.db.query(MRBReview).one()
    assert t.status == "APPROVED" and t.disposition == "VENDOR_SENT"
    ret(e, "DC-1", good=10, dest="FI")                                   # no MRB at receipt
    assert wip(e, "FI").ent_qty == 10
    counted_once(e)


def test_review_is_split_when_only_part_of_a_pending_batch_is_sent(env):
    e = env
    entry(e, "F1", 6)
    approve(e, "F1")                                                     # 6 approved
    entry(e, "F1", 4)                                                    # 4 pending
    send(e, "F1", 8, "DC-1", source="COMPLETED")                         # 6 approved + 2 out of the pending 4
    rows = e.db.query(MRBReview).order_by(MRBReview.created_at).all()
    assert sorted((r.status, r.reported_ok_qty) for r in rows) == [("APPROVED", 2), ("APPROVED", 6), ("PENDING", 2)]
    ret(e, "DC-1", good=8)
    counted_once(e)
    move(e, "F1", "F2", 8)                                               # the 2 still pending cannot move
    with refused(text="locked"):
        move(e, "F1", "F2", 2)
    assert wip(e, "F2").ent_qty == 8
    counted_once(e)


def test_part_lands_ahead_part_returns_for_more_work(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=6, dest="FI")
    ret(e, "DC-1", good=4)
    assert (wip(e, "F1").ok_qty, wip(e, "F1").inproc_qty, wip(e, "FI").ent_qty) == (6, 4, 6)
    counted_once(e)
    entry(e, "F1", 4)
    counted_once(e)


def test_scrap_with_pieces_landing_at_another_gate(env):
    e = env
    send(e, "F1", 10, "DC-1")
    ret(e, "DC-1", good=8, scrap=2, dest="F3")
    assert (wip(e, "F1").ok_qty, wip(e, "F1").onhand_qty, wip(e, "F3").ent_qty) == (8, 0, 8)
    counted_once(e)


def test_landing_destination_rules(env):
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    send(e, "F1", 4, "DC-1")
    with refused(text="not part of the route"):
        ret(e, "DC-1", good=4, dest="F9")
    with refused(text="not Dispatch"):
        ret(e, "DC-1", good=4, dest="DISPATCH")
    counted_once(e)
    # destination ignored when only scrap comes back
    ret(e, "DC-1", scrap=1, dest="FI")
    assert wip(e, "FI").ent_qty == 0
    counted_once(e)


def test_scrap_only_return_with_a_destination_lands_nothing(env):
    e = env
    send(e, "F1", 4, "DC-1")
    ret(e, "DC-1", scrap=4, dest="FI")
    assert wip(e, "FI").ent_qty == 0 and trip(e, "DC-1").status == "RECEIVED"
    counted_once(e)


def test_cannot_land_at_an_earlier_gate(env):
    e = env
    entry(e, "F1", 10)
    approve(e, "F1")
    move(e, "F1", "F2", 10)
    send(e, "F2", 10, "DC-1")
    with refused(text="later gate"):
        ret(e, "DC-1", good=10, dest="F1")
    counted_once(e)


def test_receive_at_fi_while_other_pieces_stay_at_f1(env):
    """Reported case: 5 produced at F1 stay there, 5 sent unprocessed are received at FI.
    F1 must show only its own 5 (not 10), FI must show the 5 received. Needs the app's
    no-autoflush session (the fixture), where a missing flush hid the landed pieces."""
    e = env
    entry(e, "F1", 5)
    send(e, "F1", 5, "DC-1", source="UNPROCESSED")
    ret(e, "DC-1", good=5, dest="FI")
    f1, fi = wip(e, "F1"), wip(e, "FI")
    assert (f1.ok_qty, f1.onhand_qty, f1.inproc_qty) == (10, 5, 0)
    assert (fi.ent_qty, fi.inproc_qty) == (5, 5)
    counted_once(e)
    d = ProductionService.get_stage_dashboard(e.db, WO_NO, "F1")
    assert d.remaining_movable_qty == 5
