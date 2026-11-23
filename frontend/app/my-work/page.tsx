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
  Truck,
  Undo2,
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import {
  getWorkQueue,
  getWIPMatrix,
  getCurrentUser,
  getSubcontractSummary,
  QueueItem,
  StageQueue,
  SubcontractSummary,
  SubcontractDC,
} from "@/lib/api";
import { QUEUE_STAGES, resolveWorkspace } from "@/lib/workspaces";

// Read-only view: what material is waiting at a stage, grouped by when that STAGE is
// due (its planned end date, set on release and editable by PPC). Nothing here writes
// data -- the action buttons open the existing Production Entry / Move / Packing screens,
// which do their own validation.

type BucketKey = QueueItem["bucket"];

const BUCKETS: { key: BucketKey; title: string; hint: string; tone: string }[] = [
  { key: "overdue", title: "Overdue", hint: "Stage due date already passed", tone: "rose" },
  { key: "today", title: "Due today", hint: "Stage due today", tone: "amber" },
  { key: "next", title: "Due in the next 2 days", hint: "Stage due in 1–2 days", tone: "blue" },
  { key: "later", title: "Later", hint: "Stage due in 3+ days", tone: "zinc" },
  { key: "no_date", title: "No due date", hint: "No plan or delivery date", tone: "zinc" },
];

const TONE: Record<string, { tile: string; text: string }> = {
  rose: { tile: "border-t-rose-500", text: "text-rose-600 dark:text-rose-400" },
  amber: { tile: "border-t-amber-500", text: "text-amber-600 dark:text-amber-400" },
  blue: { tile: "border-t-blue-500", text: "text-blue-600 dark:text-blue-400" },
  zinc: { tile: "border-t-zinc-400", text: "text-zinc-600 dark:text-zinc-400" },
};

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "—";
  const [y, m, d] = dateStr.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

function dueLabel(days?: number | null): string {
  if (days === null || days === undefined) return "";
  if (days < 0) return `${-days}d overdue`;
  if (days === 0) return "today";
  return `in ${days}d`;
}

const fmt = (n?: number | null) => (n ?? 0).toLocaleString("en-IN");

export default function MyWorkQueuePage() {
  const [stage, setStage] = useState<string | null>(null);
  const [queue, setQueue] = useState<StageQueue | null>(null);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [sub, setSub] = useState<SubcontractSummary | null>(null);
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

  // Piece counts on the stage tabs.
  useEffect(() => {
    getWIPMatrix()
      .then((m) => setTotals(m?.stage_totals || {}))
      .catch(() => undefined);
  }, []);

  const loadData = async (forStage: string) => {
    setLoading(true);
    setError("");
    try {
      const [q, s] = await Promise.all([
        getWorkQueue(forStage, 2),
        forStage === "SP" ? getSubcontractSummary(2) : Promise.resolve(null),
      ]);
      setQueue(q);
      setSub(s);
      setTotals((t) => ({ ...t, [forStage]: q.items.reduce((sum, i) => sum + i.qty_at_stage, 0) }));
    } catch {
      setError("Could not load the work queue from the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (stage) loadData(stage);
  }, [stage]);

  const grouped = useMemo(() => {
    const g: Record<BucketKey, QueueItem[]> = { overdue: [], today: [], next: [], later: [], no_date: [] };
    (queue?.items || []).forEach((r) => g[r.bucket].push(r));
    return g;
  }, [queue]);

  const rows = queue?.items || [];
  const stageMeta = QUEUE_STAGES.find((s) => s.key === stage);
  const isPacking = stage === "PACKING / BSR";
  const isSubcontract = stage === "SP";
  const actionableCount = grouped.overdue.length + grouped.today.length + grouped.next.length;
  const hasEstimates = rows.some((r) => r.plan_source !== "planned");

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
                ? "What to send to the subcontractor, what is at the vendor, and what should come back today and in the next two days."
                : "Work orders with material waiting at this stage — what to process today and in the next two days."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => stage && loadData(stage)}
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
            const total = totals[s.key];
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
                  <span className={`rounded-md px-1.5 py-0.5 text-[10px] ${active ? "bg-white/20" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"}`}>
                    {fmt(total)} pcs
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-zinc-600 dark:text-zinc-400">
          <Info className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
          <p>
            Grouped by each stage&rsquo;s <span className="font-semibold">planned due date</span>, set when the WO is released and
            adjustable by PPC in Edit Work Order.
            {hasEstimates && <> Older WOs without plan dates show an estimate from the customer delivery date (marked &ldquo;est.&rdquo;).</>}
          </p>
        </div>

        {error && (
          <div className="flex items-center justify-between rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-600 dark:text-rose-400">
            <span className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              {error}
            </span>
            <button type="button" onClick={() => stage && loadData(stage)} className="underline font-bold">
              Retry
            </button>
          </div>
        )}

        {isSubcontract && sub && <SubcontractPanel sub={sub} />}

        {/* Summary tiles */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {BUCKETS.slice(0, 4).map((b) => {
            const c = queue?.counts?.[b.key];
            return (
              <div
                key={b.key}
                className={`rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm border-t-4 ${TONE[b.tone].tile}`}
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{b.title}</p>
                <p className={`mt-2 text-2xl font-bold ${TONE[b.tone].text}`}>
                  {loading && !queue ? "…" : c?.wos ?? 0}
                  <span className="ml-1 text-xs font-semibold text-zinc-400">WOs</span>
                </p>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{fmt(c?.qty)} pcs at this stage</p>
              </div>
            );
          })}
        </div>

        {loading && !queue && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-10 text-center text-xs text-zinc-500">
            Loading work queue…
          </div>
        )}
        {!loading && queue && rows.length === 0 && (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-10 text-center">
            <ClipboardList className="mx-auto h-8 w-8 text-zinc-300 dark:text-zinc-600" />
            <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">Nothing waiting at {stageMeta?.name}</p>
            <p className="mt-1 text-xs text-zinc-500">No work order has material at this stage right now.</p>
          </div>
        )}

        {rows.length > 0 &&
          BUCKETS.map((b) => {
            const list = grouped[b.key];
            if (list.length === 0) return null;
            const collapsible = b.key === "later" || b.key === "no_date";
            const open = !collapsible || showLater;
            return (
              <section key={b.key} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
                <header className="flex items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 px-5 py-3.5">
                  <div className="flex items-center gap-2">
                    {b.key === "overdue" ? (
                      <AlertTriangle className={`h-4 w-4 ${TONE[b.tone].text}`} />
                    ) : b.key === "today" || b.key === "next" ? (
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
                          <th className="px-4 py-2.5">Stage due</th>
                          <th className="px-4 py-2.5">Delivery</th>
                          <th className="px-4 py-2.5 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                        {list.map((r) => {
                          const wo = encodeURIComponent(r.wo_number);
                          return (
                            <tr key={r.wo_number} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40">
                              <td className="px-4 py-3">
                                <Link href={`/production/tracking?wo=${wo}`} className="font-bold text-blue-600 dark:text-blue-400 hover:underline">
                                  {r.wo_number}
                                </Link>
                                <p className="text-[11px] text-zinc-400">Now at {r.current_stage}</p>
                              </td>
                              <td className="px-4 py-3">
                                <p className="font-semibold text-zinc-800 dark:text-zinc-200">{r.customer_name || "—"}</p>
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
                                  {fmt(r.inproc_qty)} to process · {fmt(r.onhand_qty)} done, ready to move
                                </p>
                              </td>
                              <td className="px-4 py-3">
                                <p className="font-semibold text-zinc-800 dark:text-zinc-200">
                                  {formatDate(r.planned_end)}
                                  {r.plan_source === "estimated" && <span className="ml-1 text-[10px] font-semibold text-zinc-400">est.</span>}
                                </p>
                                {r.days_to_due !== null && r.days_to_due !== undefined && (
                                  <p className={`text-[11px] font-semibold ${TONE[b.tone].text}`}>{dueLabel(r.days_to_due)}</p>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                <p className="text-zinc-700 dark:text-zinc-300">{formatDate(r.delivery_date)}</p>
                                <Badge variant={getRAGVariant(r.delivery_risk || r.status)} size="sm">
                                  {(r.delivery_risk || r.status || "").toString().toUpperCase()}
                                </Badge>
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex justify-end gap-1.5">
                                  {isPacking ? (
                                    <Link href="/packing" className="flex items-center gap-1 rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-cyan-500">
                                      <PackageCheck className="h-3.5 w-3.5" /> Pack
                                    </Link>
                                  ) : (
                                    <Link href={`/production/entry?wo=${wo}`} className="flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-emerald-500">
                                      <CheckSquare className="h-3.5 w-3.5" /> Production
                                    </Link>
                                  )}
                                  <Link href={`/production/move?wo=${wo}`} className="flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-blue-500">
                                    <ArrowRightLeft className="h-3.5 w-3.5" /> {isPacking ? "Move to BSR" : "Move"}
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

function DcTable({ rows, empty }: { rows: SubcontractDC[]; empty: string }) {
  if (rows.length === 0) return <p className="px-5 py-4 text-xs text-zinc-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
          <tr>
            <th className="px-4 py-2.5">DC</th>
            <th className="px-4 py-2.5">WO / Part</th>
            <th className="px-4 py-2.5">Vendor</th>
            <th className="px-4 py-2.5 text-right">Sent</th>
            <th className="px-4 py-2.5 text-right">Returned</th>
            <th className="px-4 py-2.5">Expected back</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
          {rows.map((d) => (
            <tr key={d.dc_number}>
              <td className="px-4 py-3 font-bold text-zinc-900 dark:text-zinc-100">
                {d.dc_number}
                <p className="text-[11px] font-medium text-zinc-400">{d.status}</p>
              </td>
              <td className="px-4 py-3">
                <p className="font-semibold">{d.wo_number}</p>
                <p className="text-[11px] text-zinc-500">{d.part_number}</p>
              </td>
              <td className="px-4 py-3">{d.vendor_name || "—"}</td>
              <td className="px-4 py-3 text-right">{d.quantity_sent ?? "—"} {d.unit}</td>
              <td className="px-4 py-3 text-right">{d.quantity_returned ?? "—"} {d.quantity_returned != null ? d.unit : ""}</td>
              <td className="px-4 py-3">
                <p className="font-semibold">{formatDate(d.expected_return_date)}</p>
                {d.days_to_return != null && (
                  <p className={`text-[11px] font-semibold ${d.days_to_return < 0 ? "text-rose-600" : d.days_to_return === 0 ? "text-amber-600" : "text-blue-600"}`}>
                    {d.days_to_return < 0 ? `${-d.days_to_return}d late` : d.days_to_return === 0 ? "today" : `in ${d.days_to_return}d`}
                  </p>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubcontractPanel({ sub }: { sub: SubcontractSummary }) {
  const dueBack = [...sub.due_back.overdue, ...sub.due_back.today, ...sub.due_back.next];
  const notYetSent = sub.ready_to_send.filter((r) => !r.already_on_dc);
  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
        <header className="flex items-center gap-2 border-b border-zinc-100 dark:border-zinc-800 px-5 py-3.5">
          <Truck className="h-4 w-4 text-indigo-500" />
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Send to subcontractor today</h2>
          <span className="text-xs text-zinc-400">Material moved to SP from the previous process, not yet on a DC</span>
        </header>
        {notYetSent.length === 0 ? (
          <p className="px-5 py-4 text-xs text-zinc-500">Nothing waiting to be sent.</p>
        ) : (
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60 text-xs">
            {notYetSent.map((r) => (
              <li key={r.wo_number} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="font-bold text-zinc-900 dark:text-zinc-100">{r.wo_number}</p>
                  <p className="text-[11px] text-zinc-500">
                    {r.customer_name} · {r.part_number} · delivery {formatDate(r.delivery_date)}
                  </p>
                </div>
                <p className="text-sm font-extrabold">
                  {fmt(r.qty_at_sp)} <span className="text-[11px] font-semibold text-zinc-400">pcs</span>
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="border-t border-zinc-100 dark:border-zinc-800 px-5 py-2.5 text-[11px] text-zinc-500">
          Raise the Delivery Challan in the DC software; it appears below once it leaves the gate.
        </p>
      </section>

      {!sub.dc_available ? (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <p>DC data unavailable: {sub.dc_message}</p>
        </div>
      ) : (
        <>
          <section className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
            <header className="flex items-center gap-2 border-b border-zinc-100 dark:border-zinc-800 px-5 py-3.5">
              <Undo2 className="h-4 w-4 text-amber-500" />
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Expected back: late, today and next 2 days</h2>
              <span className="text-xs text-zinc-400">{dueBack.length} DC{dueBack.length === 1 ? "" : "s"}</span>
            </header>
            <DcTable rows={dueBack} empty="Nothing due back in the next two days." />
          </section>
          <section className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm">
            <header className="flex items-center gap-2 border-b border-zinc-100 dark:border-zinc-800 px-5 py-3.5">
              <Truck className="h-4 w-4 text-zinc-400" />
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">All material at vendors</h2>
              <span className="text-xs text-zinc-400">{sub.at_vendor.length} open DC{sub.at_vendor.length === 1 ? "" : "s"}</span>
            </header>
            <DcTable rows={sub.at_vendor} empty="No open DCs at vendors." />
          </section>
        </>
      )}
    </div>
  );
}
