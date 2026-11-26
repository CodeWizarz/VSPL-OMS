"""MRB status shown on Move Parts: read-only fields on the route timeline and the stage state."""
from tests.test_setup_planning import env, mkwo, T, d, WorkOrder  # noqa: F401
from app.models.mrb import MRBReview
from app.services.mrb_service import MRBService, display_state
from app.services.oms_integration_service import OMSIntegrationService
from app.services.work_order_service import WorkOrderService


def _ticket(env, wo, stage, status, ok=5, n=[0]):
    n[0] += 1
    env.db.add(MRBReview(mrb_number=f"MRB-9{n[0]:04d}", work_order_id=wo.id, stage=stage, reported_ok_qty=ok,
                         reported_reject_qty=0, status=status, verified_ok_qty=ok if status != "PENDING" else None))
    env.db.commit()


def _step(env, wo, stage):
    det = WorkOrderService.get_tracking_detail(env.db, wo.wo_number)
    return next(s for s in det.timeline if s.stage == stage)


def test_display_state_labels():
    assert display_state({"total_tickets": 0}) == "NONE"
    assert display_state({"total_tickets": 2, "lock_status": "LOCKED"}) == "PENDING"
    assert display_state({"total_tickets": 2, "lock_status": "PARTIAL"}) == "PARTIAL"
    assert display_state({"total_tickets": 2, "lock_status": "UNLOCKED"}) == "CLEARED"


def test_timeline_and_stage_state_show_pending_partial_cleared(env):
    wo = mkwo(env, "WO-M1", qty=10, wip={"F1": (10, 10, 0, 0, 10)})
    assert _step(env, wo, "F1").mrb_state == "NONE"
    _ticket(env, wo, "F1", "PENDING", 5)
    s = _step(env, wo, "F1")
    assert s.mrb_state == "PENDING" and s.mrb_pending_qty == 5 and s.mrb_pending_tickets
    _ticket(env, wo, "F1", "APPROVED", 5)
    assert _step(env, wo, "F1").mrb_state == "PARTIAL"
    st = OMSIntegrationService.get_current_stage_state(env.db, wo, "F1")
    assert st["mrb_state"] == "PARTIAL" and st["mrb_approved_qty"] == 5 and st["mrb_total_tickets"] == 2
    for t in env.db.query(MRBReview).filter(MRBReview.work_order_id == wo.id, MRBReview.status == "PENDING").all():
        t.status, t.verified_ok_qty = "APPROVED", t.reported_ok_qty
    env.db.commit()
    assert _step(env, wo, "F1").mrb_state == "CLEARED"
    assert OMSIntegrationService.get_current_stage_state(env.db, wo, "F1")["mrb_state"] == "CLEARED"
    assert _step(env, wo, "F2").mrb_state == "NONE"          # other stages unaffected


def test_movement_rules_unchanged_by_the_display_fields(env):
    wo = mkwo(env, "WO-M2", qty=10, wip={"F1": (10, 10, 0, 0, 10)})
    _ticket(env, wo, "F1", "PENDING", 10)
    s = MRBService.get_stage_mrb_summary(env.db, wo.id, "F1", 10, 0)
    assert s["lock_status"] == "LOCKED" and s["approved_movable_qty"] == 0
