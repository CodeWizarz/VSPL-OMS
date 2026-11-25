"""SCM (Supply Chain Manager) role.

SCM sends material to vendors and receives it back, runs the Dispatch Center (packing, BSR,
dispatch), and can view the PO -> dispatch -> collection cycle, invoices and payments. It is
not a stage role (no stage lock) and does not record in-house production, move parts, record
payments, run the OMS Engine batch or administer users.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.core.database import Base, SessionLocal, engine
from app.core.departments import allowed_stages_for
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.main import app
from app.models.user import User, UserRole
from app.services.vendor_trip_service import is_scm

PW = "Scm-Test-Pass-1"


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


def _login(client, email, pw):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _scm_token(client, secondary=None):
    email = f"scm-{uuid.uuid4().hex[:8]}@vspl-test.com"
    db = SessionLocal()
    try:
        db.add(User(full_name="Test SCM", email=email, hashed_password=get_password_hash(PW),
                    role=UserRole.SCM, secondary_role=secondary, is_active=True, must_change_password=False))
        db.commit()
    finally:
        db.close()
    return _login(client, email, PW)


def test_admin_can_create_and_list_an_scm_user(client):
    admin = _login(client, "admin@vspl.com", "admin123")
    email = f"new-scm-{uuid.uuid4().hex[:6]}@vijayspheroidals.com"
    r = client.post("/api/v1/users", headers=_auth(admin),
                    json={"full_name": "New SCM", "email": email, "department": "Supply Chain", "role": "scm"})
    assert r.status_code == 200, r.text
    rows = client.get("/api/v1/users", headers=_auth(admin)).json()
    mine = [u for u in rows if u["email"] == email]
    assert mine and mine[0]["role"] == "scm"


def test_scm_appears_in_the_roles_matrix(client):
    token = _scm_token(client)
    rows = client.get("/api/v1/roles", headers=_auth(token)).json()
    scm = [r for r in rows if r["role"] == "scm"]
    assert scm and any("vendor" in p.lower() for p in scm[0]["permissions"])


def test_scm_is_recognised_for_vendor_trips_and_has_no_stage_lock():
    assert is_scm(User(role=UserRole.SCM))
    assert allowed_stages_for(User(role=UserRole.SCM)) is None          # any gate


def test_scm_can_use_vendor_tracking_and_send(client):
    t = _scm_token(client)
    assert client.get("/api/v1/vendor/dispatches", headers=_auth(t)).status_code == 200
    assert client.get("/api/v1/vendor/summary", headers=_auth(t)).status_code == 200
    # the send endpoint is open to SCM (the WO does not exist, so 400/404 -- never 403)
    r = client.post("/api/v1/vendor/trips", headers=_auth(t), json={
        "wo_number": "WO-NOPE", "stage": "F1", "quantity": 1, "vendor_name": "V", "dc_number": "D-1"})
    assert r.status_code != 403, r.text
    # receiving and cancelling are SCM actions too
    r = client.post("/api/v1/vendor/trips/00000000-0000-0000-0000-000000000000/returns", headers=_auth(t),
                    json={"good_qty": 1})
    assert r.status_code != 403, r.text
    r = client.post("/api/v1/vendor/trips/00000000-0000-0000-0000-000000000000/cancel", headers=_auth(t),
                    json={"reason": "test"})
    assert r.status_code != 403, r.text
    # the earlier-style Receive screen still works for SCM (records that pre-date trips)
    r = client.post("/api/v1/vendor/receive", headers=_auth(t), json={
        "dispatch_id": "00000000-0000-0000-0000-000000000000", "received_qty": 1})
    assert r.status_code != 403, r.text


def test_scm_runs_the_dispatch_center(client):
    t = _scm_token(client)
    assert client.get("/api/v1/dispatch/queue", headers=_auth(t)).status_code == 200
    assert client.get("/api/v1/packing/queue", headers=_auth(t)).status_code == 200
    # shipping and packing updates pass the role gate (an empty body fails validation: 422, not 403)
    assert client.post("/api/v1/dispatch/ship", headers=_auth(t), json={}).status_code == 422
    assert client.post("/api/v1/packing/update", headers=_auth(t), json={}).status_code == 422


def test_scm_can_view_commercial_reports_but_not_record_payments(client):
    t = _scm_token(client)
    for path in ("/api/v1/accounts/po-cycle", "/api/v1/accounts/invoices", "/api/v1/accounts/payments"):
        assert client.get(path, headers=_auth(t)).status_code == 200, path
    assert client.post("/api/v1/accounts/payments", headers=_auth(t), json={}).status_code == 403


def test_scm_cannot_do_in_house_production_move_parts_batch_or_user_admin(client):
    t = _scm_token(client)
    assert client.post("/api/v1/production/entry", headers=_auth(t), json={}).status_code == 403
    assert client.post("/api/v1/production/move", headers=_auth(t), json={}).status_code == 403
    assert client.post("/api/v1/oms/run-cycle", headers=_auth(t)).status_code == 403
    assert client.get("/api/v1/users", headers=_auth(t)).status_code == 403


def test_scm_can_read_the_work_queue_and_tracking_for_any_gate(client):
    t = _scm_token(client)
    for stage in ("F1", "F2", "SP", "FI", "PACKING"):
        assert client.get(f"/api/v1/work-orders/queue?stage={stage}", headers=_auth(t)).status_code == 200, stage
