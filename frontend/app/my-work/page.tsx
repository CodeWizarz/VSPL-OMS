"use client";
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ClipboardList,
  RefreshCw,
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  Info,
  CheckSquare,
  ArrowRightLeft,
  Route,
  PackageCheck,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getWIPMatrix, getWorkOrders, getCurrentUser } from "@/lib/api";
import { QUEUE_STAGES, resolveWorkspace } from "@/lib/workspaces";

// Read-only view: what material is waiting at a stage, grouped by how soon the
// customer delivery is due. Nothing here writes data -- the action buttons open the
// existing Production Entry / Move / Packing screens, which do their own validation.

type BucketKey = "overdue" | "today" | "next2" | "later" | "nodate";

const BUCKETS: { key: BucketKey; title: string; hint: string; tone: string }[] = [
  { key: "overdue", title: "Overdue", hint: "Delivery date already passed", tone: "rose" },
  { key: "today", title: "Due today", hint: "Delivery date is today", tone: "amber" },
  { key: "next2", title: "Due in the next 2 days", hint: "Delivery in 1–2 days", tone: "blue" },
  { key: "later", title: "Later", hint: "Delivery in 3+ days", tone: "zinc" },
  { key: "nodate", title: "No delivery date", hint: "OAR has no delivery date", tone: "zinc" },
];

const TONE: Record<string, { tile: string; text: string }> = {
  rose: { tile: "border-t-rose-500", text: "text-rose-600 dark:text-rose-400" },
  amber: { tile: "border-t-amber-500", text: "text-amber-600 dark:text-amber-400" },
  blue: { tile: "border-t-blue-500", text: "text-blue-600 dark:text-blue-400" },
  zinc: { tile: "border-t-zinc-400", text: "text-zinc-600 dark:text-zinc-400" },
};

interface QueueRow {
  wo_number: string;
  customer_name: string;
  part_number: string;
  part_name?: string | null;
  qty_at_stage: number;
  inproc: number;
  onhand: number;
  current_stage: string;
  status: string;
  delivery_date: string | null;
  days_left: number | null;
  delivery_risk: string | null;
  bucket: BucketKey;
}

// Parse "YYYY-MM-DD" as a local calendar date (not UTC) and count whole days from today.
function daysUntil(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null;
  const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  const due = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

function bucketFor(days: number | null): BucketKey {
  if (days === null) return "nodate";
  if (days < 0) return "overdue";
  if (days === 0) return "today";
  if (days <= 2) return "next2";
  return "later";
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function dueLabel(days: number | null): string {
  if (days === null) return "";
  if (days < 0) return `${-days}d overdue`;
  if (days === 0) return "today";
  return `in ${days}d`;
}

const fmt = (n: number) => n.toLocaleString("en-IN");

export default function MyWorkQueuePage() {
  const [stage, setStage] = useState<string | null>(null);
  const [wip, setWip] = useState<any>(null);
  const [woIndex, setWoIndex] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showLater, setShowLater] = useState(false);

  // Open on the user's own stage (from their department); default F1 otherwise.
  // A ?stage= in the URL wins so links can point at a specific stage.
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("stage");
    if (fromUrl && QUEUE_STAGES.some((s) => s.key === fromUrl)) {
      setStage(fromUrl);
      return;
    }
    getCurrentUser()
      .then((u) => setStage(resolveWorkspace(u.role, u.department)?.stage ?? "F1"))
      .catch(() => setStage("F1"));
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [matrix, wos] = await Promise.all([getWIPMatrix(), getWorkOrders({ limit: 500 })]);
      setWip(matrix);
      const idx: Record<string, any> = {};
      (Array.isArray(wos) ? wos : []).forEach((w: any) => (idx[w.wo_number] = w));
      setWoIndex(idx);
    } catch {
      setError("Could not load the work queue from the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const rows: QueueRow[] = useMemo(() => {
    if (!wip || !stage) return [];
    return (wip.work_orders || [])
      .filter((r: any) => (r.stage_wips?.[stage] || 0) > 0)
      .map((r: any) => {
        const wo = woIndex[r.wo_number];
        const deliveryDate: string | null = wo?.delivery_date ?? null;
        const days = daysUntil(deliveryDate);
        return {
          wo_number: r.wo_number,
          customer_name: r.customer_name || wo?.customer_name || "—",
          part_number: r.part_number,
          part_name: r.part_name,
          qty_at_stage: r.stage_wips?.[stage] || 0,
          inproc: r.stage_inproc?.[stage] || 0,
          onhand: r.stage_onhand?.[stage] || 0,
          current_stage: r.current_stage,
          status: r.status,
          delivery_date: deliveryDate,
          days_left: days,
          delivery_risk: wo?.delivery_risk ?? null,
          bucket: bucketFor(days),
        } as QueueRow;
      })
      .sort((a: QueueRow, b: QueueRow) => (a.days_left ?? 99999) - (b.days_left ?? 99999));
  }, [wip, woIndex, stage]);

  const grouped = useMemo(() => {
    const g: Record<BucketKey, QueueRow[]> = { overdue: [], today: [], next2: [], later: [], nodate: [] };
    rows.forEach((r) => g[r.bucket].push(r));
    return g;
  }, [rows]);

  const stageMeta = QUEUE_STAGES.find((s) => s.key === stage);
  const isPacking = stage === "PACKING / BSR";
  const isSubcontract = stage === "SP";
  const actionableCount = grouped.overdue.length + grouped.today.length + grouped.next2.length;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                My Work
              </span>
              {stageMeta && <span className="text-xs text-zinc-400">{stageMeta.name}</span>}
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              {isSubcontract ? "Subcontracting Work Queue" : "My Work Queue"}
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              {isSubcontract
                ? "Material that has reached SP and is available to send to the subcontractor, most urgent first."
                : "Work orders with material waiting at this stage — what to process today and in the next two days."}
            </p>
          </div>
          <button
            type="button"
            onClick={loadData}
            disabled={loading}
            className="flex items-center gap-1.5 self-start rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Stage selector */}
        <div role="tablist" aria-label="Stage" className="flex flex-wrap gap-2">
          {QUEUE_STAGES.map((s) => {
            const active = s.key === stage;
            const total = wip?.stage_totals?.[s.key];
            return (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setStage(s.key)}
                className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-xs font-bold transition-colors ${
                  active
                    ? "border-blue-600 bg-blue-600 text-white shadow-sm"
                    : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                }`}
              >
                <span>{s.short}</span>
                {typeof total === "number" && (
                  <span
                    className={`rounded-md px-1.5 py-0.5 text-[10px] ${
                      active ? "bg-white/20" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"
                    }`}
                  >
                    {fmt(total)} pcs
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* How the queue is ordered -- be honest about what the data can say. */}
        <div className="flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-zinc-600 dark:text-zinc-400">
          <Info className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
          <p>
            Grouped by the <span className="font-semibold">customer delivery date</span> on the OAR. Stage-level plan dates
            are not in the system yet, so &ldquo;today&rdquo; means orders whose delivery is today or already late.
            {isSubcontract && (
              <> Sending material on a Delivery Challan and expected return dates are handled in the DC software for now.</>
            )}
          </p>
        </div>

        {error && (
          <div className="flex items-center justify-between rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-600 dark:text-rose-400">
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              {error}
            </span>
            <button type="button" onClick={loadData} className="underline font-bold">
              Retry
            </button>
          </div>
        )}

        {/* Summary tiles */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {BUCKETS.slice(0, 4).map((b) => {
            const list = grouped[b.key];
            const pcs = list.reduce((sum, r) => sum + r.qty_at_stage, 0);
            return (
              <div
                key={b.key}
                className={`rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm border-t-4 ${TONE[b.tone].tile}`}
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{b.title}</p>
                <p className={`mt-2 text-2xl font-bold ${TONE[b.tone].text}`}>
                  {loading && !wip ? "…" : list.length}
                  <span className="ml-1 text-xs font-semibold text-zinc-400">WOs</span>
                </p>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{fmt(pcs)} pcs at this stage</p>
              </div>
            );
          })}
        </div>

        {/* Loading / empty */}
        {loading && !wip && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-10 text-center text-xs text-zinc-500">
            Loading work queue…
          </div>
        )}
        {!loading && wip && rows.length === 0 && (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-10 text-center">
            <ClipboardList className="mx-auto h-8 w-8 text-zinc-300 dark:text-zinc-600" />
            <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">Nothing waiting at {stageMeta?.name}</p>
            <p className="mt-1 text-xs text-zinc-500">No work order has material at this stage right now.</p>
          </div>
        )}

        {/* Buckets */}
        {rows.length > 0 &&
          BUCKETS.map((b) => {
            const list = grouped[b.key];
            if (list.length === 0) return null;
            const collapsible = b.key === "later" || b.key === "nodate";
            const open = !collapsible || showLater;
            return (
              <section
                key={b.key}
                className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm"
              >
                <header className="flex items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 px-5 py-3.5">
                  <div className="flex items-center gap-2">
                    {b.key === "overdue" ? (
                      <AlertTriangle className={`h-4 w-4 ${TONE[b.tone].text}`} />
                    ) : b.key === "today" || b.key === "next2" ? (
                      <CalendarClock className={`h-4 w-4 ${TONE[b.tone].text}`} />
                    ) : (
                      <CalendarDays className="h-4 w-4 text-zinc-400" />
                    )}
                    <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{b.title}</h2>
                    <span className="text-xs text-zinc-400">
                      {list.length} WO{list.length === 1 ? "" : "s"} · {b.hint}
                    </span>
                  </div>
                  {collapsible && (
                    <button
                      type="button"
                      onClick={() => setShowLater(!showLater)}
                      aria-expanded={open}
                      className="flex items-center gap-1 text-xs font-semibold text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      {open ? "Hide" : "Show"}
                    </button>
                  )}
                </header>

                {open && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                        <tr>
                          <th className="px-4 py-2.5">Work Order</th>
                          <th className="px-4 py-2.5">Customer / Part</th>
                          <th className="px-4 py-2.5 text-right">At this stage</th>
                          <th className="px-4 py-2.5">Delivery</th>
                          <th className="px-4 py-2.5">Status</th>
                          <th className="px-4 py-2.5 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                        {list.map((r) => {
                          const wo = encodeURIComponent(r.wo_number);
                          return (
                            <tr key={r.wo_number} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40">
                              <td className="px-4 py-3">
                                <Link
                                  href={`/production/tracking?wo=${wo}`}
                                  className="font-bold text-blue-600 dark:text-blue-400 hover:underline"
                                >
                                  {r.wo_number}
                                </Link>
                                <p className="text-[11px] text-zinc-400">Now at {r.current_stage}</p>
                              </td>
                              <td className="px-4 py-3">
                                <p className="font-semibold text-zinc-800 dark:text-zinc-200">{r.customer_name}</p>
                                <p className="text-[11px] text-zinc-500">
                                  {r.part_number}
                                  {r.part_name ? ` · ${r.part_name}` : ""}
                                </p>
                              </td>
                              <td className="px-4 py-3 text-right">
                                <p className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">
                                  {fmt(r.qty_at_stage)} <span className="text-[11px] font-semibold text-zinc-400">pcs</span>
                                </p>
                                <p className="text-[11px] text-zinc-500">
                                  {fmt(r.inproc)} to process · {fmt(r.onhand)} done, ready to move
                                </p>
                              </td>
                              <td className="px-4 py-3">
                                <p className="font-semibold text-zinc-800 dark:text-zinc-200">{formatDate(r.delivery_date)}</p>
                                {r.days_left !== null && (
                                  <p className={`text-[11px] font-semibold ${TONE[b.tone].text}`}>{dueLabel(r.days_left)}</p>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                <Badge variant={getRAGVariant(r.delivery_risk || r.status)} size="sm">
                                  {(r.delivery_risk || r.status || "").toString().toUpperCase()}
                                </Badge>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex justify-end gap-1.5">
                                  {isPacking ? (
                                    <Link
                                      href="/packing"
                                      className="flex items-center gap-1 rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-cyan-500"
                                    >
                                      <PackageCheck className="h-3.5 w-3.5" /> Pack
                                    </Link>
                                  ) : (
                                    <Link
                                      href={`/production/entry?wo=${wo}`}
                                      className="flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-emerald-500"
                                    >
                                      <CheckSquare className="h-3.5 w-3.5" /> Production
                                    </Link>
                                  )}
                                  <Link
                                    href={`/production/move?wo=${wo}`}
                                    className="flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-blue-500"
                                  >
                                    <ArrowRightLeft className="h-3.5 w-3.5" /> {isSubcontract ? "Send / Move" : "Move"}
                                  </Link>
                                  <Link
                                    href={`/production/tracking?wo=${wo}`}
                                    aria-label={`Track ${r.wo_number}`}
                                    title="Track"
                                    className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-700 px-2 py-1.5 text-zinc-500 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                                  >
                                    <Route className="h-3.5 w-3.5" />
                                  </Link>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            );
          })}

        {!loading && rows.length > 0 && actionableCount === 0 && (
          <p className="text-center text-xs text-zinc-500">
            Nothing at this stage is due within the next two days. Upcoming work is listed under &ldquo;Later&rdquo;.
          </p>
        )}
      </div>
    </AppShell>
  );
}
