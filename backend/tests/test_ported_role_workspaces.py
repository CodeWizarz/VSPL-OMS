"""Features ported from the main line onto the production (recovery) line:

- Re-release guard: a WO with shop-floor activity can't be re-released (it used to
  wipe routes + stage WIP).
- Schema sync targets the real stage_wips table and reports failed statements.
- Stage roles (Supervisor/Manager per stage), enforced by the backend.
- CEO has full Admin access.
- Old-role conversion by department.
- Stage plan dates on release, editable lead times, stage-plan edit, work queue.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.core.database import Base, SessionLocal, engine
from app.core.departments import allowed_stages_for, convert_legacy_role
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.main import app
from app.models.audit import AuditLog
from app.models.planning import StageLeadTime
from app.models.production_movement import StageWIP
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder
from app.services.stage_plan_service import compute_stage_plan

PW = "Port-Test-Pass-1"


@pytest.fixture(autouse=True)
def _reset():
    limiter.reset()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(StageLeadTime).delete()
        db.commit()
    finally:
        db.close()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _login_as(client, email, pw):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin(client):
    return _login_as(client, "admin@vspl.com", "admin123")


def _user(client, role, department=None, secondary=None, login=True):
    email = f"port-{role.value}-{uuid.uuid4().hex[:8]}@vspl-test.com"
    db = SessionLocal()
    try:
        u = User(full_name=f"Port {role.value}", email=email, hashed_password=get_password_hash(PW),
                 role=role, secondary_role=secondary, department=department, is_active=True,
                 must_change_password=False)
        db.add(u)
        db.commit()
        uid = str(u.id)
    finally:
        db.close()
    return (_login_as(client, email, PW) if login else None), uid, email


def _intake(client, token, qty=20, delivery=None):
    body = {
        "customer_code": "CUST-PORT", "customer_name": "Port Customer",
        "customer_po": f"PO-PORT-{uuid.uuid4().hex[:8]}", "part_number": f"PART-PORT-{uuid.uuid4().hex[:6]}",
        "po_quantity": qty, "max_batch_size": qty, "create_wos": True,
    }
    # Intake requires a commitment date on this line; plan dates schedule back from it.
    due = delivery or (date.today() + timedelta(days=30))
    body["delivery_date"] = due.isoformat()
    body["commitment_date"] = due.isoformat()
    r = client.post("/api/v1/operations/intake", headers=_auth(token), json=body)
    assert r.status_code == 200, r.text
    return r.json()["wos_created"][0]


def _release(client, token, wo, qty=20, route=("F1", "F2", "FI", "DISPATCH")):
    return client.post("/api/v1/operations/wo-release", headers=_auth(token),
                       json={"wo_number": wo, "physical_wo_qty": qty, "route_stages": list(route)})


def _entry(client, token, wo, stage, good=1):
    return client.post("/api/v1/production/entry", headers=_auth(token),
                       json={"wo_number": wo, "stage": stage, "good_qty": good, "client_request_id": uuid.uuid4().hex})


def _move(client, token, wo, frm, to, qty=1):
    return client.post("/api/v1/production/move", headers=_auth(token),
                       json={"wo_number": wo, "from_stage": frm, "to_stage": to, "quantity_moved": qty})


def _wip(wo_number):
    db = SessionLocal()
    try:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number).first()
        rows = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
        return sorted((r.stage, r.ok_qty, r.inproc_qty, r.moved_out_qty) for r in rows)
    finally:
        db.close()


# --- Re-release guard ------------------------------------------------------------

def test_re_release_allowed_before_any_production(client):
    admin = _admin(client)
    wo = _intake(client, admin)
    assert _release(client, admin, wo).status_code == 200
    assert _release(client, admin, wo, qty=18).status_code == 200


def test_re_release_refused_after_floor_activity_and_history_kept(client):
    admin = _admin(client)
    wo = _intake(client, admin)
    assert _release(client, admin, wo).status_code == 200
    # On this line material only moves after MRB approval, so production entry is the
    # first shop-floor fact; it alone must block a re-release.
    assert _entry(client, admin, wo, "F1", 5).status_code == 200
    before = _wip(wo)
    r = _release(client, admin, wo)
    assert r.status_code == 409, r.text
    assert "cannot be re-released" in r.json()["detail"]
    assert _wip(wo) == before


def test_re_release_refused_after_production_entry(client):
    admin = _admin(client)
    wo = _intake(client, admin)
    assert _release(client, admin, wo).status_code == 200
    assert _entry(client, admin, wo, "F1", 2).status_code == 200
    r = _release(client, admin, wo)
    assert r.status_code == 409 and "production has been recorded" in r.json()["detail"]


# --- Schema sync -----------------------------------------------------------------

def test_schema_sync_alters_target_real_stage_wips_table():
    import inspect
    import app.core.database as db_module
    src = inspect.getsource(db_module.auto_migrate_schema)
    assert "ALTER TABLE stage_wip " not in src
    assert "ALTER TABLE stage_wips ADD COLUMN IF NOT EXISTS scrapped_qty" in src


def test_schema_sync_lists_failed_statements():
    import app.core.database as db_module
    result = db_module.auto_migrate_schema()
    assert len(result["failed_statements"]) == result["failed"]


# --- Stage roles -----------------------------------------------------------------

def test_stage_roles_lock_and_secondary_role_unlocks():
    assert allowed_stages_for(User(role=UserRole.F2_SUPERVISOR, department="Anything")) == {"F2"}
    assert allowed_stages_for(User(role=UserRole.PACKING_MANAGER)) == {"PACKING", "BSR"}
    # A non-stage secondary role (e.g. Production Manager) lifts the lock.
    assert allowed_stages_for(User(role=UserRole.F1_SUPERVISOR, secondary_role=UserRole.PRODUCTION_MANAGER)) is None
    # Old roles keep today's behaviour (no backend lock).
    assert allowed_stages_for(User(role=UserRole.MACHINE_OPERATOR, department="F2")) is None


def test_supervisor_posts_at_own_stage_only(client):
    admin = _admin(client)
    wo = _intake(client, admin)
    assert _release(client, admin, wo).status_code == 200
    f1, _, _ = _user(client, UserRole.F1_SUPERVISOR)
    f2, _, _ = _user(client, UserRole.F2_SUPERVISOR)
    assert _entry(client, f1, wo, "F1", 2).status_code == 200
    # F1 supervisor passes the stage lock (the move itself then waits for MRB approval).
    assert _move(client, f1, wo, "F1", "F2", 2).status_code != 403
    r = _entry(client, f2, wo, "F1", 1)
    assert r.status_code == 403 and "own stage (F2)" in r.json()["detail"]
    assert _move(client, f2, wo, "F1", "F2", 1).status_code == 403


def test_stage_roles_cannot_release(client):
    admin = _admin(client)
    wo = _intake(client, admin)
    for role in (UserRole.F1_SUPERVISOR, UserRole.F1_MANAGER):
        tok, _, _ = _user(client, role)
        assert _release(client, tok, wo).status_code == 403


@pytest.mark.parametrize("role,dept,expected", [
    (UserRole.MACHINE_OPERATOR, "F1 Foundry", UserRole.F1_SUPERVISOR),
    (UserRole.OPERATOR, "Subcontracting (SP)", UserRole.SP_SUPERVISOR),
    (UserRole.PACKING, None, UserRole.PACKING_SUPERVISOR),
    (UserRole.DISPATCH, "x", UserRole.DISPATCH_SUPERVISOR),
    (UserRole.MACHINE_OPERATOR, "Manufacturing Operations", None),
    (UserRole.PRODUCTION_MANAGER, "F1", None),
])
def test_convert_legacy_role_mapping(role, dept, expected):
    assert convert_legacy_role(role, dept) == expected


def test_admin_preview_then_convert(client):
    admin = _admin(client)
    _, mid, memail = _user(client, UserRole.MACHINE_OPERATOR, "F3", login=False)
    _, uid, uemail = _user(client, UserRole.OPERATOR, "Manufacturing Operations", login=False)
    prev = client.get("/api/v1/users/legacy-roles", headers=_auth(admin)).json()
    assert next(u for u in prev["convertible"] if u["id"] == mid)["new_role"] == "f3_supervisor"
    assert any(u["id"] == uid for u in prev["needs_admin"])
    res = client.post("/api/v1/users/convert-legacy-roles", headers=_auth(admin)).json()
    assert {"email": memail, "from": "machine_operator", "to": "f3_supervisor"} in res["converted"]
    f3, _, _ = _user(client, UserRole.F3_MANAGER)
    assert client.post("/api/v1/users/convert-legacy-roles", headers=_auth(f3)).status_code == 403


# --- CEO = Admin -----------------------------------------------------------------

def test_ceo_has_admin_access(client):
    ceo = _login_as(client, "ceo@vspl.com", "ceo123")
    assert client.get("/api/v1/users", headers=_auth(ceo)).status_code == 200
    assert client.get("/api/v1/users/legacy-roles", headers=_auth(ceo)).status_code == 200
    assert User(role=UserRole.CEO).has_any_role(UserRole.ADMIN)
    assert not User(role=UserRole.DATA_ANALYST).has_any_role(UserRole.ADMIN)


# --- Plan dates, lead times, queue ---------------------------------------------

def test_release_fills_plan_dates_from_due_date(client):
    admin = _admin(client)
    delivery = date.today() + timedelta(days=12)
    wo = _intake(client, admin, delivery=delivery)
    assert _release(client, admin, wo, route=("F1", "F2", "DISPATCH")).status_code == 200
    plans = client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(admin)).json()["stage_plans"]
    assert plans["DISPATCH"]["planned_end"] == delivery.isoformat()
    assert plans["F1"]["planned_end"] is not None


def test_lead_times_update_and_effect(client):
    planner = _login_as(client, "planner@vspl.com", "planner123")
    r = client.put("/api/v1/planning/lead-times", headers=_auth(planner), json={"days": {"F2": 4}})
    assert r.status_code == 200, r.text
    delivery = date.today() + timedelta(days=20)
    wo = _intake(client, planner, delivery=delivery)
    assert _release(client, planner, wo, route=("F1", "F2", "DISPATCH")).status_code == 200
    plans = client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(planner)).json()["stage_plans"]
    s, e = date.fromisoformat(plans["F2"]["planned_start"]), date.fromisoformat(plans["F2"]["planned_end"])
    assert (e - s).days == 3
    f1, _, _ = _user(client, UserRole.F1_SUPERVISOR)
    assert client.put("/api/v1/planning/lead-times", headers=_auth(f1), json={"days": {"F1": 2}}).status_code == 403


def test_stage_plan_edit_rules(client):
    admin = _admin(client)
    wo = _intake(client, admin, delivery=date.today() + timedelta(days=15))
    assert _release(client, admin, wo).status_code == 200
    mgr, _, _ = _user(client, UserRole.F2_MANAGER)
    sup, _, _ = _user(client, UserRole.F2_SUPERVISOR)
    d = (date.today() + timedelta(days=4)).isoformat()
    ok = client.patch(f"/api/v1/work-orders/{wo}/stage-plan", headers=_auth(mgr),
                      json={"reason": "Machine down", "stages": [{"stage": "F2", "planned_start": d, "planned_end": d}]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["stage_plans"]["F2"]["planned_end"] == d
    other = client.patch(f"/api/v1/work-orders/{wo}/stage-plan", headers=_auth(mgr),
                         json={"reason": "xxx", "stages": [{"stage": "F1", "planned_end": d}]})
    assert other.status_code == 403
    assert client.patch(f"/api/v1/work-orders/{wo}/stage-plan", headers=_auth(sup),
                        json={"reason": "xxx", "stages": [{"stage": "F2", "planned_end": d}]}).status_code == 403
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(AuditLog.action == "WO_STAGE_PLAN_EDITED", AuditLog.entity_id == wo).count() == 1
    finally:
        db.close()


def test_work_queue_lists_wo_at_stage(client):
    admin = _admin(client)
    wo = _intake(client, admin, delivery=date.today() + timedelta(days=1))
    assert _release(client, admin, wo, route=("F1", "F2", "DISPATCH")).status_code == 200
    q = client.get("/api/v1/work-orders/queue", headers=_auth(admin), params={"stage": "F1"}).json()
    item = next(i for i in q["items"] if i["wo_number"] == wo)
    assert item["qty_at_stage"] == 20 and item["plan_source"] == "planned" and item["bucket"] == "overdue"


def test_compute_stage_plan_backwards():
    plan = compute_stage_plan(["F1", "F2", "DISPATCH"], delivery_date=date(2026, 12, 20))
    assert plan["DISPATCH"] == (date(2026, 12, 20), date(2026, 12, 20))
    assert plan["F1"] == (date(2026, 12, 16), date(2026, 12, 18))


def test_demo_stage_accounts_seeded(client):
    for email in ("f1.supervisor@vspl.com", "packing.manager@vspl.com", "accounts@vspl.com"):
        _login_as(client, email, "stage123")
