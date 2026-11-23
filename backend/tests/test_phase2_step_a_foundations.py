"""Phase 2 / Step A foundations:

A1. A Work Order cannot be re-released once shop-floor activity exists (re-release
    used to delete its route + stage WIP and silently erase production history).
A2. Admin can edit an existing user's name, department and role (audit-logged, with
    lock-out guards); nobody else can.
A3. Schema sync targets the real `stage_wips` table and reports which statements failed.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.core.database import SessionLocal
from app.models.audit import AuditLog
from app.models.production_movement import StageWIP
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "PLANNER": ("planner@vspl.com", "planner123"),
    "PRODUCTION_MANAGER": ("pm@vspl.com", "pm123"),
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, role_key):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _intake_wo(client, token, po_qty=20):
    resp = client.post(
        "/api/v1/operations/intake",
        headers=_auth(token),
        json={
            "customer_code": "CUST-STEPA",
            "customer_name": "Step A Customer",
            "customer_po": f"PO-SA-{uuid.uuid4().hex[:8]}",
            "part_number": f"PART-SA-{uuid.uuid4().hex[:6]}",
            "po_quantity": po_qty,
            "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


def _release(client, token, wo, qty=20, route=("F1", "F2", "DISPATCH")):
    return client.post(
        "/api/v1/operations/wo-release", headers=_auth(token),
        json={"wo_number": wo, "physical_wo_qty": qty, "route_stages": list(route)},
    )


def _stage_wip_snapshot(wo_number):
    db = SessionLocal()
    try:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number).first()
        rows = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
        return wo.physical_wo_qty, sorted((r.stage, r.ok_qty, r.inproc_qty, r.moved_out_qty) for r in rows)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# A1. Re-release guard
# ---------------------------------------------------------------------------

def test_wo_can_still_be_re_released_before_any_production(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    assert _release(client, admin, wo, qty=20).status_code == 200
    # Planner correcting the route/qty before the floor touches it stays allowed.
    resp = _release(client, admin, wo, qty=18, route=("F1", "F3", "DISPATCH"))
    assert resp.status_code == 200, resp.text
    assert _stage_wip_snapshot(wo)[0] == 18


def test_re_release_refused_after_material_movement_and_history_kept(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    assert _release(client, admin, wo).status_code == 200
    move = client.post(
        "/api/v1/production/move", headers=_auth(admin),
        json={"wo_number": wo, "from_stage": "F1", "to_stage": "F2", "quantity_moved": 5},
    )
    assert move.status_code == 200, move.text
    before = _stage_wip_snapshot(wo)

    resp = _release(client, admin, wo, qty=20)
    assert resp.status_code == 409, resp.text
    assert "cannot be re-released" in resp.json()["detail"]
    # Nothing was wiped.
    assert _stage_wip_snapshot(wo) == before


def test_re_release_refused_after_production_entry(client):
    admin = _login(client, "ADMIN")
    wo = _intake_wo(client, admin)
    assert _release(client, admin, wo).status_code == 200
    entry = client.post(
        "/api/v1/production/entry", headers=_auth(admin),
        json={"wo_number": wo, "stage": "F1", "good_qty": 3, "client_request_id": uuid.uuid4().hex},
    )
    assert entry.status_code == 200, entry.text

    resp = _release(client, admin, wo, qty=20)
    assert resp.status_code == 409, resp.text
    assert "production has been recorded" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# A2. Admin edit of an existing user
# ---------------------------------------------------------------------------

def _create_user(client, admin, role="production_manager", department="Production"):
    resp = client.post(
        "/api/v1/users", headers=_auth(admin),
        json={
            "full_name": "Step A User",
            "email": f"stepa-{uuid.uuid4().hex[:10]}@vspl-test.com",
            "department": department,
            "role": role,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["user"]


def test_admin_can_edit_department_role_and_name_and_it_is_audited(client):
    admin = _login(client, "ADMIN")
    user = _create_user(client, admin)

    resp = client.patch(
        f"/api/v1/users/{user['id']}", headers=_auth(admin),
        json={"department": "F1 Foundry", "role": "machine_operator", "full_name": "F1 Supervisor"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["department"] == "F1 Foundry"
    assert body["role"] == "machine_operator"
    assert body["full_name"] == "F1 Supervisor"
    assert "hashed_password" not in body

    db = SessionLocal()
    try:
        log = (
            db.query(AuditLog)
            .filter(AuditLog.action == "USER_UPDATED", AuditLog.entity_id == user["id"])
            .first()
        )
        assert log is not None
        assert "F1 Foundry" in log.details and "machine_operator" in log.details
    finally:
        db.close()


def test_partial_edit_only_changes_sent_fields_and_blank_department_clears(client):
    admin = _login(client, "ADMIN")
    user = _create_user(client, admin, role="planner", department="Planning")

    resp = client.patch(f"/api/v1/users/{user['id']}", headers=_auth(admin), json={"department": "  "})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["department"] is None
    assert body["role"] == "planner"
    assert body["full_name"] == "Step A User"


def test_blank_name_is_rejected(client):
    admin = _login(client, "ADMIN")
    user = _create_user(client, admin)
    resp = client.patch(f"/api/v1/users/{user['id']}", headers=_auth(admin), json={"full_name": "   "})
    assert resp.status_code == 422


@pytest.mark.parametrize("role_key", ["PLANNER", "PRODUCTION_MANAGER"])
def test_non_admin_cannot_edit_users(client, role_key):
    admin = _login(client, "ADMIN")
    user = _create_user(client, admin)
    token = _login(client, role_key)
    resp = client.patch(f"/api/v1/users/{user['id']}", headers=_auth(token), json={"role": "admin"})
    assert resp.status_code == 403


def test_unknown_user_returns_404(client):
    admin = _login(client, "ADMIN")
    resp = client.patch(f"/api/v1/users/{uuid.uuid4()}", headers=_auth(admin), json={"department": "F2"})
    assert resp.status_code == 404


def test_admin_cannot_demote_themselves(client):
    admin = _login(client, "ADMIN")
    me = client.get("/api/v1/auth/me", headers=_auth(admin)).json()
    resp = client.patch(f"/api/v1/users/{me['id']}", headers=_auth(admin), json={"role": "planner"})
    assert resp.status_code == 400
    assert "own Admin role" in resp.json()["detail"]


def test_admin_can_edit_own_department_without_touching_role(client):
    admin = _login(client, "ADMIN")
    me = client.get("/api/v1/auth/me", headers=_auth(admin)).json()
    original = me.get("department")
    try:
        resp = client.patch(f"/api/v1/users/{me['id']}", headers=_auth(admin), json={"department": "Administration"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "admin"
    finally:
        client.patch(f"/api/v1/users/{me['id']}", headers=_auth(admin), json={"department": original or ""})


def test_role_change_takes_effect_on_next_request(client):
    """Permissions are read from the database on every request (not from the JWT), so
    a role change applies immediately to the user's existing session."""
    admin = _login(client, "ADMIN")
    user = _create_user(client, admin, role="planner", department="Planning")
    resp = client.patch(f"/api/v1/users/{user['id']}", headers=_auth(admin), json={"role": "qa"})
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.email == user["email"]).first()
        assert stored.role == UserRole.QA
    finally:
        db.close()


# ---------------------------------------------------------------------------
# A3. Schema sync
# ---------------------------------------------------------------------------

def test_schema_sync_targets_real_stage_wips_table():
    import inspect
    import app.core.database as db_module

    src = inspect.getsource(db_module.auto_migrate_schema)
    assert "ALTER TABLE stage_wip " not in src, "statements must target the real 'stage_wips' table"
    assert "ALTER TABLE stage_wips ADD COLUMN IF NOT EXISTS scrapped_qty" in src


def test_schema_sync_result_lists_failed_statements():
    import app.core.database as db_module

    result = db_module.auto_migrate_schema()
    assert "failed_statements" in result
    assert len(result["failed_statements"]) == result["failed"]
    for item in result["failed_statements"]:
        assert set(item) == {"statement", "error"}
