import io
import csv
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_, and_
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.order import Order, Customer, Part
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.bsr_stock import BSRStock
from app.models.vendor import VendorDispatch
from app.models.nc import NCRecord
from app.schemas.reports import (
    SalesOpsDailyReportResponse,
    SalesOpsDailyItem,
    SalesOpsSummary,
)

class ReportService:
    @staticmethod
    def generate_wip_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        
        stages = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
        writer.writerow(["WO Number", "Customer", "Customer PO", "Part Number", "Delivery Date", "Current Stage", "Status", "Order Qty"] + stages + ["Total WIP"])

        active_wos = db.query(WorkOrder).filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])).all()
        for wo in active_wos:
            order = wo.order
            cust = order.customer.name if (order and order.customer) else "N/A"
            po = order.customer_po if order else "N/A"
            part = order.part.part_number if (order and order.part) else "N/A"
            # Authoritative delivery date from OMS order data -- never invented or
            # derived from anything else.
            delivery_date = order.delivery_date.strftime("%Y-%m-%d") if (order and order.delivery_date) else ""

            wips = {w.stage.upper(): w.available_wip for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
            if not wips:
                wips[wo.current_stage.upper()] = wo.physical_wo_qty

            row = [
                wo.wo_number,
                cust,
                po,
                part,
                delivery_date,
                wo.current_stage,
                wo.status.value,
                wo.physical_wo_qty
            ]
            for s in stages:
                row.append(wips.get(s, 0))
            row.append(sum(wips.values()))
            writer.writerow(row)

        return output.getvalue()

    @staticmethod
    def generate_movements_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Movement ID", "Timestamp", "WO Number", "Part Number", "From Stage", "To Stage", "Qty Moved", "Qty Rejected", "Machine", "Operator", "Shift", "Remarks"])

        movements = db.query(ProductionMovement).order_by(ProductionMovement.created_at.desc()).all()
        for m in movements:
            wo = m.work_order
            part = wo.order.part.part_number if (wo and wo.order and wo.order.part) else "N/A"
            writer.writerow([
                m.movement_id,
                m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
                wo.wo_number if wo else "N/A",
                part,
                m.from_stage,
                m.to_stage,
                m.quantity_moved,
                m.rejected_quantity,
                m.machine_id or "",
                m.operator_name or "",
                m.shift or "",
                m.remarks or ""
            ])

        return output.getvalue()

    @staticmethod
    def generate_dispatch_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Invoice Number", "Date", "WO Number", "Customer", "Customer PO", "Part Number", "Dispatched Qty", "Dispatcher"])

        dispatches = db.query(Dispatch).order_by(Dispatch.dispatch_date.desc()).all()
        for d in dispatches:
            wo = d.work_order
            order = wo.order if wo else None
            cust = order.customer.name if (order and order.customer) else "N/A"
            po = d.customer_po or (order.customer_po if order else "")
            part = order.part.part_number if (order and order.part) else "N/A"
            dispatcher = d.dispatcher.full_name if d.dispatcher else "Dispatch Dept"

            writer.writerow([
                d.invoice_number,
                d.dispatch_date.strftime("%Y-%m-%d") if d.dispatch_date else "",
                wo.wo_number if wo else "N/A",
                cust,
                po,
                part,
                d.dispatched_qty,
                dispatcher
            ])

        return output.getvalue()

    @staticmethod
    def get_sales_ops_daily_report(
        db: Session,
        target_date: Optional[date] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        preset: str = "today",
        status_filter: str = "all",
        search: Optional[str] = None,
        sort_by: str = "priority",
    ) -> SalesOpsDailyReportResponse:
        from app.services.dispatch_service import DispatchService

        today_ref = target_date or date.today()
        preset_clean = (preset or "today").lower().strip()
        status_clean = (status_filter or "all").lower().strip()

        eff_comm_date_col = func.coalesce(Order.revised_commitment_date, Order.commitment_date)

        query = db.query(WorkOrder).join(WorkOrder.order)

        if preset_clean == "today":
            query = query.filter(eff_comm_date_col == today_ref)
        elif preset_clean == "tomorrow":
            query = query.filter(eff_comm_date_col == today_ref + timedelta(days=1))
        elif preset_clean == "this_week":
            query = query.filter(eff_comm_date_col.between(today_ref, today_ref + timedelta(days=7)))
        elif preset_clean == "overdue_and_today":
            query = query.filter(
                eff_comm_date_col <= today_ref,
                WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])
            )
        elif preset_clean == "all_active":
            query = query.filter(WorkOrder.status != WOStatus.CLOSED)
        elif preset_clean == "custom":
            if from_date and to_date:
                query = query.filter(eff_comm_date_col.between(from_date, to_date))
            elif from_date:
                query = query.filter(eff_comm_date_col >= from_date)
            elif to_date:
                query = query.filter(eff_comm_date_col <= to_date)

        wos = query.all()
        if not wos:
            return SalesOpsDailyReportResponse(
                target_date=today_ref,
                filter_preset=preset_clean,
                summary=SalesOpsSummary(),
                items=[]
            )

        wo_ids = [w.id for w in wos]
        part_ids = list({w.order.part_id for w in wos if w.order and w.order.part_id})

        # Pre-fetch packing records
        packing_records = db.query(PackingRecord).filter(PackingRecord.work_order_id.in_(wo_ids)).all()
        packing_map = {pr.work_order_id: pr for pr in packing_records}

        # Pre-fetch dispatches
        dispatch_rows = db.query(
            Dispatch.work_order_id,
            func.coalesce(func.sum(Dispatch.dispatched_qty), 0)
        ).filter(Dispatch.work_order_id.in_(wo_ids)).group_by(Dispatch.work_order_id).all()
        dispatch_map = {row[0]: int(row[1]) for row in dispatch_rows}

        # Pre-fetch BSR stock per WO
        bsr_wo_rows = db.query(
            BSRStock.source_wo_id,
            func.coalesce(func.sum(BSRStock.available_qty + BSRStock.allocated_qty), 0)
        ).filter(BSRStock.source_wo_id.in_(wo_ids)).group_by(BSRStock.source_wo_id).all()
        bsr_wo_map = {row[0]: int(row[1]) for row in bsr_wo_rows}

        # Pre-fetch free BSR stock per Part
        part_bsr_rows = db.query(
            BSRStock.part_id,
            func.coalesce(func.sum(BSRStock.available_qty), 0)
        ).filter(
            BSRStock.part_id.in_(part_ids),
            BSRStock.available_qty > 0
        ).group_by(BSRStock.part_id).all()
        part_bsr_map = {row[0]: int(row[1]) for row in part_bsr_rows}

        # Pre-fetch stage WIPs
        stage_wip_rows = db.query(StageWIP).filter(StageWIP.work_order_id.in_(wo_ids)).all()
        stage_wip_map: Dict[Any, Dict[str, int]] = {}
        for sw in stage_wip_rows:
            stage_wip_map.setdefault(sw.work_order_id, {})[sw.stage.upper()] = sw.available_wip or 0

        # Pre-fetch vendor dispatches
        v_dispatches = db.query(VendorDispatch).filter(
            VendorDispatch.work_order_id.in_(wo_ids),
            VendorDispatch.status.in_(["AT_VENDOR", "PARTIALLY_RECEIVED"])
        ).order_by(VendorDispatch.created_at.desc()).all()
        vendor_map = {}
        for vd in v_dispatches:
            if vd.work_order_id not in vendor_map:
                rem = max(vd.dispatched_qty - (vd.received_qty or 0) - (vd.scrap_qty or 0), 0)
                vendor_map[vd.work_order_id] = {
                    "is_at_vendor": True,
                    "vendor_name": vd.vendor_name,
                    "vendor_dc": vd.dc_number,
                    "vendor_qty": rem,
                    "vendor_stage": vd.dispatch_stage,
                }

        items: List[SalesOpsDailyItem] = []

        for wo in wos:
            order = wo.order
            cust = order.customer if order else None
            part = order.part if order else None

            cust_name = cust.name if cust else "Unknown Customer"
            cust_code = cust.customer_code if cust else "N/A"
            cust_po = order.customer_po if order else "N/A"
            part_no = part.part_number if part else "N/A"
            cust_part_no = order.customer_part_number if order else ""
            part_name = part.description if part else ""
            grade = part.grade if part else ""
            oar_no = order.oar_number if order else ""

            comm_date = order.commitment_date if order else None
            rev_comm_date = order.revised_commitment_date if order else None
            eff_date = rev_comm_date or comm_date
            rev_count = order.commitment_date_revision_count if order else 0
            deliv_date = order.delivery_date if order else None

            # Date status
            if not eff_date:
                date_status = "UNDATED"
            elif eff_date < today_ref:
                date_status = "OVERDUE"
            elif eff_date == today_ref:
                date_status = "TODAY"
            elif eff_date == today_ref + timedelta(days=1):
                date_status = "TOMORROW"
            elif eff_date <= today_ref + timedelta(days=7):
                date_status = "THIS_WEEK"
            else:
                date_status = "FUTURE"

            planned_qty = wo.physical_wo_qty or 0

            pr = packing_map.get(wo.id)
            bsr_ready = pr.ready_for_dispatch_qty if pr else 0
            bsr_banked = bsr_wo_map.get(wo.id, 0)
            bsr_actual = max(bsr_ready, bsr_banked)

            dispatched_from_pr = pr.dispatched_qty if pr else 0
            dispatched_from_db = dispatch_map.get(wo.id, 0)
            dispatched = max(dispatched_from_pr, dispatched_from_db)

            # If order is marked dispatched/closed
            if wo.status in (WOStatus.DISPATCHED, WOStatus.CLOSED):
                dispatched = max(dispatched, planned_qty)

            total_fulfilled = bsr_actual + dispatched
            gap = max(0, planned_qty - total_fulfilled)

            part_bsr_avail = part_bsr_map.get(order.part_id, 0) if (order and order.part_id) else 0

            # Vendor status
            v_info = vendor_map.get(wo.id)
            is_at_vendor = bool(v_info)
            vendor_name = v_info.get("vendor_name") if v_info else None
            vendor_dc = v_info.get("vendor_dc") if v_info else None
            vendor_qty = v_info.get("vendor_qty") if v_info else None
            vendor_stage = v_info.get("vendor_stage") if v_info else None

            # Stage WIP breakdown
            wips = stage_wip_map.get(wo.id, {})
            if not wips:
                wips[wo.current_stage.upper()] = planned_qty

            # Price lookup
            price_data = DispatchService.lookup_product_pricing(
                db,
                customer_code=cust_code,
                part_number=part_no,
                wo_number=wo.wo_number
            )
            unit_price = float(price_data.get("unit_price") or 0.0)
            price_source = str(price_data.get("source") or "DEFAULT")

            planned_val = round(planned_qty * unit_price, 2)
            fulfilled_val = round(min(total_fulfilled, planned_qty) * unit_price, 2)
            gap_val = round(gap * unit_price, 2)

            # Fulfillment Status
            if dispatched >= planned_qty:
                fulfillment_status = "DISPATCHED"
            elif gap == 0:
                fulfillment_status = "READY_IN_BSR"
            elif is_at_vendor:
                fulfillment_status = "AT_VENDOR"
            elif date_status == "OVERDUE":
                fulfillment_status = "OVERDUE_DEFICIT"
            else:
                fulfillment_status = "WIP_IN_HOUSE"

            # Filter checks
            if status_clean == "gaps_only" and gap == 0:
                continue
            if status_clean == "ready_only" and gap > 0:
                continue
            if status_clean == "at_vendor" and not is_at_vendor:
                continue
            if status_clean == "overdue" and not (date_status == "OVERDUE" and gap > 0):
                continue

            if search:
                term = search.lower().strip()
                searchable = f"{wo.wo_number} {cust_name} {cust_code} {cust_po} {part_no} {cust_part_no} {part_name}".lower()
                if term not in searchable:
                    continue

            item = SalesOpsDailyItem(
                wo_id=str(wo.id),
                wo_number=wo.wo_number,
                customer_name=cust_name,
                customer_code=cust_code,
                customer_po=cust_po,
                part_id=str(part.id) if part else "",
                part_number=part_no,
                customer_part_number=cust_part_no,
                part_name=part_name,
                grade=grade,
                oar_number=oar_no,
                commitment_date=comm_date,
                revised_commitment_date=rev_comm_date,
                effective_commitment_date=eff_date,
                commitment_date_revision_count=rev_count,
                delivery_date=deliv_date,
                date_status=date_status,
                planned_qty=planned_qty,
                bsr_actual_qty=bsr_actual,
                dispatched_qty=dispatched,
                total_fulfilled_qty=total_fulfilled,
                gap_qty=gap,
                part_bsr_stock=part_bsr_avail,
                current_stage=wo.current_stage or "F1",
                is_at_vendor=is_at_vendor,
                vendor_name=vendor_name,
                vendor_dc=vendor_dc,
                vendor_qty=vendor_qty,
                vendor_stage=vendor_stage,
                stage_wip=wips,
                unit_price=unit_price,
                price_source=price_source,
                planned_value=planned_val,
                fulfilled_value=fulfilled_val,
                gap_value=gap_val,
                fulfillment_status=fulfillment_status,
                wo_status=wo.status.value,
                heat_number=wo.heat_number,
            )
            items.append(item)

        # Sorting
        date_rank_order = {"OVERDUE": 0, "TODAY": 1, "TOMORROW": 2, "THIS_WEEK": 3, "FUTURE": 4, "UNDATED": 5}
        if sort_by == "priority":
            items.sort(
                key=lambda it: (
                    date_rank_order.get(it.date_status, 9),
                    0 if it.gap_qty > 0 else 1,
                    -it.gap_value,
                    -it.planned_value,
                    it.effective_commitment_date or date.max
                )
            )
        elif sort_by == "value_desc":
            items.sort(key=lambda it: -it.planned_value)
        elif sort_by == "date_asc":
            items.sort(key=lambda it: (it.effective_commitment_date or date.max, -it.planned_value))
        elif sort_by == "gap_desc":
            items.sort(key=lambda it: (-it.gap_qty, -it.gap_value))
        elif sort_by == "customer":
            items.sort(key=lambda it: (it.customer_name, -it.planned_value))

        # Compute summary
        tot_planned_qty = sum(it.planned_qty for it in items)
        tot_bsr_qty = sum(it.bsr_actual_qty for it in items)
        tot_disp_qty = sum(it.dispatched_qty for it in items)
        tot_fulfilled_qty = sum(min(it.total_fulfilled_qty, it.planned_qty) for it in items)
        tot_gap_qty = sum(it.gap_qty for it in items)
        tot_planned_val = round(sum(it.planned_value for it in items), 2)
        tot_fulfilled_val = round(sum(it.fulfilled_value for it in items), 2)
        tot_gap_val = round(sum(it.gap_value for it in items), 2)
        fulfillment_pct = round((tot_fulfilled_qty / tot_planned_qty * 100), 1) if tot_planned_qty > 0 else 100.0

        overdue_items = [it for it in items if it.date_status == "OVERDUE" and it.gap_qty > 0]
        today_items = [it for it in items if it.date_status == "TODAY"]

        summary = SalesOpsSummary(
            total_orders=len(items),
            total_planned_qty=tot_planned_qty,
            total_bsr_actual_qty=tot_bsr_qty,
            total_dispatched_qty=tot_disp_qty,
            total_fulfilled_qty=tot_fulfilled_qty,
            total_gap_qty=tot_gap_qty,
            fulfillment_rate=fulfillment_pct,
            total_planned_value=tot_planned_val,
            total_fulfilled_value=tot_fulfilled_val,
            total_gap_value=tot_gap_val,
            overdue_orders_count=len(overdue_items),
            overdue_gap_value=round(sum(it.gap_value for it in overdue_items), 2),
            today_orders_count=len(today_items),
            today_gap_value=round(sum(it.gap_value for it in today_items if it.gap_qty > 0), 2),
            at_vendor_count=sum(1 for it in items if it.is_at_vendor),
        )

        return SalesOpsDailyReportResponse(
            target_date=today_ref,
            filter_preset=preset_clean,
            summary=summary,
            items=items
        )

    @staticmethod
    def generate_sales_ops_csv(
        db: Session,
        target_date: Optional[date] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        preset: str = "today",
        status_filter: str = "all",
        search: Optional[str] = None,
        sort_by: str = "priority",
    ) -> str:
        report = ReportService.get_sales_ops_daily_report(
            db=db,
            target_date=target_date,
            from_date=from_date,
            to_date=to_date,
            preset=preset,
            status_filter=status_filter,
            search=search,
            sort_by=sort_by
        )
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["VSPL SMES - SALES-OPS DAILY MEETING REPORT (PLAN VS ACTUAL)"])
        writer.writerow([
            "Target Date",
            report.target_date.strftime("%Y-%m-%d") if report.target_date else "N/A",
            "Filter Preset",
            report.filter_preset
        ])
        writer.writerow([
            f"Total Orders: {report.summary.total_orders}",
            f"Planned Pcs: {report.summary.total_planned_qty}",
            f"BSR Ready: {report.summary.total_bsr_actual_qty}",
            f"Dispatched: {report.summary.total_dispatched_qty}",
            f"Gap Deficit: {report.summary.total_gap_qty}",
            f"Fulfillment: {report.summary.fulfillment_rate}%",
            f"Planned Value: Rs.{report.summary.total_planned_value:,.2f}",
            f"Gap Value: Rs.{report.summary.total_gap_value:,.2f}"
        ])
        writer.writerow([])

        headers = [
            "Rank",
            "WO Number",
            "Customer Code",
            "Customer Name",
            "Customer PO",
            "Customer Part No",
            "Internal Part ID",
            "Part Description",
            "Grade",
            "Effective Commitment Date",
            "Revision Count",
            "Date Status",
            "Planned Qty (Pcs)",
            "BSR Ready (Pcs)",
            "Dispatched Qty (Pcs)",
            "Total Fulfilled (Pcs)",
            "Gap Deficit (Pcs)",
            "Free BSR Stock (Pcs)",
            "Current Stage",
            "At Vendor?",
            "Vendor Details",
            "Unit Price (Rs.)",
            "Planned Value (Rs.)",
            "Realized Value (Rs.)",
            "Gap Value (Rs.)",
            "Fulfillment Status",
            "WO Status",
            "Heat Number"
        ]
        writer.writerow(headers)

        for idx, it in enumerate(report.items, start=1):
            vendor_str = f"{it.vendor_name or 'Vendor'} ({it.vendor_qty or 0} pcs, DC: {it.vendor_dc or 'N/A'})" if it.is_at_vendor else "No"
            writer.writerow([
                idx,
                it.wo_number,
                it.customer_code,
                it.customer_name,
                it.customer_po,
                it.customer_part_number or "",
                it.part_number,
                it.part_name or "",
                it.grade or "",
                it.effective_commitment_date.strftime("%Y-%m-%d") if it.effective_commitment_date else "N/A",
                it.commitment_date_revision_count,
                it.date_status,
                it.planned_qty,
                it.bsr_actual_qty,
                it.dispatched_qty,
                it.total_fulfilled_qty,
                it.gap_qty,
                it.part_bsr_stock,
                it.current_stage,
                "YES" if it.is_at_vendor else "NO",
                vendor_str,
                f"{it.unit_price:.2f}",
                f"{it.planned_value:.2f}",
                f"{it.fulfilled_value:.2f}",
                f"{it.gap_value:.2f}",
                it.fulfillment_status,
                it.wo_status,
                it.heat_number or ""
            ])

        return output.getvalue()
