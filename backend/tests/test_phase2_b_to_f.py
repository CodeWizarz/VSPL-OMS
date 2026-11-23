"""Phase 2, steps B-F:

B. New roles (SUPERVISOR, ACCOUNTS), Sales order intake, Packing production/movement,
   stage-locked posting by department.
C. Work Order edit (state-dependent).
D. Stage plan dates + shop-floor work queue.
E. Invoices, payments and the PO -> dispatch -> collection report.
F. Subcontracting summary with the read-only DC software link.
"""
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.departments import allowed_stage_for, department_stage, normalize_stage
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.main import app
from app.models.audit import AuditLog
from app.models.dispatch import Dispatch
from app.models.order import Order
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WORoute
from app.services.stage_plan_service import compute_stage_plan
from app.services.subcontract_service import SubcontractService

SEEDED = {
    "ADMIN": ("admin@vspl.com", "admin123"),
    "PLANNER": ("planner@vspl.com", "planner123"),
    "PRODUCTION_MANAGER": ("pm@vspl.com", "pm123"),
    "STORE": ("store@vspl.com", "store123"),
}
PASSWORD = "Phase2-Test-Pass-1"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _login_as(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _login(client, key):
    return _login_as(client, *SEEDED[key])


def _make_user(client, role: UserRole, department=None):
    """Create a ready-to-use account directly (no forced password change)."""
    email = f"p2-{role.value}-{uuid.uuid4().hex[:8]}@vspl-test.com"
    db = SessionLocal()
    try:
        db.add(User(
            full_name=f"P2 {role.value}", email=email, hashed_password=get_password_hash(PASSWORD),
            role=role, department=department, is_active=True, must_change_password=False,
        ))
        db.commit()
    finally:
        db.close()
    return _login_as(client, email, PASSWORD)


def _intake(client, token, qty=20, delivery=None):
    body = {
        "customer_code": "CUST-P2",
        "customer_name": "Phase 2 Customer",
        "customer_po": f"PO-P2-{uuid.uuid4().hex[:8]}",
        "part_number": f"PART-P2-{uuid.uuid4().hex[:6]}",
        "po_quantity": qty,
        "max_batch_size": qty,
    }
    if delivery:
        body["delivery_date"] = delivery.isoformat()
    resp = client.post("/api/v1/operations/intake", headers=_auth(token), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


def _release(client, token, wo, qty=20, route=("F1", "F2", "F3", "DISPATCH")):
    resp = client.post(
        "/api/v1/operations/wo-release", headers=_auth(token),
        json={"wo_number": wo, "physical_wo_qty": qty, "route_stages": list(route)},
    )
    assert resp.status_code == 200, resp.text


def _move(client, token, wo, frm, to, qty):
    return client.post(
        "/api/v1/production/move", headers=_auth(token),
        json={"wo_number": wo, "from_stage": frm, "to_stage": to, "quantity_moved": qty},
    )


def _entry(client, token, wo, stage, good):
    return client.post(
        "/api/v1/production/entry", headers=_auth(token),
        json={"wo_number": wo, "stage": stage, "good_qty": good, "client_request_id": uuid.uuid4().hex},
    )


# ---------------------------------------------------------------------------
# B. Roles & stage locking
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dept,expected", [
    ("F1 Foundry", "F1"), ("F2", "F2"), ("F3 Machining", "F3"), ("Subcontracting (SP)", "SP"),
    ("FI Final Inspection", "FI"), ("Final Inspection", "FI"), ("Packing / BSR", "PACKING"),
    ("Manufacturing Operations", None), ("Planning", None), (None, None), ("", None),
])
def test_department_stage_resolution(dept, expected):
    assert department_stage(dept) == expected


def test_normalize_stage_folds_packing_aliases():
    for s in ("PACKING", "BSR", "PACKING / BSR", "packing/bsr"):
        assert normalize_stage(s) == "PACKING"


def test_allowed_stage_rules():
    assert allowed_stage_for(User(role=UserRole.SUPERVISOR, department="F2")) == "F2"
    assert allowed_stage_for(User(role=UserRole.MACHINE_OPERATOR, department="Manufacturing Operations")) is None
    assert allowed_stage_for(User(role=UserRole.PACKING, department=None)) == "PACKING"
    assert allowed_stage_for(User(role=UserRole.PRODUCTION_MANAGER, department="F1 Foundry")) is None
    assert allowed_stage_for(User(role=UserRole.ADMIN, department="F1")) is None


def test_supervisor_can_post_at_own_stage_only(client):
    admin = _login(client, "ADMIN")
    wo = _intake(client, admin)
    _release(client, admin, wo)
    f1_sup = _make_user(client, UserRole.SUPERVISOR, "F1 Foundry")
    f2_sup = _make_user(client, UserRole.SUPERVISOR, "F2")

    assert _entry(client, f1_sup, wo, "F1", 3).status_code == 200
    resp = _entry(client, f2_sup, wo, "F1", 1)
    assert resp.status_code == 403
    assert "own stage (F2)" in resp.json()["detail"]
    assert _move(client, f2_sup, wo, "F1", "F2", 1).status_code == 403
    assert _move(client, f1_sup, wo, "F1", "F2", 3).status_code == 200


def test_supervisor_cannot_release_or_convert(client):
    admin = _login(client, "ADMIN")
    wo = _intake(client, admin)
    sup = _make_user(client, UserRole.SUPERVISOR, "F1")
    resp = client.post(
        "/api/v1/operations/wo-release", headers=_auth(sup),
        json={"wo_number": wo, "physical_wo_qty": 20, "route_stages": ["F1", "DISPATCH"]},
    )
    assert resp.status_code == 403


def test_operator_without_stage_department_is_unrestricted(client):
    admin = _login(client, "ADMIN")
    wo = _intake(client, admin)
    _release(client, admin, wo)
    op = _make_user(client, UserRole.MACHINE_OPERATOR, "Manufacturing Operations")
    assert _entry(client, op, wo, "F1", 2).status_code == 200


def test_packing_role_is_limited_to_packing_stage(client):
    admin = _login(client, "ADMIN")
    wo = _intake(client, admin)
    _release(client, admin, wo)
    packer = _make_user(client, UserRole.PACKING, "Packing / BSR")
    resp = _entry(client, packer, wo, "F1", 1)
    assert resp.status_code == 403
    assert "Packing / BSR" in resp.json()["detail"]
    assert _move(client, packer, wo, "F1", "F2", 1).status_code == 403


def test_sales_can_input_orders_and_read_masters_but_not_edit_masters(client):
    sales = _make_user(client, UserRole.SALES, "Sales")
    _intake(client, sales)
    assert client.get("/api/v1/masters/customers", headers=_auth(sales)).status_code == 200
    assert client.get("/api/v1/masters/pos", headers=_auth(sales)).status_code == 200
    assert client.get("/api/v1/masters/schedules", headers=_auth(sales)).status_code == 200
    assert client.post(
        "/api/v1/masters/customers", headers=_auth(sales),
        json={"customer_code": f"C-{uuid.uuid4().hex[:6]}", "name": "Nope"},
    ).status_code == 403


def test_store_and_accounts_still_cannot_input_orders(client):
    for role in (UserRole.STORE, UserRole.ACCOUNTS):
        token = _make_user(client, role)
        resp = client.post(
            "/api/v1/operations/intake", headers=_auth(token),
            json={"customer_code": "X", "customer_name": "X", "customer_po": "X", "part_number": "X",
                  "po_quantity": 1, "max_batch_size": 1},
        )
        assert resp.status_code == 403, role


# ---------------------------------------------------------------------------
# C. Work Order edit
# ---------------------------------------------------------------------------

def _edit(client, token, wo, **body):
    body.setdefault("reason", "Customer revised the requirement")
    return client.patch(f"/api/v1/operations/work-orders/{wo}", headers=_auth(token), json=body)


def test_edit_before_production_changes_qty_and_route(client):
    planner = _login(client, "PLANNER")
    wo = _intake(client, planner)
    _release(client, planner, wo)
    resp = _edit(client, planner, wo, physical_wo_qty=15, route_stages=["F1", "F3", "FI"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["physical_wo_qty"] == 15
    assert body["route_stages"] == ["F1", "F3", "FI", "DISPATCH"]
    assert body["changes"]
    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(AuditLog.action == "WO_EDITED", AuditLog.entity_id == wo).count() == 1
    finally:
        db.close()


def test_edit_after_production_locks_qty_and_reached_stages(client):
    planner = _login(client, "PLANNER")
    admin = _login(client, "ADMIN")
    wo = _intake(client, planner)
    _release(client, planner, wo, route=("F1", "F2", "F3", "DISPATCH"))
    assert _move(client, admin, wo, "F1", "F2", 5).status_code == 200

    resp = _edit(client, planner, wo, physical_wo_qty=30)
    assert resp.status_code == 409
    assert "Quantity is locked" in resp.json()["detail"]

    # F1 and F2 already have material -> must stay; F3 may be swapped for SP + FI.
    resp = _edit(client, planner, wo, route_stages=["F2", "F1", "SP", "DISPATCH"])
    assert resp.status_code == 409
    resp = _edit(client, planner, wo, route_stages=["F1", "F2", "SP", "FI", "DISPATCH"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["route_stages"] == ["F1", "F2", "SP", "FI", "DISPATCH"]

    # Movement still works on the edited route.
    assert _move(client, admin, wo, "F1", "F2", 2).status_code == 200


def test_edit_stage_plan_dates_and_validation(client):
    planner = _login(client, "PLANNER")
    wo = _intake(client, planner)
    _release(client, planner, wo)
    d1, d2 = date.today() + timedelta(days=3), date.today() + timedelta(days=4)
    resp = _edit(client, planner, wo, stage_plan=[{"stage": "F2", "planned_start": d1.isoformat(), "planned_end": d2.isoformat()}])
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage_plans"]["F2"] == {"planned_start": d1.isoformat(), "planned_end": d2.isoformat()}

    bad = _edit(client, planner, wo, stage_plan=[{"stage": "F2", "planned_start": d2.isoformat(), "planned_end": d1.isoformat()}])
    assert bad.status_code == 400
    missing = _edit(client, planner, wo, stage_plan=[{"stage": "SP", "planned_end": d2.isoformat()}])
    assert missing.status_code == 400


def test_edit_requires_reason_and_planning_role(client):
    planner = _login(client, "PLANNER")
    pm = _login(client, "PRODUCTION_MANAGER")
    wo = _intake(client, planner)
    assert client.patch(f"/api/v1/operations/work-orders/{wo}", headers=_auth(planner), json={"physical_wo_qty": 10}).status_code == 422
    assert _edit(client, pm, wo, physical_wo_qty=10).status_code == 403
    assert _edit(client, planner, "WO-DOES-NOT-EXIST", physical_wo_qty=10).status_code == 404


# ---------------------------------------------------------------------------
# D. Stage plan dates + work queue
# ---------------------------------------------------------------------------

def test_compute_stage_plan_backwards_from_delivery():
    plan = compute_stage_plan(["F1", "F2", "DISPATCH"], delivery_date=date(2026, 12, 20))
    assert plan["DISPATCH"] == (date(2026, 12, 20), date(2026, 12, 20))
    assert plan["F2"] == (date(2026, 12, 19), date(2026, 12, 20))
    assert plan["F1"] == (date(2026, 12, 16), date(2026, 12, 18))


def test_compute_stage_plan_forwards_without_delivery():
    plan = compute_stage_plan(["F1", "F2", "DISPATCH"], delivery_date=None, start_date=date(2026, 12, 1))
    assert plan["F1"] == (date(2026, 12, 1), date(2026, 12, 3))
    assert plan["F2"] == (date(2026, 12, 4), date(2026, 12, 5))
    assert plan["DISPATCH"][0] >= plan["F2"][1]


def test_release_fills_plan_dates_and_route_endpoint_returns_them(client):
    planner = _login(client, "PLANNER")
    delivery = date.today() + timedelta(days=10)
    wo = _intake(client, planner, delivery=delivery)
    _release(client, planner, wo, route=("F1", "F2", "DISPATCH"))
    route = client.get(f"/api/v1/work-orders/{wo}/route", headers=_auth(planner)).json()
    assert route["stage_plans"]["DISPATCH"]["planned_end"] == delivery.isoformat()
    assert route["stage_plans"]["F1"]["planned_end"] is not None


def test_work_queue_lists_wo_at_stage_with_bucket(client):
    planner = _login(client, "PLANNER")
    wo = _intake(client, planner, delivery=date.today() + timedelta(days=1))
    _release(client, planner, wo, route=("F1", "F2", "DISPATCH"))
    resp = client.get("/api/v1/work-orders/queue", headers=_auth(planner), params={"stage": "F1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    item = next(i for i in body["items"] if i["wo_number"] == wo)
    assert item["qty_at_stage"] == 20
    assert item["plan_source"] == "planned"
    # Delivery tomorrow -> F1 should have ended already.
    assert item["bucket"] == "overdue"
    assert body["counts"]["overdue"]["wos"] >= 1
    # Not at F2 yet.
    f2 = client.get("/api/v1/work-orders/queue", headers=_auth(planner), params={"stage": "F2"}).json()
    assert all(i["wo_number"] != wo for i in f2["items"])


# ---------------------------------------------------------------------------
# E. Invoices, payments, PO cycle
# ---------------------------------------------------------------------------

def _fake_dispatch(wo_number, invoice, qty=10):
    """Insert a Dispatch row directly (the packing->dispatch flow is covered elsewhere);
    accounts only reads dispatch rows."""
    db = SessionLocal()
    try:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number).first()
        db.add(Dispatch(
            work_order_id=wo.id, customer_po=wo.order.customer_po, invoice_number=invoice,
            dispatched_qty=qty, dispatch_date=datetime.now(),
        ))
        db.commit()
    finally:
        db.close()


def test_payment_cycle_partial_then_paid(client):
    planner = _login(client, "PLANNER")
    accounts = _make_user(client, UserRole.ACCOUNTS, "Accounts")
    wo = _intake(client, planner)
    inv = f"INV-P2-{uuid.uuid4().hex[:6]}"
    _fake_dispatch(wo, inv)

    invoices = client.get("/api/v1/accounts/invoices", headers=_auth(accounts)).json()
    row = next(i for i in invoices if i["invoice_number"] == inv)
    assert row["status"] == "NOT_VALUED"

    resp = client.put(f"/api/v1/accounts/invoices/{inv}", headers=_auth(accounts), json={"amount": "1000.00"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "UNPAID"

    pay = {"invoice_number": inv, "amount": "400", "received_date": date.today().isoformat(), "mode": "NEFT", "reference": "UTR1"}
    assert client.post("/api/v1/accounts/payments", headers=_auth(accounts), json=pay).status_code == 200
    row = next(i for i in client.get("/api/v1/accounts/invoices", headers=_auth(accounts)).json() if i["invoice_number"] == inv)
    assert row["status"] == "PARTIAL" and row["outstanding"] == 600.0

    over = dict(pay, amount="700")
    assert client.post("/api/v1/accounts/payments", headers=_auth(accounts), json=over).status_code == 400
    future = dict(pay, amount="10", received_date=(date.today() + timedelta(days=2)).isoformat())
    assert client.post("/api/v1/accounts/payments", headers=_auth(accounts), json=future).status_code == 400

    assert client.post("/api/v1/accounts/payments", headers=_auth(accounts), json=dict(pay, amount="600")).status_code == 200
    row = next(i for i in client.get("/api/v1/accounts/invoices", headers=_auth(accounts)).json() if i["invoice_number"] == inv)
    assert row["status"] == "PAID" and row["outstanding"] == 0.0

    # Amount can't drop below what's been received.
    assert client.put(f"/api/v1/accounts/invoices/{inv}", headers=_auth(accounts), json={"amount": "500"}).status_code == 400


def test_payment_rules_and_permissions(client):
    planner = _login(client, "PLANNER")
    wo = _intake(client, planner)
    inv = f"INV-P2-{uuid.uuid4().hex[:6]}"
    _fake_dispatch(wo, inv)
    sales = _make_user(client, UserRole.SALES)
    store = _login(client, "STORE")
    pay = {"invoice_number": inv, "amount": "10", "received_date": date.today().isoformat()}

    assert client.post("/api/v1/accounts/payments", headers=_auth(sales), json=pay).status_code == 403
    assert client.get("/api/v1/accounts/invoices", headers=_auth(sales)).status_code == 200
    assert client.get("/api/v1/accounts/invoices", headers=_auth(store)).status_code == 403
    admin = _login(client, "ADMIN")
    unknown = dict(pay, invoice_number="INV-NOPE-404")
    assert client.post("/api/v1/accounts/payments", headers=_auth(admin), json=unknown).status_code == 404


def test_po_cycle_report_tracks_dispatch_and_collection(client):
    planner = _login(client, "PLANNER")
    accounts = _make_user(client, UserRole.ACCOUNTS)
    sales = _make_user(client, UserRole.SALES)
    wo = _intake(client, planner, qty=20)
    db = SessionLocal()
    try:
        po = db.query(WorkOrder).filter(WorkOrder.wo_number == wo).first().order.customer_po
    finally:
        db.close()

    rows = client.get("/api/v1/accounts/po-cycle", headers=_auth(sales), params={"search": po}).json()
    assert len(rows) == 1 and rows[0]["collection_status"] == "NOT_INVOICED" and rows[0]["stage"] == "IN_PRODUCTION"

    inv = f"INV-P2-{uuid.uuid4().hex[:6]}"
    _fake_dispatch(wo, inv, qty=8)
    client.put(f"/api/v1/accounts/invoices/{inv}", headers=_auth(accounts), json={"amount": "800"})
    client.post("/api/v1/accounts/payments", headers=_auth(accounts),
                json={"invoice_number": inv, "amount": "300", "received_date": date.today().isoformat()})
    row = client.get("/api/v1/accounts/po-cycle", headers=_auth(sales), params={"search": po}).json()[0]
    assert row["dispatched_qty"] == 8 and row["pending_qty"] == 12
    assert row["stage"] == "PART_DISPATCHED"
    assert row["invoices"] == [inv]
    assert row["invoiced_amount"] == 800.0 and row["paid_amount"] == 300.0 and row["outstanding_amount"] == 500.0
    assert row["collection_status"] == "PARTIAL"


def test_dispatch_request_accepts_invoice_amount():
    from app.schemas.dispatch import DispatchRequest
    req = DispatchRequest(wo_number="WO-1", invoice_number="INV-1", dispatched_quantity=1, invoice_amount="125.50")
    assert str(req.invoice_amount) == "125.50"
    with pytest.raises(Exception):
        DispatchRequest(wo_number="WO-1", invoice_number="INV-1", dispatched_quantity=1, invoice_amount="-1")


# ---------------------------------------------------------------------------
# F. Subcontracting summary / DC link
# ---------------------------------------------------------------------------

def test_subcontract_summary_without_dc_link(client):
    admin = _login(client, "ADMIN")
    resp = client.get("/api/v1/subcontract/summary", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dc_available"] is False
    assert "not configured" in body["dc_message"]
    assert isinstance(body["ready_to_send"], list)


def test_subcontract_summary_buckets_dc_returns(client):
    admin = _login(client, "ADMIN")
    wo = _intake(client, admin)
    _release(client, admin, wo, route=("F1", "SP", "FI", "DISPATCH"))
    assert _move(client, admin, wo, "F1", "SP", 6).status_code == 200
    today = date(2026, 12, 10)

    class FakeDC:
        @staticmethod
        def fetch_open_dcs(wos):
            assert wo in wos
            base = {"woNumber": wo, "partNumber": "P", "vendorName": "Vendor", "status": "AT_VENDOR",
                    "quantitySent": 6, "unit": "NOS", "quantityReturned": None, "closed": False,
                    "sentAt": "2026-12-01T10:00:00Z"}
            return [
                dict(base, dcNumber="DC-1", expectedReturnDate="2026-12-08"),  # overdue
                dict(base, dcNumber="DC-2", expectedReturnDate="2026-12-10"),  # today
                dict(base, dcNumber="DC-3", expectedReturnDate="2026-12-12"),  # next 2 days
                dict(base, dcNumber="DC-4", expectedReturnDate="2026-12-20"),  # later
                dict(base, dcNumber="DC-5", expectedReturnDate="2026-12-11", closed=True),
                dict(base, dcNumber="DC-6", expectedReturnDate=None, sentAt=None),  # not sent yet
            ], None

    db = SessionLocal()
    try:
        s = SubcontractService.summary(db, days=2, today=today, client=FakeDC)
    finally:
        db.close()
    assert s["dc_available"] is True
    assert [e["dc_number"] for e in s["due_back"]["overdue"]] == ["DC-1"]
    assert [e["dc_number"] for e in s["due_back"]["today"]] == ["DC-2"]
    assert [e["dc_number"] for e in s["due_back"]["next"]] == ["DC-3"]
    assert {e["dc_number"] for e in s["at_vendor"]} == {"DC-1", "DC-2", "DC-3", "DC-4"}
    ready = next(r for r in s["ready_to_send"] if r["wo_number"] == wo)
    assert ready["qty_at_sp"] == 6 and ready["already_on_dc"] is True


def test_dc_client_reports_unreachable(monkeypatch):
    from app.core.config import settings
    from app.services.subcontract_service import DCClient
    monkeypatch.setattr(settings, "DC_API_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "DC_API_TOKEN", "t")
    monkeypatch.setattr(settings, "DC_API_TIMEOUT_SECONDS", 1.0)
    dcs, err = DCClient.fetch_open_dcs(["WO-1"])
    assert dcs is None and "unreachable" in err
