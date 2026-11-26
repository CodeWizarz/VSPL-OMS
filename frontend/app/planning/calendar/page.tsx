"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { deletePlanCalendarDay, getPlanCalendar, planningErrorText, PlanCalendarDay, setPlanCalendarDay } from "@/lib/api";

// PPC: the plant's working calendar. Weekly off days come from the server; holidays and worked
// off-days are exceptions. Dates on non-working days only raise a warning when planning.

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const inputCls = "w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100";

export default function PlanCalendarPage() {
  const [month, setMonth] = useState(() => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), 1); });
  const [off, setOff] = useState<number[]>([6]);
  const [days, setDays] = useState<Record<string, PlanCalendarDay>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const end = new Date(month.getFullYear(), month.getMonth() + 1, 0);
      const r = await getPlanCalendar(iso(month), iso(end));
      setOff(r.weekly_off);
      setDays(Object.fromEntries(r.days.map((d) => [d.day, d])));
    } catch (e: any) {
      setError(planningErrorText(e, "Could not load the calendar."));
    } finally {
      setLoading(false);
    }
  }, [month]);
  useEffect(() => { load(); }, [load]);

  const cells = useMemo(() => {
    const first = (month.getDay() + 6) % 7; // Monday = 0
    const count = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const out: (string | null)[] = Array(first).fill(null);
    for (let i = 1; i <= count; i++) out.push(iso(new Date(month.getFullYear(), month.getMonth(), i)));
    while (out.length % 7) out.push(null);
    return out;
  }, [month]);

  const pick = (d: string) => { setSel(d); setNote(days[d]?.note || ""); };
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); await load(); setSel(null); } catch (e: any) { setError(planningErrorText(e, "Could not save.")); } finally { setBusy(false); }
  };
  const weekdayOff = (d: string) => off.includes((new Date(d + "T00:00:00").getDay() + 6) % 7);

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-4 p-4">
        <div>
          <h1 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-100">Working calendar</h1>
          <p className="text-xs text-zinc-500">Weekly off: {off.length ? off.map((i) => DOW[i]).join(", ") : "none"}. Mark holidays, or off-days the plant works. Planning warns when a gate date falls on a non-working day.</p>
        </div>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 dark:bg-rose-950/30 px-3 py-2 text-xs text-rose-800 dark:text-rose-300">{error}</div>}
        <div className="flex items-center justify-between">
          <button type="button" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} className="rounded-xl p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800"><ChevronLeft className="h-4 w-4" /></button>
          <div className="text-sm font-extrabold text-zinc-800 dark:text-zinc-200">{month.toLocaleString("en-GB", { month: "long", year: "numeric" })} {loading && <Loader2 className="inline h-3.5 w-3.5 animate-spin" />}</div>
          <button type="button" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} className="rounded-xl p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800"><ChevronRight className="h-4 w-4" /></button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-extrabold uppercase text-zinc-500">{DOW.map((d) => <div key={d}>{d}</div>)}</div>
        <div className="grid grid-cols-7 gap-1">
          {cells.map((d, i) => {
            if (!d) return <div key={i} />;
            const ex = days[d];
            const nonWorking = ex ? ex.kind === "HOLIDAY" : weekdayOff(d);
            const cls = ex?.kind === "HOLIDAY" ? "bg-rose-100 dark:bg-rose-950/40 border-rose-300 dark:border-rose-800 text-rose-800 dark:text-rose-300"
              : ex?.kind === "WORKING" ? "bg-emerald-100 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300"
              : nonWorking ? "bg-zinc-200 dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700 text-zinc-500"
              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200";
            return (
              <button key={d} type="button" onClick={() => pick(d)} title={ex?.note || ""}
                className={`h-16 rounded-xl border p-1.5 text-left text-xs font-bold ${cls} ${sel === d ? "ring-2 ring-orange-500" : ""}`}>
                <div>{Number(d.slice(8))}</div>
                <div className="text-[9px] font-semibold leading-tight truncate">{ex ? (ex.kind === "HOLIDAY" ? "Holiday" : "Working") : nonWorking ? "Off" : ""}{ex?.note ? ` · ${ex.note}` : ""}</div>
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-3 text-[11px] text-zinc-500">
          <span><span className="inline-block h-2.5 w-2.5 rounded bg-zinc-300 dark:bg-zinc-700" /> Weekly off</span>
          <span><span className="inline-block h-2.5 w-2.5 rounded bg-rose-300" /> Holiday</span>
          <span><span className="inline-block h-2.5 w-2.5 rounded bg-emerald-300" /> Worked off-day</span>
        </div>
        {sel && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-3">
            <h2 className="text-sm font-extrabold text-zinc-800 dark:text-zinc-200">{new Date(sel + "T00:00:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</h2>
            <div>
              <label htmlFor="cal-note" className="text-[11px] font-extrabold uppercase text-zinc-500">Note (optional)</label>
              <input id="cal-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} className={inputCls} placeholder="e.g. Diwali" />
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => act(() => setPlanCalendarDay(sel, "HOLIDAY", note))} className="rounded-xl bg-rose-600 hover:bg-rose-500 disabled:opacity-60 px-3 py-2 text-xs font-bold text-white">Mark as holiday</button>
              <button type="button" disabled={busy} onClick={() => act(() => setPlanCalendarDay(sel, "WORKING", note))} className="rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 px-3 py-2 text-xs font-bold text-white">Mark as working day</button>
              {days[sel] && <button type="button" disabled={busy} onClick={() => act(() => deletePlanCalendarDay(sel))} className="rounded-xl border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300">Remove exception</button>}
              <button type="button" onClick={() => setSel(null)} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-500">Close</button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
