# Setup planning and scheduling: architecture

Status: **all five phases built on branch `feat/setup-planning` (not committed, not deployed).** Behind `SETUP_PLANNING_ENABLED` (off by default). Date: 25 Nov 2026.
Page with diagrams: https://claude.ai/artifact/WS4RoWg4C8pzDSsmQSbyRm

Replaces the earlier AI planner / planning-masters / planning-engine design. That design was never built into OMS, so no code is removed. PPC supplies the dates by Excel; OMS stores, checks, shows and flags them.

## 1. The idea

- **Setup number**: one production day with N work orders, planned by PPC. A setup holds many work orders and many heat numbers.
- **Mandatory at release**: a work order cannot be released without a setup number (and heat numbers when the route includes F1). Release is when the work order joins the setup.
- **Excel in, Excel out**: PPC downloads a setup as a sheet, fills the date for each gate, uploads it back. OMS checks it, shows the differences, applies it on approval.
- **One set of dates**: gate dates are stored on the work order's route (`wo_routes.planned_start/planned_end`), which the floor's work queue already reads. Planning never changes quantities, WIP or MRB.
- The commitment date (revised date wins) is the reference for every delay check.

## 2. What exists today (reused)

- `wo_routes.planned_start/planned_end` per gate; default dates filled at release backwards from the due date using standard lead times (`stage_plan_service`).
- Audit-logged stage plan edit (`PATCH /work-orders/{wo}/stage-plan`, reason required).
- Floor work queue (`/work-orders/queue`): groups by planned end (overdue, today, next days) and carries delivery risk.
- Order commitment date, revised commitment date, OAR, customer PO.
- Release form (`POST /operations/release`): quantity, route stages, casting process, one optional heat number.

## 3. Data (additive only)

| Table / field | New? | Content |
|---|---|---|
| `planning_setups` | new | setup_number (unique), setup_date, status open/closed, remarks, created_by/at |
| `work_orders.setup_id` | new field | the one setup the work order belongs to (empty for older work orders) |
| `work_orders.plan_version` | new field | goes up whenever the work order's dates change; detects an old Excel file |
| `wo_heats` | new | work_order_id, setup_id, heat_number, added_by/at; many per work order, one heat may serve several work orders |
| `wo_routes.plan_source`, `plan_updated_at` | new fields | release / excel / manual; when changed |
| `plan_imports` | new | setup_id, file name, file hash, uploaded by/at, status review/applied/discarded, counts |
| `plan_import_rows` | new | import_id, wo_number, stage, old dates, new dates, result, message |
| `work_orders.heat_number` | kept | stays for compatibility (first heat) |

Every date or heat change also goes to the existing audit log: who, old, new, reason or file name.

## 4. Release

| Field | Change | Rule |
|---|---|---|
| Setup number | new, mandatory | pick an open setup or create one (number + production day); a closed setup takes no new work orders |
| Heat numbers | new, one or many | at least one when the route includes F1 |
| Route, commitment date, default gate dates | unchanged | route is the key to the schedule; defaults stay "estimated" until PPC's dates replace them |

Work orders released before the change appear under **Unassigned**; PPC maps each once, with a reason.

## 5. Screens (PPC only; new sidebar group)

1. **Setups**: list with work order count, quantity, heats, earliest commitment date, delayed and at-risk counts, plan completeness.
2. **Setup detail** (click a setup number): table of work orders with mapped OAR, PO, part, quantity, route (gate columns), heats, commitment date, planned end per gate coloured by state, status. Buttons: Download Excel, Upload Excel, Add WO. Click a row: panel with start and end for every gate, reason box, heat editor, move to another setup.
3. **Import review**: counts (in file / ready / warning / error), every changed gate with old and new dates, Apply, Download error report, Discard. Nothing changes until Apply; a work order's gates apply together or not at all.
4. **Delay board**: delayed and at-risk work orders across setups with gate, days late, commitment date.
5. **Unassigned**: released work orders without a setup.

## 6. Excel sheet

One round trip per setup. Locked: Setup No, WO No (the key), OAR, PO, Part, Qty, Commitment date, Route, hidden sheet (template version, setup number, export time, each work order's plan version). Editable: Heat numbers (comma separated) and Start/End for each gate (gates a work order lacks are greyed). README sheet explains date format and that blank means no change.

### Checks on upload (nothing is saved before Apply)

| Check | Result |
|---|---|
| Not xlsx, too large, unknown template version, headers changed | file rejected |
| WO not found, not released, closed or dispatched | row error |
| WO belongs to a different setup | row error |
| Date unreadable (accepts Excel dates and dd-mm-yyyy), start after end | row error |
| Gate not on the work order's route | row error |
| Gate already finished on the floor | row error |
| Gate dates out of sequence | warning |
| Last gate ends after the commitment date | warning |
| Plan changed after the sheet was downloaded (plan version) | warning: overwrite or skip |
| Blank date cell | no change (blank never clears a date; use Clear on screen) |
| Same file uploaded again (hash) | no change |

## 7. Delays (computed live, not stored)

| State | Rule |
|---|---|
| On track | every gate done, or its planned end still ahead and work started when it should have |
| At risk | a gate ends within 2 days and has not started, or its start date passed with no material at the gate |
| Delayed | a gate's planned end passed and it is not finished; or the last gate's planned end is after the commitment date; or the commitment date passed and the work order is not dispatched |
| No plan | at least one gate on the route has no date |

A gate is finished when it has received material, nothing is unprocessed or waiting to move, and some pieces were produced or rejected. Pieces at a vendor count as in progress. The delay line names the gate and days ("Delayed · F2 +2 days (planned 24 Nov)"). The at-risk window (2 days) is one setting.

## 8. What the shop floor sees (read-only)

| Screen | Adds |
|---|---|
| My Work Queue | setup number, heat numbers, commitment date, red/amber state (already grouped by planned end) |
| Production Entry | banner: setup, heats, "this gate due 28 Nov (2 days)", commitment, state colour |
| Move Parts | same banner, plus the next gate's due date |
| WO Tracking and Timeline | planned against actual per gate, late gates marked |
| Vendor Tracking | the gate's due date for work orders at a vendor |

Dates are information only: production entry, moves, MRB and dispatch validation do not read them.

## 9. Access

PPC (planner) and admin: whole module. Everyone else: menu hidden and every planning endpoint refuses on the server. Gate supervisors, managers and SCM see the plan information on floor screens as they see those screens today.

## 10. Endpoints (new, PPC/admin unless noted)

`GET/POST /planning/setups` · `GET/PATCH /planning/setups/{setup}` · `POST/DELETE /planning/setups/{setup}/work-orders` · `PUT /planning/setups/{setup}/work-orders/{wo}/heats` · `PATCH /planning/work-orders/{wo}/plan` · `GET /planning/setups/{setup}/export.xlsx` · `POST /planning/imports` (check only) · `GET /planning/imports/{id}` · `POST /planning/imports/{id}/apply` · `DELETE /planning/imports/{id}` · `POST /planning/imports/{id}/undo` · `GET /planning/export-all.xlsx?status=OPEN|CLOSED|ALL` (multi-setup sheet; upload through the same `POST /planning/imports`, META setup `*`) · `GET /planning/digest` · `POST /planning/digest/send` · `POST /planning/digest/run` (token) · `GET /planning/delays` · `GET /planning/unassigned`. Release gets `setup_number` and `heat_numbers`. Floor reads (any signed-in role, as today): the queue and WO detail gain setup, heats, commitment and state.

## 11. Edge cases

- Work order released before the change: Unassigned, mapped once with a reason.
- Added to the setup after the download: not in the file, untouched.
- Removed from the setup after the download: row error.
- Route changed after planning (only gates after the ones already reached can change): the removed gates' dates go; new gates get the default estimated dates until PPC sets them; the plan version goes up so an older sheet is flagged stale.
- Commitment date revised after planning: delay check uses it at once; the plan is unchanged.
- Two people edit one work order: plan version check, second save must confirm the overwrite.
- Several heats per work order, one heat across work orders: allowed inside a setup.
- Closed setup: no new work orders, no date changes; reopenable.
- Replacement/patch work order: needs a setup like any other.
- Planning while production runs: allowed; finished gates are locked.
- Wrong file applied: each import keeps old and new dates; undo if no later change touched those gates.
- Vendor trips: unchanged; a gate with pieces at a vendor is not finished.
- Holidays/working calendar: warnings only (see 12a).

## 12. Safety and rollout

- Switch `SETUP_PLANNING_ENABLED`, off by default. Off: release works as today, module hidden. On: setup number mandatory at release, PPC sees the module.
- Additive schema via the existing start-up migration; existing work orders, routes and dates are not rewritten.
- Planning never reads or writes quantities, WIP or MRB.

| Phase | Scope |
|---|---|
| 1 | setup tables, mandatory setup and heats on release, Setups list, Setup detail (read-only), Unassigned, PPC-only menu |
| 2 | Excel download, upload, checks, review, apply, change log, undo |
| 3 | edit one work order's dates and heats on screen, move between setups, close/reopen |
| 4 | delay check, Delay board, red/amber on Setup detail, banners on the floor screens |
| 5 | daily delayed list to PPC (preview + send now + token endpoint for a scheduler), multi-setup sheet, clear a gate's date on screen (**built**) |

## 12a. Calendar, capacity and split (built after phase 5)

All three are warnings and views only; nothing blocks a save and the floor never reads them.

- **Working calendar**: weekly off days (setting `PLANNING_WEEKLY_OFF`, default `6` = Sunday) plus PPC-marked holidays and worked off-days. A gate start or end on a day off gives a warning on screen and in the Excel check. Screen: Planning > Calendar.
- **Capacity**: pieces per gate per working day (`planning_capacity`). When PPC sets a gate end date, the pieces already planned to end that day at that gate plus this work order's quantity are compared with the capacity; over gives a warning. A gate with no number is not checked. Screen: Planning > Capacity, with a 7/14/30 day load grid (red = over, grey = day off).
- **Split**: a work order keeps its main setup and can have shares planned in other setups (`wo_setup_splits`). The main setup shows the remainder, each other setup a read-only row tagged Split. Dates stay with the work order, so Excel sheets carry only the main-setup row. Floor quantities are untouched. A work order cannot be moved into a setup that holds one of its shares (remove the split first).
- Endpoints: `GET/PUT/DELETE /planning/calendar[/{day}]` · `GET/PUT/DELETE /planning/capacity[/{gate}]` · `GET /planning/capacity-view` · `GET/PUT /planning/work-orders/{wo}/splits`.

## 13. Decisions (defaults are what gets built)

1. Who is PPC: planner and admin.
2. One setup per work order (no splitting across setups).
3. At least one heat number at release when the route includes F1.
4. Setup number: free text that PPC types, unique.
5. Stage managers keep editing their own gate's dates on the Stage Plan screen; every change logged and visible to PPC.
6. At-risk window 2 days.
7. Multi-setup sheet and the daily digest: built in phase 5. The digest e-mails planners only when the server has SMTP set up (otherwise it is logged); a scheduler (Cloud Scheduler) can call `POST /planning/digest/run` with header `X-Planning-Digest-Token` once `PLANNING_DIGEST_TOKEN` is set. Not scheduled yet.
