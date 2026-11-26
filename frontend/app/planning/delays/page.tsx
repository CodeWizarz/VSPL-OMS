"use client";
import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Loader2, Mail, RefreshCw } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getDelayBoard, getPlanDigest, listSetups, planningErrorText, PlanDigest, PlanWorkOrder, sendPlanDigest, SetupSummary } from "@/lib/api";
import { fmtDay, PlanStatusChip } from "@/app/components/planning/PlanUi";

// PPC: every work order that is late or at risk, across setups. Computed live from the plan dates,
// the floor's records and the commitment date. docs/setup-planning-architecture.md

type Filter = "DELAYED" | "AT_RISK" | "NO_PLAN";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "DELAYED", label: "Delayed" },
  { key: "AT_RISK", label: "At risk" },
  { key: "NO_PLAN", label: "No plan" },
];

export default function DelayBoardPage() {
  const [on, setOn] = useState<Record<Filter, boolean>>({ DELAYED: true, AT_RISK: true, NO_PLAN: false });
  const [setup, setSetup] = useState("");
  const [setups, setSetups] = useState<SetupSummary[]>([]);
  const [rows, setRows] = useState<PlanWorkOrder[]>([]);
  const [today, setToday] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [digest, setDigest] = useState<PlanDigest | null>(null);
  const [digestOpen, setDigestOpen] = useState(false);
  const [digestBusy, setDigestBusy] = useState(false);
  const [digestMsg, setDigestMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const openDigest = async () => {
    const next = !digestOpen;
    setDigestOpen(next);
    if (!next) return;
    setDigestMsg(null);
    try {
      setDigest(await getPlanDigest());
    } catch (err: any) {
      setDigestMsg({ ok: false, text: planningErrorText(err, "Could not load the digest.") });
    }
  };

  const sendDigest = async () => {
    setDigestBusy(true);
    setDigestMsg(null);
    try {
      const r = await sendPlanDigest();
      setDigest(r);
      setDigestMsg({
        ok: true,
        text: r.email_sent
          ? `Sent to ${r.recipients.length} planner${r.recipients.length === 1 ? "" : "s"}: ${r.recipients.join(", ")}.`
          : `Not emailed (the server has no email set up or there are no planner addresses); it was recorded in the server log.`,
      });
    } catch (err: any) {
      setDigestMsg({ ok: false, text: planningErrorText(err, "Could not send the digest.") });
    } finally {
      setDigestBusy(false);
    }
  };

  useEffect(() => {
    listSetups().then(setSetups).catch(() => setSetups([]));
  }, []);

  const load = useCallback(async () => {
    const statuses = FILTERS.filter((f) => on[f.key]).map((f) => f.key);
    if (!statuses.length) {
      setRows([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await getDelayBoard({ setup: setup || undefined, status: statuses.join(",") });
      setRows(res.work_orders);
      setToday(res.today);
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load the delay board."));
    } finally {
      setLoading(false);
    }
  }, [on, setup]);

  useEffect(() => {
    load();
  }, [load]);

  const delayed = rows.filter((r) => r.plan_status === "DELAYED").length;
  const atRisk = rows.filter((r) => r.plan_status === "AT_RISK").length;

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
              <AlertTriangle className="h-6 w-6 text-rose-500" /> Delay Board
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 max-w-2xl">
              Work orders behind their plan or at risk of missing the commitment date{today ? ` (as of ${fmtDay(today)})` : ""}. Worst first.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start">
            <button type="button" onClick={openDigest} aria-expanded={digestOpen} className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800">
              <Mail className="h-3.5 w-3.5" /> Daily digest
            </button>
            <button type="button" onClick={load} className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800">
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        </div>

        {digestOpen && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">Morning digest for PPC</h2>
                <p className="text-[11px] text-zinc-500">Delayed and at-risk work orders, worst first. Preview only until you send it.</p>
              </div>
              <button type="button" onClick={sendDigest} disabled={digestBusy || !digest} className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-3.5 py-2 text-xs font-bold text-white">
                {digestBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Mail className="h-3.5 w-3.5" />} Send to planners now
              </button>
            </div>
            {digestMsg && (
              <div className={`flex items-start gap-2 rounded-xl border p-2.5 text-xs font-semibold ${digestMsg.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300" : "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300"}`} role={digestMsg.ok ? "status" : "alert"}>
                {digestMsg.ok ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />} <span>{digestMsg.text}</span>
              </div>
            )}
            {digest ? (
              <div className="space-y-2 text-xs">
                <div className="text-zinc-600 dark:text-zinc-400">
                  {digest.counts.delayed} delayed · {digest.counts.at_risk} at risk · {digest.counts.no_plan} without a full plan
                </div>
                {[...digest.delayed, ...digest.at_risk].length === 0 ? (
                  <div className="text-zinc-500">Nothing is late or at risk today.</div>
                ) : (
                  <ul className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800">
                    {[...digest.delayed, ...digest.at_risk].map((r) => (
                      <li key={r.wo_number} className="px-3 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
                        <span className="font-mono font-extrabold">{r.wo_number}</span>
                        <span className="text-zinc-500">{r.setup_number || "no setup"}</span>
                        <span className={r.plan_status === "DELAYED" ? "text-rose-700 dark:text-rose-300 font-semibold" : "text-amber-700 dark:text-amber-300 font-semibold"}>{r.plan_text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : !digestMsg ? (
              <div className="flex items-center gap-2 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
            ) : null}
          </div>
        )}

        <div className="flex flex-wrap items-end gap-4">
          <fieldset className="flex items-center gap-3 text-xs font-bold text-zinc-700 dark:text-zinc-300">
            <legend className="sr-only">Show</legend>
            {FILTERS.map((f) => (
              <label key={f.key} htmlFor={`f-${f.key}`} className="inline-flex items-center gap-1.5 cursor-pointer">
                <input id={`f-${f.key}`} type="checkbox" checked={on[f.key]} onChange={(e) => setOn((o) => ({ ...o, [f.key]: e.target.checked }))} /> {f.label}
              </label>
            ))}
          </fieldset>
          <div>
            <label htmlFor="delay-setup" className="block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1">Setup</label>
            <select id="delay-setup" value={setup} onChange={(e) => setSetup(e.target.value)} className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1.5 text-xs text-zinc-900 dark:text-zinc-100">
              <option value="">All setups</option>
              {setups.map((s) => <option key={s.setup_number} value={s.setup_number}>{s.setup_number}</option>)}
            </select>
          </div>
          <div className="text-xs text-zinc-500 pb-1.5">{delayed} delayed · {atRisk} at risk</div>
        </div>

        {error ? (
          <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-4 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
        ) : rows.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 p-10 text-center text-xs text-zinc-500">Nothing to show for these filters.</div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                  <th className="py-3 px-3">WO</th>
                  <th className="py-3 px-3">Setup</th>
                  <th className="py-3 px-3">Part · qty</th>
                  <th className="py-3 px-3">Commitment</th>
                  <th className="py-3 px-3">Late gate</th>
                  <th className="py-3 px-3">Why</th>
                  <th className="py-3 px-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const dc = r.days_to_commitment;
                  return (
                    <tr key={r.wo_number} className={`border-b border-zinc-100 dark:border-zinc-800/60 last:border-0 ${r.plan_status === "DELAYED" ? "bg-rose-50/80 dark:bg-rose-950/25" : r.plan_status === "AT_RISK" ? "bg-amber-50/60 dark:bg-amber-950/15" : ""}`}>
                      <td className="py-2.5 px-3 font-mono font-extrabold whitespace-nowrap">{r.wo_number}</td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        {r.setup_number ? (
                          <Link href={`/planning/setups/${encodeURIComponent(r.setup_number)}`} className="font-mono font-bold text-orange-700 dark:text-orange-400 hover:underline">{r.setup_number}</Link>
                        ) : (
                          <Link href="/planning/unassigned" className="text-zinc-400 hover:underline">no setup</Link>
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-zinc-700 dark:text-zinc-300">
                        <div className="max-w-[170px] truncate" title={r.part_name || r.part_number || ""}>{r.part_name || r.part_number || "—"}</div>
                        <div className="text-[10px] text-zinc-400">{r.qty} pcs · {r.oar_number || "—"}</div>
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <div className="font-semibold">{fmtDay(r.commitment_date)}</div>
                        {dc !== null && dc !== undefined && <div className={`text-[10px] ${dc < 0 ? "text-rose-600 dark:text-rose-400 font-bold" : "text-zinc-400"}`}>{dc < 0 ? `${Math.abs(dc)} d overdue` : dc === 0 ? "today" : `${dc} d left`}</div>}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">{r.late_gate ? <span className="font-extrabold text-rose-700 dark:text-rose-300">{r.late_gate} +{r.late_days}d</span> : <span className="text-zinc-300 dark:text-zinc-700">—</span>}</td>
                      <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400 max-w-[280px]">{r.plan_text}</td>
                      <td className="py-2.5 px-3"><PlanStatusChip status={r.plan_status} compact /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  );
}
