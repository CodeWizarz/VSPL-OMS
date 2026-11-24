"use client";
import React, { useEffect, useState } from "react";
import { Timer, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getLeadTimes, updateLeadTimes, LeadTimeRow } from "@/lib/api";

// PPC: standard calendar days per stage. Used to auto-fill stage plan dates when a WO
// is released or its route is edited (scheduled backwards from the delivery date).

const STAGE_NAMES: Record<string, string> = {
  F1: "F1 — Foundry / Casting",
  F2: "F2 — Rough Machining",
  F3: "F3 — Finish Machining",
  SP: "SP — Subcontract (incl. transit)",
  FI: "FI — Final Inspection",
  PACKING: "Packing (also Packing / BSR)",
  BSR: "BSR",
};

export default function LeadTimesPage() {
  const [rows, setRows] = useState<LeadTimeRow[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const apply = (data: { stages: LeadTimeRow[] }) => {
    setRows(data.stages);
    setDraft(Object.fromEntries(data.stages.map((r) => [r.stage, String(r.days)])));
  };

  useEffect(() => {
    getLeadTimes()
      .then(apply)
      .catch(() => setError("Could not load lead times."))
      .finally(() => setLoading(false));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaved(false);
    const changed: Record<string, number> = {};
    for (const r of rows) {
      const v = Number(draft[r.stage]);
      if (!Number.isInteger(v) || v < 0 || v > 60) {
        setError(`${r.stage}: enter whole days between 0 and 60.`);
        return;
      }
      if (v !== r.days) changed[r.stage] = v;
    }
    if (Object.keys(changed).length === 0) {
      setError("Nothing has changed.");
      return;
    }
    setSaving(true);
    try {
      apply(await updateLeadTimes(changed));
      setSaved(true);
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setError(err?.response?.status === 403 ? "Only PPC / Admin can change lead times." : typeof d === "string" ? d : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">PPC</span>
            <span className="text-xs text-zinc-400">Planning settings</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Stage Lead Times</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Standard calendar days each stage takes (weekends and holidays included). Used to work out every stage&rsquo;s due date backwards from the customer delivery date.
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-zinc-600 dark:text-zinc-400">
          <Info className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
          <p>Changes apply to work orders released or re-routed from now on. Existing plan dates are not changed — adjust those in Stage Plan Dates.</p>
        </div>

        <form onSubmit={save} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4">
          {loading ? (
            <p className="text-xs text-zinc-500">Loading…</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-[11px] uppercase text-zinc-500">
                <tr>
                  <th className="text-left py-2">Stage</th>
                  <th className="text-left py-2">Days</th>
                  <th className="text-left py-2">Default</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {rows.map((r) => (
                  <tr key={r.stage}>
                    <td className="py-2.5 pr-3">
                      <label htmlFor={`lt-${r.stage}`} className="font-semibold text-zinc-800 dark:text-zinc-200">
                        {STAGE_NAMES[r.stage] || r.stage}
                      </label>
                    </td>
                    <td className="py-2.5 pr-3">
                      <input
                        id={`lt-${r.stage}`}
                        type="number"
                        min={0}
                        max={60}
                        step={1}
                        value={draft[r.stage] ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, [r.stage]: e.target.value }))}
                        className="w-24 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-2 py-1.5"
                      />
                    </td>
                    <td className="py-2.5 text-zinc-500">
                      {r.default_days ?? "—"}
                      {r.customised && <span className="ml-2 rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-bold text-blue-600">changed</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
            </div>
          )}
          {saved && (
            <p className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs font-bold text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="h-4 w-4" /> Lead times saved.
            </p>
          )}

          <button
            type="submit"
            disabled={saving || loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50"
          >
            <Timer className="h-4 w-4" /> {saving ? "Saving…" : "Save Lead Times"}
          </button>
        </form>
      </div>
    </AppShell>
  );
}
