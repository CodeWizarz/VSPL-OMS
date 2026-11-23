"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { PencilLine, AlertTriangle, CheckCircle2, Lock, Info } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getWorkOrders, getWorkOrderRoute, editWorkOrder, WOEditResult } from "@/lib/api";

// PPC edit of a Work Order. The backend decides what is allowed (quantity and route
// only before production starts; afterwards only the stages not yet reached, plus plan
// dates) -- this page just collects the change and shows the backend's answer.

const STAGE_OPTIONS = ["F1", "F2", "F3", "SP", "FI", "PACKING"];

type PlanRow = { stage: string; planned_start: string; planned_end: string };

const inputCls =
  "mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500";

export default function WOEditPage() {
  const [wos, setWos] = useState<any[]>([]);
  const [woNumber, setWoNumber] = useState("");
  const [route, setRoute] = useState<any>(null);
  const [qty, setQty] = useState<number | "">("");
  const [stages, setStages] = useState<string[]>([]);
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [reason, setReason] = useState("");
  const [loadingWO, setLoadingWO] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<WOEditResult | null>(null);

  useEffect(() => {
    getWorkOrders({ limit: 500 })
      .then((data) => {
        const list = Array.isArray(data) ? data.filter((w: any) => !["dispatched", "closed"].includes(w.status)) : [];
        setWos(list);
        const requested = new URLSearchParams(window.location.search).get("wo");
        if (requested) setWoNumber(requested);
      })
      .catch(() => setError("Could not load work orders."));
  }, []);

  const loadRoute = async (wo: string) => {
    if (!wo) return;
    setLoadingWO(true);
    setError("");
    setResult(null);
    try {
      const r = await getWorkOrderRoute(wo);
      setRoute(r);
      setQty(r.physical_wo_qty);
      setStages((r.route_stages || []).filter((s: string) => s !== "DISPATCH"));
      setPlans(
        (r.route_stages || []).map((s: string) => ({
          stage: s,
          planned_start: r.stage_plans?.[s]?.planned_start || "",
          planned_end: r.stage_plans?.[s]?.planned_end || "",
        }))
      );
    } catch {
      setError(`Could not load Work Order '${wo}'.`);
      setRoute(null);
    } finally {
      setLoadingWO(false);
    }
  };

  useEffect(() => {
    if (woNumber) loadRoute(woNumber);
  }, [woNumber]);

  const toggleStage = (code: string) => {
    // Removing drops it; adding appends it (reorder with the arrows). Stages the route
    // already has that aren't in STAGE_OPTIONS (e.g. "PACKING / BSR") are kept as-is.
    setStages((cur) => (cur.includes(code) ? cur.filter((s) => s !== code) : [...cur, code]));
  };

  const moveStage = (idx: number, dir: -1 | 1) => {
    setStages((cur) => {
      const next = [...cur];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return cur;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!route) return;
    setError("");
    setResult(null);
    const payload: Parameters<typeof editWorkOrder>[1] = { reason };
    if (qty !== "" && Number(qty) !== route.physical_wo_qty) payload.physical_wo_qty = Number(qty);
    const originalStages = (route.route_stages || []).filter((s: string) => s !== "DISPATCH");
    if (stages.join(",") !== originalStages.join(",")) payload.route_stages = [...stages, "DISPATCH"];
    const changedPlans = plans.filter((p) => {
      const orig = route.stage_plans?.[p.stage] || {};
      return (p.planned_start || "") !== (orig.planned_start || "") || (p.planned_end || "") !== (orig.planned_end || "");
    });
    if (changedPlans.length > 0 && !payload.route_stages) {
      payload.stage_plan = changedPlans.map((p) => ({
        stage: p.stage,
        planned_start: p.planned_start || null,
        planned_end: p.planned_end || null,
      }));
    }
    if (!payload.physical_wo_qty && !payload.route_stages && !payload.stage_plan) {
      setError("Nothing has changed.");
      return;
    }
    setSaving(true);
    try {
      const res = await editWorkOrder(route.wo_number, payload);
      setResult(res);
      await loadRoute(route.wo_number);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not save the change. Check the values and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">PPC</span>
            <span className="text-xs text-zinc-400">Planning</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Edit Work Order</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Change a WO&rsquo;s quantity, route or stage plan dates. Every change is recorded with your reason.
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-zinc-600 dark:text-zinc-400">
          <Lock className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
          <p>
            Before any production: quantity and route can change. Once production has started, quantity is locked and only the
            stages <span className="font-semibold">not yet reached</span> can change. Plan dates can change any time until dispatch.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5">
          <div>
            <label htmlFor="wo-select" className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Work Order</label>
            <select id="wo-select" value={woNumber} onChange={(e) => setWoNumber(e.target.value)} className={inputCls}>
              <option value="">Select a work order…</option>
              {woNumber && !wos.some((w) => w.wo_number === woNumber) && <option value={woNumber}>{woNumber}</option>}
              {wos.map((w) => (
                <option key={w.wo_number} value={w.wo_number}>
                  {w.wo_number} — {w.customer_name} · {w.part_number} (at {w.current_stage})
                </option>
              ))}
            </select>
          </div>

          {loadingWO && <p className="text-xs text-zinc-500">Loading…</p>}

          {route && !loadingWO && (
            <>
              <div>
                <label htmlFor="wo-qty" className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Physical WO quantity</label>
                <input
                  id="wo-qty"
                  type="number"
                  min={1}
                  value={qty}
                  onChange={(e) => setQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className={inputCls}
                />
              </div>

              <div>
                <p className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Route (in order)</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {STAGE_OPTIONS.map((code) => {
                    const on = stages.includes(code);
                    return (
                      <button
                        key={code}
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggleStage(code)}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-bold ${
                          on ? "border-blue-600 bg-blue-600 text-white" : "border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400"
                        }`}
                      >
                        {code}
                      </button>
                    );
                  })}
                </div>
                <ol className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
                  {stages.map((s, i) => (
                    <li key={s} className="flex items-center gap-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2 py-1">
                      <button type="button" aria-label={`Move ${s} earlier`} onClick={() => moveStage(i, -1)} className="text-zinc-400 hover:text-zinc-700">‹</button>
                      <span className="font-bold">{s}</span>
                      <button type="button" aria-label={`Move ${s} later`} onClick={() => moveStage(i, 1)} className="text-zinc-400 hover:text-zinc-700">›</button>
                    </li>
                  ))}
                  <li className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2 py-1 font-bold text-zinc-500">DISPATCH</li>
                </ol>
              </div>

              <div>
                <p className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Stage plan dates</p>
                <p className="text-[11px] text-zinc-500">These drive each department&rsquo;s My Work Queue. Save route changes first; new stages get dates automatically.</p>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-[11px] uppercase text-zinc-500">
                      <tr>
                        <th className="text-left py-1.5">Stage</th>
                        <th className="text-left py-1.5">Planned start</th>
                        <th className="text-left py-1.5">Planned end (due)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plans.map((p, i) => (
                        <tr key={p.stage}>
                          <td className="py-1.5 pr-3 font-bold">{p.stage}</td>
                          <td className="py-1.5 pr-3">
                            <input
                              type="date"
                              aria-label={`${p.stage} planned start`}
                              value={p.planned_start}
                              onChange={(e) => setPlans((cur) => cur.map((x, j) => (j === i ? { ...x, planned_start: e.target.value } : x)))}
                              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-2 py-1"
                            />
                          </td>
                          <td className="py-1.5">
                            <input
                              type="date"
                              aria-label={`${p.stage} planned end`}
                              value={p.planned_end}
                              onChange={(e) => setPlans((cur) => cur.map((x, j) => (j === i ? { ...x, planned_end: e.target.value } : x)))}
                              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-2 py-1"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div>
                <label htmlFor="wo-reason" className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Reason for change *</label>
                <input
                  id="wo-reason"
                  required
                  minLength={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Customer revised quantity"
                  className={inputCls}
                />
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-600 dark:text-rose-400">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              {result && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-400">
                  <p className="flex items-center gap-2 font-bold">
                    <CheckCircle2 className="h-4 w-4" /> {result.message}
                  </p>
                  <ul className="mt-1 list-disc pl-6">
                    {result.changes.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}

              <button
                type="submit"
                disabled={saving}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50"
              >
                <PencilLine className="h-4 w-4" />
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </>
          )}
          {!route && !loadingWO && error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-600">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </form>

        <p className="flex items-center gap-1.5 text-[11px] text-zinc-500">
          <Info className="h-3.5 w-3.5" /> To release a new WO, use{" "}
          <Link href="/planning/wo-release" className="font-semibold text-blue-600 hover:underline">WO Release &amp; Routing</Link>.
        </p>
      </div>
    </AppShell>
  );
}
