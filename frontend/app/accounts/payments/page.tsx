"use client";
import React, { useEffect, useMemo, useState } from "react";
import { RefreshCw, AlertTriangle, Wallet, IndianRupee } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, BadgeVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { getInvoices, recordPayment, setInvoiceAmount, InvoiceSummary } from "@/lib/api";

// Accounts: invoice values and payments received (PO-to-receipt cycle). The backend
// enforces the rules (payments can't exceed the invoice, no future dates, audit log).

const STATUS: Record<InvoiceSummary["status"], [string, BadgeVariant]> = {
  NOT_VALUED: ["Value pending", "purple"],
  UNPAID: ["Unpaid", "red"],
  PARTIAL: ["Part paid", "amber"],
  PAID: ["Paid", "green"],
};
const FILTERS = [
  ["", "All"],
  ["UNPAID", "Unpaid"],
  ["PARTIAL", "Part paid"],
  ["NOT_VALUED", "Value pending"],
  ["PAID", "Paid"],
] as const;

const inr = (n?: number | null) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const inputCls =
  "mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs focus:outline-none focus:border-blue-500";

export default function PaymentsPage() {
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [payFor, setPayFor] = useState<InvoiceSummary | null>(null);
  const [amount, setAmount] = useState("");
  const [received, setReceived] = useState(today());
  const [mode, setMode] = useState("NEFT");
  const [reference, setReference] = useState("");
  const [valueFor, setValueFor] = useState<InvoiceSummary | null>(null);
  const [value, setValue] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      setInvoices(await getInvoices());
    } catch (err: any) {
      setError(err?.response?.status === 403 ? "You don't have access to invoices." : "Could not load invoices.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const shown = useMemo(() => (filter ? invoices.filter((i) => i.status === filter) : invoices), [invoices, filter]);
  const outstanding = invoices.reduce((s, i) => s + (i.outstanding || 0), 0);
  const received30 = invoices.reduce((s, i) => s + i.paid, 0);

  const openPay = (inv: InvoiceSummary) => {
    setPayFor(inv);
    setAmount(inv.outstanding ? String(inv.outstanding) : "");
    setReceived(today());
    setMode("NEFT");
    setReference("");
    setFormError("");
  };
  const openValue = (inv: InvoiceSummary) => {
    setValueFor(inv);
    setValue(inv.amount != null ? String(inv.amount) : "");
    setFormError("");
  };

  async function submitPayment(e: React.FormEvent) {
    e.preventDefault();
    if (!payFor) return;
    setSaving(true);
    setFormError("");
    try {
      await recordPayment({ invoice_number: payFor.invoice_number, amount, received_date: received, mode, reference: reference || undefined });
      setPayFor(null);
      await load();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setFormError(typeof d === "string" ? d : "Check the amount and date.");
    } finally {
      setSaving(false);
    }
  }

  async function submitValue(e: React.FormEvent) {
    e.preventDefault();
    if (!valueFor) return;
    setSaving(true);
    setFormError("");
    try {
      await setInvoiceAmount(valueFor.invoice_number, value);
      setValueFor(null);
      await load();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      setFormError(typeof d === "string" ? d : "Check the amount.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">Accounts</span>
              <span className="text-xs text-zinc-400">PO-to-receipt</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">Invoices &amp; Payments</h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">Record money received against dispatched invoices.</p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 self-start rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold shadow-sm disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            ["Invoices", String(invoices.length)],
            ["Received", inr(received30)],
            ["Outstanding", inr(outstanding)],
          ].map(([label, v]) => (
            <div key={label} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm border-t-4 border-t-indigo-500">
              <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</p>
              <p className="mt-2 text-xl font-bold">{loading && invoices.length === 0 ? "…" : v}</p>
            </div>
          ))}
        </div>

        <div role="tablist" aria-label="Filter invoices" className="flex flex-wrap gap-2">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              onClick={() => setFilter(key)}
              className={`rounded-xl border px-3 py-1.5 text-xs font-bold ${
                filter === key ? "border-indigo-600 bg-indigo-600 text-white" : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs font-semibold text-rose-600">
            <AlertTriangle className="h-4 w-4" /> {error}
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-x-auto">
          {loading && invoices.length === 0 ? (
            <p className="p-10 text-center text-xs text-zinc-500">Loading…</p>
          ) : shown.length === 0 ? (
            <div className="p-10 text-center">
              <Wallet className="mx-auto h-8 w-8 text-zinc-300" />
              <p className="mt-3 text-sm font-bold text-zinc-700 dark:text-zinc-300">{error ? "Invoices unavailable" : "No invoices here"}</p>
            </div>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-950/60 text-[11px] font-bold uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5">Invoice</th>
                  <th className="px-4 py-2.5">Customer / PO</th>
                  <th className="px-4 py-2.5 text-right">Qty</th>
                  <th className="px-4 py-2.5 text-right">Value</th>
                  <th className="px-4 py-2.5 text-right">Received</th>
                  <th className="px-4 py-2.5 text-right">Outstanding</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {shown.map((i) => (
                  <tr key={i.invoice_number}>
                    <td className="px-4 py-3">
                      <p className="font-bold">{i.invoice_number}</p>
                      <p className="text-[11px] text-zinc-500">
                        {i.days_since_dispatch != null ? `${i.days_since_dispatch} days since dispatch` : ""}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-semibold">{i.customer_name}</p>
                      <p className="text-[11px] text-zinc-500">{i.customer_pos.join(", ")}</p>
                    </td>
                    <td className="px-4 py-3 text-right">{i.dispatched_qty.toLocaleString("en-IN")}</td>
                    <td className="px-4 py-3 text-right">{inr(i.amount)}</td>
                    <td className="px-4 py-3 text-right">{inr(i.paid)}</td>
                    <td className="px-4 py-3 text-right font-bold">{inr(i.outstanding)}</td>
                    <td className="px-4 py-3">
                      <Badge variant={STATUS[i.status][1]} size="sm">{STATUS[i.status][0]}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1.5">
                        <button type="button" onClick={() => openValue(i)} className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1.5 text-[11px] font-semibold">
                          {i.amount == null ? "Set value" : "Edit value"}
                        </button>
                        {i.status !== "PAID" && (
                          <button type="button" onClick={() => openPay(i)} className="flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[11px] font-bold text-white hover:bg-indigo-500">
                            <IndianRupee className="h-3.5 w-3.5" /> Record payment
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <Modal isOpen={payFor !== null} onClose={() => setPayFor(null)} title="Record Payment" subtitle={payFor?.invoice_number} maxWidth="md">
        <form onSubmit={submitPayment} className="space-y-4">
          <p className="text-xs text-zinc-500">
            Value {inr(payFor?.amount)} · received so far {inr(payFor?.paid)} · outstanding {inr(payFor?.outstanding)}
          </p>
          <div>
            <label htmlFor="pay-amount" className="text-xs font-bold">Amount received (₹) *</label>
            <input id="pay-amount" type="number" step="0.01" min="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="pay-date" className="text-xs font-bold">Received on *</label>
              <input id="pay-date" type="date" required max={today()} value={received} onChange={(e) => setReceived(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label htmlFor="pay-mode" className="text-xs font-bold">Mode</label>
              <select id="pay-mode" value={mode} onChange={(e) => setMode(e.target.value)} className={inputCls}>
                {["NEFT", "RTGS", "IMPS", "Cheque", "UPI", "Cash", "Other"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="pay-ref" className="text-xs font-bold">Reference (UTR / cheque no.)</label>
            <input id="pay-ref" value={reference} onChange={(e) => setReference(e.target.value)} className={inputCls} />
          </div>
          {formError && <p className="rounded-lg bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-xs font-semibold text-rose-600">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setPayFor(null)} className="rounded-xl border border-zinc-200 dark:border-zinc-700 px-4 py-2 text-xs font-semibold">Cancel</button>
            <button type="submit" disabled={saving} className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-60">
              {saving ? "Saving…" : "Record Payment"}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={valueFor !== null} onClose={() => setValueFor(null)} title="Invoice Value" subtitle={valueFor?.invoice_number} maxWidth="sm">
        <form onSubmit={submitValue} className="space-y-4">
          <div>
            <label htmlFor="inv-value" className="text-xs font-bold">Invoice value (₹) *</label>
            <input id="inv-value" type="number" step="0.01" min="0" required value={value} onChange={(e) => setValue(e.target.value)} className={inputCls} />
            <p className="mt-1 text-[11px] text-zinc-500">Cannot be less than the amount already received.</p>
          </div>
          {formError && <p className="rounded-lg bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-xs font-semibold text-rose-600">{formError}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setValueFor(null)} className="rounded-xl border border-zinc-200 dark:border-zinc-700 px-4 py-2 text-xs font-semibold">Cancel</button>
            <button type="submit" disabled={saving} className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-60">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </Modal>
    </AppShell>
  );
}
