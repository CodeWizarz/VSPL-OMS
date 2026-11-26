"use client";
import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Undo2 } from "lucide-react";
import { Modal } from "@/app/components/ui/Modal";
import { applyPlanImport, discardPlanImport, planningErrorText, PlanImportOut, undoPlanImport } from "@/lib/api";
import { fmtDay } from "@/app/components/planning/PlanUi";

// Review of an uploaded plan sheet (one setup or several). Nothing changes until Apply.

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
      <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{children}</span>
    </div>
  );
}

export function ImportReview({ imp, onChange, onClose }: { imp: PlanImportOut; onChange: (i: PlanImportOut) => void; onClose: () => void | Promise<void> }) {
  const [overwrite, setOverwrite] = useState(false);
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState("");

  const staleRows = imp.rows.filter((r) => r.stage === "PLAN");
  const errorRows = imp.rows.filter((r) => r.result === "ERROR");
  const changeRows = imp.rows.filter((r) => r.result !== "ERROR" && r.stage !== "PLAN");
  const reviewing = imp.status === "REVIEW";
  const applied = imp.status === "APPLIED";
  const canApply = reviewing && imp.counts.ready + imp.counts.warning > 0;

  const run = async (fn: () => Promise<PlanImportOut>) => {
    setWorking(true);
    setErr("");
    try {
      onChange(await fn());
    } catch (e: any) {
      setErr(planningErrorText(e, "That did not work."));
    } finally {
      setWorking(false);
    }
  };

  const range = (a: string | null, b: string | null) => (a || b ? `${fmtDay(a)} to ${fmtDay(b)}` : "—");

  const tile = (label: string, n: number, tone: string) => (
    <div className={`rounded-xl border p-3 ${tone}`}>
      <div className="text-xl font-extrabold">{n}</div>
      <div className="text-[11px] font-semibold">{label}</div>
    </div>
  );

  return (
    <Modal isOpen onClose={() => onClose()} title={`Import review · ${imp.file_name}`} subtitle={applied ? "Applied" : imp.status === "REVIEW" ? "Nothing changes until you click Apply" : imp.status.toLowerCase()} maxWidth="2xl">
      <div className="space-y-4">
        {err && <ErrorBox>{err}</ErrorBox>}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {tile("work orders in file", imp.counts.total_wos, "border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200")}
          {tile("ready", imp.counts.ready, "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300")}
          {tile("with warnings", imp.counts.warning, "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300")}
          {tile("with errors", imp.counts.error, "border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300")}
          {tile("unchanged", imp.counts.unchanged, "border-zinc-200 dark:border-zinc-800 text-zinc-500")}
        </div>
        {imp.notes.map((n, i) => <div key={i} className="rounded-xl border border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/40 p-2.5 text-xs text-blue-800 dark:text-blue-300">{n}</div>)}

        {errorRows.length > 0 && (
          <div className="rounded-xl border border-rose-200 dark:border-rose-900 overflow-hidden">
            <div className="bg-rose-50 dark:bg-rose-950/40 px-3 py-1.5 text-[11px] font-extrabold uppercase tracking-wider text-rose-700 dark:text-rose-300">Errors: these work orders are skipped</div>
            <ul className="divide-y divide-rose-100 dark:divide-rose-900/50 text-xs">
              {errorRows.map((r, i) => (
                <li key={i} className="px-3 py-1.5 flex flex-wrap gap-x-3">
                  <span className="text-zinc-400">row {r.row_no ?? "?"}</span>
                  <span className="font-mono font-bold">{r.wo_number || "—"}</span>
                  {r.stage && <span className="text-zinc-500">{r.stage}</span>}
                  <span className="text-rose-700 dark:text-rose-300">{r.message}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {changeRows.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-xs min-w-[560px]">
              <thead>
                <tr className="bg-zinc-50 dark:bg-zinc-800/40 text-left text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                  <th className="py-2 px-3">WO</th><th className="py-2 px-3">Gate</th><th className="py-2 px-3">Old</th><th className="py-2 px-3">New</th><th className="py-2 px-3">Result</th>
                </tr>
              </thead>
              <tbody>
                {changeRows.map((r, i) => (
                  <tr key={i} className="border-t border-zinc-100 dark:border-zinc-800/60 align-top">
                    <td className="py-1.5 px-3 font-mono font-bold">{r.wo_number}</td>
                    <td className="py-1.5 px-3">{r.stage === "HEATS" ? "Heat numbers" : r.stage}</td>
                    <td className="py-1.5 px-3 text-zinc-500">{r.stage === "HEATS" ? (r.old_text || "—") : range(r.old_start, r.old_end)}</td>
                    <td className="py-1.5 px-3 font-bold">{r.stage === "HEATS" ? (r.new_text || "—") : range(r.new_start, r.new_end)}</td>
                    <td className="py-1.5 px-3">
                      {r.result === "WARNING" ? <span className="text-amber-700 dark:text-amber-300 font-semibold">Warning: {r.message}</span> : <span className="text-emerald-700 dark:text-emerald-300 font-semibold">{applied && r.applied ? "Applied" : "Ready"}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {changeRows.length === 0 && errorRows.length === 0 && <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 text-xs text-zinc-500">The file makes no changes.</div>}

        {staleRows.length > 0 && reviewing && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40 p-3 text-xs space-y-1.5">
            <div className="font-bold text-amber-800 dark:text-amber-300">Plans changed after this sheet was downloaded: {staleRows.map((r) => r.wo_number).join(", ")}</div>
            <label className="flex items-center gap-2 text-amber-900 dark:text-amber-200">
              <input id="overwrite-stale" type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
              Overwrite changed plans (otherwise these work orders are skipped)
            </label>
          </div>
        )}

        {applied && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 p-3 text-xs space-y-1">
            <div className="flex items-center gap-2 font-bold text-emerald-800 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" /> {imp.counts.applied} work order{imp.counts.applied === 1 ? "" : "s"} updated, {imp.counts.skipped} skipped.</div>
            {(imp.skipped || []).map((s, i) => <div key={i} className="text-amber-800 dark:text-amber-300"><span className="font-mono font-bold">{s.wo_number}</span>: {s.message}</div>)}
          </div>
        )}
        {imp.status === "UNDONE" && (
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 text-xs space-y-1">
            <div className="font-bold">Undone: {imp.restored ?? 0} work order{(imp.restored ?? 0) === 1 ? "" : "s"} restored.</div>
            {(imp.skipped || []).map((s, i) => <div key={i} className="text-amber-700 dark:text-amber-300"><span className="font-mono font-bold">{s.wo_number}</span>: {s.message}</div>)}
          </div>
        )}
        {imp.status === "DISCARDED" && <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 text-xs text-zinc-500">Discarded. Nothing was changed.</div>}

        <div className="flex flex-wrap items-center justify-end gap-2">
          {reviewing && (
            <>
              <button type="button" disabled={working} onClick={() => run(() => discardPlanImport(imp.id))} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Discard</button>
              <button type="button" disabled={working || !canApply} onClick={() => run(() => applyPlanImport(imp.id, overwrite))}
                className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
                {working && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Apply {imp.counts.ready + imp.counts.warning} work order{imp.counts.ready + imp.counts.warning === 1 ? "" : "s"}
              </button>
            </>
          )}
          {applied && (
            <button type="button" disabled={working} onClick={() => run(() => undoPlanImport(imp.id))}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60">
              {working ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Undo2 className="h-3.5 w-3.5" />} Undo this import
            </button>
          )}
          {!reviewing && <button type="button" onClick={() => onClose()} className="rounded-xl bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-xs font-bold text-white dark:text-zinc-900">Close</button>}
        </div>
      </div>
    </Modal>
  );
}
