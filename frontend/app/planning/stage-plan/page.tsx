"use client";
import React, { useEffect, useState } from "react";
import { CalendarClock, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getWorkOrders, getWorkOrderRoute, updateStagePlan, getCurrentUserRoles } from "@/lib/api";
import { stageRole } from "@/lib/workspaces";

// Stage plan dates: when each route stage of a WO should be worked on. Filled when the WO
// is released (scheduled back from the commitment date); PPC can change any stage and a
// stage Manager only their own. Planning only -- drives each department's My Work Queue.

type Row = { stage: string; planned_start: string; planned_end: string };

const norm = (s: string) => (["PACKING / BSR", "PACKING/BSR"].includes(s.toUpperCase()) ? "PACKING" : s.toUpperCase());

export default function StagePlanPage() {
  const [wos, setWos] = useState<any[]>([]);
  const [wo, setWo] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [original, setOriginal] = useState<Record<string, Row>>({});
  const [reason, setReason] = useState("");
  const [ownStage, setOwnStage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<string[] | null>(null);

  useEffect(() => {
    const roles = getCurrentUserRoles();
    const sr = roles.map(stageRole).find(Boolean);
    const unlocked = roles.some((r) => !stageRole(r));
    if (sr && sr.level === "manager" && !unlocked) setOwnStage(sr.stage);
    getWorkOrders({ limit: 500 })
      .then((d) => setWos(Array.isArray(d) ? d.filter((w: any) => !["dispatched", "closed"].includes(w.status)) : []))
      .catch(() => setError("Could not load work orders."));
    const requested = new URLSearchParams(window.location.search).get("wo");
    if (requested) setWo(requested);
  }, []);

  useEffect(() => {
    if (!wo) return;
    setLoading(true);
    setError("");
    setSaved(null);
    getWorkOrderRoute(wo)
      .then((r: any) => {
        const list: Row[] = (r.route_stages || []).map((s: string) => ({
          stage: s,
          planned_start: r.stage_plans?.[s]?.planned_start || "",
          planned_end: r.stage_plans?.[s]?.planned_end || "",
        }));
        setRows(list);
        setOriginal(Object.fromEntries(list.map((x) => [x.stage, x])));
      })
      .catch(() => setError(`Could not load Work Order '${wo}'.`))
      .finally(() => setLoading(false));
  }, [wo]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const changed = rows.filter(
      (r) => r.planned_start !== original[r.stage]?.planned_start || r.planned_end !== original[r.stage]?.planned_end
    );
    if (changed.length === 0) {
      setError("Nothing has changed.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await updateStagePlan(
        wo,
        changed.map((r) => ({ stage: r.stage, planned_start: r.planned_start || null, planned_end: r.planned_end || null })),
        reason
      );
      setSaved(res.changes);
      setOriginal(Object.fromEntries(rows.map((x) => [x.stage, x])));
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setError(typeof d === "string" ? d : "Could not save the plan dates.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">Planning</span>
            {ownStage && <span className="text-xs text-zinc-400">{ownStage} Manager</span>}
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Stage Plan Dates</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            When each stage of a work order is due. These dates drive every department&rsquo;s My Work Queue.
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-zinc-600 dark:text-zinc-400">
          <Info className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
          <p>
            {ownStage
              ? `As ${ownStage} Manager you can change the dates of your own stage only.`
              : "Filled automatically on WO release from the commitment date and the Stage Lead Times. Change any stage here."}
          </p>
        </div>

        <form onSubmit={save} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5">
          <div>
            <label htmlFor="sp-wo" className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Work Order</label>
            <select
              id="sp-wo"
              value={wo}
              onChange={(e) => setWo(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs"
            >
              <option value="">Select a work order…</option>
              {wo && !wos.some((w) => w.wo_number === wo) && <option value={wo}>{wo}</option>}
              {wos.map((w) => (
                <option key={w.wo_number} value={w.wo_number}>
                  {w.wo_number} — {w.customer_name} · {w.part_number} (at {w.current_stage})
                </option>
              ))}
            </select>
          </div>

          {loading && <p className="text-xs text-zinc-500">Loading…</p>}

          {!loading && rows.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-[11px] uppercase text-zinc-500">
                    <tr>
                      <th className="text-left py-1.5">Stage</th>
                      <th className="text-left py-1.5">Planned start</th>
                      <th className="text-left py-1.5">Planned end (due)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      const locked = !!ownStage && norm(r.stage) !== ownStage;
                      return (
                        <tr key={r.stage}>
                          <td className="py-1.5 pr-3 font-bold">{r.stage}</td>
                          {(["planned_start", "planned_end"] as const).map((f) => (
                            <td key={f} className="py-1.5 pr-3">
                              <input
                                type="date"
                                aria-label={`${r.stage} ${f === "planned_start" ? "planned start" : "planned end"}`}
                                value={r[f]}
                                disabled={locked}
                                onChange={(e) => setRows((cur) => cur.map((x, j) => (j === i ? { ...x, [f]: e.target.value } : x)))}
                                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-2 py-1 disabled:opacity-40"
                              />
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div>
                <label htmlFor="sp-reason" className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Reason for change *</label>
                <input
                  id="sp-reason"
                  required
                  minLength={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Machine breakdown at F2"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs"
                />
              </div>
              {error && (
                <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-600">
                  <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
                </div>
              )}
              {saved && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-400">
                  <p className="flex items-center gap-2 font-bold">
                    <CheckCircle2 className="h-4 w-4" /> {saved.length ? "Plan dates saved." : "No changes were needed."}
                  </p>
                  <ul className="mt-1 list-disc pl-6">
                    {saved.map((c) => (
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
                <CalendarClock className="h-4 w-4" /> {saving ? "Saving…" : "Save Plan Dates"}
              </button>
            </>
          )}
          {!loading && rows.length === 0 && error && (
            <p className="text-xs font-semibold text-rose-600">{error}</p>
          )}
        </form>
      </div>
    </AppShell>
  );
}
