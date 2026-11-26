"use client";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Download, Loader2, Lock, Plus, RefreshCw, Unlock, Upload,
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Modal } from "@/app/components/ui/Modal";
import { ImportReview } from "@/app/components/planning/ImportReview";
import {
  downloadSetupExcel, getSetupDetail, getUnassignedWorkOrders, listSetups,
  getWoSplits, mapWorkOrdersToSetup, moveWorkOrderToSetup, saveWoSplits, planningErrorText, PlanGate, PlanImportOut, PlanWorkOrder, SetupDetail,
  SetupSummary, updateSetup, updateWorkOrderPlan, uploadPlanImport,
} from "@/lib/api";
import {
  fmtDay, fmtDayYear, GateCell, GateLegend, PlanStatusChip, toNull,
} from "@/app/components/planning/PlanUi";

function normStage(s: string): string {
  const v = (s || "").trim().toUpperCase();
  return v === "PACKING / BSR" || v === "PACKING/BSR" ? "PACKING" : v;
}

const inputCls =
  "w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-900 dark:text-zinc-100 disabled:opacity-50";
const labelCls = "block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1";

function ErrorBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
      <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{children}</span>
    </div>
  );
}

export default function SetupDetailPage() {
  const params = useParams<{ setup: string }>();
  const setupNumber = decodeURIComponent(String(params?.setup || ""));

  const [data, setData] = useState<SetupDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ text: string; warnings: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getSetupDetail(setupNumber));
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load this setup."));
    } finally {
      setLoading(false);
    }
  }, [setupNumber]);

  useEffect(() => {
    if (setupNumber) load();
  }, [setupNumber, load]);

  const closed = data?.setup.status === "CLOSED";

  // ------------------------------------------------------------------ download / upload
  const fileRef = useRef<HTMLInputElement>(null);
  const [excelError, setExcelError] = useState("");
  const [importOut, setImportOut] = useState<PlanImportOut | null>(null);

  const onDownload = async () => {
    setExcelError("");
    setBusy(true);
    try {
      await downloadSetupExcel(setupNumber);
    } catch (err: any) {
      // errors on a blob response come back as a Blob; read the text
      let msg = planningErrorText(err, "Could not download the sheet.");
      try {
        const b = err?.response?.data;
        if (b instanceof Blob) msg = JSON.parse(await b.text())?.detail || msg;
      } catch {}
      setExcelError(typeof msg === "string" ? msg : "Could not download the sheet.");
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setExcelError("");
    setBusy(true);
    try {
      setImportOut(await uploadPlanImport(f, setupNumber));
    } catch (err: any) {
      setExcelError(planningErrorText(err, "Could not read the file."));
    } finally {
      setBusy(false);
    }
  };

  // ------------------------------------------------------------------------ close / reopen
  const toggleStatus = async () => {
    if (!data) return;
    setBusy(true);
    try {
      setData(await updateSetup(setupNumber, { status: closed ? "OPEN" : "CLOSED" }));
    } catch (err: any) {
      setError(planningErrorText(err, "Could not change the status."));
    } finally {
      setBusy(false);
    }
  };

  // --------------------------------------------------------------------------- edit panel
  const [editWo, setEditWo] = useState<PlanWorkOrder | null>(null);

  // ------------------------------------------------------------------------------ add WO
  const [addOpen, setAddOpen] = useState(false);

  const gateCols = data?.gate_columns || [];

  return (
    <AppShell>
      <div className="max-w-[1400px] mx-auto space-y-5">
        <Link href="/planning/setups" className="inline-flex items-center gap-1 text-xs font-bold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
          <ArrowLeft className="h-3.5 w-3.5" /> All setups
        </Link>

        {error ? (
          <ErrorBox>{error}</ErrorBox>
        ) : loading && !data ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading setup...</div>
        ) : data ? (
          <>
            {/* header */}
            <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
              <div>
                <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 flex flex-wrap items-center gap-2">
                  Setup <span className="font-mono text-orange-700 dark:text-orange-400">{data.setup.setup_number}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase ${closed ? "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300" : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"}`}>
                    {data.setup.status}
                  </span>
                </h1>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
                  Production day <strong>{fmtDayYear(data.setup.setup_date)}</strong> · {data.rollup.wo_count} work order{data.rollup.wo_count === 1 ? "" : "s"} · {data.rollup.total_qty} pcs ·{" "}
                  {data.rollup.heat_count} heat{data.rollup.heat_count === 1 ? "" : "s"} · earliest commitment {fmtDay(data.rollup.earliest_commitment)}
                  {data.finished_work_orders > 0 && ` · ${data.finished_work_orders} finished not shown`}
                </p>
                {data.setup.remarks && <p className="text-xs text-zinc-500 mt-0.5">{data.setup.remarks}</p>}
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  {data.rollup.delayed > 0 && <span className="rounded-full border border-rose-300 bg-rose-100 px-2.5 py-0.5 text-[11px] font-extrabold text-rose-800 dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-300">{data.rollup.delayed} delayed</span>}
                  {data.rollup.at_risk > 0 && <span className="rounded-full border border-amber-300 bg-amber-100 px-2.5 py-0.5 text-[11px] font-extrabold text-amber-800 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-300">{data.rollup.at_risk} at risk</span>}
                  {data.rollup.no_plan > 0 && <span className="rounded-full border border-zinc-300 bg-zinc-100 px-2.5 py-0.5 text-[11px] font-extrabold text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">{data.rollup.no_plan} no plan</span>}
                  {data.rollup.delayed + data.rollup.at_risk + data.rollup.no_plan === 0 && data.rollup.wo_count > 0 && (
                    <span className="rounded-full border border-emerald-300 bg-emerald-100 px-2.5 py-0.5 text-[11px] font-extrabold text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">all on track</span>
                  )}
                  <span className="text-[11px] text-zinc-400">dates filled {data.rollup.gates_dated}/{data.rollup.gates_total} gates</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={load} className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800">
                  <RefreshCw className="h-3.5 w-3.5" /> Refresh
                </button>
                <button type="button" onClick={onDownload} disabled={busy || data.work_orders.length === 0}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50">
                  <Download className="h-3.5 w-3.5" /> Download Excel
                </button>
                <button type="button" onClick={() => fileRef.current?.click()} disabled={busy || closed}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50">
                  <Upload className="h-3.5 w-3.5" /> Upload Excel
                </button>
                <input ref={fileRef} id="plan-file" type="file" accept=".xlsx" className="hidden" aria-label="Upload the filled Excel plan" onChange={onFile} />
                <button type="button" onClick={() => setAddOpen(true)} disabled={closed}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-50 px-3.5 py-2 text-xs font-bold text-white shadow-sm">
                  <Plus className="h-3.5 w-3.5" /> Add WO
                </button>
                <button type="button" onClick={toggleStatus} disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50">
                  {closed ? <><Unlock className="h-3.5 w-3.5" /> Reopen</> : <><Lock className="h-3.5 w-3.5" /> Close setup</>}
                </button>
              </div>
            </div>

            {excelError && <ErrorBox>{excelError}</ErrorBox>}
            {closed && <div className="rounded-xl border border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 p-2.5 text-xs text-zinc-600 dark:text-zinc-400">This setup is closed. Reopen it to add work orders or change dates.</div>}
            {notice && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 p-3 text-xs space-y-1">
                <div className="flex items-center gap-2 font-bold text-emerald-800 dark:text-emerald-300"><CheckCircle2 className="h-4 w-4" /> {notice.text}
                  <button type="button" onClick={() => setNotice(null)} className="ml-auto text-[11px] font-bold text-emerald-700 dark:text-emerald-400 hover:underline">Dismiss</button>
                </div>
                {notice.warnings.map((w, i) => <div key={i} className="text-amber-800 dark:text-amber-300">Warning: {w}</div>)}
              </div>
            )}

            {/* table */}
            {data.work_orders.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 p-10 text-center text-xs text-zinc-500">
                No work orders in this setup yet. Release a work order into it, or use Add WO for ones released earlier.
              </div>
            ) : (
              <div className="space-y-2">
                <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
                  <table className="w-full text-left text-xs" style={{ minWidth: 760 + gateCols.length * 84 }}>
                    <thead>
                      <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                        <th className="py-3 px-3">WO</th>
                        <th className="py-3 px-3">OAR / PO</th>
                        <th className="py-3 px-3">Part · qty</th>
                        <th className="py-3 px-3">Heat</th>
                        <th className="py-3 px-3">Commit</th>
                        {gateCols.map((g) => <th key={g} className="py-3 px-1.5 text-center">{g}</th>)}
                        <th className="py-3 px-3">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.work_orders.map((wo) => {
                        const by = new Map(wo.gates.map((g) => [normStage(g.stage), g] as [string, PlanGate]));
                        const late = wo.plan_status === "DELAYED";
                        return (
                          <tr key={wo.wo_number + (wo.is_split ? "-split" : "")} onClick={() => { if (!wo.is_split) setEditWo(wo); }} tabIndex={wo.is_split ? -1 : 0}
                            onKeyDown={(e) => { if (e.key === "Enter" && !wo.is_split) setEditWo(wo); }}
                            className={`${wo.is_split ? "cursor-default opacity-80" : "cursor-pointer"} border-b border-zinc-100 dark:border-zinc-800/60 last:border-0 hover:bg-zinc-50 dark:hover:bg-zinc-800/30 ${late ? "bg-rose-50/80 dark:bg-rose-950/25" : ""}`}>
                            <td className="py-2.5 px-3 font-mono font-extrabold text-zinc-900 dark:text-zinc-100 whitespace-nowrap">{wo.wo_number}{wo.is_split && <span className="ml-1.5 rounded-md bg-sky-100 dark:bg-sky-950/50 px-1.5 py-0.5 text-[9px] font-extrabold uppercase text-sky-700 dark:text-sky-300">Split</span>}</td>
                            <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
                              <div>{wo.oar_number || "—"}</div>
                              <div className="text-[10px] text-zinc-400">{wo.customer_po || "—"}</div>
                            </td>
                            <td className="py-2.5 px-3 text-zinc-700 dark:text-zinc-300">
                              <div className="max-w-[160px] truncate" title={wo.part_name || wo.part_number || ""}>{wo.part_name || wo.part_number || "—"}</div>
                              <div className="text-[10px] text-zinc-400">{wo.qty} pcs</div>
                              {wo.split_note && <div className="text-[10px] text-sky-600 dark:text-sky-400 max-w-[180px]">{wo.split_note}</div>}
                            </td>
                            <td className="py-2.5 px-3 font-mono text-zinc-600 dark:text-zinc-400">{wo.heat_numbers.length ? wo.heat_numbers.join(", ") : <span className="text-zinc-300 dark:text-zinc-700">—</span>}</td>
                            <td className="py-2.5 px-3 whitespace-nowrap text-zinc-700 dark:text-zinc-300">{fmtDay(wo.commitment_date)}</td>
                            {gateCols.map((g) => (
                              <td key={g} className="py-2.5 px-1.5 text-center"><GateCell gate={by.get(normStage(g))} /></td>
                            ))}
                            <td className="py-2.5 px-3 min-w-[150px]">
                              <PlanStatusChip status={wo.plan_status} text={wo.plan_text} />
                              {(wo.plan_status === "DELAYED" || wo.plan_status === "AT_RISK") && <div className="mt-1 text-[10px] text-zinc-500 dark:text-zinc-400 max-w-[210px]">{wo.plan_text}</div>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <GateLegend />
                  <span className="text-[11px] text-zinc-400">Each gate shows its planned end date. Click a work order to edit start and end for every gate.</span>
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* edit panel */}
      {editWo && data && (
        <EditPanel
          key={editWo.wo_number}
          wo={editWo}
          setupNumber={setupNumber}
          closed={!!closed}
          onClose={() => setEditWo(null)}
          onSaved={async (text, warnings) => {
            setEditWo(null);
            setNotice({ text, warnings });
            await load();
          }}
          onReload={async () => {
            setEditWo(null);
            await load();
          }}
        />
      )}

      {/* import review */}
      {importOut && (
        <ImportReview
          imp={importOut}
          onChange={setImportOut}
          onClose={async () => {
            setImportOut(null);
            await load();
          }}
        />
      )}

      {/* add WO */}
      {addOpen && (
        <AddWoModal
          setupNumber={setupNumber}
          onClose={() => setAddOpen(false)}
          onDone={async (n) => {
            setAddOpen(false);
            setNotice({ text: `${n} work order${n === 1 ? "" : "s"} added to ${setupNumber}.`, warnings: [] });
            await load();
          }}
        />
      )}
    </AppShell>
  );
}

// ================================================================================== edit panel
function EditPanel({
  wo, setupNumber, closed, onClose, onSaved, onReload,
}: {
  wo: PlanWorkOrder;
  setupNumber: string;
  closed: boolean;
  onClose: () => void;
  onSaved: (text: string, warnings: string[]) => void | Promise<void>;
  onReload: () => void | Promise<void>;
}) {
  const initial = useMemo(() => {
    const m: Record<string, { s: string; e: string }> = {};
    wo.gates.forEach((g) => (m[g.stage] = { s: g.planned_start || "", e: g.planned_end || "" }));
    return m;
  }, [wo]);
  const [draft, setDraft] = useState(initial);
  const [cleared, setCleared] = useState<Record<string, boolean>>({});
  const [heats, setHeats] = useState(wo.heat_numbers.join(", "));
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [stale, setStale] = useState(false);

  const [others, setOthers] = useState<SetupSummary[]>([]);
  const [target, setTarget] = useState("");
  const [moveReason, setMoveReason] = useState("");
  const [moving, setMoving] = useState(false);
  const [moveErr, setMoveErr] = useState("");

  useEffect(() => {
    listSetups("OPEN").then((l) => setOthers(l.filter((s) => s.setup_number !== setupNumber))).catch(() => setOthers([]));
  }, [setupNumber]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setStale(false);
    const gates = wo.gates
      .filter((g) => g.state !== "DONE")
      .filter((g) => cleared[g.stage] || (draft[g.stage]?.s || "") !== (initial[g.stage]?.s || "") || (draft[g.stage]?.e || "") !== (initial[g.stage]?.e || ""))
      .map((g) => cleared[g.stage]
        ? { stage: g.stage, clear: true }
        : { stage: g.stage, planned_start: toNull(draft[g.stage]?.s || ""), planned_end: toNull(draft[g.stage]?.e || "") });
    const heatList = heats.split(/[,;\n]/).map((h) => h.trim()).filter(Boolean);
    const heatsChanged = heatList.join("|").toUpperCase() !== wo.heat_numbers.join("|").toUpperCase();
    if (!gates.length && !heatsChanged) {
      setErr("Nothing changed.");
      return;
    }
    if (reason.trim().length < 3) {
      setErr("Give a short reason (it goes in the change log).");
      return;
    }
    setSaving(true);
    try {
      const res = await updateWorkOrderPlan(wo.wo_number, {
        gates,
        heat_numbers: heatsChanged ? heatList : undefined,
        reason: reason.trim(),
        expected_plan_version: wo.plan_version,
      });
      await onSaved(
        `${wo.wo_number} saved${res.changed_gates.length ? ` (${res.changed_gates.join(", ")})` : ""}.`,
        res.warnings.map((w) => w.message)
      );
    } catch (error: any) {
      setErr(planningErrorText(error, "Could not save the plan."));
      if (error?.response?.status === 409) setStale(true);
      setSaving(false);
    }
  };

  const move = async () => {
    setMoveErr("");
    if (!target) {
      setMoveErr("Choose the setup to move it to.");
      return;
    }
    if (moveReason.trim().length < 3) {
      setMoveErr("Give a short reason.");
      return;
    }
    setMoving(true);
    try {
      await moveWorkOrderToSetup(wo.wo_number, { to_setup_number: target, reason: moveReason.trim() });
      await onSaved(`${wo.wo_number} moved to setup ${target}.`, []);
    } catch (error: any) {
      setMoveErr(planningErrorText(error, "Could not move the work order."));
      setMoving(false);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`${wo.wo_number} · gate dates`} subtitle={`${wo.part_name || wo.part_number || ""} · ${wo.qty} pcs · commitment ${fmtDayYear(wo.commitment_date)}`} maxWidth="2xl">
      <form onSubmit={save} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <PlanStatusChip status={wo.plan_status} text={wo.plan_text} />
          <span className="text-[11px] text-zinc-500">{wo.plan_text}</span>
        </div>
        {err && (
          <div className="space-y-1.5">
            <ErrorBox>{err}</ErrorBox>
            {stale && (
              <button type="button" onClick={() => onReload()} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 px-2.5 py-1 text-[11px] font-bold text-zinc-700 dark:text-zinc-300">
                <RefreshCw className="h-3 w-3" /> Reload the latest plan
              </button>
            )}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[460px]">
            <thead>
              <tr className="text-left text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                <th className="py-1.5 pr-2">Gate</th><th className="py-1.5 pr-2">State</th><th className="py-1.5 pr-2">Start</th><th className="py-1.5 pr-2">End</th><th className="py-1.5"><span className="sr-only">Clear</span></th>
              </tr>
            </thead>
            <tbody>
              {wo.gates.map((g) => {
                const done = g.state === "DONE";
                const id = `gate-${g.stage.replace(/[^A-Za-z0-9]/g, "")}`;
                return (
                  <tr key={g.stage} className="border-t border-zinc-100 dark:border-zinc-800/60">
                    <td className="py-1.5 pr-2 font-extrabold text-zinc-800 dark:text-zinc-200">{g.stage}</td>
                    <td className="py-1.5 pr-2 text-[11px] text-zinc-500">{done ? "done" : g.state === "IN_PROGRESS" ? "in progress" : "not started"}{g.flag === "LATE" ? ` · +${g.days_late}d late` : ""}</td>
                    <td className="py-1.5 pr-2">
                      <label htmlFor={`${id}-s`} className="sr-only">{g.stage} start</label>
                      <input id={`${id}-s`} type="date" disabled={done || closed || !!cleared[g.stage]} value={cleared[g.stage] ? "" : draft[g.stage]?.s || ""} className={inputCls}
                        onChange={(e) => setDraft((d) => ({ ...d, [g.stage]: { ...d[g.stage], s: e.target.value } }))} />
                    </td>
                    <td className="py-1.5 pr-2">
                      <label htmlFor={`${id}-e`} className="sr-only">{g.stage} end</label>
                      <input id={`${id}-e`} type="date" disabled={done || closed || !!cleared[g.stage]} value={cleared[g.stage] ? "" : draft[g.stage]?.e || ""} className={inputCls}
                        onChange={(e) => setDraft((d) => ({ ...d, [g.stage]: { ...d[g.stage], e: e.target.value } }))} />
                    </td>
                    <td className="py-1.5 whitespace-nowrap">
                      {!done && !closed && (initial[g.stage]?.s || initial[g.stage]?.e) && (
                        <button type="button" onClick={() => setCleared((c) => ({ ...c, [g.stage]: !c[g.stage] }))}
                          className={`rounded-md px-2 py-1 text-[11px] font-bold ${cleared[g.stage] ? "bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300" : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
                          aria-pressed={!!cleared[g.stage]} aria-label={`Clear ${g.stage} dates`}>
                          {cleared[g.stage] ? "Will clear (undo)" : "Clear"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-zinc-400">A finished gate cannot be re-planned. Use Clear to remove a gate's dates; leaving a date blank keeps it.</p>
        <div>
          <label htmlFor="edit-heats" className={labelCls}>Heat numbers (comma separated)</label>
          <input id="edit-heats" value={heats} onChange={(e) => setHeats(e.target.value)} disabled={closed} className={inputCls} placeholder="e.g. H-771, H-772" />
        </div>
        <div>
          <label htmlFor="edit-reason" className={labelCls}>Reason *</label>
          <input id="edit-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} disabled={closed} className={inputCls} placeholder="e.g. Furnace breakdown, moved F2 by 2 days" />
        </div>
        <div className="flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Cancel</button>
          <button type="submit" disabled={saving || closed} className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save dates
          </button>
        </div>
      </form>

      <div className="mt-5 border-t border-zinc-200 dark:border-zinc-800 pt-4 space-y-2">
        <h3 className="text-xs font-extrabold text-zinc-800 dark:text-zinc-200">Move to another setup</h3>
        {moveErr && <ErrorBox>{moveErr}</ErrorBox>}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-end">
          <div>
            <label htmlFor="move-target" className={labelCls}>Setup</label>
            <select id="move-target" value={target} onChange={(e) => setTarget(e.target.value)} disabled={closed} className={inputCls}>
              <option value="">Choose a setup</option>
              {others.map((s) => <option key={s.setup_number} value={s.setup_number}>{s.setup_number}{s.setup_date ? ` · ${fmtDay(s.setup_date)}` : ""}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="move-reason" className={labelCls}>Reason</label>
            <input id="move-reason" value={moveReason} onChange={(e) => setMoveReason(e.target.value)} disabled={closed} className={inputCls} />
          </div>
          <button type="button" onClick={move} disabled={moving || closed} className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60">
            {moving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Move
          </button>
        </div>
      </div>
      {!closed && <SplitSection wo={wo} setupNumber={setupNumber} others={others} onSaved={onSaved} />}
    </Modal>
  );
}

// ================================================================================ split section
function SplitSection({ wo, setupNumber, others, onSaved }: {
  wo: PlanWorkOrder; setupNumber: string; others: SetupSummary[];
  onSaved: (text: string, warnings: string[]) => void | Promise<void>;
}) {
  const [total, setTotal] = useState(wo.total_qty ?? wo.qty ?? 0);
  const [parts, setParts] = useState<{ setup_number: string; qty: string }[]>([]);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getWoSplits(wo.wo_number)
      .then((r) => { setTotal(r.total_qty); setParts(r.splits.map((x) => ({ setup_number: x.setup_number, qty: String(x.qty) }))); })
      .catch(() => setParts([]));
  }, [wo.wo_number]);

  const used = parts.reduce((a, p) => a + (parseInt(p.qty, 10) || 0), 0);
  const remainder = total - used;

  const save = async () => {
    setErr("");
    if (parts.some((p) => !p.setup_number || !(parseInt(p.qty, 10) > 0))) { setErr("Choose a setup and a quantity for every row."); return; }
    if (remainder < 1 && parts.length) { setErr(`The shares add up to ${used} of ${total} pieces; ${setupNumber} must keep at least 1.`); return; }
    if (reason.trim().length < 3) { setErr("Give a short reason."); return; }
    setBusy(true);
    try {
      await saveWoSplits(wo.wo_number, parts.map((p) => ({ setup_number: p.setup_number, qty: parseInt(p.qty, 10) })), reason.trim());
      await onSaved(parts.length ? `${wo.wo_number} split across ${parts.length + 1} setups.` : `${wo.wo_number} is no longer split.`, []);
    } catch (e: any) {
      setErr(planningErrorText(e, "Could not save the split."));
      setBusy(false);
    }
  };

  return (
    <div className="mt-5 border-t border-zinc-200 dark:border-zinc-800 pt-4 space-y-2">
      <h3 className="text-xs font-extrabold text-zinc-800 dark:text-zinc-200">Split across setups</h3>
      <p className="text-[11px] text-zinc-500">Plan part of the {total} pieces in another setup. Dates stay with the work order; floor quantities are not changed.</p>
      {err && <ErrorBox>{err}</ErrorBox>}
      {parts.map((p, i) => (
        <div key={i} className="grid grid-cols-[1fr_90px_auto] gap-2 items-center">
          <select aria-label="Setup" value={p.setup_number} onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, setup_number: e.target.value } : x)))} className={inputCls}>
            <option value="">Choose a setup</option>
            {others.map((s) => <option key={s.setup_number} value={s.setup_number}>{s.setup_number}</option>)}
          </select>
          <input aria-label="Pieces" type="number" min={1} value={p.qty} onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))} className={inputCls} />
          <button type="button" onClick={() => setParts(parts.filter((_, j) => j !== i))} className="rounded-xl px-2 py-2 text-xs font-bold text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30">Remove</button>
        </div>
      ))}
      <div className="flex items-center justify-between text-[11px]">
        <button type="button" onClick={() => setParts([...parts, { setup_number: "", qty: "" }])} className="font-bold text-orange-600">+ Add a setup</button>
        <span className={remainder < 1 && parts.length ? "font-bold text-rose-600" : "text-zinc-500"}>{setupNumber} keeps {remainder} pcs</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 items-end">
        <div>
          <label htmlFor="split-reason" className={labelCls}>Reason</label>
          <input id="split-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} className={inputCls} placeholder="e.g. Two furnace days needed" />
        </div>
        <button type="button" onClick={save} disabled={busy} className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save split
        </button>
      </div>
    </div>
  );
}

// ================================================================================= add WO
function AddWoModal({ setupNumber, onClose, onDone }: { setupNumber: string; onClose: () => void; onDone: (n: number) => void | Promise<void> }) {
  const [rows, setRows] = useState<PlanWorkOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [skipped, setSkipped] = useState<{ wo_number: string; message: string }[]>([]);

  useEffect(() => {
    getUnassignedWorkOrders()
      .then(setRows)
      .catch((e) => setErr(planningErrorText(e, "Could not load the unassigned work orders.")))
      .finally(() => setLoading(false));
  }, []);

  const chosen = Object.keys(picked).filter((k) => picked[k]);

  const submit = async () => {
    setErr("");
    if (!chosen.length) {
      setErr("Tick at least one work order.");
      return;
    }
    if (reason.trim().length < 3) {
      setErr("Give a short reason.");
      return;
    }
    setSaving(true);
    try {
      const res = await mapWorkOrdersToSetup(setupNumber, { wo_numbers: chosen, reason: reason.trim() });
      if (res.errors.length) {
        setSkipped(res.errors);
        if (res.mapped.length) await onDone(res.mapped.length);
        setSaving(false);
        return;
      }
      await onDone(res.mapped.length);
    } catch (e: any) {
      setErr(planningErrorText(e, "Could not add the work orders."));
      setSaving(false);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title="Add work orders" subtitle={`Released work orders that are not in any setup yet → ${setupNumber}`} maxWidth="2xl">
      <div className="space-y-3">
        {err && <ErrorBox>{err}</ErrorBox>}
        {skipped.map((s, i) => <div key={i} className="text-xs text-amber-700 dark:text-amber-300"><span className="font-mono font-bold">{s.wo_number}</span>: {s.message}</div>)}
        {loading ? (
          <div className="flex items-center justify-center gap-2 p-6 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
        ) : rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-700 p-6 text-center text-xs text-zinc-500">Every released work order already has a setup.</div>
        ) : (
          <div className="max-h-72 overflow-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-xs min-w-[460px]">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.wo_number} className="border-b border-zinc-100 dark:border-zinc-800/60 last:border-0">
                    <td className="py-2 px-3 w-8">
                      <input id={`pick-${r.wo_number}`} type="checkbox" checked={!!picked[r.wo_number]} onChange={(e) => setPicked((p) => ({ ...p, [r.wo_number]: e.target.checked }))} aria-label={`Add ${r.wo_number}`} />
                    </td>
                    <td className="py-2 px-3 font-mono font-bold"><label htmlFor={`pick-${r.wo_number}`}>{r.wo_number}</label></td>
                    <td className="py-2 px-3 text-zinc-600 dark:text-zinc-400">{r.part_name || r.part_number || "—"} · {r.qty} pcs</td>
                    <td className="py-2 px-3 text-zinc-500">commit {fmtDay(r.commitment_date)}</td>
                    <td className="py-2 px-3"><PlanStatusChip status={r.plan_status} text={r.plan_text} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div>
          <label htmlFor="add-reason" className={labelCls}>Reason *</label>
          <input id="add-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} className={inputCls} placeholder="e.g. Released before setup planning" />
        </div>
        <div className="flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Cancel</button>
          <button type="button" onClick={submit} disabled={saving || loading || rows.length === 0} className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Add {chosen.length || ""} to setup
          </button>
        </div>
      </div>
    </Modal>
  );
}
