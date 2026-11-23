// Stage-role workspaces: which screens a stage Supervisor / Manager (and Accounts) sees,
// their home page, and the stage their work queue opens on.
//
// Only the NEW roles get a narrowed menu here. Every existing role keeps exactly the
// menu it has today (AppShell's own `roles` rules). This is a UI convenience only --
// the backend enforces permissions and the stage lock (backend/app/core/departments.py).

export type StageKey = "F1" | "F2" | "F3" | "SP" | "FI" | "PACKING" | "DISPATCH";

export interface Workspace {
  key: string;
  label: string;
  home: string;
  hrefs: string[];
  stage?: string;
}

// Stage keys as the work-queue API returns them.
export const QUEUE_STAGES: { key: string; short: string; name: string }[] = [
  { key: "F1", short: "F1", name: "Foundry" },
  { key: "F2", short: "F2", name: "F2" },
  { key: "F3", short: "F3", name: "F3" },
  { key: "SP", short: "SP", name: "Subcontracting / Surface Prep" },
  { key: "FI", short: "FI", name: "Final Inspection" },
  { key: "PACKING", short: "Packing", name: "Packing" },
];

const STAGE_LABEL: Record<StageKey, string> = {
  F1: "F1", F2: "F2", F3: "F3", SP: "SP", FI: "FI", PACKING: "Packing", DISPATCH: "Dispatch",
};

// Supervisor: only their own stage's work.
const SUPERVISOR_HREFS: Record<StageKey, string[]> = {
  F1: ["/my-work", "/production/entry", "/production/move", "/production/tracking", "/training/work-instructions"],
  F2: ["/my-work", "/production/entry", "/production/move", "/production/tracking", "/training/work-instructions"],
  F3: ["/my-work", "/production/entry", "/production/move", "/production/tracking", "/training/work-instructions"],
  SP: ["/my-work", "/production/entry", "/production/move", "/production/vendor", "/production/tracking", "/training/work-instructions"],
  FI: ["/my-work", "/production/entry", "/production/move", "/production/tracking", "/training/work-instructions"],
  PACKING: ["/my-work", "/packing", "/bsr", "/production/entry", "/production/move", "/production/tracking", "/training/work-instructions"],
  DISPATCH: ["/dispatch", "/bsr", "/packing", "/production/tracking", "/training/work-instructions"],
};

// Manager: every stage F1 -> Dispatch, plus own-stage plan dates.
const MANAGER_HREFS = [
  "/dashboard", "/my-work", "/production/entry", "/production/move", "/production/vendor", "/quality/mrb",
  "/production/tracking", "/production/wip", "/production/history", "/packing", "/bsr", "/dispatch",
  "/planning/stage-plan", "/training/work-instructions",
];

export function stageRole(role?: string | null): { stage: StageKey; level: "supervisor" | "manager" } | null {
  const m = /^(f1|f2|f3|sp|fi|packing|dispatch)_(supervisor|manager)$/.exec(role || "");
  return m ? { stage: m[1].toUpperCase() as StageKey, level: m[2] as "supervisor" | "manager" } : null;
}

/** Workspace for a user, or null to keep the normal (existing) menu. */
export function resolveWorkspace(roles: (string | null | undefined)[]): Workspace | null {
  const list = roles.filter(Boolean) as string[];
  const stageRoles = list.map(stageRole).filter(Boolean) as { stage: StageKey; level: "supervisor" | "manager" }[];
  const others = list.filter((r) => !stageRole(r));
  if (stageRoles.length > 0 && others.length === 0) {
    const sr = stageRoles.find((s) => s.level === "manager") || stageRoles[0];
    const home = sr.stage === "DISPATCH" ? "/dispatch" : "/my-work";
    return {
      key: `${sr.stage}_${sr.level}`,
      label: `${STAGE_LABEL[sr.stage]} ${sr.level === "manager" ? "Manager" : "Supervisor"}`,
      home,
      hrefs: sr.level === "manager" ? MANAGER_HREFS : SUPERVISOR_HREFS[sr.stage],
      stage: sr.stage === "DISPATCH" ? undefined : sr.stage,
    };
  }
  if (list.length === 1 && list[0] === "accounts") {
    return {
      key: "ACCOUNTS",
      label: "Accounts",
      home: "/dispatch",
      hrefs: ["/dispatch", "/reports/sales-ops", "/reports", "/dashboard"],
    };
  }
  return null;
}

/** Queue stage a stage SUPERVISOR is limited to, else null. */
export function supervisorStage(roles: (string | null | undefined)[]): string | null {
  const ws = resolveWorkspace(roles);
  return ws && ws.key.endsWith("_supervisor") ? ws.stage ?? null : null;
}
