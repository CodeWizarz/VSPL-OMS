"use client";
import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import {
  CalendarCheck,
  TrendingUp,
  Download,
  Search,
  Filter,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Building2,
  Layers,
  Truck,
  ArrowRight,
  ExternalLink,
  ChevronDown,
  Info,
  DollarSign,
  AlertCircle,
  Eye,
  X
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getSalesOpsDailyReport,
  getSalesOpsCsvExportUrl,
  downloadFile,
  SalesOpsDailyReportResponse,
  SalesOpsDailyItem,
  SalesOpsSummary,
} from "@/lib/api";

type DatePreset = "today" | "overdue_and_today" | "tomorrow" | "this_week" | "all_active" | "custom";
type StatusFilter = "all" | "gaps_only" | "ready_only" | "at_vendor" | "overdue";
type SortOption = "priority" | "value_desc" | "date_asc" | "gap_desc" | "customer";

export default function SalesOpsDailyReportPage() {
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters & State
  const [preset, setPreset] = useState<DatePreset>("today");
  const [targetDate, setTargetDate] = useState<string>(() => {
    return new Date().toISOString().split("T")[0];
  });
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<SortOption>("priority");
  const [search, setSearch] = useState("");

  // Report Data
  const [report, setReport] = useState<SalesOpsDailyReportResponse | null>(null);
  const [selectedItem, setSelectedItem] = useState<SalesOpsDailyItem | null>(null);

  const fetchReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSalesOpsDailyReport({
        target_date: targetDate,
        from_date: preset === "custom" ? fromDate : undefined,
        to_date: preset === "custom" ? toDate : undefined,
        preset,
        status_filter: statusFilter,
        search: search.trim() || undefined,
        sort_by: sortBy,
      });
      setReport(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load Sales-Ops Daily Report. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, targetDate, statusFilter, sortBy]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchReport();
  };

  const handleExportCsv = async () => {
    setDownloading(true);
    try {
      const url = getSalesOpsCsvExportUrl({
        target_date: targetDate,
        from_date: preset === "custom" ? fromDate : undefined,
        to_date: preset === "custom" ? toDate : undefined,
        preset,
        status_filter: statusFilter,
        search: search.trim() || undefined,
        sort_by: sortBy,
      });
      const filename = `vspl_sales_ops_${preset}_${targetDate || "report"}.csv`;
      await downloadFile(url, filename);
    } catch (err: any) {
      alert("Failed to download CSV: " + (err?.message || "Unknown error"));
    } finally {
      setDownloading(false);
    }
  };

  const summary = report?.summary || {
    total_orders: 0,
    total_planned_qty: 0,
    total_bsr_actual_qty: 0,
    total_dispatched_qty: 0,
    total_fulfilled_qty: 0,
    total_gap_qty: 0,
    fulfillment_rate: 0,
    total_planned_value: 0,
    total_fulfilled_value: 0,
    total_gap_value: 0,
    overdue_orders_count: 0,
    overdue_gap_value: 0,
    today_orders_count: 0,
    today_gap_value: 0,
    at_vendor_count: 0,
  };

  const items = report?.items || [];

  return (
    <AppShell>
      <div className="space-y-6 max-w-7xl mx-auto pb-12">
        {/* Top Header & Breadcrumb */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Sales-Ops
              </span>
              <span className="text-xs text-zinc-400 dark:text-zinc-500 font-medium">Daily Standup Dashboard</span>
            </div>
            <h1 className="text-2xl font-black tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2.5">
              <span>Sales-Ops Daily Meeting Report</span>
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                Plan vs Actual
              </span>
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 max-w-2xl">
              Track today’s customer commitment quantities vs finished pieces ready in BSR and dispatches.
              Prioritized by order value (₹) to unblock high-impact shipments before the morning standup.
            </p>
          </div>

          {/* Top Actions: Export CSV & Refresh */}
          <div className="flex items-center gap-2.5 self-start md:self-auto">
            <button
              onClick={fetchReport}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 text-xs font-semibold hover:bg-zinc-50 dark:hover:bg-zinc-800/80 transition-all shadow-sm"
              title="Refresh live data"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin text-indigo-500" : ""}`} />
              <span>Refresh</span>
            </button>

            <button
              onClick={handleExportCsv}
              disabled={downloading || items.length === 0}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className={`h-4 w-4 ${downloading ? "animate-bounce" : ""}`} />
              <span>{downloading ? "Generating CSV..." : "Export Standup CSV"}</span>
            </button>
          </div>
        </div>

        {/* Filter Toolbar Card */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Date Preset Selector */}
            <div className="flex flex-wrap items-center gap-1.5 bg-zinc-100 dark:bg-zinc-800/60 p-1 rounded-xl">
              <button
                type="button"
                onClick={() => setPreset("today")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "today"
                    ? "bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                Today
              </button>
              <button
                type="button"
                onClick={() => setPreset("overdue_and_today")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "overdue_and_today"
                    ? "bg-white dark:bg-zinc-900 text-rose-600 dark:text-rose-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                Overdue + Today
              </button>
              <button
                type="button"
                onClick={() => setPreset("tomorrow")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "tomorrow"
                    ? "bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                Tomorrow
              </button>
              <button
                type="button"
                onClick={() => setPreset("this_week")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "this_week"
                    ? "bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                This Week (7 Days)
              </button>
              <button
                type="button"
                onClick={() => setPreset("all_active")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "all_active"
                    ? "bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                All Active Orders
              </button>
              <button
                type="button"
                onClick={() => setPreset("custom")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  preset === "custom"
                    ? "bg-white dark:bg-zinc-900 text-indigo-600 dark:text-indigo-400 shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200"
                }`}
              >
                Custom Range
              </button>
            </div>

            {/* Target Date Picker (if today or picking reference date) */}
            {preset !== "custom" && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-500 font-medium">Reference Date:</span>
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className="px-2.5 py-1 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800 font-semibold text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            )}

            {/* Custom Date Inputs */}
            {preset === "custom" && (
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  placeholder="From"
                  className="px-2 py-1 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200"
                />
                <span className="text-xs text-zinc-400">to</span>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                  placeholder="To"
                  className="px-2 py-1 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200"
                />
                <button
                  type="button"
                  onClick={fetchReport}
                  className="px-3 py-1 rounded-lg bg-indigo-600 text-white text-xs font-semibold"
                >
                  Apply
                </button>
              </div>
            )}
          </div>

          {/* Secondary Filter Row: Search, Status Filter & Sorting */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
            {/* Search Input */}
            <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-400" />
              <input
                type="text"
                placeholder="Search WO ID, Customer, Internal Part, Customer Part, PO..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-800/70 text-zinc-900 dark:text-zinc-100 focus:bg-white dark:focus:bg-zinc-900 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </form>

            <div className="flex flex-wrap items-center gap-2">
              {/* Status Filter Dropdown */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400 font-medium">Status:</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                  className="px-2.5 py-1.5 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 font-semibold text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="all">All Orders</option>
                  <option value="gaps_only">Deficit / Gaps Only</option>
                  <option value="ready_only">Ready in BSR (100% Fulfilled)</option>
                  <option value="at_vendor">At Outside Vendor</option>
                  <option value="overdue">Overdue Orders Only</option>
                </select>
              </div>

              {/* Sort By Dropdown */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-zinc-400 font-medium">Sort By:</span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortOption)}
                  className="px-2.5 py-1.5 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 font-semibold text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="priority">Priority Rank (Urgent + High Value)</option>
                  <option value="value_desc">Order Value: High to Low (₹)</option>
                  <option value="date_asc">Commitment Date: Earliest First</option>
                  <option value="gap_desc">Gap Deficit: Largest First</option>
                  <option value="customer">Customer Name (A-Z)</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900/50 dark:bg-rose-950/30 p-4 text-xs text-rose-700 dark:text-rose-400 flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
            <span>{error}</span>
          </div>
        )}

        {/* Executive KPI Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {/* Card 1: Planned Demand */}
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3.5 shadow-sm space-y-1">
            <div className="flex items-center justify-between text-zinc-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">Plan Demand</span>
              <CalendarCheck className="h-4 w-4 text-indigo-500" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-black text-zinc-900 dark:text-zinc-50">
                {summary.total_planned_qty.toLocaleString()}
              </span>
              <span className="text-xs text-zinc-400 font-medium">pcs</span>
            </div>
            <div className="text-[11px] font-semibold text-indigo-600 dark:text-indigo-400">
              ₹{summary.total_planned_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </div>
            <div className="text-[10px] text-zinc-400">
              {summary.total_orders} orders matching
            </div>
          </div>

          {/* Card 2: BSR Actual (Ready to Ship) */}
          <div className="rounded-2xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/40 dark:bg-emerald-950/20 p-3.5 shadow-sm space-y-1">
            <div className="flex items-center justify-between text-emerald-700 dark:text-emerald-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">BSR Ready</span>
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-black text-emerald-700 dark:text-emerald-300">
                {summary.total_bsr_actual_qty.toLocaleString()}
              </span>
              <span className="text-xs text-emerald-600 font-medium">pcs ready</span>
            </div>
            <div className="text-[11px] font-semibold text-emerald-800 dark:text-emerald-300">
              + {summary.total_dispatched_qty.toLocaleString()} dispatched
            </div>
            <div className="text-[10px] text-emerald-600/80 dark:text-emerald-400/80">
              Finished & available to dispatch
            </div>
          </div>

          {/* Card 3: Deficit / Gap Quantity */}
          <div className="rounded-2xl border border-rose-200 dark:border-rose-900/60 bg-rose-50/40 dark:bg-rose-950/20 p-3.5 shadow-sm space-y-1">
            <div className="flex items-center justify-between text-rose-700 dark:text-rose-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">Plan vs Actual Gap</span>
              <AlertTriangle className="h-4 w-4 text-rose-600" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-black text-rose-700 dark:text-rose-300">
                {summary.total_gap_qty.toLocaleString()}
              </span>
              <span className="text-xs text-rose-600 font-medium">pcs deficit</span>
            </div>
            <div className="text-[11px] font-semibold text-rose-700 dark:text-rose-400">
              ₹{summary.total_gap_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })} at risk
            </div>
            <div className="text-[10px] text-rose-600/80 dark:text-rose-400/80">
              Pieces pending on floor/vendor
            </div>
          </div>

          {/* Card 4: Fulfillment % */}
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3.5 shadow-sm space-y-1.5">
            <div className="flex items-center justify-between text-zinc-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">Fulfillment Rate</span>
              <TrendingUp className="h-4 w-4 text-indigo-500" />
            </div>
            <div className="text-xl font-black text-zinc-900 dark:text-zinc-50">
              {summary.fulfillment_rate}%
            </div>
            {/* Progress bar */}
            <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  summary.fulfillment_rate >= 80
                    ? "bg-emerald-500"
                    : summary.fulfillment_rate >= 50
                    ? "bg-amber-500"
                    : "bg-rose-500"
                }`}
                style={{ width: `${Math.min(100, summary.fulfillment_rate)}%` }}
              />
            </div>
            <div className="text-[10px] text-zinc-400">
              {summary.total_fulfilled_qty.toLocaleString()} / {summary.total_planned_qty.toLocaleString()} pcs satisfied
            </div>
          </div>

          {/* Card 5: Overdue Attention Alert */}
          <div className="rounded-2xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/40 dark:bg-amber-950/20 p-3.5 shadow-sm space-y-1">
            <div className="flex items-center justify-between text-amber-700 dark:text-amber-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">Overdue Gaps</span>
              <Clock className="h-4 w-4 text-amber-600" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-black text-amber-800 dark:text-amber-200">
                {summary.overdue_orders_count}
              </span>
              <span className="text-xs text-amber-700 font-medium">orders overdue</span>
            </div>
            <div className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">
              ₹{summary.overdue_gap_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </div>
            <div className="text-[10px] text-amber-700/80 dark:text-amber-400/80">
              Past commitment date
            </div>
          </div>

          {/* Card 6: At Outside Vendor */}
          <div className="rounded-2xl border border-purple-200 dark:border-purple-900/60 bg-purple-50/40 dark:bg-purple-950/20 p-3.5 shadow-sm space-y-1">
            <div className="flex items-center justify-between text-purple-700 dark:text-purple-400">
              <span className="text-[11px] font-bold uppercase tracking-wider">At Vendor</span>
              <Truck className="h-4 w-4 text-purple-600" />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-xl font-black text-purple-800 dark:text-purple-200">
                {summary.at_vendor_count}
              </span>
              <span className="text-xs text-purple-700 font-medium">WOs at vendor</span>
            </div>
            <div className="text-[11px] font-semibold text-purple-700 dark:text-purple-300">
              Subcontracting Stage
            </div>
            <div className="text-[10px] text-purple-700/80 dark:text-purple-400/80">
              Require inward receipt
            </div>
          </div>
        </div>

        {/* Main Data Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100 uppercase tracking-wider">
                Sales-Ops Standup Ledger
              </h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 font-semibold text-zinc-600 dark:text-zinc-400">
                {items.length} orders
              </span>
            </div>
            <span className="text-xs text-zinc-400 hidden sm:inline">
              Click any row to inspect stage WIP breakdown & vendor traceability
            </span>
          </div>

          {loading ? (
            <div className="py-20 text-center space-y-3">
              <RefreshCw className="h-6 w-6 animate-spin text-indigo-600 mx-auto" />
              <p className="text-xs text-zinc-500 font-semibold">Aggregating live Work Orders, BSR balances and pricing...</p>
            </div>
          ) : items.length === 0 ? (
            <div className="py-20 text-center space-y-3">
              <CalendarCheck className="h-10 w-10 text-zinc-300 dark:text-zinc-700 mx-auto" />
              <p className="text-sm font-bold text-zinc-700 dark:text-zinc-300">No Orders Found for Selected Filter</p>
              <p className="text-xs text-zinc-400 max-w-sm mx-auto">
                No active work orders matched the commitment date window or search terms. Try clicking <span className="font-bold text-indigo-600 cursor-pointer" onClick={() => setPreset("all_active")}>All Active Orders</span> or <span className="font-bold text-rose-600 cursor-pointer" onClick={() => setPreset("overdue_and_today")}>Overdue + Today</span>.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-50 dark:bg-zinc-800/60 text-zinc-500 dark:text-zinc-400 font-bold border-b border-zinc-200 dark:border-zinc-800 uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="py-3 px-3 w-10 text-center">#</th>
                    <th className="py-3 px-3">WO ID</th>
                    <th className="py-3 px-3">Customer & PO</th>
                    <th className="py-3 px-3">Customer Part No</th>
                    <th className="py-3 px-3">Internal Part ID</th>
                    <th className="py-3 px-3 text-center">Commitment Date</th>
                    <th className="py-3 px-3 text-right">Plan Qty</th>
                    <th className="py-3 px-3 text-right bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-800 dark:text-emerald-300">
                      BSR Actual
                    </th>
                    <th className="py-3 px-3 text-right">Dispatched</th>
                    <th className="py-3 px-3 text-right bg-rose-50/50 dark:bg-rose-950/20 text-rose-800 dark:text-rose-300 font-black">
                      Gap Deficit
                    </th>
                    <th className="py-3 px-3 text-center">Floor Location</th>
                    <th className="py-3 px-3 text-right">Unit Rate (₹)</th>
                    <th className="py-3 px-3 text-right font-black">Planned Value</th>
                    <th className="py-3 px-3 text-right text-rose-600 dark:text-rose-400 font-black">Gap Value</th>
                    <th className="py-3 px-3 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 font-medium text-zinc-800 dark:text-zinc-200">
                  {items.map((it, idx) => {
                    const isOverdue = it.date_status === "OVERDUE" && it.gap_qty > 0;
                    const isFullyReady = it.gap_qty === 0;

                    return (
                      <tr
                        key={it.wo_id}
                        onClick={() => setSelectedItem(it)}
                        className={`hover:bg-zinc-50 dark:hover:bg-zinc-800/50 cursor-pointer transition-colors ${
                          isOverdue
                            ? "bg-rose-50/30 dark:bg-rose-950/10"
                            : isFullyReady
                            ? "bg-emerald-50/20 dark:bg-emerald-950/10"
                            : ""
                        }`}
                      >
                        {/* Rank */}
                        <td className="py-3 px-3 text-center font-bold text-zinc-400">
                          {idx + 1}
                        </td>

                        {/* WO ID */}
                        <td className="py-3 px-3 font-mono font-bold text-indigo-600 dark:text-indigo-400 whitespace-nowrap">
                          {it.wo_number}
                          {it.heat_number && (
                            <div className="text-[10px] text-zinc-400 font-sans font-normal">
                              Heat: {it.heat_number}
                            </div>
                          )}
                        </td>

                        {/* Customer & PO */}
                        <td className="py-3 px-3">
                          <div className="font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                            <span className="truncate max-w-[140px]">{it.customer_name}</span>
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 font-bold">
                              {it.customer_code}
                            </span>
                          </div>
                          <div className="text-[11px] text-zinc-500 font-mono">
                            PO: {it.customer_po}
                          </div>
                        </td>

                        {/* Customer Part No */}
                        <td className="py-3 px-3">
                          <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 bg-amber-50 dark:bg-amber-950/40 px-1.5 py-0.5 rounded text-[11px] border border-amber-200/60 dark:border-amber-800/60">
                            {it.customer_part_number || "—"}
                          </span>
                        </td>

                        {/* Internal Part ID */}
                        <td className="py-3 px-3">
                          <div className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                            {it.part_number}
                          </div>
                          {it.grade && (
                            <div className="text-[10px] text-zinc-400">
                              {it.grade}
                            </div>
                          )}
                        </td>

                        {/* Commitment Date */}
                        <td className="py-3 px-3 text-center whitespace-nowrap">
                          <div className="font-semibold text-zinc-900 dark:text-zinc-100">
                            {it.effective_commitment_date || "Not Set"}
                          </div>
                          <div className="mt-0.5 flex items-center justify-center gap-1">
                            {it.date_status === "OVERDUE" && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-extrabold bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-400">
                                OVERDUE
                              </span>
                            )}
                            {it.date_status === "TODAY" && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-extrabold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                                TODAY
                              </span>
                            )}
                            {it.date_status === "TOMORROW" && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-extrabold bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                                TOMORROW
                              </span>
                            )}
                            {it.commitment_date_revision_count > 0 && (
                              <span className="px-1 py-0.2 rounded text-[9px] font-bold bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400" title={`Rescheduled ${it.commitment_date_revision_count} time(s)`}>
                                Rev {it.commitment_date_revision_count}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Planned Qty */}
                        <td className="py-3 px-3 text-right font-bold text-zinc-700 dark:text-zinc-300">
                          {it.planned_qty.toLocaleString()}
                        </td>

                        {/* BSR Actual Qty */}
                        <td className="py-3 px-3 text-right font-black bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300">
                          {it.bsr_actual_qty.toLocaleString()}
                        </td>

                        {/* Dispatched */}
                        <td className="py-3 px-3 text-right text-zinc-500 font-semibold">
                          {it.dispatched_qty > 0 ? it.dispatched_qty.toLocaleString() : "0"}
                        </td>

                        {/* Plan vs Actual Gap Deficit */}
                        <td className="py-3 px-3 text-right bg-rose-50/50 dark:bg-rose-950/20 whitespace-nowrap">
                          {it.gap_qty > 0 ? (
                            <div className="font-black text-rose-600 dark:text-rose-400 text-sm">
                              -{it.gap_qty.toLocaleString()}
                            </div>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 dark:text-emerald-400">
                              <CheckCircle2 className="h-3 w-3" />
                              100% Ready
                            </span>
                          )}
                          {it.part_bsr_stock > 0 && it.gap_qty > 0 && (
                            <div className="text-[10px] text-indigo-600 dark:text-indigo-400 font-semibold" title="Free buffer stock available in BSR for this part number">
                              BSR Stock: {it.part_bsr_stock} pcs
                            </div>
                          )}
                        </td>

                        {/* Current Floor Location */}
                        <td className="py-3 px-3 text-center whitespace-nowrap">
                          {it.is_at_vendor ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-black bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                              Vendor: {it.vendor_name || "Outside"}
                            </span>
                          ) : it.bsr_actual_qty >= it.planned_qty ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                              BSR / Packing
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200">
                              Stage {it.current_stage}
                            </span>
                          )}
                        </td>

                        {/* Unit Rate */}
                        <td className="py-3 px-3 text-right font-mono text-zinc-600 dark:text-zinc-400">
                          ₹{it.unit_price > 0 ? it.unit_price.toFixed(2) : "0.00"}
                        </td>

                        {/* Planned Value */}
                        <td className="py-3 px-3 text-right font-bold text-zinc-900 dark:text-zinc-100 whitespace-nowrap">
                          ₹{it.planned_value.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                        </td>

                        {/* Gap Exposure Value */}
                        <td className="py-3 px-3 text-right font-black whitespace-nowrap text-rose-600 dark:text-rose-400">
                          {it.gap_value > 0 ? `₹${it.gap_value.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : "₹0"}
                        </td>

                        {/* Status Badge */}
                        <td className="py-3 px-3 text-center whitespace-nowrap">
                          {it.fulfillment_status === "READY_IN_BSR" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                              Ready in BSR
                            </span>
                          )}
                          {it.fulfillment_status === "DISPATCHED" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                              Dispatched
                            </span>
                          )}
                          {it.fulfillment_status === "AT_VENDOR" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300">
                              At Vendor
                            </span>
                          )}
                          {it.fulfillment_status === "OVERDUE_DEFICIT" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300">
                              Overdue Deficit
                            </span>
                          )}
                          {it.fulfillment_status === "WIP_IN_HOUSE" && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                              Floor WIP
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Selected Order Detailed Drawer / Modal */}
        {selectedItem && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-150">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between border-b border-zinc-100 dark:border-zinc-800 pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300 uppercase">
                      Work Order Inspector
                    </span>
                    <span className="text-xs text-zinc-400 font-mono">ID: {selectedItem.wo_id.slice(0, 8)}...</span>
                  </div>
                  <h3 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-1 font-mono">
                    {selectedItem.wo_number}
                  </h3>
                  <p className="text-xs text-zinc-500">
                    Customer: <span className="font-bold text-zinc-800 dark:text-zinc-200">{selectedItem.customer_name} ({selectedItem.customer_code})</span> | PO: <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200">{selectedItem.customer_po}</span>
                  </p>
                </div>
                <button
                  onClick={() => setSelectedItem(null)}
                  className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Part & Pricing Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-zinc-50 dark:bg-zinc-800/50 p-3.5 rounded-xl text-xs">
                <div>
                  <span className="text-zinc-400 font-medium">Customer Part:</span>
                  <div className="font-mono font-bold text-zinc-900 dark:text-zinc-100 text-sm mt-0.5">
                    {selectedItem.customer_part_number || "—"}
                  </div>
                </div>
                <div>
                  <span className="text-zinc-400 font-medium">Internal Part ID:</span>
                  <div className="font-mono font-bold text-zinc-900 dark:text-zinc-100 text-sm mt-0.5">
                    {selectedItem.part_number}
                  </div>
                </div>
                <div>
                  <span className="text-zinc-400 font-medium">Unit Price:</span>
                  <div className="font-bold text-zinc-900 dark:text-zinc-100 text-sm mt-0.5">
                    ₹{selectedItem.unit_price.toFixed(2)}
                  </div>
                  <span className="text-[10px] text-zinc-400">Src: {selectedItem.price_source}</span>
                </div>
                <div>
                  <span className="text-zinc-400 font-medium">Total Order Value:</span>
                  <div className="font-black text-indigo-600 dark:text-indigo-400 text-sm mt-0.5">
                    ₹{selectedItem.planned_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </div>
                </div>
              </div>

              {/* Plan vs Actual Execution Progress */}
              <div className="space-y-2 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4">
                <div className="flex items-center justify-between text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  <span>Fulfillment Progress</span>
                  <span>{selectedItem.total_fulfilled_qty} / {selectedItem.planned_qty} pcs</span>
                </div>
                <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-3 rounded-full overflow-hidden flex">
                  <div
                    className="bg-emerald-500 h-full"
                    style={{ width: `${Math.min(100, (selectedItem.bsr_actual_qty / (selectedItem.planned_qty || 1)) * 100)}%` }}
                    title={`BSR Ready: ${selectedItem.bsr_actual_qty} pcs`}
                  />
                  <div
                    className="bg-blue-500 h-full"
                    style={{ width: `${Math.min(100, (selectedItem.dispatched_qty / (selectedItem.planned_qty || 1)) * 100)}%` }}
                    title={`Dispatched: ${selectedItem.dispatched_qty} pcs`}
                  />
                </div>
                <div className="flex items-center justify-between text-[11px] text-zinc-500 pt-1">
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 inline-block" />
                      Ready in BSR: <strong>{selectedItem.bsr_actual_qty}</strong>
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full bg-blue-500 inline-block" />
                      Dispatched: <strong>{selectedItem.dispatched_qty}</strong>
                    </span>
                  </div>
                  <span className="text-rose-600 font-bold">
                    Deficit: {selectedItem.gap_qty} pcs (₹{selectedItem.gap_value.toLocaleString("en-IN")})
                  </span>
                </div>
              </div>

              {/* Stage WIP Breakdown */}
              <div className="space-y-2">
                <h4 className="text-xs font-extrabold uppercase tracking-wider text-zinc-500">
                  Shop Floor Stage WIP Breakdown
                </h4>
                <div className="grid grid-cols-4 sm:grid-cols-7 gap-2 text-center text-xs">
                  {["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR"].map((stg) => {
                    const qty = selectedItem.stage_wip[stg] || 0;
                    const isCurrent = selectedItem.current_stage.toUpperCase() === stg;
                    return (
                      <div
                        key={stg}
                        className={`p-2.5 rounded-xl border ${
                          isCurrent
                            ? "border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/30 font-bold text-indigo-700 dark:text-indigo-300"
                            : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/30 dark:bg-zinc-800/30 text-zinc-700 dark:text-zinc-300"
                        }`}
                      >
                        <div className="text-[10px] text-zinc-400 uppercase font-semibold">{stg}</div>
                        <div className="text-sm font-black mt-0.5">{qty}</div>
                        {isCurrent && <div className="text-[9px] text-indigo-600 font-bold">Current</div>}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Outside Vendor Subcontracting Alert if applicable */}
              {selectedItem.is_at_vendor && (
                <div className="rounded-xl border border-purple-200 dark:border-purple-900 bg-purple-50/60 dark:bg-purple-950/30 p-3.5 text-xs text-purple-900 dark:text-purple-200 space-y-1">
                  <div className="font-bold flex items-center gap-1.5 text-purple-700 dark:text-purple-300">
                    <Truck className="h-4 w-4" />
                    <span>Material Currently Dispatched to Outside Vendor</span>
                  </div>
                  <p className="text-[11px] text-purple-800 dark:text-purple-300">
                    Vendor: <strong>{selectedItem.vendor_name}</strong> | Quantity: <strong>{selectedItem.vendor_qty} pcs</strong> | DC: <strong>{selectedItem.vendor_dc || "N/A"}</strong>
                  </p>
                  <p className="text-[10px] text-purple-600 dark:text-purple-400">
                    This material must be inwarded on the Vendor Tracking screen (/production/vendor) before proceeding to final inspection and packing.
                  </p>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-zinc-100 dark:border-zinc-800">
                <Link
                  href={`/production/entry?wo=${encodeURIComponent(selectedItem.wo_number)}`}
                  className="px-3.5 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 text-xs font-bold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center gap-1.5"
                >
                  <span>Open Production Entry</span>
                  <ExternalLink className="h-3.5 w-3.5" />
                </Link>
                {selectedItem.is_at_vendor && (
                  <Link
                    href="/production/vendor"
                    className="px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold flex items-center gap-1.5"
                  >
                    <span>Open Vendor Screen</span>
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                )}
                <button
                  type="button"
                  onClick={() => setSelectedItem(null)}
                  className="px-4 py-2 rounded-xl bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-xs font-bold"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
