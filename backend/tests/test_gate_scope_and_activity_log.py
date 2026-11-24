"""F1..FI Supervisors see only their own gate; Packing/Dispatch have Managers only;
Admin can edit a user's email; every create/update/delete is recorded with who did it.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.gate_scope import supervisor_gate
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.main import app
from app.models.activity import ActivityLog
from app.models.user import User, UserRole

PW = "Gate-Test-Pass-1"


@pytest.fixture(autouse=True)
def _reset():
    limiter.reset()
    Base.metadata.create_all(bind=engine)
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


def _user(client, role, secondary=None, name=None):
    email = f"gate-{role.value}-{uuid.uuid4().hex[:8]}@vspl-test.com"
    db = SessionLocal()
    try:
        db.add(User(full_name=name or f"Gate {role.value}", email=email, hashed_password=get_password_hash(PW),
                    role=role, secondary_role=secondary, is_active=True, must_change_password=False))
        db.commit()
    finally:
        db.close()
    return _login_as(client, email, PW), email


def _wo_at_f1(client, admin):
    due = (date.today() + timedelta(days=20)).isoformat()
    r = client.post("/api/v1/operations/intake", headers=_auth(admin), json={
        "customer_code": "CUST-GATE", "customer_name": "Gate Customer",
        "customer_po": f"PO-G-{uuid.uuid4().hex[:8]}", "part_number": f"PART-G-{uuid.uuid4().hex[:6]}",
        "po_quantity": 10, "max_batch_size": 10, "create_wos": True,
        "delivery_date": due, "commitment_date": due,
    })
    assert r.status_code == 200, r.text
    wo = r.json()["wos_created"][0]
    r = client.post("/api/v1/operations/wo-release", headers=_auth(admin),
                    json={"wo_number": wo, "physical_wo_qty": 10, "route_stages": ["F1", "F2", "DISPATCH"]})
    assert r.status_code == 200, r.text
    return wo


# --- Roles ------------------------------------------------------------------------

def test_every_stage_has_supervisor_and_manager():
    values = {r.value for r in UserRole}
    for stage in ("f1", "f2", "f3", "sp", "fi", "packing", "dispatch"):
        assert {f"{stage}_supervisor", f"{stage}_manager"} <= values


def test_packing_supervisor_works_at_packing_only(client):
    admin = _admin(client)
    wo = _wo_at_f1(client, admin)
    packer, _ = _user(client, UserRole.PACKING_SUPERVISOR)
    r = client.post("/api/v1/production/entry", headers=_auth(packer),
                    json={"wo_number": wo, "stage": "F1", "good_qty": 1, "client_request_id": uuid.uuid4().hex})
    assert r.status_code == 403 and "PACKING" in r.json()["detail"]
    assert client.get("/api/v1/packing/queue", headers=_auth(packer)).status_code == 200
    # Packing update is a Packing-role action (fails on business rules here, not permission).
    assert client.post("/api/v1/packing/update", headers=_auth(packer), json={"wo_number": wo, "packed_quantity": 1}).status_code != 403


def test_dispatch_supervisor_can_dispatch_but_not_produce(client):
    admin = _admin(client)
    wo = _wo_at_f1(client, admin)
    disp, _ = _user(client, UserRole.DISPATCH_SUPERVISOR)
    assert client.get("/api/v1/dispatch/queue", headers=_auth(disp)).status_code == 200
    assert client.post("/api/v1/dispatch/ship", headers=_auth(disp),
                       json={"wo_number": wo, "invoice_number": "INV-T", "dispatched_quantity": 1}).status_code != 403
    assert client.post("/api/v1/production/entry", headers=_auth(disp),
                       json={"wo_number": wo, "stage": "F1", "good_qty": 1, "client_request_id": uuid.uuid4().hex}).status_code == 403


def test_supervisor_gate_only_for_pure_f1_to_fi_supervisors():
    assert supervisor_gate(User(role=UserRole.F2_SUPERVISOR)) == "F2"
    assert supervisor_gate(User(role=UserRole.F2_MANAGER)) is None
    assert supervisor_gate(User(role=UserRole.F1_SUPERVISOR, secondary_role=UserRole.QA)) is None
    assert supervisor_gate(User(role=UserRole.PRODUCTION_MANAGER)) is None


# --- Gate scoping -----------------------------------------------------------------

def test_supervisor_sees_only_wos_at_own_gate(client):
    admin = _admin(client)
    wo = _wo_at_f1(client, admin)
    f1, _ = _user(client, UserRole.F1_SUPERVISOR)
    f2, _ = _user(client, UserRole.F2_SUPERVISOR)

    f1_list = [w["wo_number"] for w in client.get("/api/v1/work-orders", headers=_auth(f1), params={"limit": 500}).json()]
    f2_list = [w["wo_number"] for w in client.get("/api/v1/work-orders", headers=_auth(f2), params={"limit": 500}).json()]
    assert wo in f1_list and wo not in f2_list

    assert client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(f1)).status_code == 200
    assert client.get(f"/api/v1/work-orders/{wo}/stage/F1/state", headers=_auth(f1)).status_code == 200
    assert client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(f2)).status_code == 403
    assert client.get(f"/api/v1/work-orders/{wo}/tracking", headers=_auth(f2)).status_code == 403
    assert client.get(f"/api/v1/work-orders/{wo}/stage/F2/state", headers=_auth(f1)).status_code == 403


def test_supervisor_blocked_from_other_gates_and_plant_wide_views(client):
    f1, _ = _user(client, UserRole.F1_SUPERVISOR)
    assert client.get("/api/v1/work-orders/queue", headers=_auth(f1), params={"stage": "F1"}).status_code == 200
    assert client.get("/api/v1/work-orders/queue", headers=_auth(f1), params={"stage": "F3"}).status_code == 403
    for url in ("/api/v1/production/wip", "/api/v1/production/reconciliation", "/api/v1/dashboard/stats",
                "/api/v1/work-orders/planning-summary"):
        assert client.get(url, headers=_auth(f1)).status_code == 403, url
    movable = client.get("/api/v1/work-orders/movable", headers=_auth(f1), params={"stage": "F3"})
    assert movable.status_code == 200


def test_managers_and_others_unaffected(client):
    admin = _admin(client)
    wo = _wo_at_f1(client, admin)
    f2_mgr, _ = _user(client, UserRole.F2_MANAGER)
    for tok in (f2_mgr, _login_as(client, "pm@vspl.com", "pm123")):
        assert client.get("/api/v1/production/wip", headers=_auth(tok)).status_code == 200
        assert client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(tok)).status_code == 200
        lst = [w["wo_number"] for w in client.get("/api/v1/work-orders", headers=_auth(tok), params={"limit": 500}).json()]
        assert wo in lst


# --- Admin edits email --------------------------------------------------------------

def test_admin_changes_user_email_and_user_signs_in_with_it(client):
    admin = _admin(client)
    _, email = _user(client, UserRole.QA)
    db = SessionLocal()
    try:
        uid = str(db.query(User).filter(User.email == email).first().id)
    finally:
        db.close()
    new_email = f"renamed-{uuid.uuid4().hex[:6]}@vspl-test.com"
    r = client.patch(f"/api/v1/users/{uid}", headers=_auth(admin), json={"email": new_email})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == new_email
    _login_as(client, new_email, PW)
    clash = client.patch(f"/api/v1/users/{uid}", headers=_auth(admin), json={"email": "admin@vspl.com"})
    assert clash.status_code == 409


# --- Activity log -------------------------------------------------------------------

def _latest(path_part, email=None):
    db = SessionLocal()
    try:
        q = db.query(ActivityLog).filter(ActivityLog.path.contains(path_part))
        if email:
            q = q.filter(ActivityLog.user_email == email)
        return q.order_by(ActivityLog.created_at.desc()).first()
    finally:
        db.close()


def test_changes_are_logged_with_who_and_what(client):
    admin = _admin(client)
    wo = _wo_at_f1(client, admin)
    f1, f1_email = _user(client, UserRole.F1_SUPERVISOR, name="Ravi F1")
    r = client.post("/api/v1/production/entry", headers=_auth(f1),
                    json={"wo_number": wo, "stage": "F1", "good_qty": 3, "client_request_id": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    row = _latest("/production/entry", f1_email)
    assert row is not None
    assert row.user_name == "Ravi F1" and row.user_role == "f1_supervisor"
    assert row.action == "Create" and row.outcome == "Success"
    assert wo in (row.target or "") and "stage=F1" in (row.details or "") and "good_qty=3" in (row.details or "")

    # A refused change is logged too, as Refused.
    f2, f2_email = _user(client, UserRole.F2_SUPERVISOR)
    client.post("/api/v1/production/entry", headers=_auth(f2),
                json={"wo_number": wo, "stage": "F1", "good_qty": 1, "client_request_id": uuid.uuid4().hex})
    assert _latest("/production/entry", f2_email).outcome == "Refused"


def test_passwords_and_sign_in_are_never_logged(client):
    admin = _admin(client)
    db = SessionLocal()
    try:
        assert db.query(ActivityLog).filter(ActivityLog.path.contains("/auth/login")).count() == 0
    finally:
        db.close()
    client.post("/api/v1/users", headers=_auth(admin), json={
        "full_name": "Log Test", "email": f"logtest-{uuid.uuid4().hex[:6]}@vijayspheroidals.com",
        "role": "qa", "password": "should-not-be-stored"})
    db = SessionLocal()
    try:
        for row in db.query(ActivityLog).all():
            assert "should-not-be-stored" not in (row.details or "") + (row.target or "")
    finally:
        db.close()


def test_logging_failure_never_breaks_the_request(client, monkeypatch):
    import app.core.activity_log as al
    monkeypatch.setattr(al, "_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    admin = _admin(client)
    r = client.put("/api/v1/planning/lead-times", headers=_auth(admin), json={"days": {"F1": 3}})
    assert r.status_code == 200


def test_activity_log_admin_and_ceo_only(client):
    admin = _admin(client)
    assert client.get("/api/v1/activity-log", headers=_auth(admin)).status_code == 200
    ceo = _login_as(client, "ceo@vspl.com", "ceo123")
    assert client.get("/api/v1/activity-log", headers=_auth(ceo)).status_code == 200
    pm = _login_as(client, "pm@vspl.com", "pm123")
    assert client.get("/api/v1/activity-log", headers=_auth(pm)).status_code == 403
    body = client.get("/api/v1/activity-log", headers=_auth(admin), params={"search": "lead-times"}).json()
    assert "items" in body and "total" in body


# --- Engineering & retired Manufacturing role --------------------------------------

def test_engineering_can_generate_and_release_wos_and_view_customers(client):
    eng, _ = _user(client, UserRole.ENGINEERING)
    assert client.get("/api/v1/masters/customers", headers=_auth(eng)).status_code == 200
    # Permission passes (the body is intentionally incomplete -> validation, not 403).
    for url in ("/api/v1/operations/work-orders", "/api/v1/operations/work-orders/merge", "/api/v1/work-orders"):
        assert client.post(url, headers=_auth(eng), json={}).status_code != 403, url
    assert client.post("/api/v1/operations/wo-release", headers=_auth(eng),
                       json={"wo_number": "WO-NOPE", "physical_wo_qty": 1, "route_stages": ["F1"]}).status_code != 403


def test_engineering_still_cannot_edit_masters_or_take_orders(client):
    eng, _ = _user(client, UserRole.ENGINEERING)
    assert client.post("/api/v1/masters/customers", headers=_auth(eng),
                       json={"customer_code": "X", "name": "X"}).status_code == 403
    assert client.post("/api/v1/operations/intake", headers=_auth(eng), json={
        "customer_code": "X", "customer_name": "X", "customer_po": "X", "part_number": "X",
        "po_quantity": 1, "max_batch_size": 1}).status_code == 403


def test_manufacturing_role_is_retired_but_existing_accounts_keep_working(client):
    from app.core.departments import LEGACY_ROLES, convert_legacy_role
    assert UserRole.MANUFACTURING in LEGACY_ROLES
    assert convert_legacy_role(UserRole.MANUFACTURING, "Manufacturing") is None
    mfg, email = _user(client, UserRole.MANUFACTURING)          # existing account still signs in
    assert client.get("/api/v1/work-orders", headers=_auth(mfg)).status_code == 200
    admin = _admin(client)
    plan = client.get("/api/v1/users/legacy-roles", headers=_auth(admin)).json()
    assert any(u["email"] == email for u in plan["needs_admin"])
