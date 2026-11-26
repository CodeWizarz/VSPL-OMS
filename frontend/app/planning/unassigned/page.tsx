"use client";
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Inbox, Loader2, RefreshCw } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getUnassignedWorkOrders, listSetups, mapWorkOrdersToSetup, planningErrorText, PlanWorkOrder, SetupSummary } from "@/lib/api";
import { fmtDay, PlanStatusChip } from "@/app/components/planning/PlanUi";

// PPC: released work orders that were released before setup planning, so they have no setup yet.
// Map each to a setup once, with a reason. docs/setup-planning-architecture.md

export default function UnassignedPage() {
  const [rows, setRows] = useState<PlanWorkOrder[]>([]);
  const [setups, setSetups] = useState<SetupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [skipped, setSkipped] = useState<{ wo_number: string; message: string }[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [w, s] = await Promise.all([getUnassignedWorkOrders(), listSetups("OPEN")]);
      setRows(w);
      setSetups(s);
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load the unassigned work orders."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const chosen = Object.keys(picked).filter((k) => picked[k]);
  const allTicked = rows.length > 0 && chosen.length === rows.length;

  const submit = async () => {
    setError("");
    setMsg("");
    setSkipped([]);
    if (!chosen.length) return setError("Tick at least one work order.");
    if (!target) return setError("Choose the setup to put them in.");
    if (reason.trim().length < 3) return setError("Give a short reason.");
    setSaving(true);
    try {
      const res = await mapWorkOrdersToSetup(target, { wo_numbers: chosen, reason: reason.trim() });
      setMsg(`${res.mapped.length} work order${res.mapped.length === 1 ? "" : "s"} added to ${target}.`);
      setSkipped(res.errors);
      setPicked({});
      setReason("");
      await load();
    } catch (err: any) {
      setError(planningErrorText(err, "Could not add the work orders."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-orange-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">PPC</span>
              <span className="text-xs text-zinc-400">Planning &amp; Scheduling</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2">
              <Inbox className="h-6 w-6 text-zinc-500" /> Unassigned work orders
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 max-w-2xl">
              Released work orders without a setup. New releases need a setup number, so these are older ones. Put each in a setup to plan it.
            </p>
          </div>
          <button type="button" onClick={load} className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 self-start">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-3 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
          </div>
        )}
        {msg && (
          <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 p-3 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4 shrink-0" /> <span>{msg}</span>
          </div>
        )}
        {skipped.map((s, i) => <div key={i} className="text-xs text-amber-700 dark:text-amber-300"><span className="font-mono font-bold">{s.wo_number}</span>: {s.message}</div>)}

        {loading ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
        ) : rows.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 p-10 text-center text-xs text-zinc-500">Every released work order already has a setup.</div>
        ) : (
          <>
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
              <div>
                <label htmlFor="un-setup" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Setup</label>
                <select id="un-setup" value={target} onChange={(e) => setTarget(e.target.value)} className="w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-900 dark:text-zinc-100">
                  <option value="">Choose an open setup</option>
                  {setups.map((s) => <option key={s.setup_number} value={s.setup_number}>{s.setup_number}{s.setup_date ? ` · ${fmtDay(s.setup_date)}` : ""}</option>)}
                </select>
              </div>
              <div className="md:col-span-2">
                <label htmlFor="un-reason" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Reason *</label>
                <input id="un-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Released before setup planning" className="w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-900 dark:text-zinc-100" />
              </div>
              <button type="button" onClick={submit} disabled={saving} className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Add {chosen.length || ""} to setup
              </button>
            </div>

            <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    <th className="py-3 px-3 w-8"><input id="un-all" type="checkbox" aria-label="Tick all" checked={allTicked} onChange={(e) => setPicked(e.target.checked ? Object.fromEntries(rows.map((r) => [r.wo_number, true])) : {})} /></th>
                    <th className="py-3 px-3">WO</th><th className="py-3 px-3">OAR / PO</th><th className="py-3 px-3">Part · qty</th><th className="py-3 px-3">Commitment</th><th className="py-3 px-3">At gate</th><th className="py-3 px-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.wo_number} className="border-b border-zinc-100 dark:border-zinc-800/60 last:border-0">
                      <td className="py-2.5 px-3"><input id={`un-${r.wo_number}`} type="checkbox" aria-label={`Tick ${r.wo_number}`} checked={!!picked[r.wo_number]} onChange={(e) => setPicked((p) => ({ ...p, [r.wo_number]: e.target.checked }))} /></td>
                      <td className="py-2.5 px-3 font-mono font-extrabold">{r.wo_number}</td>
                      <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400"><div>{r.oar_number || "—"}</div><div className="text-[10px] text-zinc-400">{r.customer_po || "—"}</div></td>
                      <td className="py-2.5 px-3 text-zinc-700 dark:text-zinc-300"><div className="max-w-[180px] truncate" title={r.part_name || r.part_number || ""}>{r.part_name || r.part_number || "—"}</div><div className="text-[10px] text-zinc-400">{r.qty} pcs</div></td>
                      <td className="py-2.5 px-3 whitespace-nowrap">{fmtDay(r.commitment_date)}</td>
                      <td className="py-2.5 px-3">{r.current_stage || "—"}</td>
                      <td className="py-2.5 px-3"><PlanStatusChip status={r.plan_status} text={r.plan_text} compact /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
