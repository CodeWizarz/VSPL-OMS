"use client";
import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import {
  Warehouse,
  Search,
  CheckCircle2,
  Boxes,
  Truck,
  ArrowRight,
  RefreshCw,
  Layers,
  ShieldCheck,
  PackageCheck,
  PlusCircle,
  AlertTriangle,
  History,
  Tag,
  Check
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import {
  getPackingQueue,
  listBSRStock,
  allocateBSRStock,
  PackingQueueItem,
  BSRStockSummary
} from "@/lib/api";

type TabMode = "all" | "committed" | "buffer" | "history";

export default function BSRStorePage() {
  const [activeTab, setActiveTab] = useState<TabMode>("all");
  const [packingQueue, setPackingQueue] = useState<PackingQueueItem[]>([]);
  const [bsrStockList, setBsrStockList] = useState<BSRStockSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [successToast, setSuccessToast] = useState("");

  // Allocate Modal
  const [allocateModalPart, setAllocateModalPart] = useState<BSRStockSummary | null>(null);
  const [targetOarId, setTargetOarId] = useState("");
  const [allocateQty, setAllocateQty] = useState<number | "">("");
  const [allocating, setAllocating] = useState(false);
  const [allocateError, setAllocateError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [queueData, stockData] = await Promise.all([
        getPackingQueue().catch(() => [] as PackingQueueItem[]),
        listBSRStock().catch(() => [] as BSRStockSummary[])
      ]);
      setPackingQueue(queueData);
      setBsrStockList(stockData);
    } catch (err: any) {
      setError(err?.message || "Failed to load BSR warehouse data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleAllocateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!allocateModalPart) return;
    const qty = Number(allocateQty);
    if (!targetOarId.trim()) {
      setAllocateError("Please enter the target OAR Reference or ID.");
      return;
    }
    if (!qty || qty <= 0) {
      setAllocateError("Quantity must be greater than 0.");
      return;
    }
    if (qty > allocateModalPart.total_available) {
      setAllocateError(`Cannot allocate ${qty} pcs. Only ${allocateModalPart.total_available} pcs free buffer available.`);
      return;
    }

    setAllocating(true);
    setAllocateError("");
    try {
      const res = await allocateBSRStock({
        oar_id: targetOarId.trim(),
        quantity: qty
      });
      setSuccessToast(`Successfully allocated ${res.allocated_from_stock} pcs to OAR ${res.oar_number} from BSR buffer!`);
      setAllocateModalPart(null);
      await loadData();
      setTimeout(() => setSuccessToast(""), 5000);
    } catch (err: any) {
      setAllocateError(err?.response?.data?.detail || err?.message || "Failed to allocate BSR buffer stock.");
    } finally {
      setAllocating(false);
    }
  };

  // 1. PO-Committed Lots physically sitting in BSR waiting for Dispatch
  const activeCommittedLots = useMemo(() => {
    return packingQueue.filter((item) => (item.ready_for_dispatch_qty || 0) > 0);
  }, [packingQueue]);

  // 2. Previously Dispatched Lots (Audit / History)
  const dispatchedLots = useMemo(() => {
    return packingQueue.filter(
      (item) => (item.ready_for_dispatch_qty || 0) === 0 && (item.dispatched_qty || 0) > 0
    );
  }, [packingQueue]);

  // 3. Free Buffer Stock lots
  const activeBufferStock = useMemo(() => {
    return bsrStockList.filter((item) => (item.total_available || 0) > 0);
  }, [bsrStockList]);

  // Total Calculations
  const totalCommittedPcs = useMemo(() => {
    return activeCommittedLots.reduce((acc, it) => acc + (it.ready_for_dispatch_qty || 0), 0);
  }, [activeCommittedLots]);

  const totalBufferPcs = useMemo(() => {
    return activeBufferStock.reduce((acc, it) => acc + (it.total_available || 0), 0);
  }, [activeBufferStock]);

  const totalPhysicalInBSR = totalCommittedPcs + totalBufferPcs;

  // Filtered queries
  const q = search.toLowerCase().trim();

  const filteredCommitted = useMemo(() => {
    return activeCommittedLots.filter((item) => {
      if (!q) return true;
      return (
        item.wo_number.toLowerCase().includes(q) ||
        item.customer_name.toLowerCase().includes(q) ||
        item.part_number.toLowerCase().includes(q) ||
        (item.customer_part_number && item.customer_part_number.toLowerCase().includes(q)) ||
        (item.oar_number && item.oar_number.toLowerCase().includes(q))
      );
    });
  }, [activeCommittedLots, q]);

  const filteredBuffer = useMemo(() => {
    return activeBufferStock.filter((item) => {
      if (!q) return true;
      return (
        item.part_number.toLowerCase().includes(q) ||
        (item.part_description && item.part_description.toLowerCase().includes(q)) ||
        item.lots?.some((l) => l.heat_number?.toLowerCase().includes(q) || l.source_wo_number?.toLowerCase().includes(q))
      );
    });
  }, [activeBufferStock, q]);

  const filteredHistory = useMemo(() => {
    return dispatchedLots.filter((item) => {
      if (!q) return true;
      return (
        item.wo_number.toLowerCase().includes(q) ||
        item.customer_name.toLowerCase().includes(q) ||
        item.part_number.toLowerCase().includes(q) ||
        (item.customer_part_number && item.customer_part_number.toLowerCase().includes(q))
      );
    });
  }, [dispatchedLots, q]);

  return (
    <AppShell>
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-purple-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Stage 7 / Gate BSR
              </span>
              <span className="text-xs text-zinc-400">Bonded Storage Room & Finished Goods Warehouse</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              BSR Bonded Storage & Finished Goods
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Live inventory of all packed goods physically held in BSR custody — both lots committed to Customer POs and free excess buffer stock.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/packing"
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <PackageCheck className="h-3.5 w-3.5 text-teal-600" />
              <span>Back to Packing</span>
            </Link>
            <Link
              href="/dispatch"
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 transition-colors"
            >
              <Truck className="h-3.5 w-3.5" />
              <span>Go to Dispatch Bay</span>
            </Link>
            <button
              onClick={loadData}
              disabled={loading}
              className="p-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm cursor-pointer"
              title="Refresh BSR Data"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin text-purple-600" : ""}`} />
            </button>
          </div>
        </div>

        {/* Success Toast */}
        {successToast && (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5 flex items-center gap-3 text-xs text-emerald-800 dark:text-emerald-200 font-bold shadow-sm animate-in fade-in">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
            <span>{successToast}</span>
          </div>
        )}

        {/* KPI Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm flex items-center gap-3.5">
            <div className="p-3 rounded-xl bg-purple-50 dark:bg-purple-950/40 text-purple-600">
              <Warehouse className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Total Stock Physically in BSR</p>
              <h3 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-50">
                {totalPhysicalInBSR.toLocaleString()} <span className="text-xs font-normal text-zinc-500">pcs</span>
              </h3>
              <p className="text-[10px] text-zinc-500">
                {activeCommittedLots.length} customer lots + {activeBufferStock.length} buffer part types
              </p>
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm flex items-center gap-3.5">
            <div className="p-3 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600">
              <PackageCheck className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Committed to Customer POs</p>
              <h3 className="text-xl font-extrabold text-indigo-600 dark:text-indigo-400">
                {totalCommittedPcs.toLocaleString()} <span className="text-xs font-normal text-zinc-500">pcs</span>
              </h3>
              <p className="text-[10px] text-zinc-500">Ready in BSR for truck dispatch</p>
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm flex items-center gap-3.5">
            <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600">
              <Boxes className="h-6 w-6" />
            </div>
            <div>
              <p className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Free Excess Buffer Stock</p>
              <h3 className="text-xl font-extrabold text-emerald-600 dark:text-emerald-400">
                {totalBufferPcs.toLocaleString()} <span className="text-xs font-normal text-zinc-500">pcs</span>
              </h3>
              <p className="text-[10px] text-zinc-500">Surplus stock ready to fulfill any OAR</p>
            </div>
          </div>
        </div>

        {/* Tab & Search Navigation */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-200 dark:border-zinc-800 pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab("all")}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
                  activeTab === "all"
                    ? "bg-purple-600 text-white shadow-sm"
                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                }`}
              >
                <Layers className="h-3.5 w-3.5" />
                <span>All in BSR ({activeCommittedLots.length + activeBufferStock.length})</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("committed")}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
                  activeTab === "committed"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                }`}
              >
                <PackageCheck className="h-3.5 w-3.5" />
                <span>Committed to POs ({activeCommittedLots.length})</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("buffer")}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
                  activeTab === "buffer"
                    ? "bg-emerald-600 text-white shadow-sm"
                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                }`}
              >
                <Boxes className="h-3.5 w-3.5" />
                <span>Free Buffer Stock ({activeBufferStock.length})</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab("history")}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
                  activeTab === "history"
                    ? "bg-zinc-800 dark:bg-zinc-200 text-white dark:text-zinc-900 shadow-sm"
                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                }`}
              >
                <History className="h-3.5 w-3.5" />
                <span>Dispatched History ({dispatchedLots.length})</span>
              </button>
            </div>

            <div className="relative w-full sm:w-72">
              <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search WO, Customer, Part #, OAR..."
                className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-9 pr-3 py-1.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-purple-500"
              />
            </div>
          </div>

          {/* TAB 1: ALL IN BSR (UNIFIED VIEW) */}
          {activeTab === "all" && (
            <div>
              {loading ? (
                <p className="text-xs text-zinc-400 py-8 text-center">Loading BSR inventory...</p>
              ) : filteredCommitted.length === 0 && filteredBuffer.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-400 flex flex-col items-center justify-center gap-2">
                  <Warehouse className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                  <p className="font-bold">No inventory currently sitting in BSR.</p>
                  <p className="text-[11px] text-zinc-500">
                    When packing is completed at Stage 6, goods immediately land in BSR ready for customer dispatch.
                  </p>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Committed Lots Section */}
                  {filteredCommitted.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="h-2 w-2 rounded-full bg-indigo-500" />
                          <h3 className="text-xs font-bold text-zinc-900 dark:text-zinc-100 uppercase tracking-wider">
                            PO-Committed Finished Lots ({filteredCommitted.length})
                          </h3>
                        </div>
                        <span className="text-[11px] text-zinc-400">
                          {totalCommittedPcs.toLocaleString()} pcs ready for truck loading
                        </span>
                      </div>

                      <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider">
                            <tr>
                              <th className="p-3">Work Order &amp; OAR</th>
                              <th className="p-3">Customer</th>
                              <th className="p-3">Part Details</th>
                              <th className="p-3 text-right">Order Qty</th>
                              <th className="p-3 text-right">In BSR (Ready)</th>
                              <th className="p-3 text-center">Stock Type</th>
                              <th className="p-3 text-right">Action</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                            {filteredCommitted.map((item) => (
                              <tr key={item.work_order_id} className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition">
                                <td className="p-3">
                                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                                    {item.wo_number}
                                  </span>
                                  <span className="text-[10px] text-zinc-400 font-mono">
                                    OAR: {item.oar_number || "—"}
                                  </span>
                                </td>
                                <td className="p-3">
                                  <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                                    {item.customer_name}
                                  </span>
                                </td>
                                <td className="p-3">
                                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                                    {item.customer_part_number || item.part_number}
                                  </span>
                                  {item.customer_part_number && item.customer_part_number !== item.part_number && (
                                    <span className="text-[10px] text-zinc-400 font-mono">
                                      Internal: {item.part_number}
                                    </span>
                                  )}
                                </td>
                                <td className="p-3 text-right font-mono text-zinc-600 dark:text-zinc-400">
                                  {item.order_qty} pcs
                                </td>
                                <td className="p-3 text-right font-mono font-extrabold text-indigo-600 dark:text-indigo-400 text-sm">
                                  {item.ready_for_dispatch_qty} pcs
                                </td>
                                <td className="p-3 text-center">
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                                    <Tag className="h-2.5 w-2.5" />
                                    <span>Committed PO</span>
                                  </span>
                                </td>
                                <td className="p-3 text-right">
                                  <Link
                                    href={`/dispatch?wo=${encodeURIComponent(item.wo_number)}`}
                                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-[11px] shadow-xs transition"
                                  >
                                    <span>Dispatch</span>
                                    <ArrowRight className="h-3 w-3" />
                                  </Link>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Free Buffer Section */}
                  {filteredBuffer.length > 0 && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="h-2 w-2 rounded-full bg-emerald-500" />
                          <h3 className="text-xs font-bold text-zinc-900 dark:text-zinc-100 uppercase tracking-wider">
                            Free Excess Buffer Stock ({filteredBuffer.length})
                          </h3>
                        </div>
                        <span className="text-[11px] text-zinc-400">
                          {totalBufferPcs.toLocaleString()} surplus pcs available for any OAR
                        </span>
                      </div>

                      <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                        <table className="w-full text-left text-xs">
                          <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider">
                            <tr>
                              <th className="p-3">Part Details</th>
                              <th className="p-3">Source Heat / Lots</th>
                              <th className="p-3 text-right">Free Buffer Qty</th>
                              <th className="p-3 text-center">Stock Type</th>
                              <th className="p-3 text-right">Action</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                            {filteredBuffer.map((partStock) => (
                              <tr key={partStock.part_id} className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition">
                                <td className="p-3">
                                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                                    {partStock.part_number}
                                  </span>
                                  {partStock.part_description && (
                                    <span className="text-[10px] text-zinc-500">
                                      {partStock.part_description}
                                    </span>
                                  )}
                                </td>
                                <td className="p-3 font-mono text-[11px] text-zinc-600 dark:text-zinc-400">
                                  {partStock.lots?.map((l) => l.heat_number).filter(Boolean).join(", ") || "—"}
                                </td>
                                <td className="p-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400 text-sm">
                                  {partStock.total_available} pcs
                                </td>
                                <td className="p-3 text-center">
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                                    <Boxes className="h-2.5 w-2.5" />
                                    <span>Free Buffer</span>
                                  </span>
                                </td>
                                <td className="p-3 text-right">
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setAllocateModalPart(partStock);
                                      setAllocateQty(partStock.total_available);
                                      setTargetOarId("");
                                      setAllocateError("");
                                    }}
                                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white font-bold text-[11px] shadow-xs transition cursor-pointer"
                                  >
                                    <PlusCircle className="h-3 w-3" />
                                    <span>Allocate to OAR</span>
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* TAB 2: COMMITTED TO POS ONLY */}
          {activeTab === "committed" && (
            <div>
              {loading ? (
                <p className="text-xs text-zinc-400 py-8 text-center">Loading committed lots...</p>
              ) : filteredCommitted.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-400 flex flex-col items-center justify-center gap-2">
                  <PackageCheck className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                  <p className="font-bold">No PO-committed lots currently sitting in BSR.</p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider">
                      <tr>
                        <th className="p-3">Work Order &amp; OAR</th>
                        <th className="p-3">Customer Details</th>
                        <th className="p-3">Part Details</th>
                        <th className="p-3 text-right">Order Qty</th>
                        <th className="p-3 text-right">Ready in BSR</th>
                        <th className="p-3 text-center">BSR Status</th>
                        <th className="p-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {filteredCommitted.map((item) => (
                        <tr key={item.work_order_id} className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition">
                          <td className="p-3">
                            <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                              {item.wo_number}
                            </span>
                            <span className="text-[10px] text-zinc-400 font-mono">
                              OAR: {item.oar_number || "—"}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                              {item.customer_name}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                              {item.customer_part_number || item.part_number}
                            </span>
                            {item.customer_part_number && item.customer_part_number !== item.part_number && (
                              <span className="text-[10px] text-zinc-400 font-mono">
                                Internal: {item.part_number}
                              </span>
                            )}
                          </td>
                          <td className="p-3 text-right font-mono text-zinc-600 dark:text-zinc-400">
                            {item.order_qty} pcs
                          </td>
                          <td className="p-3 text-right font-mono font-extrabold text-indigo-600 dark:text-indigo-400 text-sm">
                            {item.ready_for_dispatch_qty} pcs
                          </td>
                          <td className="p-3 text-center">
                            <Badge variant="green" size="sm">
                              In BSR (Ready for Dispatch)
                            </Badge>
                          </td>
                          <td className="p-3 text-right">
                            <Link
                              href={`/dispatch?wo=${encodeURIComponent(item.wo_number)}`}
                              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-[11px] shadow-xs transition"
                            >
                              <span>Dispatch</span>
                              <ArrowRight className="h-3 w-3" />
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: FREE BUFFER STOCK */}
          {activeTab === "buffer" && (
            <div>
              {loading ? (
                <p className="text-xs text-zinc-400 py-8 text-center">Loading BSR buffer stock...</p>
              ) : filteredBuffer.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-400 flex flex-col items-center justify-center gap-2">
                  <Boxes className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                  <p className="font-bold">No excess buffer stock currently in BSR.</p>
                  <p className="text-[11px] text-zinc-500">
                    When Work Orders produce more quantity than the PO, excess good pieces are automatically banked into BSR buffer stock.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {filteredBuffer.map((partStock) => (
                    <div
                      key={partStock.part_id}
                      className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-4 bg-zinc-50/50 dark:bg-zinc-950/40 space-y-3"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-extrabold text-zinc-900 dark:text-zinc-100">
                              {partStock.part_number}
                            </span>
                            {partStock.part_description && (
                              <span className="text-xs text-zinc-500">
                                ({partStock.part_description})
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-zinc-400">
                            Part ID: {partStock.part_id}
                          </p>
                        </div>

                        <div className="flex items-center gap-3">
                          <div className="text-right">
                            <span className="text-xs font-bold text-zinc-500 block">Available Free Stock</span>
                            <span className="font-mono text-base font-extrabold text-emerald-600 dark:text-emerald-400">
                              {partStock.total_available} pcs
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              setAllocateModalPart(partStock);
                              setAllocateQty(partStock.total_available);
                              setTargetOarId("");
                              setAllocateError("");
                            }}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white font-bold text-xs shadow-xs transition cursor-pointer"
                          >
                            <PlusCircle className="h-3.5 w-3.5" />
                            <span>Allocate to OAR</span>
                          </button>
                        </div>
                      </div>

                      {/* Lot breakdown */}
                      {partStock.lots && partStock.lots.length > 0 && (
                        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
                          <table className="w-full text-left text-[11px]">
                            <thead className="bg-zinc-100 dark:bg-zinc-800/60 text-zinc-500 text-[10px] uppercase font-bold">
                              <tr>
                                <th className="p-2">Source Work Order</th>
                                <th className="p-2">Melt Heat Number</th>
                                <th className="p-2 text-right">Available in BSR</th>
                                <th className="p-2 text-right">Allocated</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                              {partStock.lots.map((lot) => (
                                <tr key={lot.id}>
                                  <td className="p-2 font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                                    {lot.source_wo_number || "Direct Deposit"}
                                  </td>
                                  <td className="p-2 font-mono text-zinc-600 dark:text-zinc-400">
                                    {lot.heat_number || "—"}
                                  </td>
                                  <td className="p-2 text-right font-mono font-bold text-emerald-600">
                                    {lot.available_qty} pcs
                                  </td>
                                  <td className="p-2 text-right font-mono text-zinc-400">
                                    {lot.allocated_qty} pcs
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 4: DISPATCHED HISTORY */}
          {activeTab === "history" && (
            <div>
              {loading ? (
                <p className="text-xs text-zinc-400 py-8 text-center">Loading dispatched history...</p>
              ) : filteredHistory.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-400 flex flex-col items-center justify-center gap-2">
                  <History className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                  <p className="font-bold">No historical dispatched records found.</p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider">
                      <tr>
                        <th className="p-3">Work Order &amp; OAR</th>
                        <th className="p-3">Customer Details</th>
                        <th className="p-3">Part Details</th>
                        <th className="p-3 text-right">Dispatched Qty</th>
                        <th className="p-3 text-center">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {filteredHistory.map((item) => (
                        <tr key={item.work_order_id} className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition opacity-80">
                          <td className="p-3">
                            <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                              {item.wo_number}
                            </span>
                            <span className="text-[10px] text-zinc-400 font-mono">
                              OAR: {item.oar_number || "—"}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                              {item.customer_name}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                              {item.customer_part_number || item.part_number}
                            </span>
                          </td>
                          <td className="p-3 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                            {item.dispatched_qty} pcs
                          </td>
                          <td className="p-3 text-center">
                            <Badge variant="gray" size="sm">
                              {item.status || "Fully-Dispatched"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Allocate Stock Modal */}
        {allocateModalPart && (
          <Modal
            isOpen={Boolean(allocateModalPart)}
            onClose={() => setAllocateModalPart(null)}
            title={`Allocate BSR Buffer Stock: ${allocateModalPart.part_number}`}
          >
            <form onSubmit={handleAllocateSubmit} className="space-y-4">
              <div className="rounded-xl bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800/60 p-3 text-xs text-purple-900 dark:text-purple-200">
                <p className="font-bold">Immediate OAR Fulfillment from BSR Warehouse</p>
                <p className="text-[11px] mt-0.5 text-purple-700 dark:text-purple-300">
                  Allocating stock satisfies an open Sales OAR immediately from existing finished buffer stock, bypassing casting and machining.
                </p>
              </div>

              {allocateError && (
                <div className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 font-semibold flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{allocateError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Target OAR Reference or Order ID <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  value={targetOarId}
                  onChange={(e) => setTargetOarId(e.target.value)}
                  placeholder="e.g. OAR-8786 or Order UUID..."
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Quantity to Allocate (Max: {allocateModalPart.total_available} pcs) <span className="text-rose-500">*</span>
                </label>
                <input
                  type="number"
                  min={1}
                  max={allocateModalPart.total_available}
                  value={allocateQty}
                  onChange={(e) => setAllocateQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-zinc-200 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setAllocateModalPart(null)}
                  className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={allocating}
                  className="px-4 py-2 text-xs font-bold rounded-xl bg-purple-600 text-white hover:bg-purple-700 transition flex items-center gap-1.5 shadow-sm cursor-pointer"
                >
                  {allocating ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  <span>{allocating ? "Allocating..." : "Confirm Stock Allocation"}</span>
                </button>
              </div>
            </form>
          </Modal>
        )}
      </div>
    </AppShell>
  );
}
