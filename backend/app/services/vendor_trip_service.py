"""Vendor trips: pieces of a work order that leave a gate for a vendor and come back.

Design: docs/vendor-trips-architecture.md.

The one rule: a vendor trip MOVES pieces, it never produces them. A piece is counted as
done at a gate exactly once, either by an in-house production entry or by SCM marking
"gate work done" when it returns from a vendor.

  * send()          takes pieces out of the gate's UNPROCESSED or COMPLETED state. It touches
                    no production counter (ok / rejected / entered); recompute_work_order
                    removes the pieces from that state because they are at the vendor.
  * record_return() puts pieces back. SCM enters the RECEIVE GATE (default: the gate they left
                    from, or any later gate of the released route); the outcome follows from it:
                      left unprocessed, same gate   -> back to unprocessed (a later entry counts them)
                      left unprocessed, later gate  -> the gate's work is counted as done once, the
                                                       pieces enter the receive gate
                      left completed, same gate     -> back to completed (never counted again)
                      left completed, later gate    -> enter the receive gate (already counted)
                    There is no MRB at receipt: pieces sent out as completed have any pending review
                    approved when they are sent (see _approve_pending_for_sent). Scrap stays on the
                    trip and is counted in the balance.
  * cancel()        only while nothing has come back; pieces return to where they left from.

recompute_work_order is the single writer of the derived gate counts; the only thing that
changes a gate's good count here is a return received at a LATER gate for pieces that left unprocessed,
through its own production entry.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.departments import assert_user_may_post_at
from app.models.audit import AuditLog
from app.models.mrb import MRBReview, next_mrb_number
from app.models.production import ProductionStatus, ProductionUpdate
from app.models.production_movement import StageWIP
from app.models.user import User, UserRole
from app.models.vendor import VendorDispatch, VendorTripReturn
from app.models.work_order import WORoute, WorkOrder, WOStatus
from app.services.oms_integration_service import OMSIntegrationService, match_route_stage

# SCM = the Supply Chain Manager role, Subcontracting managers/supervisors, plus admin, production manager and CEO.
SCM_ROLES = (
    UserRole.SCM, UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.CEO,
    UserRole.SP_MANAGER, UserRole.SP_SUPERVISOR,
)
UNPROCESSED = "UNPROCESSED"
COMPLETED = "COMPLETED"
MORE_WORK = "MORE_WORK"
BACK_TO_COMPLETED = "BACK_TO_COMPLETED"
MOVED_ON = "MOVED_ON"

# Packing / dispatch quantities are driven by the packing record, not by gate stock.
_NO_TRIP_STAGES = ("PACKING", "BSR", "PACKING / BSR", "PACKING/BSR", "DISPATCH")


def is_scm(user: Optional[User]) -> bool:
    if user is None:
        return False
    roles = [user.role, getattr(user, "secondary_role", None)]
    return any(r in SCM_ROLES for r in roles if r is not None)


def _bad(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _remaining(trip: VendorDispatch) -> int:
    if trip.status not in ("AT_VENDOR", "PARTIALLY_RECEIVED"):
        return 0
    return max(trip.dispatched_qty - (trip.received_qty or 0) - (trip.scrap_qty or 0), 0)


class VendorTripService:
    @staticmethod
    def enabled() -> bool:
        return bool(settings.VENDOR_TRIPS_ENABLED)

    @staticmethod
    def _require_enabled() -> None:
        if not VendorTripService.enabled():
            raise _bad("Vendor trips are not enabled yet. Use the existing vendor flow.")

    @staticmethod
    def _require_scm(user: Optional[User], action: str) -> None:
        if not is_scm(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only SCM (Subcontracting), Production Manager or Admin can {action}."
            )

    # ------------------------------------------------------------------ gate state
    @staticmethod
    def gate_state(db: Session, wo_number: str, stage: str) -> Dict[str, Any]:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == (wo_number or "").strip()).first()
        if not wo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work Order '{wo_number}' not found.")
        routes = [r.stage for r in db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()]
        matched = match_route_stage(stage, routes)
        if not matched:
            raise _bad(f"Stage '{stage}' is not part of the route for WO '{wo.wo_number}'.")
        wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == matched).first()
        trips = db.query(VendorDispatch).filter(
            VendorDispatch.work_order_id == wo.id,
            VendorDispatch.dispatch_stage == matched,
            VendorDispatch.source_state.isnot(None),
        ).all()
        out_u = sum(_remaining(t) for t in trips if t.source_state == UNPROCESSED)
        out_c = sum(_remaining(t) for t in trips if t.source_state == COMPLETED)
        return {
            "wo_number": wo.wo_number,
            "stage": matched,
            "unprocessed_qty": (wip.inproc_qty or 0) if wip else 0,
            "completed_qty": (wip.onhand_qty or 0) if wip else 0,
            "at_vendor_from_unprocessed_qty": out_u,
            "at_vendor_from_completed_qty": out_c,
            "trips_enabled": VendorTripService.enabled(),
        }

    # ------------------------------------------------------------------------ send
    @staticmethod
    def send(
        db: Session,
        wo_number: str,
        stage: str,
        quantity: int,
        vendor_name: str,
        dc_number: str,
        source_state: Optional[str] = None,
        process_name: Optional[str] = None,
        remarks: Optional[str] = None,
        current_user: Optional[User] = None,
        origin: str = "PE",
    ) -> Dict[str, Any]:
        VendorTripService._require_enabled()
        from app.services.production_service import ProductionService

        vendor = (vendor_name or "").strip()
        dc = (dc_number or "").strip()
        if not vendor or not dc:
            raise _bad("Vendor name and DC number are required to send pieces to a vendor.")
        if quantity is None or quantity <= 0:
            raise _bad("Quantity to send must be greater than zero.")
        if source_state is not None and source_state not in (UNPROCESSED, COMPLETED):
            raise _bad("source_state must be UNPROCESSED or COMPLETED.")

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == (wo_number or "").strip()).with_for_update().first()
        if not wo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work Order '{wo_number}' not found.")
        if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED) or wo.current_stage == "Completed":
            raise _bad(f"Work Order '{wo.wo_number}' is completely dispatched; nothing can be sent to a vendor.")
        ProductionService._enforce_release_gate(wo)

        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes]
        matched = match_route_stage(stage, route_stages)
        if not matched:
            raise _bad(f"Stage '{stage}' is not part of the route for WO '{wo.wo_number}'. Valid route: {' -> '.join(route_stages)}")
        if matched.upper() in _NO_TRIP_STAGES:
            raise _bad(f"Pieces cannot be sent to a vendor from '{matched}'.")
        if not is_scm(current_user):
            assert_user_may_post_at(current_user, matched, "send material to a vendor")

        # One DC = one trip. Checked on the exact DC number, case-insensitive, ignoring cancelled trips.
        dup = db.query(VendorDispatch).filter(
            func.lower(VendorDispatch.dc_number) == dc.lower(),
            VendorDispatch.status != "CANCELLED",
        ).first()
        if dup:
            other = db.query(WorkOrder).filter(WorkOrder.id == dup.work_order_id).first()
            raise _bad(
                f"DC #{dc} is already recorded ({dup.dispatched_qty} pcs of {other.wo_number if other else 'another WO'} "
                f"to {dup.vendor_name}). One DC is one trip: use a new DC number, or cancel the earlier trip first.",
                status.HTTP_409_CONFLICT,
            )

        # Refresh the derived counts, then read them under lock.
        OMSIntegrationService.recompute_work_order(db, wo)
        wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == matched).with_for_update().first()
        unproc = (wip.inproc_qty or 0) if wip else 0
        comp = (wip.onhand_qty or 0) if wip else 0
        gate = VendorTripService.gate_state(db, wo.wo_number, matched)
        out_u = gate["at_vendor_from_unprocessed_qty"]
        out_c = gate["at_vendor_from_completed_qty"]

        if source_state is None:
            if unproc > 0 and comp > 0:
                raise _bad(
                    f"{matched} has {unproc} unprocessed and {comp} completed pieces of {wo.wo_number}. "
                    f"Choose which ones are going to the vendor (source_state UNPROCESSED or COMPLETED)."
                )
            if unproc <= 0 and comp <= 0:
                raise _bad(
                    f"No pieces of {wo.wo_number} are available at {matched} to send: 0 unprocessed, 0 completed"
                    + (f", {out_u + out_c} already at a vendor." if out_u + out_c else ".")
                )
            source_state = UNPROCESSED if unproc > 0 else COMPLETED
        available = unproc if source_state == UNPROCESSED else comp
        if quantity > available:
            raise _bad(
                f"Cannot send {quantity} {source_state.lower()} pcs of {wo.wo_number} from {matched}. "
                f"Available: {unproc} unprocessed, {comp} completed; already at a vendor: "
                f"{out_u} (left unprocessed), {out_c} (left completed)."
            )

        approved_now = 0
        if source_state == COMPLETED:
            approved_now = VendorTripService._approve_pending_for_sent(
                db, wo, matched, quantity, comp, (wip.ok_qty or 0) if wip else 0, current_user, dc)

        trip = VendorDispatch(
            work_order_id=wo.id,
            dispatch_stage=matched,
            vendor_name=vendor,
            dc_number=dc,
            target_return_stage=matched,
            dispatched_qty=quantity,
            status="AT_VENDOR",
            source_state=source_state,
            origin=origin,
            process_name=(process_name or "").strip() or None,
            remarks=(remarks or "").strip() or None,
            created_by=current_user.id if current_user else None,
        )
        db.add(trip)
        db.flush()

        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Floor",
            action="VENDOR_TRIP_SENT",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"{matched}: {unproc} unprocessed, {comp} completed",
            new_value=f"Sent {quantity} {source_state.lower()} pcs to {vendor} (DC #{dc})"
                      + (f" for {trip.process_name}" if trip.process_name else ""),
            details="Vendor trip: pieces moved, no production counted."
                    + (f" {approved_now} pcs of pending MRB review approved because they were sent out." if approved_now else ""),
        ))

        db.flush()
        OMSIntegrationService.recompute_work_order(db, wo)
        db.commit()
        db.refresh(trip)
        return VendorTripService._response(db, wo, trip, f"Sent {quantity} {source_state.lower()} pcs of {wo.wo_number} from {matched} to {vendor} (DC #{dc}).")

    # ------------------------------------------------------------------ MRB at send
    @staticmethod
    def _approve_pending_for_sent(db, wo, stage, qty, onhand, ok, user, dc) -> int:
        """Pieces that go to a vendor skip MRB (there is none at receipt). The sent pieces are taken
        from the already-approved stock first; only if more are sent than are approved does the
        shortfall come out of pending reviews, oldest first. A review bigger than the shortfall is
        split: the sent part is approved, the rest stays pending. Returns the pieces approved."""
        from app.services.mrb_service import MRBService
        summary = MRBService.get_stage_mrb_summary(
            db=db, work_order_id=wo.id, stage=stage, onhand_qty=onhand, already_moved=max(ok - onhand, 0))
        need = max(qty - (summary.get("approved_movable_qty") or 0), 0)
        if need <= 0:
            return 0
        now = datetime.now()
        who = user.full_name if user else "SCM"
        note = f"Sent to a vendor (DC #{dc}); no MRB at receipt, so the sent pieces were approved."
        tickets = db.query(MRBReview).filter(
            MRBReview.work_order_id == wo.id, MRBReview.stage == stage.upper(), MRBReview.status == "PENDING",
            MRBReview.reported_ok_qty > 0,
        ).order_by(MRBReview.created_at).with_for_update().all()
        left = need
        for t in tickets:
            if left <= 0:
                break
            n = t.reported_ok_qty or 0
            if n <= left:
                t.status = "APPROVED"
                t.verified_ok_qty = n
                t.verified_reject_qty = t.reported_reject_qty
                t.verified_defect_code = t.reported_defect_code
                t.disposition = "SCRAP" if (t.reported_reject_qty or 0) > 0 else "VENDOR_SENT"
                t.reviewed_by_id = user.id if user else None
                t.reviewed_by_name = f"System (Sent to vendor, {who})"
                t.reviewed_at = now
                t.review_notes = note
                left -= n
            else:
                db.add(MRBReview(
                    mrb_number=next_mrb_number(db),
                    production_update_id=t.production_update_id,
                    work_order_id=t.work_order_id,
                    stage=t.stage,
                    machine_id=t.machine_id,
                    operator_name=t.operator_name,
                    shift=t.shift,
                    heat_number=t.heat_number,
                    reported_ok_qty=left,
                    reported_reject_qty=0,
                    floor_remarks=f"Part of a review ({t.mrb_number}) split when {left} pcs were sent to a vendor.",
                    verified_ok_qty=left,
                    verified_reject_qty=0,
                    status="APPROVED",
                    disposition="VENDOR_SENT",
                    reviewed_by_id=user.id if user else None,
                    reviewed_by_name=f"System (Sent to vendor, {who})",
                    reviewed_at=now,
                    review_notes=note,
                ))
                t.reported_ok_qty = n - left
                t.verified_ok_qty = n - left
                left = 0
                db.flush()
        return need - left

    # --------------------------------------------------------------------- return
    @staticmethod
    def record_return(
        db: Session,
        trip_id: str,
        good_qty: int = 0,
        scrap_qty: int = 0,
        inward_dc: Optional[str] = None,
        remarks: Optional[str] = None,
        current_user: Optional[User] = None,
        destination_stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        VendorTripService._require_scm(current_user, "record a vendor return")
        good = int(good_qty or 0)
        scrap = int(scrap_qty or 0)
        if good < 0 or scrap < 0 or good + scrap <= 0:
            raise _bad("Enter the good and/or scrap pieces that came back (more than zero in total).")

        trip = db.query(VendorDispatch).filter(VendorDispatch.id == trip_id).with_for_update().first()
        if not trip:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Vendor trip '{trip_id}' not found.")
        if trip.source_state is None:
            raise _bad("This is an earlier-style vendor record. Receive it on the existing Receive screen.")
        if trip.status == "CANCELLED":
            raise _bad(f"DC #{trip.dc_number} was cancelled.")
        if trip.status == "RECEIVED":
            raise _bad(f"DC #{trip.dc_number} has already been fully received.")
        remaining = _remaining(trip)
        if good + scrap > remaining:
            raise _bad(
                f"Cannot receive {good + scrap} pcs ({good} good + {scrap} scrap). "
                f"Only {remaining} pcs are still at {trip.vendor_name} for DC #{trip.dc_number}."
            )

        wo = db.query(WorkOrder).filter(WorkOrder.id == trip.work_order_id).with_for_update().first()
        if not wo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Work Order linked to this trip was not found.")
        now = datetime.now()
        stage = trip.dispatch_stage
        update_id = None
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes]

        # SCM enters the receive gate. Default: the gate the trip left from. Any LATER gate of the
        # released route is allowed (e.g. F1 -> FI). A scrap-only return has no destination.
        dest = None
        if destination_stage and good > 0:
            d = match_route_stage(destination_stage, route_stages)
            if not d:
                raise _bad(f"Stage '{destination_stage}' is not part of the route for WO '{wo.wo_number}'. Valid route: {' -> '.join(route_stages)}")
            if d != stage:
                if d.upper() == "DISPATCH" or route_stages.index(d) < route_stages.index(stage):
                    raise _bad(f"Pieces cannot be received at '{d}' from {stage}: choose {stage} or a later gate (not Dispatch).")
                dest = d

        # The outcome follows from the receive gate; nobody is asked to decide it separately.
        if good <= 0:
            decision = None
        elif dest:
            decision = MOVED_ON
        elif trip.source_state == COMPLETED:
            decision = BACK_TO_COMPLETED
        else:
            decision = MORE_WORK

        counts_here = trip.source_state == UNPROCESSED and decision == MOVED_ON
        if counts_here:
            if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED) or wo.current_stage == "Completed":
                raise _bad(f"Work Order '{wo.wo_number}' is completely dispatched; nothing more can be counted at {stage}.")
            from app.services.continuous_casting_gate_service import ContinuousCastingGateService
            wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == stage).with_for_update().first()
            if not wip:
                raise _bad(f"No stage record for {stage} on {wo.wo_number}.")
            ContinuousCastingGateService.enforce_first_stage_production(
                db, wo, routes, stage, (wip.ok_qty or 0) + (wip.rejected_qty or 0), good)
            who = current_user.full_name if current_user else "SCM"
            entry = ProductionUpdate(
                work_order_id=wo.id,
                stage=stage,
                operator_id=current_user.id if current_user else None,
                operator_name=who,
                shift="Shift A",
                production_type="VENDOR",
                vendor_name=trip.vendor_name,
                dc_number=trip.dc_number,
                good_qty=good,
                reject_qty=0,
                status=ProductionStatus.COMPLETED,
                heat_number=wo.heat_number or None,
                remarks=f"Gate work done at vendor {trip.vendor_name} (DC #{trip.dc_number}); marked by SCM"
                        + (f", pieces went straight to {dest}." if dest else "."),
            )
            db.add(entry)
            db.flush()
            update_id = entry.id
            wip.ok_qty = (wip.ok_qty or 0) + good
            # Pieces that go straight to a later gate never wait at this one, so (as in the earlier
            # vendor flow) their review is recorded as approved by the system on SCM's choice of receive gate.
            direct = True
            db.add(MRBReview(
                mrb_number=next_mrb_number(db),
                production_update_id=entry.id,
                work_order_id=wo.id,
                stage=stage,
                operator_name=who,
                shift="Shift A",
                heat_number=entry.heat_number,
                reported_ok_qty=good,
                reported_reject_qty=0,
                floor_remarks=f"Returned from {trip.vendor_name} (DC #{trip.dc_number}); SCM marked the gate's work done"
                              + (f" and sent the pieces straight to {dest}." if direct else "."),
                verified_ok_qty=good,
                verified_reject_qty=0,
                status="APPROVED" if direct else "PENDING",
                disposition="VENDOR_RETURN_DIRECT" if direct else "PENDING",
                reviewed_by_name=("System (Vendor return, SCM)" if direct else None),
                reviewed_at=(now if direct else None),
            ))
            trip.done_qty = (trip.done_qty or 0) + good

        if dest:
            # Land the pieces at the later gate, as a move would.
            from app.services.production_service import _get_next_movement_id
            from app.models.production_movement import ProductionMovement
            dst = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == dest).with_for_update().first()
            if not dst:
                dst = StageWIP(work_order_id=wo.id, stage=dest, ent_qty=0, ok_qty=0, inproc_qty=0,
                               onhand_qty=0, rejected_qty=0, available_wip=0, received_qty=0)
                db.add(dst)
                db.flush()
            dst.ent_qty = (dst.ent_qty or 0) + good
            db.add(ProductionMovement(
                movement_id=_get_next_movement_id(db),
                work_order_id=wo.id,
                part_id=wo.order.part_id if wo.order else None,
                from_stage=f"{stage} (VENDOR)",
                to_stage=dest,
                quantity_moved=good,
                rejected_quantity=scrap,
                production_type="VENDOR",
                vendor_name=trip.vendor_name,
                dc_number=(inward_dc or trip.dc_number),
                operator_name=current_user.full_name if current_user else "SCM",
                movement_date=str(now.date()),
                movement_time=now.strftime("%H:%M:%S"),
                heat_number=wo.heat_number,
                remarks=f"Inward from vendor '{trip.vendor_name}' (DC #{trip.dc_number}) straight to {dest}.",
                created_by=current_user.id if current_user else None,
            ))

        trip.received_qty = (trip.received_qty or 0) + good
        trip.scrap_qty = (trip.scrap_qty or 0) + scrap
        trip.received_stage = stage
        if inward_dc and inward_dc.strip():
            trip.inward_dc_number = inward_dc.strip()
        if remarks and remarks.strip():
            trip.remarks = f"{trip.remarks or ''} | Inward: {remarks.strip()}".strip(" | ")
        if (trip.received_qty + trip.scrap_qty) >= trip.dispatched_qty:
            trip.status = "RECEIVED"
            trip.received_at = now
        else:
            trip.status = "PARTIALLY_RECEIVED"

        db.add(VendorTripReturn(
            trip_id=trip.id,
            good_qty=good,
            scrap_qty=scrap,
            decision=decision,
            destination_stage=dest,
            production_update_id=update_id,
            inward_dc=(inward_dc or "").strip() or None,
            remarks=(remarks or "").strip() or None,
            received_by=current_user.id if current_user else None,
        ))
        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "SCM",
            action="VENDOR_TRIP_RETURNED",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"At vendor {remaining} pcs (DC #{trip.dc_number})",
            new_value=f"Received {good} good ({decision or 'no decision'}) {('-> ' + dest) if dest else 'at ' + stage}, {scrap} scrap",
            details=f"Trip left {trip.source_state.lower()}. Inward DC: {trip.inward_dc_number or 'N/A'}",
        ))

        # The app's session does not autoflush: the return row (and any landing/ticket rows) must be
        # in the database before the recompute reads them.
        db.flush()
        OMSIntegrationService.recompute_work_order(db, wo)
        db.commit()
        db.refresh(trip)
        msg = f"Received {good} good + {scrap} scrap from {trip.vendor_name} at {stage}."
        if decision == MOVED_ON:
            msg = f"Received {good} good + {scrap} scrap from {trip.vendor_name}; the good pieces landed at {dest}."
        elif decision == MORE_WORK:
            msg += " Back to unprocessed; record the in-house work in Production Entry."
        return VendorTripService._response(db, wo, trip, msg)

    # ---------------------------------------------------------------------- cancel
    @staticmethod
    def cancel(db: Session, trip_id: str, reason: str, current_user: Optional[User] = None) -> Dict[str, Any]:
        VendorTripService._require_scm(current_user, "cancel a vendor trip")
        why = (reason or "").strip()
        if len(why) < 3:
            raise _bad("A reason is required to cancel a vendor trip.")
        trip = db.query(VendorDispatch).filter(VendorDispatch.id == trip_id).with_for_update().first()
        if not trip:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Vendor trip '{trip_id}' not found.")
        if trip.source_state is None:
            raise _bad("This is an earlier-style vendor record and cannot be cancelled here.")
        if trip.status == "CANCELLED":
            raise _bad(f"DC #{trip.dc_number} is already cancelled.")
        if trip.status != "AT_VENDOR" or (trip.received_qty or 0) > 0 or (trip.scrap_qty or 0) > 0:
            raise _bad("This trip already has returns recorded, so it cannot be cancelled.")
        wo = db.query(WorkOrder).filter(WorkOrder.id == trip.work_order_id).with_for_update().first()
        trip.status = "CANCELLED"
        trip.cancelled_at = datetime.now()
        trip.cancel_reason = why
        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "SCM",
            action="VENDOR_TRIP_CANCELLED",
            entity="WorkOrder",
            entity_id=wo.wo_number if wo else "",
            old_value=f"{trip.dispatched_qty} pcs at {trip.vendor_name} (DC #{trip.dc_number})",
            new_value=f"Cancelled: {why}",
            details=f"Pieces return to {trip.source_state.lower()} at {trip.dispatch_stage}.",
        ))
        db.flush()
        if wo:
            OMSIntegrationService.recompute_work_order(db, wo)
        db.commit()
        db.refresh(trip)
        return VendorTripService._response(db, wo, trip, f"Cancelled DC #{trip.dc_number}; {trip.dispatched_qty} pcs are back at {trip.dispatch_stage}.")

    # --------------------------------------------------------------------- helpers
    @staticmethod
    def _response(db: Session, wo: WorkOrder, trip: VendorDispatch, message: str) -> Dict[str, Any]:
        gate = VendorTripService.gate_state(db, wo.wo_number, trip.dispatch_stage)
        return {
            "success": True,
            "message": message,
            "trip_id": str(trip.id),
            "wo_number": wo.wo_number,
            "stage": trip.dispatch_stage,
            "source_state": trip.source_state,
            "status": trip.status,
            "at_vendor_qty": _remaining(trip),
            "gate_unprocessed_qty": gate["unprocessed_qty"],
            "gate_completed_qty": gate["completed_qty"],
        }
