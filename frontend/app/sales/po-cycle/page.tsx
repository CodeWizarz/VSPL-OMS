"use client";
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { RefreshCw, Search, AlertTriangle, BarChart3 } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, BadgeVariant } from "@/app/components/ui/Badge";
import { getPOCycle, POCycleRow } from "@/lib/api";

// Read-only: each customer PO / OAR from order through production, BSR, dispatch,
// invoicing and collection.

const STAGE_LABEL: Record<POCycleRow["stage"], [string, BadgeVariant]> = {
  IN_PRODUCTION: ["In production", "blue"],
  READY_IN_BSR: ["Ready in BSR", "cyan"],
  PART_DISPATCHED: ["Part dispatched", "amber"],
  DISPATCHED: ["Dispatched", "green"],
};
const COLLECTION_LABEL: Record<POCycleRow["collection_status"], [string, BadgeVariant]> = {
  NOT_INVOICED: ["Not invoiced", "gray"],
  NOT_VALUED: ["Value pending", "purple"],
  UNPAID: ["Unpaid", "red"],
  PARTIAL: ["Part paid", "amber"],
  PAID: ["Paid", "green"],
};

const qty = (n?: number | null) => (n ?? 0).toLocaleString("en-IN");
const inr = (n?: number | null) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export default function POCyclePage() {
  const [rows, setRows] = useState<POCycleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setRows(await getPOCycle());
    } catch (err: any) {
      setError(err?.response?.status === 403 ? "You don't have access to this report." : "Could not load the report.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      [r.customer_po, r.oar_number, r.customer_name, r.customer_code, r.part_number, ...r.invoices]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    );
  }, [rows, search]);

  const totals = useMemo(
    () => ({
      ordered: filtered.reduce((s, r) => s + r.po_qty, 0),
      dispatched: filtered.reduce((s, r) => s + r.dispatched_qty, 0),
      bsr: filtered.reduce((s, r) => s + r.in_bsr_qty, 0),
      outstanding: filtered.reduce((s, r) => s + (r.outstanding_amount || 0), 0),
    }),
    [filtered]
  );

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">Sales</span>
              <span className="text-xs text-zinc-400">PO → Dispatch → Collection</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Order Tracking &amp; Collections</h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Every customer PO from order to production, BSR stock, dispatch, invoice and payment.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 self-start rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-sm disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            ["Ordered", `${qty(totals.ordered)} pcs`],
            ["In BSR", `${qty(totals.bsr)} pcs`],
            ["Dispatched", `${qty(totals.dispatched)} pcs`],
            ["Outstanding", inr(totals.outstanding)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm border-t-4 border-t-emerald-500">
              <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
              <p className="mt-2 text-xl font-bold text-zinc-900 dark:text-zinc-50">{loading && rows.length === 0 ? "…" : value}</p>
            </div>
          ))}
        </div>

        <div className="relative w-full sm:max-w-sm">
          <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-zinc-400" />
          <label htmlFor="po-search" className="sr-only">Search</label>
          <input
            id="po-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search PO, OAR, customer, part or invoice"
            className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2 text-xs focus:border-blue-500 focus:outline-none"
          />
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-600 dark:text-rose-400">
            <AlertTriangle className="h-4 w-4" /> {error}
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-x-auto">
          {loading && rows.length === 0 ? (
            <p className="p-10 text-center text-xs text-zinc-500">Loading…</p>
          ) : filtered.length === 0 ? (
            <div className="p-10 text-center">
              <BarChart3 className="mx-auto h-8 w-8 text-zinc-300" />
              <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">{error ? "Report unavailable" : "No orders found"}</p>
            </div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">Customer / PO</th>
                  <th className="px-4 py-2.5">Part</th>
                  <th className="px-4 py-2.5 text-right">Ordered</th>
                  <th className="px-4 py-2.5 text-right">In BSR</th>
                  <th className="px-4 py-2.5 text-right">Dispatched</th>
                  <th className="px-4 py-2.5 text-right">Pending</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Invoices</th>
                  <th className="px-4 py-2.5 text-right">Paid / Outstanding</th>
                  <th className="px-4 py-2.5">Collection</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {filtered.map((r) => (
                  <tr key={`${r.oar_number}-${r.customer_po}`} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40">
                    <td className="px-4 py-3">
                      <p className="font-bold text-zinc-900 dark:text-zinc-100">{r.customer_name}</p>
                      <p className="text-[11px] text-zinc-500">
                        {r.customer_po}
                        {r.oar_number && (
                          <>
                            {" · "}
                            <Link href="/orders/list" className="text-blue-600 hover:underline">{r.oar_number}</Link>
                          </>
                        )}
                      </p>
                    </td>
                    <td className="px-4 py-3">{r.part_number}</td>
                    <td className="px-4 py-3 text-right font-semibold">{qty(r.po_qty)}</td>
                    <td className="px-4 py-3 text-right">{qty(r.in_bsr_qty)}</td>
                    <td className="px-4 py-3 text-right">{qty(r.dispatched_qty)}</td>
                    <td className="px-4 py-3 text-right">{qty(r.pending_qty)}</td>
                    <td className="px-4 py-3">
                      <Badge variant={STAGE_LABEL[r.stage][1]} size="sm">{STAGE_LABEL[r.stage][0]}</Badge>
                    </td>
                    <td className="px-4 py-3 text-[11px] text-zinc-600 dark:text-zinc-400">{r.invoices.join(", ") || "—"}</td>
                    <td className="px-4 py-3 text-right">
                      <p className="font-semibold">{inr(r.paid_amount)}</p>
                      <p className="text-[11px] text-zinc-500">{inr(r.outstanding_amount)} due</p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={COLLECTION_LABEL[r.collection_status][1]} size="sm">{COLLECTION_LABEL[r.collection_status][0]}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </AppShell>
  );
}
