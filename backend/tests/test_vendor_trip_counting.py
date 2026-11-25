"""Vendor (subcontract) trips must count every piece exactly once.

Rule checked after every step:
    WO quantity = in process + on hand (all stages) + rejected + at vendor + scrapped at vendor

Covers the two fixes in docs/vendor-trip-counting.md:
  C1 - scrap on a return to the same stage was counted twice (returned pieces could not
       be recorded; at F1 the shortfall looked like excess production and grew the WO).
  C2 - the stage screen subtracted at-vendor pieces from on-hand a second time, showing
       0 movable / locking the MRB check while in-house pieces were on hand.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
import app.models  # noqa: F401  registers every table
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute
from app.models.production_movement import StageWIP
from app.models.vendor import VendorDispatch
from app.schemas.production import RecordStageProductionRequest, MovePartsRequest
from app.services.production_service import ProductionService
from app.services.vendor_service import VendorService
from app.services.mrb_service import MRBService
from app.services.oms_integration_service import OMSIntegrationService
from app.models.mrb import MRBReview

ROUTE = ["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"]
QTY = 10
WO_NO = "WO-VTC-1"


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    user = User(full_name="Tester", email="vtc@vspl.test", hashed_password="x", role=UserRole.ADMIN)
    cust = Customer(name="Customer", customer_code="VTC")
    part = Part(part_number="P-VTC")
    db.add_all([user, cust, part])
    db.flush()
    order = Order(customer_id=cust.id, part_id=part.id, customer_po="PO-VTC", po_qty=QTY, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()
    wo = WorkOrder(wo_number=WO_NO, order_id=order.id, physical_wo_qty=QTY, current_stage="F1")
    db.add(wo)
    db.flush()
    for i, stage in enumerate(ROUTE, 1):
        db.add(WORoute(work_order_id=wo.id, stage=stage, sequence=i, stage_target_qty=QTY))
    db.add(StageWIP(work_order_id=wo.id, stage="F1", ent_qty=QTY, ok_qty=0, inproc_qty=QTY,
                    onhand_qty=0, rejected_qty=0, available_wip=QTY))
    db.commit()
    yield db, user, wo
    db.close()


def entry(db, user, stage, good, vendor=False, ret="FI", remarks=None):
    return ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=WO_NO, stage=stage, good_qty=good,
        production_type="VENDOR" if vendor else "IN_HOUSE",
        vendor_name="Vendor A" if vendor else None,
        dc_number="DC-1" if vendor else None,
        target_return_stage=ret, remarks=remarks), current_user=user)


def receive(db, user, good, scrap=0, dest="FI"):
    disp = db.query(VendorDispatch).filter(VendorDispatch.status != "RECEIVED").one()
    return VendorService.receive_from_vendor(db, str(disp.id), good, scrap, dest, current_user=user)


def approve(db, user, stage):
    MRBService.approve_stage_reviews(db, WO_NO, stage, current_user=user)


def move(db, user, frm, to, qty):
    return ProductionService.move_parts(db, MovePartsRequest(
        wo_number=WO_NO, from_stage=frm, to_stage=to, quantity_moved=qty), current_user=user)


def wip(db, wo, stage):
    db.expire_all()
    return db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == stage).one()


def assert_counted_once(db, wo):
    db.expire_all()
    wips = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
    disps = db.query(VendorDispatch).filter(VendorDispatch.work_order_id == wo.id).all()
    at_vendor = sum(max(d.dispatched_qty - (d.received_qty or 0) - (d.scrap_qty or 0), 0) for d in disps)
    vendor_scrap = sum(d.scrap_qty or 0 for d in disps)
    live = sum((w.inproc_qty or 0) + (w.onhand_qty or 0) for w in wips)
    rejected = sum(w.rejected_qty or 0 for w in wips)
    wo_now = db.query(WorkOrder).filter(WorkOrder.id == wo.id).one()
    assert live + rejected + at_vendor + vendor_scrap == wo_now.physical_wo_qty == QTY
    rec = OMSIntegrationService.reconcile_work_order(db, wo_now)
    assert rec.is_balanced, rec.details


def test_send_out_and_receive_into_next_stage_counts_once(env):
    db, user, wo = env
    entry(db, user, "F1", 10, vendor=True, ret="F2")
    assert wip(db, wo, "F1").onhand_qty == 0          # out at the vendor, not stock at F1
    assert_counted_once(db, wo)
    receive(db, user, 10, dest="F2")
    assert wip(db, wo, "F2").inproc_qty == 10 and wip(db, wo, "F1").onhand_qty == 0
    assert_counted_once(db, wo)


def test_return_to_same_stage_then_in_house_counts_once(env):
    db, user, wo = env
    entry(db, user, "F1", 10, vendor=True, ret="F1")
    receive(db, user, 10, dest="F1")
    assert wip(db, wo, "F1").inproc_qty == 10
    entry(db, user, "F1", 10)
    assert wip(db, wo, "F1").onhand_qty == 10
    assert_counted_once(db, wo)


def test_scrap_on_return_to_same_stage_keeps_every_returned_piece(env):
    """C1: 8 good + 2 scrap back into F1 leaves 8 to process, not 6."""
    db, user, wo = env
    entry(db, user, "F1", 10, vendor=True, ret="F1")
    receive(db, user, 8, scrap=2, dest="F1")
    f1 = wip(db, wo, "F1")
    assert f1.inproc_qty == 8 and f1.rejected_qty == 0 and f1.onhand_qty == 0
    assert_counted_once(db, wo)
    entry(db, user, "F1", 8)                            # previously refused
    assert wip(db, wo, "F1").onhand_qty == 8
    approve(db, user, "F1")
    move(db, user, "F1", "F2", 8)
    assert wip(db, wo, "F2").ent_qty == 8 and wip(db, wo, "F1").onhand_qty == 0
    assert_counted_once(db, wo)


def test_scrap_return_with_remark_does_not_grow_the_work_order(env):
    """C1: the returned pieces are no longer mistaken for F1 excess production."""
    db, user, wo = env
    entry(db, user, "F1", 10, vendor=True, ret="F1")
    receive(db, user, 8, scrap=2, dest="F1")
    entry(db, user, "F1", 8, remarks="returned from vendor")
    db.expire_all()
    wo_now = db.query(WorkOrder).filter(WorkOrder.id == wo.id).one()
    assert wo_now.physical_wo_qty == 10 and (wo_now.excess_qty or 0) == 0
    assert_counted_once(db, wo)


def test_more_than_returned_is_still_refused_after_scrap_return(env):
    db, user, wo = env
    entry(db, user, "F1", 10, vendor=True, ret="F1")
    receive(db, user, 8, scrap=2, dest="F1")
    with pytest.raises(HTTPException):
        entry(db, user, "F1", 9)                        # only 8 came back; no remark -> refused


def test_stage_screen_shows_in_house_pieces_movable_while_others_are_out(env):
    """C2: 5 in-house on hand + 5 at the vendor -> screen and MRB check show 5 movable."""
    db, user, wo = env
    entry(db, user, "F1", 10)
    approve(db, user, "F1")
    move(db, user, "F1", "F2", 10)
    entry(db, user, "F2", 5)
    entry(db, user, "F2", 5, vendor=True, ret="FI")

    before = ProductionService.get_stage_dashboard(db, WO_NO, "F2")
    assert before.remaining_movable_qty == 5
    assert before.mrb_lock_status == "LOCKED"         # in-house pieces still await MRB

    approve(db, user, "F2")
    after = ProductionService.get_stage_dashboard(db, WO_NO, "F2")
    assert after.remaining_movable_qty == 5
    assert after.mrb_approved_movable_qty == 5
    move(db, user, "F2", "F3", 5)
    assert_counted_once(db, wo)

    receive(db, user, 5, dest="FI")
    assert wip(db, wo, "FI").inproc_qty == 5 and wip(db, wo, "F3").inproc_qty == 5
    assert_counted_once(db, wo)


def test_stage_screen_unchanged_without_vendor(env):
    db, user, wo = env
    entry(db, user, "F1", 10)
    approve(db, user, "F1")
    dash = ProductionService.get_stage_dashboard(db, WO_NO, "F1")
    assert dash.remaining_movable_qty == 10 and dash.mrb_approved_movable_qty == 10
