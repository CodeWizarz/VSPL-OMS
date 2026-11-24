"use client";
import React, { useEffect, useState } from "react";
import { History, Search, RefreshCw, AlertTriangle } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getActivityLog, ActivityItem } from "@/lib/api";

// Admin: every create / update / delete made in the app, with who did it, when, what it
// touched and whether it went through. Read-only.

const PAGE = 100;

function when(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function screen(path: string) {
  const parts = path.split("/").filter(Boolean).slice(2);
  return parts.filter((p) => !/\d/.test(p)).join(" / ") || path;
}

const OUTCOME_STYLE: Record<string, string> = {
  Success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  Refused: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  Failed: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
};

export default function ActivityLogPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async (newOffset = 0) => {
    setLoading(true);
    setError("");
    try {
      const res = await getActivityLog({
        search: search || undefined,
        action: action || undefined,
        outcome: outcome || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: PAGE,
        offset: newOffset,
      });
      setItems(res.items);
      setTotal(res.total);
      setOffset(newOffset);
    } catch (err: any) {
      setError(err?.response?.status === 403 ? "Only Admin can view the activity log." : "Could not load the activity log.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, outcome, dateFrom, dateTo]);

  const inputCls =
    "rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none";

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-zinc-800 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">Administration</span>
              <span className="text-xs text-zinc-400">{total.toLocaleString("en-IN")} entries</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Activity Log</h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Every entry, change and deletion: who did it, when, what it touched, and whether it went through.
            </p>
          </div>
          <button
            type="button"
            onClick={() => load(offset)}
            disabled={loading}
            className="flex items-center gap-1.5 self-start rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold shadow-sm disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            load(0);
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="relative min-w-[240px] flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400" />
            <label htmlFor="act-search" className="sr-only">Search</label>
            <input
              id="act-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search person, email, WO / record, screen…"
              className={`${inputCls} w-full pl-9`}
            />
          </div>
          <label className="text-[11px] text-zinc-500">
            Action
            <select value={action} onChange={(e) => setAction(e.target.value)} className={`${inputCls} ml-1`}>
              <option value="">All</option>
              <option>Create</option>
              <option>Update</option>
              <option>Delete</option>
            </select>
          </label>
          <label className="text-[11px] text-zinc-500">
            Result
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={`${inputCls} ml-1`}>
              <option value="">All</option>
              <option>Success</option>
              <option>Refused</option>
              <option>Failed</option>
            </select>
          </label>
          <label className="text-[11px] text-zinc-500">
            From
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={`${inputCls} ml-1`} />
          </label>
          <label className="text-[11px] text-zinc-500">
            To
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={`${inputCls} ml-1`} />
          </label>
          <button type="submit" className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500">
            Search
          </button>
        </form>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-600">
            <AlertTriangle className="h-4 w-4" /> {error}
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-x-auto">
          {loading && items.length === 0 ? (
            <p className="p-10 text-center text-xs text-zinc-500">Loading…</p>
          ) : items.length === 0 ? (
            <div className="p-10 text-center">
              <History className="mx-auto h-8 w-8 text-zinc-300" />
              <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">No activity found</p>
            </div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">When</th>
                  <th className="px-4 py-2.5">Who</th>
                  <th className="px-4 py-2.5">Action</th>
                  <th className="px-4 py-2.5">Screen</th>
                  <th className="px-4 py-2.5">Record</th>
                  <th className="px-4 py-2.5">Details</th>
                  <th className="px-4 py-2.5">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {items.map((r) => (
                  <tr key={r.id} className="align-top">
                    <td className="px-4 py-2.5 whitespace-nowrap text-zinc-600 dark:text-zinc-400">{when(r.at)}</td>
                    <td className="px-4 py-2.5">
                      <p className="font-bold text-zinc-900 dark:text-zinc-100">{r.user_name}</p>
                      <p className="text-[11px] text-zinc-500">{r.user_email}</p>
                      {r.user_role && <p className="text-[10px] uppercase text-zinc-400">{r.user_role.replace(/_/g, " ")}</p>}
                    </td>
                    <td className="px-4 py-2.5 font-semibold">{r.action}</td>
                    <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400" title={r.path}>{screen(r.path)}</td>
                    <td className="px-4 py-2.5 font-semibold text-zinc-800 dark:text-zinc-200">{r.target || "—"}</td>
                    <td className="px-4 py-2.5 max-w-[320px] text-[11px] text-zinc-500 break-words">{r.details || "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${OUTCOME_STYLE[r.outcome || ""] || ""}`}>
                        {r.outcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {total > PAGE && (
          <div className="flex items-center justify-end gap-2 text-xs">
            <button type="button" disabled={offset === 0 || loading} onClick={() => load(Math.max(0, offset - PAGE))} className="rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 disabled:opacity-40">
              Newer
            </button>
            <span className="text-zinc-500">
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <button type="button" disabled={offset + PAGE >= total || loading} onClick={() => load(offset + PAGE)} className="rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 disabled:opacity-40">
              Older
            </button>
          </div>
        )}
      </div>
    </AppShell>
  );
}
