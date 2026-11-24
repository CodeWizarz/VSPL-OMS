"""Records WHO changed WHAT: every create / edit / delete request to the API is logged with
the signed-in person's name, email and role, the screen action, the record it touched and
whether it succeeded.

Safety (this runs in front of production logic, so it must never get in its way):
- It does not change the request or the response. The request body is only *copied* as
  the app reads it (first 8 KB, JSON only) to pick out identifying fields; the app
  receives exactly the same messages it would without this middleware.
- Passwords, tokens and secrets are never stored (sign-in / password endpoints are
  skipped entirely, and any field whose name looks secret is dropped).
- Writing the log happens after the response is sent, in a worker thread, inside a
  try/except. If logging fails for any reason the user's action is unaffected.
"""
import json
import logging
from typing import Optional

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

LOGGED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ACTION_BY_METHOD = {"POST": "Create", "PUT": "Update", "PATCH": "Update", "DELETE": "Delete"}
# Never logged: sign-in and password flows (bodies hold credentials), and the temporary
# migration endpoint.
SKIP_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/change-password",
    "/api/v1/auth/register",
    "/api/v1/migration",
)
SECRET_HINTS = ("password", "token", "secret", "otp", "pin", "key")
# Request fields worth showing, in display order.
TARGET_KEYS = (
    "wo_number", "oar_number", "nc_number", "invoice_number", "po_number", "customer_po",
    "part_number", "customer_code", "schedule_number", "dc_number", "heat_number",
    "conversion_wo_number", "source_wo_number", "destination_oar_number", "email",
)
DETAIL_KEYS = (
    "stage", "from_stage", "to_stage", "good_qty", "rejected_quantity", "quantity_moved",
    "physical_wo_qty", "po_quantity", "quantity", "qty", "packed_quantity", "dispatched_quantity",
    "status", "action", "role", "secondary_role", "department", "full_name", "is_active",
    "route_stages", "casting_process", "reason", "remarks", "amount", "payment_status",
    "days", "stages", "planned_start", "planned_end", "name", "description", "grade",
)
MAX_BODY = 8192


def _is_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in SECRET_HINTS)


def _short(value) -> str:
    if isinstance(value, dict):
        value = ", ".join(f"{k}:{_short(v)}" for k, v in list(value.items())[:12] if not _is_secret(str(k)))
    elif isinstance(value, list):
        value = " -> ".join(_short(v) if isinstance(v, dict) else str(v) for v in value[:12])
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def summarize_body(raw: bytes) -> tuple[Optional[str], Optional[str]]:
    """(target, details) from a JSON request body; secrets are never included."""
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    target = " · ".join(_short(data[k]) for k in TARGET_KEYS if data.get(k) not in (None, "") and not _is_secret(k))
    details = ", ".join(
        f"{k}={_short(data[k])}" for k in DETAIL_KEYS if k in data and data[k] not in (None, "") and not _is_secret(k)
    )
    return (target or None), (details[:500] or None)


def target_from_path(path: str) -> Optional[str]:
    """Record identifiers that appear in the URL, e.g. /work-orders/WO-1001/stage-plan."""
    parts = [p for p in path.split("/") if p]
    ids = [p for p in parts[3:] if any(ch.isdigit() for ch in p)]
    return " · ".join(ids) or None


def _area(path: str) -> Optional[str]:
    parts = [p for p in path.split("/") if p]
    return parts[2] if len(parts) > 2 else None


def _write(entry: dict, auth_header: Optional[str]) -> None:
    from app.core.database import SessionLocal
    from app.core.security import decode_access_token
    from app.models.activity import ActivityLog
    from app.models.user import User

    db = SessionLocal()
    try:
        if auth_header and auth_header.lower().startswith("bearer "):
            payload = decode_access_token(auth_header[7:].strip()) or {}
            email = payload.get("sub")
            if email:
                user = db.query(User).filter(User.email == email).first()
                entry["user_email"] = email
                if user:
                    entry["user_id"] = str(user.id)
                    entry["user_name"] = user.full_name
                    role = getattr(user.role, "value", user.role)
                    sec = getattr(user.secondary_role, "value", user.secondary_role) if getattr(user, "secondary_role", None) else None
                    entry["user_role"] = f"{role} + {sec}" if sec else role
        db.add(ActivityLog(**entry))
        db.commit()
    except Exception as exc:  # never let logging affect anything
        db.rollback()
        logger.warning("Activity log write failed (%s)", type(exc).__name__)
    finally:
        db.close()


class ActivityLogMiddleware:
    """Pure ASGI middleware (no request/response rewriting)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        method = scope.get("method", "")
        path = scope.get("path", "")
        if method not in LOGGED_METHODS or not path.startswith("/api/") or path.startswith(SKIP_PREFIXES):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        is_json = "application/json" in headers.get("content-type", "")
        captured = bytearray()
        status_holder = {"code": None}

        async def receive_copy():
            message = await receive()
            if is_json and message.get("type") == "http.request" and len(captured) < MAX_BODY:
                captured.extend(message.get("body", b"")[: MAX_BODY - len(captured)])
            return message

        async def send_watch(message):
            if message.get("type") == "http.response.start":
                status_holder["code"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive_copy, send_watch)
        finally:
            try:
                code = status_holder["code"]
                body_target, details = summarize_body(bytes(captured)) if is_json else (None, None)
                target = " · ".join(t for t in (target_from_path(path), body_target) if t) or None
                client = scope.get("client") or ("", 0)
                entry = {
                    "action": ACTION_BY_METHOD.get(method, method),
                    "method": method,
                    "path": path[:300],
                    "area": _area(path),
                    "target": (target or "")[:300] or None,
                    "details": details,
                    "status_code": code,
                    "outcome": "Success" if code and code < 400 else ("Refused" if code and code < 500 else "Failed"),
                    "client_ip": headers.get("x-forwarded-for", client[0] if client else "")[:64],
                }
                await run_in_threadpool(_write, entry, headers.get("authorization"))
            except Exception as exc:  # never let logging affect anything
                logger.warning("Activity log skipped (%s)", type(exc).__name__)
