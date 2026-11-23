"""Subcontracting (SP) view: what to send to the subcontractor, what is at the vendor,
and what should come back today / in the next two days.

- "Ready to send" comes from OMS itself: material that has reached the SP stage (moved
  there from the previous process) and is still at SP.
- "At vendor" and "expected back" come READ-ONLY from the DC (Delivery Challan) software
  via its /api/integrations/oms/dcs endpoint, matched on WO number. OMS never writes to
  the DC app. If the link is not configured or the DC app is unreachable, the SP view
  still works and reports that DC data is unavailable.

Quantities from the DC app are shown in the DC's own unit (it may be kg or pieces);
they are not converted or added to OMS piece counts.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.departments import normalize_stage
from app.models.production_movement import StageWIP
from app.models.work_order import WorkOrder, WOStatus

logger = logging.getLogger(__name__)


class DCClient:
    """Minimal read-only client for the DC software's OMS integration endpoint."""

    @staticmethod
    def configured() -> bool:
        return bool(settings.DC_API_URL.strip() and settings.DC_API_TOKEN.strip())

    @staticmethod
    def fetch_open_dcs(wo_numbers: List[str]) -> Tuple[Optional[List[Dict]], Optional[str]]:
        """(dcs, error). dcs is None when the DC data could not be fetched."""
        if not DCClient.configured():
            return None, "The DC software link is not configured (DC_API_URL / DC_API_TOKEN)."
        if not wo_numbers:
            return [], None
        query = urllib.parse.urlencode({"woNumber": ",".join(wo_numbers[:200]), "openOnly": "true"})
        url = settings.DC_API_URL.rstrip("/") + "/api/integrations/oms/dcs?" + query
        req = urllib.request.Request(url, headers={"x-oms-token": settings.DC_API_TOKEN, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=settings.DC_API_TIMEOUT_SECONDS) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            dcs = body.get("dcs")
            if not isinstance(dcs, list):
                return None, "The DC software returned an unexpected response."
            return dcs, None
        except urllib.error.HTTPError as exc:
            logger.warning("DC integration HTTP %s", exc.code)
            return None, f"The DC software refused the request (HTTP {exc.code})."
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("DC integration unavailable: %s", type(exc).__name__)
            return None, "The DC software is unreachable right now."


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class SubcontractService:
    @staticmethod
    def summary(db: Session, days: int = 2, today: Optional[date] = None, client=DCClient) -> Dict:
        today = today or date.today()

        ready: List[Dict] = []
        sp_wos: List[str] = []
        active = (
            db.query(WorkOrder)
            .filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED]))
            .all()
        )
        for wo in active:
            wips = [
                w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()
                if normalize_stage(w.stage) == "SP"
            ]
            qty = sum(w.available_wip or 0 for w in wips)
            if qty <= 0:
                continue
            sp_wos.append(wo.wo_number)
            order = wo.order
            ready.append({
                "wo_number": wo.wo_number,
                "customer_name": order.customer.name if order and order.customer else None,
                "part_number": order.part.part_number if order and order.part else None,
                "qty_at_sp": qty,
                "delivery_date": order.delivery_date.isoformat() if order and order.delivery_date else None,
            })

        # Ask the DC app about every active WO, not just those at SP -- a WO's material can
        # be out on a DC while OMS already shows it further along.
        dcs, dc_error = client.fetch_open_dcs([wo.wo_number for wo in active])

        at_vendor: List[Dict] = []
        due_back = {"overdue": [], "today": [], "next": []}
        sent_wos = set()
        if dcs is not None:
            for dc in dcs:
                if dc.get("closed"):
                    continue
                if not dc.get("sentAt"):
                    continue  # DC raised but material not yet out of the gate
                sent_wos.add(dc.get("woNumber"))
                exp = _parse_date(dc.get("expectedReturnDate"))
                entry = {
                    "dc_number": dc.get("dcNumber"),
                    "wo_number": dc.get("woNumber"),
                    "part_number": dc.get("partNumber"),
                    "vendor_name": dc.get("vendorName"),
                    "status": dc.get("status"),
                    "quantity_sent": dc.get("quantitySent"),
                    "quantity_returned": dc.get("quantityReturned"),
                    "unit": dc.get("unit"),
                    "sent_at": dc.get("sentAt"),
                    "expected_return_date": exp.isoformat() if exp else None,
                    "days_to_return": (exp - today).days if exp else None,
                }
                at_vendor.append(entry)
                if exp is not None:
                    delta = (exp - today).days
                    if delta < 0:
                        due_back["overdue"].append(entry)
                    elif delta == 0:
                        due_back["today"].append(entry)
                    elif delta <= days:
                        due_back["next"].append(entry)

        for r in ready:
            r["already_on_dc"] = r["wo_number"] in sent_wos
        at_vendor.sort(key=lambda e: (e["days_to_return"] is None, e["days_to_return"] or 0))

        return {
            "today": today.isoformat(),
            "days": days,
            "ready_to_send": ready,
            "dc_available": dcs is not None,
            "dc_message": dc_error,
            "at_vendor": at_vendor,
            "due_back": due_back,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
