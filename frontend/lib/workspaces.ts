// Department workspaces: which screens each department sees in the sidebar, which page
// is their home, and which shop-floor stage their work queue opens on.
//
// This is a UI convenience ONLY. It narrows what the sidebar shows so each person sees
// the screens relevant to their job; it never grants access. Every endpoint still
// enforces its own role check on the backend (see backend/app/core/roles.py), and a
// hidden page is still reachable by URL -- the backend decides what it may do.
//
// A user's workspace comes from the free-text `department` on their account (set on the
// Users screen), falling back to their role when the department is blank or unknown.

export type WorkspaceKey =
  | "PPC"
  | "F1"
  | "F2"
  | "F3"
  | "SP"
  | "FI"
  | "PACKING"
  | "QUALITY"
  | "SALES"
  | "ACCOUNTS";

export interface Workspace {
  key: WorkspaceKey;
  label: string;
  home: string;
  /** Sidebar hrefs this department sees. */
  hrefs: string[];
  /** Sidebar label overrides, e.g. QA sees Rejection Tracking as "MRB Update". */
  labels?: Record<string, string>;
  /** WIP-matrix stage key the My Work Queue opens on. */
  stage?: string;
}

// Stage keys exactly as the WIP matrix returns them (STANDARD_STAGES in
// backend/app/services/work_order_service.py).
export const QUEUE_STAGES: { key: string; short: string; name: string }[] = [
  { key: "F1", short: "F1", name: "Foundry" },
  { key: "F2", short: "F2", name: "Machining (F2)" },
  { key: "F3", short: "F3", name: "Machining (F3)" },
  { key: "SP", short: "SP", name: "Subcontracting" },
  { key: "FI", short: "FI", name: "Final Inspection" },
  { key: "PACKING / BSR", short: "Packing", name: "Packing / BSR" },
];

const SHOP_FLOOR_HREFS = [
  "/my-work",
  "/production/entry",
  "/production/move",
  "/production/tracking",
  "/production/wip",
  "/production/history",
];

export const WORKSPACES: Record<WorkspaceKey, Workspace> = {
  PPC: {
    key: "PPC",
    label: "PPC / Planning",
    home: "/orders/list",
    hrefs: [
      "/dashboard",
      "/orders/intake",
      "/orders/list",
      "/orders/po-matching",
      "/planning/wo-release",
      "/planning/wo-edit",
      "/production/tracking",
      "/production/wip",
      "/my-work",
      "/masters/customers",
      "/masters/pos",
      "/masters/schedules",
    ],
  },
  F1: { key: "F1", label: "F1 Foundry", home: "/my-work", hrefs: SHOP_FLOOR_HREFS, stage: "F1" },
  F2: { key: "F2", label: "F2", home: "/my-work", hrefs: SHOP_FLOOR_HREFS, stage: "F2" },
  F3: { key: "F3", label: "F3", home: "/my-work", hrefs: SHOP_FLOOR_HREFS, stage: "F3" },
  SP: { key: "SP", label: "Subcontracting", home: "/my-work", hrefs: SHOP_FLOOR_HREFS, stage: "SP" },
  FI: { key: "FI", label: "Final Inspection", home: "/my-work", hrefs: SHOP_FLOOR_HREFS, stage: "FI" },
  PACKING: {
    key: "PACKING",
    label: "Packing / BSR",
    home: "/my-work",
    hrefs: ["/my-work", "/packing", "/bsr", "/production/entry", "/production/move", "/production/tracking"],
    stage: "PACKING / BSR",
  },
  QUALITY: {
    key: "QUALITY",
    label: "Quality",
    home: "/quality/nc",
    hrefs: ["/dashboard", "/quality/nc", "/production/tracking", "/production/wip", "/production/history"],
    labels: { "/quality/nc": "MRB Update" },
  },
  SALES: {
    key: "SALES",
    label: "Sales",
    home: "/sales/po-cycle",
    hrefs: ["/sales/po-cycle", "/orders/intake", "/orders/list", "/production/tracking", "/bsr", "/dispatch", "/dashboard"],
  },
  ACCOUNTS: {
    key: "ACCOUNTS",
    label: "Accounts",
    home: "/accounts/payments",
    hrefs: ["/accounts/payments", "/sales/po-cycle", "/dispatch", "/dashboard"],
  },
};

// Suggested department names for the Users screen. The field stays free text; these
// just make the values consistent so they resolve to the right workspace.
export const DEPARTMENT_SUGGESTIONS = [
  "PPC / Planning",
  "F1 Foundry",
  "F2",
  "F3",
  "Subcontracting (SP)",
  "FI Final Inspection",
  "Packing / BSR",
  "Quality",
  "Sales",
  "Accounts",
  "Stores",
  "Dispatch",
  "Production",
  "Management",
];

function fromDepartment(department?: string | null): WorkspaceKey | null {
  if (!department) return null;
  const d = department.toUpperCase();
  const words = d.split(/[^A-Z0-9]+/).filter(Boolean);
  const has = (w: string) => words.includes(w);
  if (has("F1") || d.includes("FOUNDRY")) return "F1";
  if (has("F2")) return "F2";
  if (has("F3")) return "F3";
  if (has("SP") || d.includes("SUBCONTRACT")) return "SP";
  if (has("FI") || d.includes("FINAL INSPECTION")) return "FI";
  if (d.includes("PACKING") || has("BSR")) return "PACKING";
  if (has("PPC") || d.includes("PLANNING")) return "PPC";
  if (d.includes("QUALITY") || has("QA") || has("MRB")) return "QUALITY";
  if (d.includes("SALES")) return "SALES";
  if (d.includes("ACCOUNT") || d.includes("FINANCE")) return "ACCOUNTS";
  return null;
}

const ROLE_FALLBACK: Record<string, WorkspaceKey> = {
  planner: "PPC",
  qa: "QUALITY",
  packing: "PACKING",
  sales: "SALES",
  accounts: "ACCOUNTS",
};

// Admin, CEO and data analyst always keep the full navigation, whatever their department.
const FULL_NAV_ROLES = new Set(["admin", "ceo", "data_analyst"]);

export function resolveWorkspace(role?: string | null, department?: string | null): Workspace | null {
  if (role && FULL_NAV_ROLES.has(role)) return null;
  const key = fromDepartment(department) ?? (role ? ROLE_FALLBACK[role] : undefined) ?? null;
  return key ? WORKSPACES[key] : null;
}
