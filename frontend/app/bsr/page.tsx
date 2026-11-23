"use client";
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Warehouse, RefreshCw, Search, AlertTriangle, Truck, Info } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getDispatchQueue } from "@/lib/api";

// Read-only view of finished stock sitting in BSR: packed, inspected and waiting for
// dispatch. Source is the existing dispatch queue (WOs with ready_for_dispatch_qty > 0).

const fmt = (n: number) => (n ?? 0).toLocaleString("en-IN");

export default function BSRStockPage() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"part" | "wo">("part");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getDispatchQueue();
      setItems(Array.isArray(data) ? data : []);
    } catch {
      setError("Could not load BSR stock from the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items
      .filter((i) => (i.ready_for_dispatch_qty || 0) > 0)
      .filter(
        (i) =>
          !q ||
          [i.wo_number, i.part_number, i.part_name, i.customer_name, i.customer_po, i.oar_number]
            .filter(Boolean)
            .some((v: string) => v.toLowerCase().includes(q))
      );
  }, [items, search]);

  const byPart = useMemo(() => {
    const map = new Map<string, { part_number: string; part_name?: string; qty: number; wos: number; customers: Set<string> }>();
    filtered.forEach((i) => {
      const cur = map.get(i.part_number) || {
        part_number: i.part_number,
        part_name: i.part_name,
        qty: 0,
        wos: 0,
        customers: new Set<string>(),
      };
      cur.qty += i.ready_for_dispatch_qty || 0;
      cur.wos += 1;
      if (i.customer_name) cur.customers.add(i.customer_name);
      map.set(i.part_number, cur);
    });
    return Array.from(map.values()).sort((a, b) => b.qty - a.qty);
  }, [filtered]);

  const totalQty = filtered.reduce((s, i) => s + (i.ready_for_dispatch_qty || 0), 0);
  const customerCount = new Set(filtered.map((i) => i.customer_name)).size;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-cyan-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                BSR
              </span>
              <span className="text-xs text-zinc-400">Finished goods store</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">BSR Stock</h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Material that is packed, inspected and available in BSR, waiting for dispatch.
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

        {/* Summary */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { label: "Available in BSR", value: `${fmt(totalQty)} pcs` },
            { label: "Part numbers", value: fmt(byPart.length) },
            { label: "Customers", value: fmt(customerCount) },
          ].map((t) => (
            <div
              key={t.label}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm border-t-4 border-t-cyan-500"
            >
              <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{t.label}</p>
              <p className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{loading && items.length === 0 ? "…" : t.value}</p>
            </div>
          ))}
        </div>

        {/* Controls */}
        <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
          <div className="relative w-full sm:max-w-sm">
            <Search className="absolute left-3.5 top-2.5 h-4 w-4 text-zinc-400" />
            <label htmlFor="bsr-search" className="sr-only">
              Search BSR stock
            </label>
            <input
              id="bsr-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search part, WO, customer or PO"
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div role="tablist" aria-label="Group by" className="flex rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-1">
            {(
              [
                { key: "part", label: "By part" },
                { key: "wo", label: "By work order" },
              ] as const
            ).map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={view === t.key}
                onClick={() => setView(t.key)}
                className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-colors ${
                  view === t.key ? "bg-cyan-600 text-white" : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
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

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-x-auto">
          {loading && items.length === 0 ? (
            <p className="p-10 text-center text-xs text-zinc-500">Loading BSR stock…</p>
          ) : error && items.length === 0 ? (
            <p className="p-10 text-center text-xs text-zinc-500">Stock could not be loaded.</p>
          ) : filtered.length === 0 ? (
            <div className="p-10 text-center">
              <Warehouse className="mx-auto h-8 w-8 text-zinc-300 dark:text-zinc-600" />
              <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">
                {search ? "No stock matches your search" : "BSR is empty"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {search ? "Try a different part, WO or customer." : "Nothing is packed and waiting for dispatch right now."}
              </p>
            </div>
          ) : view === "part" ? (
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">Part</th>
                  <th className="px-4 py-2.5">Customers</th>
                  <th className="px-4 py-2.5 text-right">Work orders</th>
                  <th className="px-4 py-2.5 text-right">Available</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {byPart.map((p) => (
                  <tr key={p.part_number} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40">
                    <td className="px-4 py-3">
                      <p className="font-bold text-zinc-900 dark:text-zinc-100">{p.part_number}</p>
                      {p.part_name && <p className="text-[11px] text-zinc-500">{p.part_name}</p>}
                    </td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">{Array.from(p.customers).join(", ")}</td>
                    <td className="px-4 py-3 text-right font-semibold">{p.wos}</td>
                    <td className="px-4 py-3 text-right text-sm font-extrabold text-cyan-700 dark:text-cyan-400">
                      {fmt(p.qty)} <span className="text-[11px] font-semibold text-zinc-400">pcs</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">Work Order</th>
                  <th className="px-4 py-2.5">Customer / PO</th>
                  <th className="px-4 py-2.5">Part</th>
                  <th className="px-4 py-2.5 text-right">Order qty</th>
                  <th className="px-4 py-2.5 text-right">Dispatched</th>
                  <th className="px-4 py-2.5 text-right">Available in BSR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {filtered.map((i) => (
                  <tr key={i.id || i.wo_number} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40">
                    <td className="px-4 py-3">
                      <Link
                        href={`/production/tracking?wo=${encodeURIComponent(i.wo_number)}`}
                        className="font-bold text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        {i.wo_number}
                      </Link>
                      {i.oar_number && <p className="text-[11px] text-zinc-400">{i.oar_number}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-zinc-800 dark:text-zinc-200">{i.customer_name}</p>
                      <p className="text-[11px] text-zinc-500">{i.customer_po}</p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-semibold text-zinc-800 dark:text-zinc-200">{i.part_number}</p>
                      {i.part_name && <p className="text-[11px] text-zinc-500">{i.part_name}</p>}
                    </td>
                    <td className="px-4 py-3 text-right">{fmt(i.order_qty)}</td>
                    <td className="px-4 py-3 text-right">{fmt(i.already_dispatched_qty)}</td>
                    <td className="px-4 py-3 text-right text-sm font-extrabold text-cyan-700 dark:text-cyan-400">
                      {fmt(i.ready_for_dispatch_qty)} <span className="text-[11px] font-semibold text-zinc-400">pcs</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-start gap-2 text-xs text-zinc-500">
          <Info className="h-4 w-4 shrink-0 text-zinc-400 mt-0.5" />
          <p>
            Read-only. To ship stock, use the{" "}
            <Link href="/dispatch" className="inline-flex items-center gap-1 font-semibold text-blue-600 dark:text-blue-400 hover:underline">
              <Truck className="h-3.5 w-3.5" /> Dispatch Center
            </Link>
            .
          </p>
        </div>
      </div>
    </AppShell>
  );
}
