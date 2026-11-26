"""Sales order status dashboard: buckets, sources never double-counted, value, access, export."""
import io
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from tests.test_setup_planning import env, T, mkwo  # noqa: F401
from app.models.dispatch import Dispatch
from app.models.master_data import POLine, POMaster, ScheduleMaster, ScheduleStatus
from app.models.order import Order, OrderStatus
from app.services import sales_report_service as svc


def _order(env, po, qty, due, price_line=None, status=OrderStatus.ACCEPT, ref=None):
    o = Order(oar_number=ref or f"OAR-{po}", customer_id=env.cust.id, part_id=env.part.id, customer_po=po, po_qty=qty,
              delivery_date=due, status=status)
    env.db.add(o)
    env.db.commit()
    return o


def _po(env, number, qty, price, req):
    p = POMaster(po_number=number, customer_id=env.cust.id)
    env.db.add(p)
    env.db.flush()
    l = POLine(po_id=p.id, part_id=env.part.id, po_qty=qty, unit_price=price, line_total=qty * price, required_date=req)
    env.db.add(l)
    env.db.commit()
    return l


def test_buckets_follow_today_and_inr_grouping():
    b = svc.buckets_for(date(2026, 11, 26))
    assert [x["label"] for x in b] == ["Due up to Nov-2026", "Dec-2026 Delivery", "Jan-2027 Delivery", "Feb-2027 Delivery", "Beyond Feb-2027"]
    assert svc._inr(103509629) == "10,35,09,629" and svc._inr(999) == "999" and svc._inr(1536) == "1,536"
    assert svc._bucket_key(date(2026, 10, 1), b) == "DUE" and svc._bucket_key(date(2026, 11, 30), b) == "DUE"
    assert svc._bucket_key(date(2026, 12, 1), b) == "M1" and svc._bucket_key(date(2027, 3, 1), b) == "BEYOND"
    assert svc._bucket_key(None, b) == "NODATE"


def test_oar_pending_value_dispatch_and_po_price_matching(env):
    _po(env, "PO-A", 100, 50.0, date(2026, 12, 5))
    _order(env, "PO-A", 100, date(2026, 12, 10))                       # price found by PO number + customer + part
    o2 = _order(env, "PO-B", 10, date(2026, 11, 1))                    # no price anywhere
    _order(env, "PO-R", 10, date(2026, 11, 1), status=OrderStatus.REJECT)
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    by = {b["key"]: b for b in rep["buckets"]}
    assert by["M1"]["count"] == 1 and by["M1"]["value"] == 5000.0
    assert by["DUE"]["count"] == 1 and by["DUE"]["value"] == 0.0 and rep["no_price_count"] == 1
    assert rep["overdue"]["count"] == 1                                 # PO-B is past due; the rejected order is not counted
    # dispatch reduces pending
    wo = mkwo(env, "WO-D1", qty=100)
    wo.order_id = env.db.query(Order).filter(Order.customer_po == "PO-A").one().id
    env.db.add(Dispatch(work_order_id=wo.id, dispatched_qty=40, customer_po="PO-A"))
    env.db.commit()
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    assert {b["key"]: b for b in rep["buckets"]}["M1"]["value"] == 3000.0


def test_sources_are_never_double_counted(env):
    line = _po(env, "PO-C", 100, 10.0, date(2027, 1, 15))
    # nothing ordered yet: the PO line is the pending item
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    assert rep["by_source"]["PO_LINE"]["count"] == 1 and rep["by_source"]["OAR"]["count"] == 0
    _order(env, "PO-C", 60, date(2027, 1, 15))                          # now 60 are an OAR; 40 remain on the PO line
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    items = {i["source"]: i for i in rep["items"]}
    assert items["OAR"]["pending_qty"] == 60 and items["PO_LINE"]["pending_qty"] == 40
    assert rep["total"]["value"] == 1000.0
    _order(env, "PO-C", 40, date(2027, 1, 15), ref="OAR-PO-C2")
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    assert rep["by_source"]["PO_LINE"]["count"] == 0 and rep["total"]["value"] == 1000.0
    only = svc.build_report(env.db, include=["OAR"], today=date(2026, 11, 26))
    assert only["by_source"]["PO_LINE"]["count"] == 0


def test_schedules_without_oar_count_and_matched_ones_do_not(env):
    s1 = ScheduleMaster(schedule_number="SCH-1", customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=20, unit_price=5.0,
                        total_value=100.0, required_date=date(2026, 12, 20), po_status=ScheduleStatus.AWAITING_PO)
    s2 = ScheduleMaster(schedule_number="SCH-2", customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=20, unit_price=5.0,
                        total_value=100.0, required_date=date(2026, 12, 20), po_status=ScheduleStatus.MATCHED)
    env.db.add_all([s1, s2])
    env.db.commit()
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    assert rep["by_source"]["SCHEDULE"]["count"] == 1 and rep["total"]["value"] == 100.0


def test_export_workbook_has_dashboard_and_detail(env):
    _po(env, "PO-X", 10, 100.0, date(2026, 12, 5))
    wb = load_workbook(io.BytesIO(svc.export_report(env.db, today=date(2026, 11, 26))))
    ws = wb["Dashboard"]
    assert ws["A1"].value == "Sales Order Status" and "26 Nov 2026" in ws["A2"].value
    assert any(c.value == "TOTAL" for row in ws.iter_rows() for c in row)
    assert wb["Details"].max_row >= 2 and ws._charts


def test_bucket_split_by_source(env):
    _po(env, "PO-S", 10, 100.0, date(2026, 12, 5))
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    m1 = {b["key"]: b for b in rep["buckets"]}["M1"]
    assert m1["by_source"]["PO_LINE"] == {"count": 1, "value": 1000.0} and m1["by_source"]["OAR"]["count"] == 0


def test_schedule_report_and_export(env):
    def sch(no, status, qty, price, req):
        env.db.add(ScheduleMaster(schedule_number=no, customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=qty, unit_price=price,
                                  total_value=qty * price, required_date=req, po_status=status))
    sch("S-1", ScheduleStatus.AWAITING_PO, 10, 100.0, date(2026, 11, 10))      # overdue
    sch("S-2", ScheduleStatus.SCHEDULED, 20, 50.0, date(2026, 12, 20))
    sch("S-3", ScheduleStatus.MATCHED, 99, 99.0, date(2026, 12, 20))           # converted: not open
    sch("S-4", ScheduleStatus.CANCELLED, 99, 99.0, date(2026, 12, 20))
    env.db.commit()
    r = svc.build_schedule_report(env.db, today=date(2026, 11, 26))
    assert r["total"] == {"count": 2, "value": 2000.0, "qty": 30}
    assert r["awaiting_po"] == {"count": 1, "value": 1000.0} and r["overdue"]["count"] == 1
    assert {x["status"]: x["count"] for x in r["status_split"]}["matched"] == 1
    wb = load_workbook(io.BytesIO(svc.export_schedule_report(env.db, today=date(2026, 11, 26))))
    assert wb["Dashboard"]["A1"].value == "Customer Schedule Status"
