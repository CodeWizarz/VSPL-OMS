"""Setup planning API: access (PPC / admin only, only while switched on), the open read-only
endpoints, and one full flow over HTTP (create setup, map, export, upload, apply, delays, undo)."""
import io
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.main import app
from app.models.order import Customer, Order, OrderStatus, Part
from app.models.user import User, UserRole
from app.models.work_order import WORoute, WOStatus, WorkOrder
from app.models.production_movement import StageWIP

PW = "Plan-Test-Pass-1"
T = date.today()


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "SETUP_PLANNING_ENABLED", True)
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


def _user(client, role):
    email = f"plan-{role.value}-{uuid.uuid4().hex[:8]}@vspl-test.com"
    db = SessionLocal()
    try:
        db.add(User(full_name=f"Plan {role.value}", email=email, hashed_password=get_password_hash(PW), role=role,
                    is_active=True, must_change_password=False))
        db.commit()
    finally:
        db.close()
    return _login(client, email, PW)


def _wo(tag, wip_f1=True, commitment_days=40):
    """A released work order with a full route and dates, straight in the database."""
    db = SessionLocal()
    try:
        cust = db.query(Customer).first() or Customer(name="C", customer_code=f"C-{tag}")
        part = db.query(Part).first() or Part(part_number=f"P-{tag}")
        db.add_all([x for x in (cust, part) if x.id is None])
        db.flush()
        order = Order(oar_number=f"OAR-{tag}", customer_id=cust.id, part_id=part.id, customer_po=f"PO-{tag}", po_qty=10,
                      status=OrderStatus.ACCEPT, commitment_date=T + timedelta(days=commitment_days))
        db.add(order)
        db.flush()
        wo = WorkOrder(wo_number=f"WO-{tag}", order_id=order.id, physical_wo_qty=10, current_stage="F1",
                       status=WOStatus.IN_PRODUCTION, release_date=datetime.now())
        db.add(wo)
        db.flush()
        for i, s in enumerate(["F1", "F2", "FI", "DISPATCH"], 1):
            db.add(WORoute(work_order_id=wo.id, stage=s, sequence=i, stage_target_qty=10,
                           planned_start=T + timedelta(days=2 * i), planned_end=T + timedelta(days=2 * i + 1)))
        if wip_f1:
            db.add(StageWIP(work_order_id=wo.id, stage="F1", ent_qty=10, ok_qty=0, rejected_qty=0, inproc_qty=10,
                            onhand_qty=0, available_wip=10))
        db.commit()
        return wo.wo_number
    finally:
        db.close()


PPC_PATHS = [
    ("get", "/api/v1/planning/setups"),
    ("post", "/api/v1/planning/setups"),
    ("get", "/api/v1/planning/setups/S-NOPE"),
    ("get", "/api/v1/planning/unassigned"),
    ("get", "/api/v1/planning/export-all.xlsx"),
    ("get", "/api/v1/planning/digest"),
    ("post", "/api/v1/planning/digest/send"),
    ("get", "/api/v1/planning/delays"),
    ("get", "/api/v1/planning/setups/S-NOPE/export.xlsx"),
    ("get", "/api/v1/planning/imports/00000000-0000-0000-0000-000000000000"),
]


def _call(client, method, path, token):
    kw = {"json": {}} if method == "post" else {}
    return getattr(client, method)(path, headers=_auth(token), **kw)


def test_only_ppc_and_admin_may_use_the_planning_endpoints(client):
    for role in (UserRole.PLANNER,):
        t = _user(client, role)
        for m, p in PPC_PATHS:
            assert _call(client, m, p, t).status_code != 403, (role, p)
    admin = _login(client, "admin@vspl.com", "admin123")
    assert client.get("/api/v1/planning/setups", headers=_auth(admin)).status_code == 200
    for role in (UserRole.SALES, UserRole.F1_SUPERVISOR, UserRole.F1_MANAGER, UserRole.OPERATOR, UserRole.QA,
                 UserRole.PRODUCTION_MANAGER, UserRole.ACCOUNTS, UserRole.STORE):
        t = _user(client, role)
        for m, p in PPC_PATHS:
            assert _call(client, m, p, t).status_code == 403, (role, p)


def test_planning_is_refused_for_ppc_while_the_switch_is_off(client, monkeypatch):
    t = _user(client, UserRole.PLANNER)
    monkeypatch.setattr(settings, "SETUP_PLANNING_ENABLED", False)
    for m, p in PPC_PATHS:
        r = _call(client, m, p, t)
        assert r.status_code == 403 and "not enabled" in r.text, p


def test_config_and_plan_info_are_open_to_every_signed_in_role(client, monkeypatch):
    wo = _wo(uuid.uuid4().hex[:6].upper())
    sup = _user(client, UserRole.F1_SUPERVISOR)
    assert client.get("/api/v1/planning/config", headers=_auth(sup)).json()["setup_planning_enabled"] is True
    info = client.get(f"/api/v1/planning/wo/{wo}/plan-info?stage=F1", headers=_auth(sup)).json()
    assert info["enabled"] and info["this_gate"]["stage"] == "F1" and info["setup_number"] is None
    assert client.get(f"/api/v1/planning/wo/{wo}/plan-info", headers=_auth(sup)).status_code == 200
    assert client.get(f"/api/v1/planning/wo/{wo}/plan-info").status_code == 401          # not signed in
    assert client.get("/api/v1/planning/config").status_code == 401
    monkeypatch.setattr(settings, "SETUP_PLANNING_ENABLED", False)
    assert client.get(f"/api/v1/planning/wo/{wo}/plan-info", headers=_auth(sup)).json() == {"enabled": False}
    assert client.get("/api/v1/planning/config", headers=_auth(sup)).json()["setup_planning_enabled"] is False


def test_full_flow_over_http(client):
    tag = uuid.uuid4().hex[:6].upper()
    wo = _wo(tag)
    t = _user(client, UserRole.PLANNER)
    sn = f"S-{tag}"
    r = client.post("/api/v1/planning/setups", headers=_auth(t), json={"setup_number": sn, "setup_date": T.isoformat()})
    assert r.status_code == 200 and r.json()["setup"]["setup_number"] == sn
    assert client.post("/api/v1/planning/setups", headers=_auth(t), json={"setup_number": sn.lower()}).status_code == 409
    # unassigned -> map
    assert wo in [x["wo_number"] for x in client.get("/api/v1/planning/unassigned", headers=_auth(t)).json()["work_orders"]]
    m = client.post(f"/api/v1/planning/setups/{sn}/work-orders", headers=_auth(t), json={"wo_numbers": [wo], "reason": "plan day"})
    assert m.json()["mapped"] == [wo]
    det = client.get(f"/api/v1/planning/setups/{sn}", headers=_auth(t)).json()
    assert [w["wo_number"] for w in det["work_orders"]] == [wo] and det["gate_columns"] == ["F1", "F2", "FI", "DISPATCH"]
    assert det["work_orders"][0]["oar_number"] == f"OAR-{tag}" and det["work_orders"][0]["customer_po"] == f"PO-{tag}"
    # heats
    h = client.put(f"/api/v1/planning/work-orders/{wo}/heats", headers=_auth(t), json={"heat_numbers": ["H-1", "H-2"], "reason": "melt"})
    assert h.json()["heat_numbers"] == ["H-1", "H-2"]
    # export, edit, upload, review, apply
    x = client.get(f"/api/v1/planning/setups/{sn}/export.xlsx", headers=_auth(t))
    assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"] and "attachment" in x.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(x.content))
    ws = wb["PLAN"]
    headers = [c.value for c in ws[1]]
    ws.cell(2, headers.index("F2 End") + 1).value = T + timedelta(days=30)
    buf = io.BytesIO()
    wb.save(buf)
    up = client.post("/api/v1/planning/imports", headers=_auth(t), data={"setup_number": sn},
                     files={"file": ("plan.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert up.status_code == 200, up.text
    imp = up.json()
    assert imp["status"] == "REVIEW" and imp["counts"]["ready"] + imp["counts"]["warning"] == 1
    assert client.get(f"/api/v1/planning/imports/{imp['id']}", headers=_auth(t)).json()["status"] == "REVIEW"
    ap = client.post(f"/api/v1/planning/imports/{imp['id']}/apply", headers=_auth(t), json={})
    assert ap.status_code == 200 and ap.json()["counts"]["applied"] == 1
    after = client.get(f"/api/v1/planning/setups/{sn}", headers=_auth(t)).json()["work_orders"][0]
    f2 = next(g for g in after["gates"] if g["stage"] == "F2")
    assert f2["planned_end"] == (T + timedelta(days=30)).isoformat() and f2["plan_source"] == "EXCEL"
    # on-screen edit with the current plan version, then a stale one
    ok = client.patch(f"/api/v1/planning/work-orders/{wo}/plan", headers=_auth(t), json={
        "gates": [{"stage": "FI", "planned_end": (T + timedelta(days=33)).isoformat()}], "reason": "slot moved",
        "expected_plan_version": after["plan_version"]})
    assert ok.status_code == 200
    stale = client.patch(f"/api/v1/planning/work-orders/{wo}/plan", headers=_auth(t), json={
        "gates": [{"stage": "FI", "planned_end": (T + timedelta(days=34)).isoformat()}], "reason": "again",
        "expected_plan_version": after["plan_version"]})
    assert stale.status_code == 409
    bad = client.patch(f"/api/v1/planning/work-orders/{wo}/plan", headers=_auth(t), json={
        "gates": [{"stage": "NOPE", "planned_end": T.isoformat()}], "reason": "bad gate"})
    assert bad.status_code == 400 and bad.json()["detail"]["issues"][0]["level"] == "ERROR"
    # undo the Excel import (F2 still as imported)
    un = client.post(f"/api/v1/planning/imports/{imp['id']}/undo", headers=_auth(t))
    assert un.status_code == 200 and un.json()["status"] == "UNDONE"
    # delay board and discard
    assert client.get("/api/v1/planning/delays?status=DELAYED,AT_RISK,NO_PLAN", headers=_auth(t)).status_code == 200
    up2 = client.post("/api/v1/planning/imports", headers=_auth(t), files={"file": ("plan.xlsx", buf.getvalue(), "application/octet-stream")})
    assert client.delete(f"/api/v1/planning/imports/{up2.json()['id']}", headers=_auth(t)).json()["status"] == "DISCARDED"
    # a bad upload is a clean 400
    bad_up = client.post("/api/v1/planning/imports", headers=_auth(t), files={"file": ("x.xlsx", b"junk", "application/octet-stream")})
    assert bad_up.status_code == 400


def test_existing_stage_plan_endpoint_keeps_working_and_bumps_the_version(client):
    tag = uuid.uuid4().hex[:6].upper()
    wo = _wo(tag)
    t = _user(client, UserRole.PLANNER)
    r = client.patch(f"/api/v1/work-orders/{wo}/stage-plan", headers=_auth(t), json={
        "stages": [{"stage": "F2", "planned_end": (T + timedelta(days=25)).isoformat()}], "reason": "manager edit"})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        w = db.query(WorkOrder).filter(WorkOrder.wo_number == wo).one()
        assert w.plan_version == 1
        assert db.query(WORoute).filter(WORoute.work_order_id == w.id, WORoute.stage == "F2").one().plan_source == "MANUAL"
    finally:
        db.close()


def test_digest_run_endpoint_needs_the_shared_token(client, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "")
    url = "/api/v1/planning/digest/run"
    monkeypatch.setattr(settings, "PLANNING_DIGEST_TOKEN", "")
    assert client.post(url, headers={"X-Planning-Digest-Token": "anything"}).status_code == 401   # off when empty
    monkeypatch.setattr(settings, "PLANNING_DIGEST_TOKEN", "right-token")
    assert client.post(url).status_code == 401
    assert client.post(url, headers={"X-Planning-Digest-Token": "wrong"}).status_code == 401
    ok = client.post(url, headers={"X-Planning-Digest-Token": "right-token"})
    assert ok.status_code == 200 and ok.json()["email_sent"] is False and "counts" in ok.json()


def test_export_all_and_digest_for_ppc(client):
    t = _user(client, UserRole.PLANNER)
    r = client.get("/api/v1/planning/export-all.xlsx?status=ALL", headers=_auth(t))
    assert r.status_code in (200, 400)           # 400 only when the database has no work orders in setups
    d = client.get("/api/v1/planning/digest", headers=_auth(t))
    assert d.status_code == 200 and set(d.json()["counts"]) == {"delayed", "at_risk", "no_plan"}
