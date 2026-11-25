# Vendor trips — architecture

Status: **steps A and B built on branch `fix/vendor-scrap-and-movable` (not committed, not deployed). Step C (DC software link) is on hold by decision.**
Date: 25 Nov 2026 · Based on production code: recovery branch, commit `00821d8`
Replaces the "Send to vendor on the Move screen" design in `vendor-trip-counting.md` (that branch is not committed and will be reworked to this design).

---

## 1. Ground rules (from the team)

1. Until the MES is merged, OMS tracks **gates** (F1, F2, F3, SP, FI, Packing, Dispatch), not processes.
2. Each gate has several processes. Any of them may be in-house or at a vendor, **in any order**, decided case by case.
3. Whether a gate's last process is subcontracted or done in-house is decided by **SCM**.
4. A DC (Delivery Challan) covers **one work order**. It has no gate and no process. The DC software knows only what was sent and what came back.
5. OMS Vendor Tracking holds everything else. **SCM has the final say.**
6. Production entry (PE) stays the place where the floor records in-house work and sends to a vendor.

## 2. The one rule

> **A vendor trip moves pieces. It never produces them.**
> A piece is counted as done at a gate exactly once: by an in-house production entry, or when pieces that left a gate **unprocessed** are received by SCM at a **later** gate (the first gate's work is then counted as done, once).

Balance that must hold for every WO, after every action:

```
WO quantity = unprocessed + completed + at vendor + vendor scrap + rejected + moved on (next gates) + dispatched
```

## 3. Send and receive (as built, 25 Nov 2026)

**Send** (Production Entry, "At vendor"): vendor, DC number, quantity, optional process. The pieces come from the gate's *unprocessed* or *completed* stock (the screen asks only when the gate has both). The trip shows in Vendor Tracking straight away. No production is counted. Pieces sent as *completed* skip MRB: any pending review covering them is approved at send (approved stock is used first; a pending review larger than the shortfall is split).

**Receive** (Vendor Tracking, SCM): SCM enters good pieces, scrap and the **receive gate**. There is no MRB at receipt and no separate decision; the outcome follows from the gate:

| Pieces left | Receive gate | Result | Counted |
|---|---|---|---|
| Unprocessed | Same gate | Back to unprocessed; a later in-house entry counts them | by that entry |
| Unprocessed | Later gate | First gate's work counted as done; pieces enter the receive gate (system-approved review) | once, at the first gate |
| Completed | Same gate | Back to completed stock | not again |
| Completed | Later gate | Pieces enter the receive gate | not again |

Rules: only the gate the trip left from or a **later** gate of the released route (not Dispatch, not an earlier gate); a scrap-only return has no destination; partial returns can go to different gates; scrap stays on the trip and is counted in the balance. FI remains the only quality check for vendor-returned pieces.

### Piece states at one gate

```
                     in-house PE (good)                      MRB approve + Move
   ┌─────────────┐ ───────────────────────► ┌─────────────┐ ───────────────────► next gate
   │ UNPROCESSED │                          │  COMPLETED  │
   └─────────────┘                          └─────────────┘
      │       ▲   │                            │       ▲   │
 send │       │   │ receive at a LATER gate    │ send  │   │ receive at a LATER gate
      ▼       │   └───► (counted once here,    ▼       │   └───► (already counted)
   ┌──────────────────┐   enters that gate)  ┌──────────────────┐   enters that gate
   │ AT VENDOR        │──┘ receive at SAME   │ AT VENDOR        │── receive at SAME gate ─┘
   │ (from unproc.)   │    gate: back to     │ (from completed) │    back to completed
   └──────────────────┘    unprocessed       └──────────────────┘
            │ scrap                                   │ scrap
            ▼                                         ▼
       VENDOR SCRAP (stays on the trip record, counted in the balance)
```

## 4. How the counters work (no new counters on the gate)

`StageWIP` keeps its columns. `OMSIntegrationService.recompute_work_order` stays the single writer of derived counts; only the vendor part changes.

```
out_unprocessed = Σ trips from this gate, source UNPROCESSED : at vendor + vendor scrap
out_completed   = Σ trips from this gate, source COMPLETED   : at vendor + vendor scrap
legacy_outflow  = today's formula, only for trips recorded the old way (see §9)

unprocessed (inproc) = max(ent − ok − rejected − out_unprocessed, 0)
completed  (onhand)  = max(ok − ent(next gate) − out_completed − legacy_outflow, 0)
```

- "More work" returns: nothing to change; the trip's at-vendor count drops, so unprocessed rises.
- "Gate work done" returns: write a production entry (`production_type = VENDOR`, linked to the trip) that adds the good pieces to `ok`, with a **pending** MRB ticket. The trip records them as returned-done so they leave `out_unprocessed`.
- Completed-source returns: the trip's at-vendor count drops, so completed rises. `ok` is untouched.

## 5. Data model (additive only)

**`vendor_dispatches`** (existing table, one row per trip). New columns:

| Column | Meaning |
|---|---|
| `source_state` | `UNPROCESSED` / `COMPLETED`. **NULL = legacy trip** (recorded the old way, keeps old accounting) |
| `origin` | `PE` (entered on Production Entry) / `DC` (confirmed from the DC inbox) |
| `process_name` | Optional, free text from SCM/floor (e.g. heat treatment). Not used for counting |
| `done_qty` | Good pieces of unprocessed trips received at a later gate (counted at the first gate) |
| `cancelled_at`, `cancel_reason` | Trip cancelled before anything came back |
| `dc_qty_sent`, `dc_qty_returned`, `dc_unit`, `dc_status`, `dc_synced_at`, `expected_return_date` | Last values read from the DC software, for display and mismatch flags only. Never used for counting |

**`vendor_trip_returns`** (new): one row per return, because partial returns may get different decisions.

| Column | Meaning |
|---|---|
| `trip_id` | → `vendor_dispatches.id` |
| `good_qty`, `scrap_qty` | Pieces |
| `decision` | Derived from the receive gate: `MORE_WORK` / `BACK_TO_COMPLETED` (same gate) or `MOVED_ON` (later gate) |
| `destination_stage` | The receive gate when it is not the gate the trip left from |
| `production_update_id` | Set when the first gate's work was counted (unprocessed trip received at a later gate) |
| `inward_dc`, `remarks`, `received_by`, `received_at` | Audit |

**`dc_inbox`** (new): DCs read from the DC software.

| Column | Meaning |
|---|---|
| `dc_number` (unique) | Key. A DC can never create two trips |
| `wo_number`, `vendor_name`, `qty_sent`, `unit`, `sent_at`, `expected_return_date`, `qty_returned`, `dc_status`, `closed` | As read |
| `state` | `WAITING_FOR_SCM` / `LINKED` / `MISMATCH` / `IGNORED` |
| `trip_id` | Set once linked |
| `first_seen_at`, `last_synced_at` | Sync audit |

All added through `auto_migrate_schema` (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). Nothing existing is rewritten.

## 6. Services and API

| Piece | Responsibility |
|---|---|
| `VendorTripService.send(wo, gate, source, qty, vendor, dc_number, process, origin)` | Validates and creates a trip. No production counted. |
| `VendorTripService.record_return(trip, good, scrap, receive gate, inward_dc)` | Adds a return row; an unprocessed trip received at a later gate writes the production entry + a system-approved ticket. No MRB at receipt. |
| `VendorTripService.cancel(trip, reason)` | Only if nothing returned yet; pieces go back to their source state. |
| `DcSyncService.sync()` | Reads open DCs from the DC software (existing `DCClient`), upserts `dc_inbox`, links by DC number, flags mismatches. Never moves pieces. |

| Endpoint | Who | Used by |
|---|---|---|
| `POST /api/v1/vendor/trips` | Gate roles for their gate, SCM, admin | Production Entry "At vendor" |
| `POST /api/v1/vendor/trips/{id}/returns` | SCM, admin | Vendor Tracking |
| `POST /api/v1/vendor/trips/{id}/cancel` | SCM, admin | Vendor Tracking |
| `GET  /api/v1/vendor/trips` (+ existing `/dispatches`, `/summary`) | All signed-in | Vendor Tracking, dashboards |
| `GET  /api/v1/vendor/dc-inbox` | SCM, admin | Vendor Tracking "DCs waiting" |
| `POST /api/v1/vendor/dc-inbox/{dc}/confirm` (gate, source, pieces) | SCM, admin | Creates the trip from a DC |
| `POST /api/v1/vendor/dc-sync` | SCM, admin, scheduler | Refresh from DC software |

`POST /api/v1/production/entry` with `production_type = VENDOR` stops creating vendor records; the screen calls `/vendor/trips` instead. (Old behaviour stays readable for legacy trips.)

SCM roles: the Subcontracting (SP) manager and supervisor roles (`sp_manager`, `sp_supervisor`), plus admin and production manager — to confirm.

## 7. Screens

| Screen | Change |
|---|---|
| **Production Entry** | Mode "In-house" works as today. Mode "At vendor": vendor, DC number, quantity, optional process; source shown (unprocessed / completed) and asked only when the gate has both. No excess path. |
| **Vendor Tracking** (SCM) | Trips list with source, gate, process, days out, expected back (from DC). Return dialog (the old receive dialog): good, scrap and the receive gate. "DCs waiting for SCM" tab: confirm gate + source + pieces, or ignore. Mismatch badges. |
| **Move** | Back to how it was (no vendor option). Shows pieces at vendor as information. |
| **Stage / WO views** | Show "at vendor" per gate. |

## 8. DC software ↔ OMS

```
 DC software (sent / received only)                      OMS (Vendor Tracking, SCM decides)
 ──────────────────────────────────                      ───────────────────────────────────
 DC created for WO, vendor, qty                          
 DC dispatched  ──── read by OMS (DC no = key) ────►     dc_inbox
                                                           ├─ trip with same DC already entered on PE → LINKED
                                                           │     (qty differs → MISMATCH flag to SCM)
                                                           └─ no trip → WAITING FOR SCM
                                                                 SCM confirms gate / source / pieces → trip
 Qty received updated ── read by OMS ─────────────►      "DC reports 8 received — record the return"
                                                           SCM enters good / scrap / decision
 DC cancelled ───────── read by OMS ─────────────►       If nothing returned: SCM may cancel the trip
```

Decisions in this design:

- **Direction: OMS reads** (the read-only, token-protected endpoint already exists in both apps). The DC software needs no change. A missed read catches up on the next sync; a missed push would be lost.
- **When OMS reads:** when Vendor Tracking opens, from a "Refresh from DC" button, and every 15 minutes from Cloud Scheduler calling `/vendor/dc-sync` (Cloud Run has no background workers).
- **The DC number is the key.** One DC links to one trip.
- **Units:** a DC quantity may be in kg, not pieces. OMS never adds DC quantities to piece counts; SCM enters pieces when confirming. DC quantities are shown and compared only when the unit is pieces.
- **OMS never moves pieces on its own** from DC data. Every stock change is a confirmed SCM or floor action.

## 9. Rollout and production safety

1. **Legacy trips untouched.** Existing open trips (recorded as "vendor production entry") keep `source_state = NULL` and today's accounting until closed. No WO's numbers change on deploy.
2. **Additive schema only**, applied by the existing start-up migration.
3. **Feature flag** `VENDOR_TRIPS_ENABLED`. Off: today's behaviour for new entries. On: new trips. The recompute always understands both, so turning the flag off later never breaks trips already created.
4. **Read-only data check (C5) on production before switching on:** open legacy trips, scrap returns to the same gate, VENDOR moves with no vendor record, F1 excess after a vendor return.
5. **Tests before any deploy:** every case in §10, the full suite compared with production (no new failures), and a local demo for the team.
6. Deploy stays manual (team), flag switched on after a floor walkthrough.

## 10. Edge cases (each becomes a test)

| # | Case | Resolution |
|---|---|---|
| 1 | Send more than is in the source state | Refused, shows unprocessed / completed / at vendor |
| 2 | Send the same pieces twice | Refused: pieces at a vendor are in no source state |
| 3 | Same DC entered twice (double click, PE + DC inbox) | One trip; the second is refused or linked |
| 4 | Gate has both unprocessed and completed pieces | PE asks which |
| 5 | Pieces of one WO at two gates when a DC arrives | SCM picks the gate on confirm |
| 6 | Partial returns with different decisions | One return row each |
| 7 | Return more than outstanding | Refused |
| 8 | Scrap at vendor | Stays on the trip, counted in the balance |
| 9 | In-house PE while some pieces are out | Allowed only up to unprocessed; never treated as F1 excess |
| 10 | F1 excess with pieces out | The excess check ignores pieces at a vendor, so they can't trigger excess |
| 11 | Gate shows "completed" while pieces are out | Gate is not complete until nothing is at a vendor |
| 12 | Move while pieces are out | Only completed, MRB-approved pieces move |
| 13 | "Gate work done" return | Pending MRB ticket; move needs approval |
| 14 | Completed pieces approved in MRB, then sent and returned | Approval still covers them (scrap reduces movable) |
| 15 | DC quantity in kg | Not compared; SCM enters pieces |
| 16 | DC quantity ≠ trip quantity | MISMATCH flag; SCM resolves |
| 17 | DC cancelled after dispatch | SCM may cancel the trip if nothing returned |
| 18 | DC software unreachable | Vendor Tracking works from OMS data; banner says DC data is stale |
| 19 | Legacy open trip returned after deploy | Old accounting path, unchanged |
| 20 | Trips at SP gate | Same rules; SP is just another gate |
| 21 | Reconciliation | Accounts for at vendor + vendor scrap |
| 22 | WO closed / dispatched | No sends |

## 11. Decisions for the team

1. SCM roles: `sp_manager`, `sp_supervisor` (+ admin, production manager)?
2. Can gate supervisors send to a vendor from PE, or only SCM?
3. Who may record returns and choose the receive gate: SCM only (built as)?
4. Sync every 15 minutes OK?
5. A DC's pieces split across two gates: allow one DC → two trips, or always one gate per DC?

## 12. Build order and status

| Step | Scope | Status |
|---|---|---|
| A | Schema + recompute + `VendorTripService` + tests (no screens) | Built, 35 tests pass |
| B | Production Entry "At vendor" + Vendor Tracking returns/cancel; Move screen toggle hidden | Built, type-checks, checked on the local demo |
| C | DC inbox + sync + mismatch flags | **On hold** (DC software stays separate for now) |
| D | Full suite vs production, local demo, then PR | Suite and demo done; commit/PR waits for the team's test |

## 13. What was built (defaults taken for the open decisions)

- Flag `VENDOR_TRIPS_ENABLED` (default **off**). On: Production Entry "At vendor" creates a trip; a VENDOR-typed production entry or Move is refused with a pointer to it. Off: today's behaviour.
- SCM = `sp_manager`, `sp_supervisor`, `admin`, `production_manager`, `ceo`. They may send from any gate, record returns (choosing the receive gate) and cancel. Gate supervisors/managers and operators may send only from their own gate (the existing stage lock).
- One DC number = one trip (case-insensitive; a cancelled trip frees its number).
- Endpoints: `POST /api/v1/vendor/trips`, `POST /vendor/trips/{id}/returns`, `POST /vendor/trips/{id}/cancel`, `GET /vendor/gate-state`, `GET /vendor/config`. Existing `/vendor/dispatches`, `/summary` and `/receive` are unchanged (legacy trips).
- Schema (applied by the start-up migration): `vendor_dispatches.source_state, origin, process_name, done_qty, cancelled_at, cancel_reason`, and table `vendor_trip_returns`.
- Kept from the earlier branch work: scrap fix on return to the same gate (legacy path), stage screen no longer subtracting at-vendor twice, reconciliation counting at-vendor and vendor scrap, an auto-approved vendor MRB ticket being reduced on a legacy return to the same gate, and "vendor work is never F1 excess" for legacy entries.

### Receiving at a later gate: counting detail

The recompute treats pieces that landed beyond the next gate like the earlier flow: they leave the first gate's stock because they were counted there and went on (`trip_beyond`). Pieces that left unprocessed and land at a later gate get a vendor production entry (adds the good pieces at the first gate) and a system-approved MRB ticket, because they never wait at the first gate.

## 14. Edge cases: coverage report

Covered by automated tests (`backend/tests/test_vendor_trips.py`, 45 tests). After every step each test checks that all pieces are accounted for and the reconciliation balances.

| # | Case | Covered | Test |
|---|---|---|---|
| 1 | Send more than the source state holds | Yes | `test_send_more_than_available_refused_with_numbers` |
| 2 | Send the same pieces twice | Yes | `test_same_pieces_cannot_be_sent_twice` |
| 3 | Same DC entered twice | Yes (PE side; the "DC inbox + PE" half belongs to step C) | `test_same_dc_twice_is_one_trip` |
| 4 | Gate has both unprocessed and completed pieces | Yes | `test_two_vendors_unprocessed_and_completed_at_the_same_gate` |
| 5 | WO pieces at two gates when a DC arrives | **No: step C (on hold)** | — |
| 6 | Partial returns with different decisions | Yes | `test_partial_returns_can_have_different_decisions` |
| 7 | Return more than outstanding / after fully received | Yes | `test_return_more_than_outstanding_or_after_received` |
| 8 | Scrap at the vendor | Yes (unprocessed, completed, scrap-only) | three `test_scrap_*` tests |
| 9 | In-house entry while some pieces are out | Yes | `test_entry_while_some_pieces_are_out` |
| 10 | F1 excess with pieces out | Yes: refused even with a remark; WO stays 10 | `test_pieces_at_vendor_never_trigger_f1_excess` |
| 11 | Gate looks complete while pieces are out | Yes (status "At Vendor", clear message) | two tests |
| 12 | Move while pieces are out | Yes | `test_move_only_what_is_in_stock_while_the_rest_is_out` |
| 13 | Vendor does the gate's last process | Yes: received at a later gate, counted once, no MRB | `test_vendor_does_the_gates_last_process` |
| 14 | Pending or approved MRB, then sent and returned | Yes: pending review approved at send (split when needed); scrap reduces movable | four tests |
| 15–18 | DC quantity units, mismatch, DC cancelled, DC unreachable | **No: step C (on hold)** | — |
| 19 | Legacy open trip returned after deploy | Yes, incl. legacy and new trips together | two tests |
| 20 | Trips at SP and later gates | Yes | `test_trips_work_at_a_later_gate_and_at_sp` |
| 21 | Reconciliation | Yes, at every step of a long story | `test_reconciliation_balanced_at_every_step_of_a_long_story` |
| 22 | WO closed or dispatched | Yes | `test_closed_work_order_cannot_send` |

Receiving at another gate: unprocessed straight to FI and to the next gate, completed straight to a later gate, pending review approved at send so nothing waits at receipt, review split when only part of a batch is sent, part ahead / part back, scrap with landing, destination rules (unknown gate, Dispatch, earlier gate, scrap-only ignores destination).

Also covered, beyond the table: the three work orders from the team (vendor first, in-house first, vendor does the last process), vendor then in-house then vendor again, a split batch, two vendors at once, several processes in a row, parallel trips from both states, cancel (before and after a return, reason required, number reuse), role rules (own gate only, SCM anywhere, only SCM returns/cancels/decides), the flag off, old vendor entry and move label refused when on, required fields, unknown stage/WO, Packing and Dispatch refused, rejection entry while pieces are out.

Not covered by tests (screens only, checked by hand on the local demo): the Production Entry, Vendor Tracking and Move layouts.

