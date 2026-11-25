# Vendor trip counting — analysis and fixes (C1–C4, C6, C7)

Date: 24–25 Nov 2026 · Production code: recovery branch, commit `00821d8`
Reproduction: `backend/scripts/repro_vendor_counting.py` (in-memory SQLite, touches no real database)
Fixes: branch `fix/vendor-scrap-and-movable` (C1, C2) · Tests: `backend/tests/test_vendor_trip_counting.py`

## Status

**Superseded for the design: see [vendor-trips-architecture.md](vendor-trips-architecture.md).** This file keeps the original analysis of how OMS counted vendor trips and the runs that showed the failures.

| Change | State |
|---|---|
| C1 scrap on return to the same gate (earlier vendor flow) | In: `vendor_service.receive_from_vendor` no longer adds vendor scrap to the gate's rejected count. |
| C2 at-vendor subtracted twice on the stage screen | In: `production_service.get_stage_dashboard` uses on-hand as computed by the recompute. |
| C3 / C4 send out after production, Move-screen vendor label | Replaced by **vendor trips** (Production Entry "At vendor", SCM receives at a chosen gate). Behind the switch `VENDOR_TRIPS_ENABLED` (off by default). |
| C6 MRB after a return to the same gate (earlier flow) | In, earlier flow only. |
| C7 reconciliation counts pieces at a vendor and vendor scrap | In. |
| C5 read-only check of production data | Not run. |

## The rule

Every piece of a work order is in exactly one place:

```
WO quantity = in process + on hand (all gates) + at vendor + scrapped at vendor + rejected + dispatched
```

Sending pieces to a vendor removes them from the gate's stock; receiving them puts them back once.

## How OMS handles vendor trips today

| Path | How it is recorded | What happens to counts |
|---|---|---|
| A. Production entry marked VENDOR | `ProductionService.record_stage_production` with `production_type=VENDOR`, vendor name, DC | Counts the pieces as OK at the gate, auto-approves MRB, creates a `vendor_dispatches` row (AT_VENDOR). Recompute removes them from on-hand. Receive (`VendorService.receive_from_vendor`) lands them in a later gate or back at the same gate. |
| B. Move marked VENDOR | `ProductionService.move_parts` with `production_type=VENDOR` | Only a label on the movement. Pieces land at the next gate immediately. No vendor record, nothing to receive. |

Stock rule in `OMSIntegrationService.recompute_work_order`: `on-hand = OK − entered at next gate − vendor outflow` (vendor outflow = at vendor + received beyond the next gate + scrapped at vendor). It only knows about Path A.

## Results (WO of 10, route F1 → F2 → F3 → FI → Packing → Dispatch)

| Run | Steps | Result |
|---|---|---|
| S1 | F1 entry 10 in-house → MRB → move to F2 | correct (10) |
| S2 | F1 entry 10 as VENDOR → receive 10 into F2 | correct (10); F1 on-hand 0 while out |
| S3 | F1 entry 10 as VENDOR → receive back into F1 → in-house entry 10 → move | correct (10) |
| S4 | F1 entry 10 in-house → send the same 10 to vendor | refused ("Gate F1 has completed"); no way to send out after production |
| S5 | F1 entry 10 as VENDOR → receive 8 good + 2 scrap back into F1 → entry 8 | F1 left at OK 2 / rejected 2 / in process 6; 8 of 10 accounted; entry of 8 refused |
| S5b | as S5, operator adds a remark | treated as F1 excess: WO becomes 12, false excess alert |
| S6 | F2 entry 5 in-house + 5 VENDOR → move the 5 in-house | counts right; stage screen shows 0 movable / 0 MRB-approved movable, so the Move screen caps at 0 |
| S7 | F1 10 in-house → Move F1 → F2 marked VENDOR | F2 shows 10 while pieces are out; Receive has nothing to receive |
| S8 | F1 entry 10 as VENDOR → receive back into F1 → in-house entry 10 → move without approving MRB | move allowed: the vendor send's automatic MRB approval (10) is counted for the new in-house ticket. Pre-existing; not affected by C1/C2 |

With C1 + C2: S5 and S5b count all 10 pieces at every step (the WO stays at 10, no excess alert); S6 shows 5 movable and stays MRB-locked until the in-house pieces are approved. S4, S7 and S8 are unchanged.

## Causes

1. **Scrap on return to the same gate** — `services/vendor_service.py`, `receive_from_vendor`, line 180: OK is reduced by the good quantity only; scrap stays in OK and is also added to rejected (S5, S5b).
2. **At-vendor subtracted twice on screen** — `services/production_service.py`, `get_stage_dashboard`, line 114: on-hand already excludes at-vendor; the screen subtracts it again, and the figure feeds the MRB check used by `MovePartsContent.tsx` line 362 (S6).
3. **Vendor is a way to finish a gate, not a trip** — `record_stage_production`, lines 687–864: sending out counts as production, so pieces already produced can't be sent out (S4).
4. **Move marked VENDOR is only a label** — `move_parts` stores vendor name and DC on the movement but creates no vendor record (S7).

## Proposed changes (for discussion)

| # | Change | Fixes | Risk |
|---|---|---|---|
| C1 | On return to the same gate, remove good + scrap from OK | S5, S5b | Low |
| C2 | Stop the double subtraction on the stage screen and MRB check | S6 | Low |
| C3 | Add "Send out" from a gate's on-hand stock, reusing the vendor record and Receive | S4 | Medium |
| C4 | Replace the Move screen's VENDOR label with "Send out" | S7 | Medium |
| C5 | Read-only check of production data for already-affected WOs | existing data | None |
| C6 | Returned pieces get their own MRB review; the vendor send's automatic approval no longer covers later in-house work | S8 | Medium |
| C7 | Reconciliation counts pieces at the vendor and scrapped at the vendor (today they show as variance) | reports | Low |

Why C1 keeps scrap on the vendor record rather than moving it to rejected: `recompute_work_order` already removes vendor scrap from the stage via `scrapped_at_vendor`, and returns to a later stage already work this way. Moving scrap into rejected instead would mean changing the recompute, which would raise on-hand on work orders already affected in production (phantom stock). That choice can be revisited with C7 and decision 7.

## Decisions needed

Defaults taken in this change (can be revisited): returned send-out pieces land at the same gate (1); an MRB approval given before a send-out still covers the returned pieces (2); Path A stays alongside Send to vendor (3); the Move screen's VENDOR label is replaced (4); vendor pieces in Path A still count as OK when they leave (5).

1. Default landing for returned pieces: same gate, or next gate?
2. MRB review on every vendor return?
3. Keep "whole gate done at vendor" (Path A) alongside "send out after production"?
4. Remove the VENDOR option from the Move screen once Send out exists?
5. Should vendor pieces count as OK when they leave (today) or when they return?
6. Run the read-only check (C5) on production before deciding on corrections.
7. Should rejection reports include scrap at a vendor (today it lives only on the vendor record)?
