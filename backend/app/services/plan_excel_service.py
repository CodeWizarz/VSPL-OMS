"""Excel round trip for a setup's plan (docs/setup-planning-architecture.md, "The Excel sheet").

  export_setup()  builds a sheet pre-filled with the setup's work orders and current gate dates
  check_upload()  reads an uploaded sheet, runs every check, and stores the result for review;
                  NOTHING on a work order changes at this point
  apply_import()  applies the reviewed import, one work order at a time (a work order's gates and
                  heats apply together or not at all), and logs every change
  undo_import()   puts back the old dates of an applied import where nothing changed since

A blank date cell never clears an existing date. Locked columns (setup, WO, OAR, PO, part, qty,
commitment, route) are for information; changes there are ignored.
"""
import hashlib
import io
import json
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.departments import normalize_stage
from app.models.audit import AuditLog
from app.models.setup_planning import PlanImport, PlanImportRow, PlanningSetup, WOHeat
from app.models.user import User
from app.models.work_order import WORoute, WorkOrder
from app.services import plan_delay_service as delay
from app.services.setup_planning_service import (
    SetupPlanningService, _audit, _is_active, _released, clean_heats, find_setup,
)
from app.services.stage_plan_service import order_due_date

TEMPLATE_VERSION = "1"
MAX_BYTES = 5 * 1024 * 1024
FIXED = ["Setup No", "WO No", "OAR", "PO No", "Part No", "Part Name", "Qty", "Commitment Date", "Route", "Plan Status", "Heat Numbers"]
LOCKED = set(FIXED) - {"Heat Numbers"}
DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d.%m.%Y", "%d-%b-%y", "%d %B %Y"]

GREY = PatternFill("solid", fgColor="E6E9ED")
HEAD = PatternFill("solid", fgColor="1A2027")
EDIT = PatternFill("solid", fgColor="FFF8E1")
NA = PatternFill("solid", fgColor="CFD4DA")


def _bad(detail, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _d(iso: Optional[str]) -> Optional[date]:
    return date.fromisoformat(iso) if iso else None


def _fmt(d: Optional[date]) -> str:
    return d.strftime("%d %b %Y") if d else "-"


# ------------------------------------------------------------------------------ export
GATE_ORDER = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR", "DISPATCH"]
MULTI = "*"                     # META setup_number of a sheet that covers several setups


def _build_workbook(rows: List[Dict], gate_cols: List[str], meta_setup: str, title: str, user: Optional[User]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "PLAN"
    header = FIXED + [f"{g} {part}" for g in gate_cols for part in ("Start", "End")]
    ws.append(header)
    for i, name in enumerate(header, start=1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    meta_versions: List[Tuple[str, int]] = []
    for r_idx, r in enumerate(rows, start=2):
        by_key = {normalize_stage(g["stage"]): g for g in r["gates"]}
        line: List = [
            r["setup_number"], r["wo_number"], r["oar_number"], r["customer_po"], r["part_number"], r["part_name"], r["qty"],
            _d(r["commitment_date"]), " > ".join(g["stage"] for g in r["gates"]),
            r["plan_text"], ", ".join(r["heat_numbers"]),
        ]
        for g in gate_cols:
            gate = by_key.get(normalize_stage(g))
            line += [_d(gate["planned_start"]) if gate else None, _d(gate["planned_end"]) if gate else None]
        ws.append(line)
        meta_versions.append((r["wo_number"], r["plan_version"]))
        for c_idx, name in enumerate(header, start=1):
            cell = ws.cell(row=r_idx, column=c_idx)
            if name in LOCKED:
                cell.fill = GREY
            elif name == "Heat Numbers":
                cell.fill = EDIT
            else:
                gate_name = name.rsplit(" ", 1)[0]
                cell.fill = EDIT if normalize_stage(gate_name) in by_key else NA
            if name == "Commitment Date" or name.endswith(" Start") or name.endswith(" End"):
                cell.number_format = "DD-MMM-YYYY"
    widths = {"Setup No": 14, "WO No": 14, "OAR": 14, "PO No": 16, "Part No": 16, "Part Name": 26, "Qty": 8,
              "Commitment Date": 16, "Route": 28, "Plan Status": 34, "Heat Numbers": 22}
    for i, name in enumerate(header, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(name, 14)
    ws.freeze_panes = "C2"

    meta = wb.create_sheet("META")
    meta.append(["template_version", TEMPLATE_VERSION])
    meta.append(["setup_number", meta_setup])
    meta.append(["exported_at", datetime.now().isoformat(timespec="seconds")])
    meta.append(["exported_by", user.full_name if user else ""])
    meta.append([])
    meta.append(["wo_number", "plan_version"])
    for wo_no, pv in meta_versions:
        meta.append([wo_no, pv])
    meta.sheet_state = "hidden"

    readme = wb.create_sheet("README")
    for line in [
        title,
        "",
        "Fill the Start and End date of each gate, and the heat numbers if they changed, then upload this file back in OMS.",
        "Yellow cells are editable. Grey cells are for information; changes there are ignored.",
        "Dark grey gate cells: that gate is not on the work order's route. Leave them empty.",
        "Dates: a real Excel date, or dd-mm-yyyy (for example 26-11-2026).",
        "A blank date cell means no change. A blank cell never clears a date.",
        "Heat numbers: separate several with commas.",
        "A finished gate cannot be re-planned.",
        "Nothing changes in OMS until you review the differences and click Apply.",
        "Do not rename sheets or headers, and do not delete the hidden META sheet.",
    ] + (["This sheet covers several setups. The Setup No of each row must stay as it is: a work order is changed only inside its own setup."]
         if meta_setup == MULTI else []):
        readme.append([line])
    readme.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _gate_columns(rows: List[Dict]) -> List[str]:
    seen: Dict[str, str] = {}
    for r in rows:
        for g in r["gates"]:
            seen.setdefault(normalize_stage(g["stage"]), g["stage"])
    return sorted(seen.values(), key=lambda x: (GATE_ORDER.index(normalize_stage(x)) if normalize_stage(x) in GATE_ORDER else 99, x))


def export_setup(db: Session, setup_number: str, user: Optional[User]) -> Tuple[bytes, str]:
    detail = SetupPlanningService.setup_detail(db, setup_number)
    sn = detail["setup"]["setup_number"]
    content = _build_workbook([r for r in detail["work_orders"] if not r.get("is_split")], detail["gate_columns"], sn, f"Setup plan for {sn}", user)
    return content, f"setup-{re.sub(r'[^A-Za-z0-9._-]+', '_', sn)}-plan.xlsx"


def export_setups(db: Session, status_filter: Optional[str], user: Optional[User]) -> Tuple[bytes, str]:
    """One sheet with the work orders of several setups (default: all open setups)."""
    flt = (status_filter or "OPEN").upper()
    setups = SetupPlanningService.list_setups(db, None if flt == "ALL" else flt)
    rows: List[Dict] = []
    for s in sorted(setups, key=lambda x: (x["setup_date"] or "", x["setup_number"])):
        rows.extend(r for r in SetupPlanningService.setup_detail(db, s["setup_number"])["work_orders"] if not r.get("is_split"))
    if not rows:
        raise _bad("There are no work orders in the selected setups.")
    content = _build_workbook(rows, _gate_columns(rows), MULTI, "Plan for several setups", user)
    return content, f"plan-{'all' if flt == 'ALL' else flt.lower()}-setups.xlsx"


# ------------------------------------------------------------------------------ parsing
def parse_date_cell(v) -> Tuple[Optional[date], Optional[str]]:
    """(date, error). Blank gives (None, None)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, datetime):
        return v.date(), None
    if isinstance(v, date):
        return v, None
    if isinstance(v, (int, float)):
        if 20000 < float(v) < 80000:
            return from_excel(v).date(), None
        return None, f"'{v}' is not a date"
    text = str(v).strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(text, f).date(), None
        except ValueError:
            continue
    return None, f"'{text}' is not a readable date"


def _read_workbook(content: bytes):
    if len(content) > MAX_BYTES:
        raise _bad("The file is too large (5 MB at most).")
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise _bad("This is not a readable .xlsx file.")
    if "PLAN" not in wb.sheetnames or "META" not in wb.sheetnames:
        raise _bad("This is not an OMS setup plan sheet (the PLAN or META sheet is missing). Download a fresh sheet from the setup.")
    meta: Dict[str, str] = {}
    versions: Dict[str, int] = {}
    in_table = False
    for row in wb["META"].iter_rows(values_only=True):
        a = row[0] if row else None
        b = row[1] if row and len(row) > 1 else None
        if a is None:
            continue
        if str(a) == "wo_number":
            in_table = True
            continue
        if in_table:
            try:
                versions[str(a).strip().upper()] = int(b)
            except (TypeError, ValueError):
                pass
        else:
            meta[str(a)] = "" if b is None else str(b)
    if meta.get("template_version") != TEMPLATE_VERSION:
        raise _bad("This sheet was made with a different template version. Download a fresh sheet from the setup.")
    return wb, meta, versions


# ----------------------------------------------------------------------------- the check
def check_upload(db: Session, content: bytes, file_name: str, user: Optional[User], setup_number_hint: Optional[str] = None) -> Dict:
    if not (file_name or "").lower().endswith(".xlsx"):
        raise _bad("Upload an .xlsx file.")
    wb, meta, versions = _read_workbook(content)
    sn = meta.get("setup_number", "").strip()
    if not sn:
        raise _bad("The sheet does not say which setup it belongs to. Download a fresh sheet from the setup.")
    if sn == MULTI and setup_number_hint:
        raise _bad("This sheet covers several setups. Upload it from the Setups list, not from one setup.")
    if setup_number_hint and setup_number_hint.strip().upper() != sn.upper():
        raise _bad(f"This sheet is for setup {sn}, not {setup_number_hint.strip()}.")
    multi = sn == MULTI
    if multi and setup_number_hint:
        raise _bad("This sheet covers several setups. Upload it from the Setups list, not from one setup.")
    setup = None if multi else find_setup(db, sn)
    setup_cache: Dict = {}

    def setup_of(wo):
        if wo.setup_id not in setup_cache:
            setup_cache[wo.setup_id] = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first() if wo.setup_id else None
        return setup_cache[wo.setup_id]

    ws = wb["PLAN"]
    headers = [("" if c is None else str(c).strip()) for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    col = {h.lower(): i for i, h in enumerate(headers) if h}
    if "wo no" not in col:
        raise _bad("The 'WO No' column is missing. Do not change the headers; download a fresh sheet.")
    gate_cols: Dict[str, Dict[str, int]] = {}
    for i, h in enumerate(headers):
        m = re.match(r"^(.+?)\s+(Start|End)$", h, re.I)
        if m:
            gate_cols.setdefault(m.group(1).strip(), {})[m.group(2).lower()] = i

    file_hash = hashlib.sha256(content).hexdigest()
    notes: List[str] = []
    prior = db.query(PlanImport).filter(PlanImport.setup_number == (MULTI if multi else setup.setup_number),
                                        PlanImport.file_hash == file_hash,
                                        PlanImport.status == "APPLIED").order_by(PlanImport.applied_at.desc()).first()
    if prior:
        notes.append(f"This exact file was already applied on {prior.applied_at.strftime('%d %b %Y') if prior.applied_at else 'an earlier date'}.")

    imp = PlanImport(setup_id=setup.id if setup else None, setup_number=MULTI if multi else setup.setup_number, file_name=file_name, file_hash=file_hash,
                     uploaded_by=user.full_name if user else None, status="REVIEW")
    db.add(imp)
    db.flush()

    rows_out: List[PlanImportRow] = []
    wo_level: Dict[str, str] = {}          # wo -> "ERROR" | "WARNING" | "OK" | "UNCHANGED"
    seen_wo: Dict[str, int] = {}

    def add(row_no, wo_no, stage, level, message, old=(None, None), new=(None, None), old_text=None, new_text=None):
        rows_out.append(PlanImportRow(import_id=imp.id, row_no=row_no, wo_number=wo_no, stage=stage,
                                      old_start=old[0], old_end=old[1], new_start=new[0], new_end=new[1],
                                      old_text=old_text, new_text=new_text, result=level, message=message))
        rank = {"ERROR": 3, "WARNING": 2, "OK": 1, "UNCHANGED": 0}
        if rank[level] > rank.get(wo_level.get(wo_no, "UNCHANGED"), 0):
            wo_level[wo_no] = level

    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
            continue
        raw_wo = row[col["wo no"]] if col["wo no"] < len(row) else None
        wo_no = ("" if raw_wo is None else str(raw_wo)).strip().upper()
        if not wo_no:
            add(row_no, None, None, "ERROR", "The WO No is empty.")
            continue
        wo_level.setdefault(wo_no, "UNCHANGED")
        if wo_no in seen_wo:
            add(row_no, wo_no, None, "ERROR", f"{wo_no} appears twice (also in row {seen_wo[wo_no]}).")
            continue
        seen_wo[wo_no] = row_no
        row_setup = row[col["setup no"]] if "setup no" in col and col["setup no"] < len(row) else None
        wo = db.query(WorkOrder).filter(func.upper(WorkOrder.wo_number) == wo_no).first()
        if wo is None:
            add(row_no, wo_no, None, "ERROR", "Work order not found.")
            continue
        if not _released(wo) or not _is_active(wo):
            add(row_no, wo.wo_number, None, "ERROR", "Not released, or already closed or dispatched.")
            continue
        if multi:
            wo_setup = setup_of(wo)
            if wo_setup is None:
                add(row_no, wo.wo_number, None, "ERROR", "This work order is not in any setup yet. Map it to a setup first.")
                continue
            if wo_setup.status == "CLOSED":
                add(row_no, wo.wo_number, None, "ERROR", f"Setup {wo_setup.setup_number} is closed.")
                continue
            expected = wo_setup.setup_number
        else:
            if wo.setup_id != setup.id:
                add(row_no, wo.wo_number, None, "ERROR", "This work order is not in this setup now (moving a work order between setups is a separate action).")
                continue
            expected = setup.setup_number
        if row_setup is not None and str(row_setup).strip().upper() not in ("", expected.upper()):
            add(row_no, wo.wo_number, None, "ERROR", f"The row says setup {str(row_setup).strip()}, but this work order is in {expected}.")
            continue

        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        by_key = {normalize_stage(r.stage): r for r in routes}
        ev = delay.evaluate_work_orders(db, [wo])[str(wo.id)]
        changes: Dict[str, Tuple[Optional[date], Optional[date]]] = {}
        parse_failed = False
        for gate_name, parts in gate_cols.items():
            vals = {}
            for part in ("start", "end"):
                idx = parts.get(part)
                raw = row[idx] if idx is not None and idx < len(row) else None
                d, err = parse_date_cell(raw)
                if err:
                    add(row_no, wo.wo_number, gate_name, "ERROR", f"{gate_name} {part}: {err}.")
                    parse_failed = True
                vals[part] = d
            if vals["start"] is None and vals["end"] is None:
                continue
            r = by_key.get(normalize_stage(gate_name))
            if r is None:
                add(row_no, wo.wo_number, gate_name, "ERROR", f"{gate_name} is not a gate of {wo.wo_number}.")
                parse_failed = True
                continue
            changes[r.stage] = (vals["start"], vals["end"])
        if parse_failed:
            continue

        issues = SetupPlanningService.validate_gate_changes(routes, ev, changes, order_due_date(wo.order), wo.wo_number, None, db, wo)
        errs = [i for i in issues if i["level"] == "ERROR"]
        warns: Dict[str, List[str]] = {}
        for i in issues:
            if i["level"] == "WARNING":
                warns.setdefault(normalize_stage(i["stage"]), []).append(i["message"])
        for i in errs:
            add(row_no, wo.wo_number, i["stage"], "ERROR", i["message"])
        if not errs:
            for stage, (ns, ne) in changes.items():
                r = by_key[normalize_stage(stage)]
                old = (r.planned_start, r.planned_end)
                new = (ns if ns is not None else old[0], ne if ne is not None else old[1])
                if new == old:
                    continue
                w = warns.pop(normalize_stage(stage), [])
                add(row_no, wo.wo_number, r.stage, "WARNING" if w else "OK", " ".join(w) or None, old, new)
            for key, msgs in warns.items():          # a warning on a gate whose dates did not change
                r = by_key.get(key)
                add(row_no, wo.wo_number, r.stage if r else key, "WARNING", " ".join(msgs), (r.planned_start, r.planned_end) if r else (None, None), (r.planned_start, r.planned_end) if r else (None, None))
        # heats (blank cell = no change)
        hi = col.get("heat numbers")
        raw_heat = row[hi] if hi is not None and hi < len(row) else None
        if raw_heat is not None and str(raw_heat).strip():
            try:
                new_heats = clean_heats([str(raw_heat)])
            except HTTPException as e:
                add(row_no, wo.wo_number, "HEATS", "ERROR", str(e.detail))
                new_heats = None
            if new_heats is not None:
                old_heats = [h.heat_number for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all()]
                if {h.upper() for h in old_heats} != {h.upper() for h in new_heats}:
                    add(row_no, wo.wo_number, "HEATS", "OK", None, old_text=", ".join(old_heats), new_text=", ".join(new_heats))
        # stale plan: changed after this sheet was downloaded
        if wo.wo_number.upper() in versions and versions[wo.wo_number.upper()] != (wo.plan_version or 0) and wo_level.get(wo.wo_number, "UNCHANGED") in ("OK", "WARNING"):
            add(row_no, wo.wo_number, "PLAN", "WARNING", "The plan of this work order was changed after this sheet was downloaded. Applying it overwrites those changes.")

    for r in rows_out:
        db.add(r)
    levels = list(wo_level.values())
    imp.total_wos = len(wo_level)
    imp.error_count = levels.count("ERROR")
    imp.warning_count = levels.count("WARNING")
    imp.ok_count = levels.count("OK")
    imp.file_errors = json.dumps(notes) if notes else None
    db.flush()
    return import_to_dict(db, imp)


def import_to_dict(db: Session, imp: PlanImport) -> Dict:
    rows = db.query(PlanImportRow).filter(PlanImportRow.import_id == imp.id).order_by(PlanImportRow.row_no, PlanImportRow.stage).all()
    iso = lambda d: d.isoformat() if d else None
    return {
        "id": str(imp.id),
        "setup_number": imp.setup_number,
        "file_name": imp.file_name,
        "status": imp.status,
        "uploaded_by": imp.uploaded_by,
        "uploaded_at": imp.uploaded_at.isoformat() if imp.uploaded_at else None,
        "applied_at": imp.applied_at.isoformat() if imp.applied_at else None,
        "counts": {
            "total_wos": imp.total_wos or 0,
            "ready": imp.ok_count or 0,
            "warning": imp.warning_count or 0,
            "error": imp.error_count or 0,
            "unchanged": max((imp.total_wos or 0) - (imp.ok_count or 0) - (imp.warning_count or 0) - (imp.error_count or 0), 0),
            "applied": imp.applied_count or 0,
            "skipped": imp.skipped_count or 0,
        },
        "notes": json.loads(imp.file_errors) if imp.file_errors else [],
        "rows": [{
            "row_no": r.row_no, "wo_number": r.wo_number, "stage": r.stage,
            "old_start": iso(r.old_start), "old_end": iso(r.old_end), "new_start": iso(r.new_start), "new_end": iso(r.new_end),
            "old_text": r.old_text, "new_text": r.new_text, "result": r.result, "message": r.message, "applied": bool(r.applied),
        } for r in rows],
    }


def get_import(db: Session, import_id: str, lock: bool = False) -> PlanImport:
    q = db.query(PlanImport).filter(PlanImport.id == import_id)
    if lock:
        q = q.with_for_update()
    imp = q.first()
    if not imp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found.")
    return imp


# ------------------------------------------------------------------------------- apply
def apply_import(db: Session, import_id: str, user: Optional[User], overwrite_stale: bool = False) -> Dict:
    imp = get_import(db, import_id, lock=True)
    if imp.status != "REVIEW":
        raise _bad(f"This import is already {imp.status.lower()}.", status.HTTP_409_CONFLICT)
    multi = imp.setup_number == MULTI
    setup = None if multi else find_setup(db, imp.setup_number)
    if setup is not None and setup.status == "CLOSED":
        raise _bad(f"Setup '{setup.setup_number}' is closed. Reopen it to apply a plan.", status.HTTP_409_CONFLICT)
    rows = db.query(PlanImportRow).filter(PlanImportRow.import_id == imp.id).all()
    groups: Dict[str, List[PlanImportRow]] = {}
    for r in rows:
        if r.wo_number:
            groups.setdefault(r.wo_number, []).append(r)
    reason = f"Excel import {imp.file_name} (#{str(imp.id)[:8]})"
    applied, skipped, skipped_list = 0, 0, []
    for wo_no, rs in groups.items():
        if any(r.result == "ERROR" for r in rs):
            skipped += 1
            skipped_list.append({"wo_number": wo_no, "message": "Has errors."})
            continue
        if any(r.stage == "PLAN" for r in rs) and not overwrite_stale:
            skipped += 1
            skipped_list.append({"wo_number": wo_no, "message": "Plan changed after the sheet was downloaded (not overwritten)."})
            continue
        gate_rows = [r for r in rs if r.stage not in ("PLAN", "HEATS") and (r.new_start != r.old_start or r.new_end != r.old_end)]
        heat_row = next((r for r in rs if r.stage == "HEATS"), None)
        if not gate_rows and not heat_row:
            continue
        wo = db.query(WorkOrder).filter(func.upper(WorkOrder.wo_number) == wo_no.upper()).with_for_update().first()
        wo_setup = setup if setup is not None else (db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first() if wo is not None and wo.setup_id else None)
        if wo is None or not _is_active(wo) or wo_setup is None or (setup is not None and wo.setup_id != setup.id):
            skipped += 1
            skipped_list.append({"wo_number": wo_no, "message": "No longer in this setup, or closed."})
            continue
        if wo_setup.status == "CLOSED":
            skipped += 1
            skipped_list.append({"wo_number": wo_no, "message": f"Setup {wo_setup.setup_number} is closed."})
            continue
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        changes = {r.stage: (r.new_start, r.new_end) for r in gate_rows}
        ev = delay.evaluate_work_orders(db, [wo])[str(wo.id)]
        issues = SetupPlanningService.validate_gate_changes(routes, ev, changes, order_due_date(wo.order), wo.wo_number, None, db, wo)
        errs = [i for i in issues if i["level"] == "ERROR"]
        if errs:
            skipped += 1
            skipped_list.append({"wo_number": wo_no, "message": errs[0]["message"] + " (changed since the check)"})
            continue
        SetupPlanningService.apply_gate_changes(db, wo, routes, changes, "EXCEL", user, reason)
        if heat_row and heat_row.new_text is not None:
            try:
                SetupPlanningService.set_heats(db, wo, [heat_row.new_text], reason, user)
            except HTTPException as e:
                skipped_list.append({"wo_number": wo_no, "message": f"Dates applied, heat numbers not: {e.detail}"})
        for r in rs:
            if r.result in ("OK", "WARNING"):
                r.applied = True
        applied += 1
    imp.status = "APPLIED"
    imp.applied_count = applied
    imp.skipped_count = skipped
    imp.applied_at = datetime.now()
    imp.applied_by = user.full_name if user else None
    _audit(db, user, "PLAN_IMPORT_APPLIED", "several setups" if multi else setup.setup_number, "", f"{applied} work orders updated, {skipped} skipped", reason)
    db.flush()
    out = import_to_dict(db, imp)
    out["skipped"] = skipped_list
    return out


def discard_import(db: Session, import_id: str, user: Optional[User]) -> Dict:
    imp = get_import(db, import_id, lock=True)
    if imp.status != "REVIEW":
        raise _bad(f"This import is already {imp.status.lower()}.", status.HTTP_409_CONFLICT)
    imp.status = "DISCARDED"
    db.flush()
    return import_to_dict(db, imp)


# -------------------------------------------------------------------------------- undo
def undo_import(db: Session, import_id: str, user: Optional[User]) -> Dict:
    imp = get_import(db, import_id, lock=True)
    if imp.status != "APPLIED":
        raise _bad("Only an applied import can be undone.", status.HTTP_409_CONFLICT)
    multi = imp.setup_number == MULTI
    setup = None if multi else find_setup(db, imp.setup_number)
    if setup is not None and setup.status == "CLOSED":
        raise _bad(f"Setup '{setup.setup_number}' is closed. Reopen it to undo an import.", status.HTTP_409_CONFLICT)
    rows = db.query(PlanImportRow).filter(PlanImportRow.import_id == imp.id, PlanImportRow.applied.is_(True)).all()
    reason = f"Undo of Excel import {imp.file_name} (#{str(imp.id)[:8]})"
    restored, skipped = 0, []
    now = datetime.now()
    by_wo: Dict[str, List[PlanImportRow]] = {}
    for r in rows:
        by_wo.setdefault(r.wo_number, []).append(r)
    for wo_no, rs in by_wo.items():
        wo = db.query(WorkOrder).filter(func.upper(WorkOrder.wo_number) == wo_no.upper()).with_for_update().first()
        if wo is None:
            continue
        if multi and wo.setup_id:
            ws_ = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first()
            if ws_ is not None and ws_.status == "CLOSED":
                skipped.append({"wo_number": wo_no, "message": f"Setup {ws_.setup_number} is closed; left as it is."})
                continue
        routes = {normalize_stage(x.stage): x for x in db.query(WORoute).filter(WORoute.work_order_id == wo.id).all()}
        done_here = []
        for r in rs:
            if r.stage in ("PLAN", "HEATS") or r.stage is None:
                continue
            route = routes.get(normalize_stage(r.stage))
            if route is None:
                continue
            if (route.planned_start, route.planned_end) != (r.new_start, r.new_end):
                skipped.append({"wo_number": wo_no, "message": f"{r.stage} was changed after the import; left as it is."})
                continue
            route.planned_start, route.planned_end = r.old_start, r.old_end
            route.plan_source = "MANUAL"
            route.plan_updated_at = now
            done_here.append(r.stage)
        heat_row = next((r for r in rs if r.stage == "HEATS"), None)
        if heat_row is not None:
            current = {h.heat_number.upper() for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all()}
            if current == {h.upper() for h in clean_heats([heat_row.new_text or ""])}:
                try:
                    SetupPlanningService.set_heats(db, wo, [heat_row.old_text or ""], reason, user)
                    done_here.append("heats")
                except HTTPException as e:
                    skipped.append({"wo_number": wo_no, "message": f"Heat numbers not restored: {e.detail}"})
            else:
                skipped.append({"wo_number": wo_no, "message": "Heat numbers were changed after the import; left as they are."})
        if done_here:
            wo.plan_version = (wo.plan_version or 0) + 1
            _audit(db, user, "WO_PLAN_CHANGED", wo.wo_number, "", f"Restored: {', '.join(done_here)}", reason)
            restored += 1
    imp.status = "UNDONE"
    _audit(db, user, "PLAN_IMPORT_UNDONE", "several setups" if multi else setup.setup_number, "", f"{restored} work orders restored", reason)
    db.flush()
    out = import_to_dict(db, imp)
    out["restored"] = restored
    out["skipped"] = skipped
    return out
