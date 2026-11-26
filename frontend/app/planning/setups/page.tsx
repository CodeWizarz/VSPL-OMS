"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CalendarRange, Plus, Loader2, AlertTriangle, RefreshCw, Download, Upload } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { createSetup, downloadAllSetupsExcel, listSetups, planningErrorText, PlanImportOut, SetupSummary, uploadPlanImport } from "@/lib/api";
import { ImportReview } from "@/app/components/planning/ImportReview";
import { fmtDay, fmtDayYear } from "@/app/components/planning/PlanUi";

// PPC: every released work order belongs to a setup (one production day with several work orders).
// docs/setup-planning-architecture.md

export default function SetupsPage() {
  const router = useRouter();
  const [setups, setSetups] = useState<SetupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"OPEN" | "CLOSED" | "ALL">("OPEN");

  const [showForm, setShowForm] = useState(false);
  const [number, setNumber] = useState("");
  const [day, setDay] = useState("");
  const [remarks, setRemarks] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");

  const fileRef = useRef<HTMLInputElement>(null);
  const [excelBusy, setExcelBusy] = useState(false);
  const [excelError, setExcelError] = useState("");
  const [importOut, setImportOut] = useState<PlanImportOut | null>(null);

  const downloadAll = async () => {
    setExcelBusy(true);
    setExcelError("");
    try {
      await downloadAllSetupsExcel(tab);
    } catch (err: any) {
      let msg = "";
      try { msg = JSON.parse(await err?.response?.data?.text?.())?.detail; } catch {}
      setExcelError(typeof msg === "string" && msg ? msg : planningErrorText(err, "Could not download the sheet."));
    } finally {
      setExcelBusy(false);
    }
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setExcelBusy(true);
    setExcelError("");
    try {
      setImportOut(await uploadPlanImport(f));
    } catch (err: any) {
      setExcelError(planningErrorText(err, "Could not read the file."));
    } finally {
      setExcelBusy(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSetups(await listSetups(tab === "ALL" ? undefined : tab));
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load the setups."));
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!number.trim()) {
      setFormError("Enter a setup number.");
      return;
    }
    setCreating(true);
    setFormError("");
    try {
      const d = await createSetup({ setup_number: number.trim(), setup_date: day || null, remarks: remarks.trim() || undefined });
      router.push(`/planning/setups/${encodeURIComponent(d.setup.setup_number)}`);
    } catch (err: any) {
      setFormError(planningErrorText(err, "Could not create the setup."));
      setCreating(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-orange-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">PPC</span>
              <span className="text-xs text-zinc-400">Planning &amp; Scheduling</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2">
              <CalendarRange className="h-6 w-6 text-orange-500" /> Setups
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 max-w-2xl">
              A setup is one production day with several work orders. Open a setup to see its work orders, set the date for each gate, and download or upload the Excel plan.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={load}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
            <button type="button" onClick={downloadAll} disabled={excelBusy}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60">
              <Download className="h-3.5 w-3.5" /> Download all ({tab === "ALL" ? "all" : tab.toLowerCase()})
            </button>
            <button type="button" onClick={() => fileRef.current?.click()} disabled={excelBusy}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60">
              <Upload className="h-3.5 w-3.5" /> Upload multi-setup sheet
            </button>
            <input ref={fileRef} type="file" accept=".xlsx" className="hidden" aria-label="Upload a filled multi-setup Excel plan" onChange={onFile} />
            <button
              type="button"
              onClick={() => setShowForm((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 px-3.5 py-2 text-xs font-bold text-white shadow-sm"
            >
              <Plus className="h-3.5 w-3.5" /> New setup
            </button>
          </div>
        </div>

        {excelError && (
          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{excelError}</span>
          </div>
        )}

        {showForm && (
          <form onSubmit={submit} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3">
            <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">Create a setup</h2>
            {formError && (
              <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300">
                <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{formError}</span>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label htmlFor="setup-number" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Setup number *</label>
                <input id="setup-number" value={number} onChange={(e) => setNumber(e.target.value)} maxLength={60} placeholder="e.g. S-2026-0142"
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm font-mono font-bold text-zinc-900 dark:text-zinc-100" />
              </div>
              <div>
                <label htmlFor="setup-day" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Production day</label>
                <input id="setup-day" type="date" value={day} onChange={(e) => setDay(e.target.value)}
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100" />
              </div>
              <div>
                <label htmlFor="setup-remarks" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Remarks</label>
                <input id="setup-remarks" value={remarks} onChange={(e) => setRemarks(e.target.value)} maxLength={1000}
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button type="submit" disabled={creating} className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
                {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Create setup
              </button>
              <button type="button" onClick={() => setShowForm(false)} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Cancel</button>
            </div>
          </form>
        )}

        <div className="flex items-center gap-1 text-xs font-bold">
          {(["OPEN", "CLOSED", "ALL"] as const).map((t) => (
            <button key={t} type="button" onClick={() => setTab(t)}
              className={`rounded-lg px-3 py-1.5 ${tab === t ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}>
              {t === "OPEN" ? "Open" : t === "CLOSED" ? "Closed" : "All"}
            </button>
          ))}
        </div>

        {error ? (
          <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-4 text-xs font-semibold text-rose-700 dark:text-rose-300">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading setups...</div>
        ) : setups.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 p-10 text-center text-xs text-zinc-500">
            No setups here yet. Create one, then release work orders into it.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
            <table className="w-full min-w-[860px] text-left text-xs">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                  <th className="py-3 px-4">Setup</th>
                  <th className="py-3 px-4">Production day</th>
                  <th className="py-3 px-4 text-center">Work orders</th>
                  <th className="py-3 px-4 text-center">Qty</th>
                  <th className="py-3 px-4 text-center">Heats</th>
                  <th className="py-3 px-4">Earliest commitment</th>
                  <th className="py-3 px-4">Delays</th>
                  <th className="py-3 px-4">Dates filled</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {setups.map((s) => (
                  <tr key={s.setup_number} className="border-b border-zinc-100 dark:border-zinc-800/60 last:border-0 hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                    <td className="py-3 px-4">
                      <Link href={`/planning/setups/${encodeURIComponent(s.setup_number)}`} className="font-mono font-extrabold text-orange-700 dark:text-orange-400 hover:underline">
                        {s.setup_number}
                      </Link>
                      {s.remarks && <div className="text-[10px] text-zinc-400 max-w-[200px] truncate" title={s.remarks}>{s.remarks}</div>}
                    </td>
                    <td className="py-3 px-4 text-zinc-700 dark:text-zinc-300">{fmtDayYear(s.setup_date)}</td>
                    <td className="py-3 px-4 text-center font-bold">{s.wo_count}</td>
                    <td className="py-3 px-4 text-center">{s.total_qty}</td>
                    <td className="py-3 px-4 text-center">{s.heat_count}</td>
                    <td className="py-3 px-4 text-zinc-700 dark:text-zinc-300">{fmtDay(s.earliest_commitment)}</td>
                    <td className="py-3 px-4">
                      <div className="flex flex-wrap gap-1.5">
                        {s.delayed > 0 && <span className="rounded-full border border-rose-300 bg-rose-100 px-2 py-0.5 text-[10px] font-extrabold text-rose-800 dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-300">{s.delayed} delayed</span>}
                        {s.at_risk > 0 && <span className="rounded-full border border-amber-300 bg-amber-100 px-2 py-0.5 text-[10px] font-extrabold text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-300">{s.at_risk} at risk</span>}
                        {s.no_plan > 0 && <span className="rounded-full border border-zinc-300 bg-zinc-100 px-2 py-0.5 text-[10px] font-extrabold text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">{s.no_plan} no plan</span>}
                        {s.delayed + s.at_risk + s.no_plan === 0 && <span className="text-zinc-400">{s.wo_count ? "on track" : "—"}</span>}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <span className="font-mono">{s.gates_dated}/{s.gates_total}</span>
                      <span className="text-zinc-400"> gates</span>
                    </td>
                    <td className="py-3 px-4">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase ${s.status === "OPEN" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300" : "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"}`}>{s.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    {importOut && (
        <ImportReview imp={importOut} onChange={setImportOut} onClose={async () => { setImportOut(null); await load(); }} />
      )}
    </AppShell>
  );
}
