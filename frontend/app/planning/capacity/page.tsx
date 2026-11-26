"use client";
import React, { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  CapacityView, deletePlanCapacity, getCapacityView, getPlanCapacity, planningErrorText, PlanCapacityRow, setPlanCapacity,
} from "@/lib/api";
import { fmtDay } from "@/app/components/planning/PlanUi";

// PPC: pieces each gate can finish per working day, and the planned load against it.
// Warnings only: nothing here stops a plan from being saved.

const GATES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR", "DISPATCH"];
const inputCls = "w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100";

export default function CapacityPage() {
  const [rows, setRows] = useState<Record<string, PlanCapacityRow>>({});
  const [draft, setDraft] = useState<Record<string, { q: string; n: string }>>({});
  const [view, setView] = useState<CapacityView | null>(null);
  const [span, setSpan] = useState(14);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [cap, v] = await Promise.all([getPlanCapacity(), getCapacityView(span)]);
      const m = Object.fromEntries(cap.map((r) => [r.stage, r]));
      setRows(m);
      setDraft(Object.fromEntries(GATES.map((g) => [g, { q: m[g] ? String(m[g].daily_qty) : "", n: m[g]?.note || "" }])));
      setView(v);
    } catch (e: any) {
      setError(planningErrorText(e, "Could not load capacity."));
    } finally {
      setLoading(false);
    }
  }, [span]);
  useEffect(() => { load(); }, [load]);

  const save = async (g: string) => {
    const q = parseInt(draft[g]?.q || "", 10);
    if (!q || q < 1) { setError(`${g}: enter pieces per day (at least 1), or use Remove.`); return; }
    setBusy(g);
    setError("");
    try { await setPlanCapacity(g, q, draft[g].n); await load(); } catch (e: any) { setError(planningErrorText(e, "Could not save.")); } finally { setBusy(""); }
  };
  const remove = async (g: string) => {
    setBusy(g);
    setError("");
    try { await deletePlanCapacity(g); await load(); } catch (e: any) { setError(planningErrorText(e, "Could not remove.")); } finally { setBusy(""); }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-5 p-4">
        <div>
          <h1 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-100">Gate capacity</h1>
          <p className="text-xs text-zinc-500">Pieces a gate can finish per working day. A gate with no number is not checked. Planning warns when a day goes over; it never blocks a save.</p>
        </div>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-950/30 px-3 py-2 text-xs text-rose-800 dark:text-rose-300">{error}</div>}

        <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
          <table className="w-full text-left text-xs">
            <thead><tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500">
              <th className="py-3 px-3">Gate</th><th className="py-3 px-3">Pieces per day</th><th className="py-3 px-3">Note</th><th className="py-3 px-3" />
            </tr></thead>
            <tbody>
              {GATES.map((g) => (
                <tr key={g} className="border-b border-zinc-100 dark:border-zinc-800/60 last:border-0">
                  <td className="py-2 px-3 font-mono font-extrabold">{g}</td>
                  <td className="py-2 px-3 w-40"><input type="number" min={1} aria-label={`${g} pieces per day`} value={draft[g]?.q ?? ""} onChange={(e) => setDraft({ ...draft, [g]: { ...draft[g], q: e.target.value } })} className={inputCls} /></td>
                  <td className="py-2 px-3"><input aria-label={`${g} note`} value={draft[g]?.n ?? ""} onChange={(e) => setDraft({ ...draft, [g]: { ...draft[g], n: e.target.value } })} maxLength={120} className={inputCls} /></td>
                  <td className="py-2 px-3 whitespace-nowrap">
                    <button type="button" disabled={busy === g} onClick={() => save(g)} className="rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-3 py-1.5 text-xs font-bold text-white">{busy === g ? "Saving…" : "Save"}</button>
                    {rows[g] && <button type="button" disabled={busy === g} onClick={() => remove(g)} className="ml-2 rounded-xl border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 text-xs font-bold text-zinc-700 dark:text-zinc-300">Remove</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-extrabold text-zinc-800 dark:text-zinc-200">Planned load {loading && <Loader2 className="inline h-3.5 w-3.5 animate-spin" />}</h2>
            <select aria-label="Days shown" value={span} onChange={(e) => setSpan(Number(e.target.value))} className="rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-xs">
              {[7, 14, 30].map((n) => <option key={n} value={n}>Next {n} days</option>)}
            </select>
          </div>
          <p className="text-[11px] text-zinc-500">Pieces whose gate is planned to end on each day. Red: over capacity. Grey column: non-working day.</p>
          {view && view.stages.length === 0 && !loading && <div className="text-xs text-zinc-500">No planned load and no capacity set yet.</div>}
          {view && view.stages.length > 0 && (
            <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
              <table className="text-center text-[11px]">
                <thead><tr className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-500">
                  <th className="py-2 px-3 text-left">Gate</th>
                  {view.days.map((d) => <th key={d.day} title={d.non_working || ""} className={`py-2 px-2 font-bold whitespace-nowrap ${d.non_working ? "bg-zinc-200 dark:bg-zinc-800" : ""}`}>{fmtDay(d.day)}</th>)}
                </tr></thead>
                <tbody>
                  {view.stages.map((s) => (
                    <tr key={s.stage} className="border-b border-zinc-100 dark:border-zinc-800/60 last:border-0">
                      <td className="py-2 px-3 text-left font-mono font-extrabold whitespace-nowrap">{s.stage}<div className="text-[10px] font-normal text-zinc-400">{s.daily_qty ? `${s.daily_qty}/day` : "no limit"}</div></td>
                      {s.cells.map((c, i) => (
                        <td key={c.day} className={`py-2 px-2 ${c.over ? "bg-rose-100 dark:bg-rose-950/40 font-extrabold text-rose-700 dark:text-rose-300" : view.days[i].non_working ? "bg-zinc-100 dark:bg-zinc-800/60 text-zinc-500" : "text-zinc-700 dark:text-zinc-300"}`}>{c.load || ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
