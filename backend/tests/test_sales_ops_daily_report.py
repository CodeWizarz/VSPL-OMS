import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.models.work_order import WorkOrder, WOStatus
from app.models.order import Order, Customer, Part, OrderStatus
from app.models.packing import PackingRecord
from app.models.master_data import POMaster, POLine, POStatus
from app.models.user import User
from app.services.report_service import ReportService

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_sales_ops_daily_report_service_and_api(db: Session):
    # Setup test customer and part
    cust = Customer(
        customer_code="TEST-SO-CUST",
        name="Test SalesOps Customer",
        is_active=True
    )
    db.add(cust)
    db.flush()

    part = Part(
        part_number="TEST-SO-P1",
        grade="CI 250",
        description="Hydraulic Cylinder Body"
    )
    db.add(part)
    db.flush()

    # PO Master and Line with Unit Price
    po = POMaster(
        po_number="PO-SO-9999",
        customer_id=cust.id,
        po_date=date.today(),
        status=POStatus.OPEN
    )
    db.add(po)
    db.flush()

    line = POLine(
        po_id=po.id,
        part_id=part.id,
        po_qty=100,
        unit_price=450.0,
        line_total=45000.0
    )
    db.add(line)
    db.flush()

    # Order with today commitment date
    today = date.today()
    order = Order(
        oar_number="OAR-SO-101",
        customer_id=cust.id,
        part_id=part.id,
        customer_po=po.po_number,
        po_qty=50,
        customer_part_number="CUST-PART-XYZ",
        commitment_date=today,
        status=OrderStatus.ACCEPT,
        po_line_id=line.id
    )
    db.add(order)
    db.flush()

    # Work Order
    wo = WorkOrder(
        wo_number="WO-SO-TEST-1",
        order_id=order.id,
        physical_wo_qty=50,
        current_stage="F2",
        status=WOStatus.IN_PRODUCTION
    )
    db.add(wo)
    db.flush()

    # Packing record with 20 pcs ready in BSR
    pr = PackingRecord(
        work_order_id=wo.id,
        ready_for_dispatch_qty=20,
        packed_qty=20,
        dispatched_qty=0,
        status="In-Packing"
    )
    db.add(pr)
    db.commit()

    # Run Report Service
    res = ReportService.get_sales_ops_daily_report(db, target_date=today, preset="today")
    assert res is not None
    assert len(res.items) >= 1
    item = next(it for it in res.items if it.wo_number == "WO-SO-TEST-1")

    assert item.customer_name == "Test SalesOps Customer"
    assert item.customer_code == "TEST-SO-CUST"
    assert item.customer_po == "PO-SO-9999"
    assert item.part_number == "TEST-SO-P1"
    assert item.customer_part_number == "CUST-PART-XYZ"
    assert item.planned_qty == 50
    assert item.bsr_actual_qty == 20
    assert item.total_fulfilled_qty == 20
    assert item.gap_qty == 30
    assert item.unit_price == 450.0
    assert item.planned_value == 22500.0  # 50 * 450
    assert item.fulfilled_value == 9000.0  # 20 * 450
    assert item.gap_value == 13500.0      # 30 * 450
    assert item.current_stage == "F2"
    assert item.date_status == "TODAY"

    # Test CSV export
    csv_str = ReportService.generate_sales_ops_csv(db, target_date=today, preset="today")
    assert "WO-SO-TEST-1" in csv_str
    assert "TEST-SO-CUST" in csv_str
    assert "22500.00" in csv_str

    # Clean up test records
    db.delete(pr)
    db.delete(wo)
    db.delete(order)
    db.delete(line)
    db.delete(po)
    db.delete(part)
    db.delete(cust)
    db.commit()
