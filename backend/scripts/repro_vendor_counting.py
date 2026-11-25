"""Reproduces vendor (subcontract) counting scenarios S1-S7 on OMS services, in-memory SQLite.
Run from backend/:  PYTHONPATH=. python scripts/repro_vendor_counting.py
See docs/vendor-trip-counting.md. Touches no real database."""
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.core.database import Base
import app.models  # noqa: F401  (register all tables)
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

ROUTE = ["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"]
QTY = 10


def fresh():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    db = sessionmaker(bind=eng)()
    user = User(full_name="Tester", email="t@vspl.test", hashed_password="x", role=UserRole.ADMIN)
    cust = Customer(name="Cust", customer_code="CU"); part = Part(part_number="P-1")
    db.add_all([user, cust, part]); db.flush()
    order = Order(customer_id=cust.id, part_id=part.id, customer_po="PO1", po_qty=QTY, status=OrderStatus.ACCEPT)
    db.add(order); db.flush()
    wo = WorkOrder(wo_number="WO-T1", order_id=order.id, physical_wo_qty=QTY, current_stage="F1")
    db.add(wo); db.flush()
    for i, s in enumerate(ROUTE, 1):
        db.add(WORoute(work_order_id=wo.id, stage=s, sequence=i, stage_target_qty=QTY))
    db.add(StageWIP(work_order_id=wo.id, stage="F1", ent_qty=QTY, ok_qty=0, inproc_qty=QTY, onhand_qty=0, rejected_qty=0, available_wip=QTY))
    db.commit()
    return db, user, wo


def pe(db, user, stage, good, vendor=False, ret="FI", remarks=None, rej=0):
    req = RecordStageProductionRequest(wo_number="WO-T1", stage=stage, good_qty=good, rejected_quantity=rej,
                                       defect_code="DIM" if rej else None,
                                       production_type="VENDOR" if vendor else "IN_HOUSE",
                                       vendor_name="Vendor A" if vendor else None,
                                       dc_number="DC-1" if vendor else None,
                                       target_return_stage=ret, remarks=remarks)
    return ProductionService.record_stage_production(db, req, current_user=user)


def mrb_ok(db, user, stage):
    return MRBService.approve_stage_reviews(db, "WO-T1", stage, current_user=user)


def move(db, user, frm, to, qty):
    req = MovePartsRequest(wo_number="WO-T1", from_stage=frm, to_stage=to, quantity_moved=qty)
    return ProductionService.move_parts(db, req, current_user=user)


def receive(db, user, qty, scrap=0, dest="FI"):
    d = db.query(VendorDispatch).filter(VendorDispatch.status != "RECEIVED").first()
    if d is None:
        raise HTTPException(status_code=400, detail="nothing at vendor to receive (no dispatch was recorded)")
    return VendorService.receive_from_vendor(db, str(d.id), qty, scrap, dest, current_user=user)


def snap(db, wo, label):
    db.expire_all()
    wip = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
    rows = {}
    for s in ROUTE:
        w = wip.get(s)
        if w and (w.ent_qty or w.ok_qty or w.rejected_qty):
            rows[s] = dict(ent=w.ent_qty, ok=w.ok_qty, rej=w.rejected_qty, inproc=w.inproc_qty, onhand=w.onhand_qty)
    disps = db.query(VendorDispatch).filter(VendorDispatch.work_order_id == wo.id).all()
    at_vendor = sum(max(d.dispatched_qty - (d.received_qty or 0) - (d.scrap_qty or 0), 0) for d in disps)
    vendor_scrap = sum(d.scrap_qty or 0 for d in disps)
    live = sum((r["inproc"] or 0) + (r["onhand"] or 0) for r in rows.values())
    rej = sum(r["rej"] or 0 for r in rows.values())
    try:
        dash = {s: ProductionService.get_stage_dashboard(db, "WO-T1", s) for s in ("F1", "F2")}
        movable = {s: (getattr(d, "remaining_movable_qty", None), getattr(d, "mrb_approved_movable_qty", None)) for s, d in dash.items()}
    except Exception as e:  # noqa: BLE001
        movable = f"dashboard error: {type(e).__name__}"
    wo_db = db.query(WorkOrder).filter(WorkOrder.id == wo.id).first()
    print(f"  [{label}] WO qty={wo_db.physical_wo_qty} excess={wo_db.excess_qty or 0} | stages={json.dumps(rows)}")
    print(f"      at_vendor={at_vendor} vendor_scrap={vendor_scrap} live_wip(inproc+onhand)={live} rejected={rej} "
          f"=> pieces accounted={live + rej + at_vendor + vendor_scrap} (should be {wo_db.physical_wo_qty}) | screen (remaining movable, MRB-approved movable)={movable}")


def run(name, steps):
    print(f"\n### {name}")
    db, user, wo = fresh()
    for label, fn in steps:
        try:
            fn(db, user)
            snap(db, wo, label)
        except HTTPException as e:
            db.rollback()
            print(f"  [{label}] REFUSED {e.status_code}: {str(e.detail)[:170]}")
            snap(db, wo, label + " (after refusal)")


run("S1 all in-house: F1 10 -> MRB -> move to F2", [
    ("F1 entry 10 in-house", lambda db, u: pe(db, u, "F1", 10)),
    ("MRB approve F1 + move 10 to F2", lambda db, u: (mrb_ok(db, u, "F1"), move(db, u, "F1", "F2", 10))),
])
run("S2 vendor at F1, comes back into F2", [
    ("F1 entry 10 as VENDOR (return F2)", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F2")),
    ("receive 10 into F2", lambda db, u: receive(db, u, 10, dest="F2")),
])
run("S3 vendor at F1, comes back to F1, then in-house finish and move", [
    ("F1 entry 10 as VENDOR (return F1)", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F1")),
    ("receive 10 back into F1", lambda db, u: receive(db, u, 10, dest="F1")),
    ("F1 entry 10 in-house after return", lambda db, u: pe(db, u, "F1", 10)),
    ("MRB approve F1 + move 10 to F2", lambda db, u: (mrb_ok(db, u, "F1"), move(db, u, "F1", "F2", 10))),
])
run("S4 physical flow: pour 10 in-house at F1, then send the same 10 to vendor", [
    ("F1 entry 10 in-house (poured)", lambda db, u: pe(db, u, "F1", 10)),
    ("F1 entry 10 as VENDOR, no remarks", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F2")),
    ("F1 entry 10 as VENDOR with remarks", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F2", remarks="sent for fettling")),
    ("receive 10 into F2", lambda db, u: receive(db, u, 10, dest="F2")),
])
run("S5 vendor return with scrap, back to the same gate", [
    ("F1 entry 10 as VENDOR (return F1)", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F1")),
    ("receive 8 OK + 2 scrap back into F1", lambda db, u: receive(db, u, 8, scrap=2, dest="F1")),
    ("F1 entry 8 in-house after return", lambda db, u: pe(db, u, "F1", 8)),
])
run("S6 F2 split: 5 in-house, 5 to vendor returning to FI", [
    ("F1 10 in-house, MRB, move 10 to F2", lambda db, u: (pe(db, u, "F1", 10), mrb_ok(db, u, "F1"), move(db, u, "F1", "F2", 10))),
    ("F2 entry 5 in-house + 5 VENDOR (return FI)", lambda db, u: (pe(db, u, "F2", 5), pe(db, u, "F2", 5, vendor=True, ret="FI"))),
    ("MRB approve F2 + move the 5 in-house to F3", lambda db, u: (mrb_ok(db, u, "F2"), move(db, u, "F2", "F3", 5))),
    ("receive 5 into FI", lambda db, u: receive(db, u, 5, dest="FI")),
])


def move_vendor(db, user, frm, to, qty):
    req = MovePartsRequest(wo_number="WO-T1", from_stage=frm, to_stage=to, quantity_moved=qty,
                           production_type="VENDOR", vendor_name="Vendor A", dc_number="DC-9")
    return ProductionService.move_parts(db, req, current_user=user)


if __name__ == "__main__" and True:
    run("S7 Move screen with VENDOR: F1 10 poured, MRB, 'move to vendor' F1->F2", [
        ("F1 entry 10 in-house + MRB approve", lambda db, u: (pe(db, u, "F1", 10), mrb_ok(db, u, "F1"))),
        ("Move F1->F2 10 marked VENDOR (pieces physically at vendor)", lambda db, u: move_vendor(db, u, "F1", "F2", 10)),
        ("vendor returns 10: try Receive", lambda db, u: receive(db, u, 10, dest="F2")),
        ("F2 entry 10 in-house after return", lambda db, u: pe(db, u, "F2", 10)),
    ])
    run("S5b same as S5, operator adds a remark to get past the refusal", [
        ("F1 entry 10 as VENDOR (return F1)", lambda db, u: pe(db, u, "F1", 10, vendor=True, ret="F1")),
        ("receive 8 OK + 2 scrap back into F1", lambda db, u: receive(db, u, 8, scrap=2, dest="F1")),
        ("F1 entry 8 in-house with remark", lambda db, u: pe(db, u, "F1", 8, remarks="returned from vendor")),
    ])
