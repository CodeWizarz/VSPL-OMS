"use client";
import React, { useEffect, useState } from "react";
import { getPlanInfo, PlanGate, PlanInfo, PlanStatus } from "@/lib/api";

/** "26 Nov" (or "—"). Dates arrive as ISO yyyy-mm-dd. */
export function fmtDay(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

export function fmtDayYear(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export const STATUS_LABEL: Record<PlanStatus, string> = {
  DELAYED: "Delayed",
  AT_RISK: "At risk",
  NO_PLAN: "No plan",
  ON_TRACK: "On track",
  COMPLETE: "Complete",
};

const STATUS_CHIP: Record<PlanStatus, string> = {
  DELAYED: "bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800",
  AT_RISK: "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800",
  NO_PLAN: "bg-zinc-100 text-zinc-600 border-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700",
  ON_TRACK: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800",
  COMPLETE: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800",
};

export function PlanStatusChip({ status, text, compact }: { status?: PlanStatus; text?: string; compact?: boolean }) {
  if (!status) return null;
  return (
    <span
      title={text}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wide whitespace-nowrap ${STATUS_CHIP[status]}`}
    >
      {compact || !text || status === "ON_TRACK" || status === "COMPLETE" ? STATUS_LABEL[status] : text}
    </span>
  );
}

export type GateTone = "done" | "prog" | "late" | "risk" | "plan" | "none";

export function gateTone(g: PlanGate): GateTone {
  if (!g.planned_end) return "none";
  if (g.state === "DONE") return "done";
  if (g.flag === "LATE") return "late";
  if (g.flag === "DUE_TODAY" || g.flag === "DUE_SOON" || g.flag === "START_MISSED") return "risk";
  if (g.state === "IN_PROGRESS") return "prog";
  return "plan";
}

export const TONE_CELL: Record<GateTone, string> = {
  done: "bg-emerald-100 text-emerald-800 border-emerald-400 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-700",
  prog: "bg-blue-100 text-blue-800 border-blue-400 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-700",
  late: "bg-rose-100 text-rose-800 border-rose-500 font-extrabold dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-600",
  risk: "bg-amber-100 text-amber-800 border-amber-400 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-700",
  plan: "bg-white text-zinc-700 border-zinc-300 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-700",
  none: "bg-transparent text-zinc-400 border-dashed border-zinc-300 dark:border-zinc-700",
};

export const TONE_LABEL: Record<GateTone, string> = {
  done: "done",
  prog: "in progress",
  late: "late",
  risk: "due soon",
  plan: "planned",
  none: "no date",
};

export function GateCell({ gate }: { gate?: PlanGate | null }) {
  if (!gate) return <span className="text-zinc-300 dark:text-zinc-700">·</span>;
  const tone = gateTone(gate);
  const tip = `${gate.stage}: ${fmtDay(gate.planned_start)} to ${fmtDay(gate.planned_end)} · ${TONE_LABEL[tone]}${gate.flag === "LATE" ? ` +${gate.days_late}d` : ""}`;
  return (
    <span title={tip} className={`inline-block min-w-[58px] rounded-md border px-1.5 py-1 text-center text-[11px] font-semibold ${TONE_CELL[tone]}`}>
      {gate.planned_end ? fmtDay(gate.planned_end) : "no date"}
    </span>
  );
}

export function GateLegend() {
  const tones: GateTone[] = ["done", "prog", "plan", "risk", "late", "none"];
  return (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
      {tones.map((t) => (
        <span key={t} className="inline-flex items-center gap-1.5">
          <span className={`inline-block h-3 w-3 rounded border ${TONE_CELL[t]}`} />
          {TONE_LABEL[t]}
        </span>
      ))}
    </div>
  );
}

/** Dates are used as <input type="date"> values; the API wants yyyy-mm-dd or null. */
export function toNull(v: string): string | null {
  return v && v.trim() ? v : null;
}

// ---------------------------------------------------------------------------------------------
// Read-only banner for the shop floor (Production Entry, Move Parts, WO Tracking).
// Shows nothing unless setup planning is switched on.
// ---------------------------------------------------------------------------------------------
const BANNER_TONE: Record<PlanStatus, string> = {
  DELAYED: "border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40",
  AT_RISK: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
  NO_PLAN: "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900",
  ON_TRACK: "border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/30",
  COMPLETE: "border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/30",
};

function dueWords(days: number | null | undefined): string {
  if (days === null || days === undefined) return "";
  if (days < 0) return `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} overdue`;
  if (days === 0) return "due today";
  return `${days} day${days === 1 ? "" : "s"} left`;
}

export function PlanBanner({ woNumber, stage }: { woNumber?: string | null; stage?: string | null }) {
  const [info, setInfo] = useState<PlanInfo | null>(null);

  useEffect(() => {
    let alive = true;
    if (!woNumber) {
      setInfo(null);
      return;
    }
    getPlanInfo(woNumber, stage || undefined)
      .then((i) => {
        if (alive) setInfo(i);
      })
      .catch(() => {
        if (alive) setInfo(null);
      });
    return () => {
      alive = false;
    };
  }, [woNumber, stage]);

  if (!info || !info.enabled || !info.plan_status) return null;
  const g = info.this_gate;
  const n = info.next_gate;
  return (
    <div className={`rounded-xl border p-3 text-xs space-y-1.5 ${BANNER_TONE[info.plan_status]}`} role="status" aria-label="Production plan for this work order">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-[10px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Plan</span>
        <PlanStatusChip status={info.plan_status} text={info.plan_text} />
        {info.setup_number && (
          <span className="text-zinc-700 dark:text-zinc-300">
            Setup <strong className="font-mono">{info.setup_number}</strong>
          </span>
        )}
        {!!info.heat_numbers?.length && (
          <span className="text-zinc-700 dark:text-zinc-300">
            Heat <strong className="font-mono">{info.heat_numbers.join(", ")}</strong>
          </span>
        )}
        {g && (
          <span className="text-zinc-700 dark:text-zinc-300">
            {g.stage} due <strong>{fmtDay(g.planned_end)}</strong>
            {g.days_to_end !== null && g.state !== "DONE" ? ` (${dueWords(g.days_to_end)})` : ""}
            {g.state === "DONE" ? " (done)" : ""}
          </span>
        )}
        {n && n.planned_end && (
          <span className="text-zinc-500 dark:text-zinc-400">
            next {n.stage} {fmtDay(n.planned_end)}
          </span>
        )}
        <span className="text-zinc-700 dark:text-zinc-300">
          Commitment <strong>{fmtDay(info.commitment_date)}</strong>
          {info.days_to_commitment !== null && info.days_to_commitment !== undefined ? ` (${dueWords(info.days_to_commitment)})` : ""}
        </span>
      </div>
      {(info.plan_status === "DELAYED" || info.plan_status === "AT_RISK") && info.plan_text && (
        <div className="font-semibold text-zinc-800 dark:text-zinc-200">{info.plan_text}</div>
      )}
    </div>
  );
}
