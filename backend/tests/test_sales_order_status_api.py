"""Only Sales and Admin may read the sales order status dashboard."""
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.models.user import UserRole
from tests.test_setup_planning_api import _auth, _login, _user  # noqa: F401


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()


@pytest.mark.parametrize("path", ["/api/v1/sales/order-status", "/api/v1/sales/order-status.xlsx",
                                  "/api/v1/sales/schedule-status", "/api/v1/sales/schedule-status.xlsx"])
def test_access(client, path):
    admin = _login(client, "admin@vspl.com", "admin123")
    assert client.get(path, headers=_auth(admin)).status_code == 200
    assert client.get(path, headers=_auth(_user(client, UserRole.SALES))).status_code == 200
    for role in (UserRole.PLANNER, UserRole.ACCOUNTS, UserRole.F1_SUPERVISOR, UserRole.OPERATOR, UserRole.SCM):
        assert client.get(path, headers=_auth(_user(client, role))).status_code == 403, role
    # the CEO role is treated as Admin everywhere in OMS
    assert client.get(path, headers=_auth(_user(client, UserRole.CEO))).status_code == 200
    assert client.get(path).status_code == 401
