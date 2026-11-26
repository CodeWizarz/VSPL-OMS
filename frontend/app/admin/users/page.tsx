"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Modal } from "@/app/components/ui/Modal";
import {
  getUsers,
  createUser,
  updateUser,
  resetUserPassword,
  setUserStatus,
  deleteUser,
  AdminUser,
  TemporaryPasswordResult,
  getLegacyRolePlan,
  convertLegacyRoles,
  LegacyRoleItem,
} from "@/lib/api";
import { UserPlus, KeyRound, Copy, CheckCircle2, AlertTriangle, ShieldAlert, Trash2, Loader2, Edit2 } from "lucide-react";

// Every stage (F1..FI, Packing, Dispatch) has a Supervisor and a Manager.
const SUPERVISED_STAGES = ["f1", "f2", "f3", "sp", "fi", "packing", "dispatch"];
// Roles offered for new accounts / edits. Each shop-floor stage has a Supervisor
// (records production + moves material at that stage) and a Manager (same, sees every
// stage, edits own-stage plan dates). Operator / Machine Operator / Packing / Dispatch are
// old roles: they keep working for existing accounts until converted, but aren't offered.
const ROLES = [
  "admin", "ceo", "production_manager", "planner", "qa", "quality", "store", "sales", "accounts",
  "engineering", "data_analyst", "scm",
  ...SUPERVISED_STAGES.flatMap((k) => [`${k}_supervisor`, `${k}_manager`]),
];
const LEGACY_ROLES = new Set(["operator", "machine_operator", "packing", "dispatch", "manufacturing"]);

const ALLOWED_EMAIL_DOMAINS = ["vijayspheroidals.com", "vijayspheroidals.onmicrosoft.com"];

function isValidCompanyEmail(emailStr: string): boolean {
  const cleaned = emailStr.trim().toLowerCase();
  const parts = cleaned.split("@");
  if (parts.length !== 2 || !parts[0] || !parts[1]) return false;
  return ALLOWED_EMAIL_DOMAINS.includes(parts[1]);
}

function roleLabel(role: string) {
  if (role === "scm") return "SCM (Supply Chain Manager)";
  return role
    .split("_")
    .map((w) => (["f1", "f2", "f3", "sp", "fi", "ceo", "qa"].includes(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [department, setDepartment] = useState("");
  const [role, setRole] = useState("planner");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  const [tempResult, setTempResult] = useState<TemporaryPasswordResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  const [userToDelete, setUserToDelete] = useState<AdminUser | null>(null);
  const [confirmEmail, setConfirmEmail] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteSuccess, setDeleteSuccess] = useState("");

  const [userToEdit, setUserToEdit] = useState<AdminUser | null>(null);
  const [editFullName, setEditFullName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editDepartment, setEditDepartment] = useState("");
  const [editRole, setEditRole] = useState("planner");
  const [editSecondaryRole, setEditSecondaryRole] = useState<string>("none");
  const [editError, setEditError] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  function openEditModal(u: AdminUser) {
    setUserToEdit(u);
    setEditFullName(u.full_name || "");
    setEditEmail(u.email || "");
    setEditDepartment(u.department || "");
    setEditRole(u.role ? u.role.toLowerCase() : "planner");
    setEditSecondaryRole(u.secondary_role ? u.secondary_role.toLowerCase() : "none");
    setEditError("");
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!userToEdit) return;
    const emailChanged = editEmail.trim().toLowerCase() !== (userToEdit.email || "").toLowerCase();
    if (emailChanged && !isValidCompanyEmail(editEmail)) {
      setEditError("Email must be a company address (" + ALLOWED_EMAIL_DOMAINS.join(" or ") + ").");
      return;
    }
    setSavingEdit(true);
    setEditError("");
    try {
      await updateUser(userToEdit.id, {
        full_name: editFullName.trim(),
        ...(emailChanged ? { email: editEmail.trim() } : {}),
        department: editDepartment.trim() || null,
        role: editRole,
        secondary_role: editSecondaryRole === "none" ? null : editSecondaryRole,
      });
      setUserToEdit(null);
      await loadUsers();
    } catch (err: any) {
      setEditError(err?.response?.data?.detail || "Failed to update user.");
    } finally {
      setSavingEdit(false);
    }
  }


  const [legacy, setLegacy] = useState<{ convertible: LegacyRoleItem[]; needs_admin: LegacyRoleItem[] } | null>(null);
  const [showConvert, setShowConvert] = useState(false);
  const [converting, setConverting] = useState(false);
  const [convertMsg, setConvertMsg] = useState("");

  async function handleConvert() {
    setConverting(true);
    try {
      const res = await convertLegacyRoles();
      setConvertMsg(
        `Converted ${res.converted.length} account(s).` +
          (res.needs_admin.length ? ` ${res.needs_admin.length} still need a role picked by hand.` : "")
      );
      setShowConvert(false);
      await loadUsers();
    } catch (err: any) {
      setConvertMsg(err?.response?.data?.detail || "Could not convert roles.");
    } finally {
      setConverting(false);
    }
  }

  async function loadUsers() {
    setLoading(true);
    setListError("");
    try {
      const data = await getUsers();
      setUsers(data);
      getLegacyRolePlan().then(setLegacy).catch(() => setLegacy(null));
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    const trimmedEmail = email.trim();
    if (!isValidCompanyEmail(trimmedEmail)) {
      setCreateError("Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed.");
      return;
    }
    setCreating(true);
    try {
      const result = await createUser({ full_name: fullName.trim(), email: trimmedEmail, department: department.trim() || undefined, role });
      setTempResult(result);
      setFullName("");
      setEmail("");
      setDepartment("");
      setRole("planner");
      await loadUsers();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create user.");
    } finally {
      setCreating(false);
    }
  }

  async function handleReset(user: AdminUser) {
    setRowBusy(user.id);
    try {
      const result = await resetUserPassword(user.id);
      setTempResult(result);
      await loadUsers();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not reset password.");
    } finally {
      setRowBusy(null);
    }
  }

  async function handleToggleActive(user: AdminUser) {
    setRowBusy(user.id);
    try {
      await setUserStatus(user.id, !user.is_active);
      await loadUsers();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not update status.");
    } finally {
      setRowBusy(null);
    }
  }

  async function handleDelete() {
    if (!userToDelete) return;
    if (confirmEmail.trim().toLowerCase() !== userToDelete.email.trim().toLowerCase()) {
      setDeleteError("Email confirmation does not match the user's email address.");
      return;
    }
    setDeleting(true);
    setDeleteError("");
    try {
      const res = await deleteUser(userToDelete.id);
      setDeleteSuccess(res.message || `User '${userToDelete.email}' was permanently deleted.`);
      setUserToDelete(null);
      setConfirmEmail("");
      await loadUsers();
    } catch (err: any) {
      setDeleteError(err?.response?.data?.detail || "Could not delete user.");
    } finally {
      setDeleting(false);
    }
  }

  function copyTempPassword() {
    if (!tempResult) return;
    navigator.clipboard.writeText(tempResult.temporary_password).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const isEmailTouched = email.trim().length > 0;
  const isEmailValid = isValidCompanyEmail(email);

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Administration
            </span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            User Accounts
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Create accounts, generate temporary passwords, and manage account status. Every
            new account must set its own permanent password on first login.
          </p>
        </div>

        {deleteSuccess && (
          <div className="flex items-center justify-between rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 px-4 py-3 text-xs text-emerald-800 dark:text-emerald-300 shadow-sm">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <span>{deleteSuccess}</span>
            </div>
            <button
              type="button"
              onClick={() => setDeleteSuccess("")}
              className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 hover:underline ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Create User */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-blue-500" /> Create User
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-3">
            <input
              required
              placeholder="Full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            />
            <div className="space-y-1">
              <input
                required
                type="email"
                placeholder="Company email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={`w-full rounded-lg border bg-transparent px-3 py-2 text-xs transition-colors ${
                  isEmailTouched && !isEmailValid
                    ? "border-rose-400 dark:border-rose-600 focus:outline-none focus:ring-1 focus:ring-rose-500"
                    : "border-zinc-200 dark:border-zinc-700"
                }`}
              />
              {isEmailTouched && !isEmailValid && (
                <p className="text-[10px] text-rose-600 dark:text-rose-400 font-medium">
                  Must be @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com
                </p>
              )}
            </div>
            <input
              placeholder="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{roleLabel(r)}</option>
              ))}
            </select>

            <div className="md:col-span-3 flex items-center gap-2 flex-wrap text-[11px] text-zinc-500 dark:text-zinc-400 self-center">
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Company email required:</span>
              <span className="inline-flex items-center rounded-md bg-blue-50 dark:bg-blue-950/40 px-2 py-0.5 text-[10px] font-mono text-blue-700 dark:text-blue-300 border border-blue-200/80 dark:border-blue-900">
                • @vijayspheroidals.com
              </span>
              <span className="inline-flex items-center rounded-md bg-blue-50 dark:bg-blue-950/40 px-2 py-0.5 text-[10px] font-mono text-blue-700 dark:text-blue-300 border border-blue-200/80 dark:border-blue-900">
                • @vijayspheroidals.onmicrosoft.com
              </span>
            </div>

            <button
              type="submit"
              disabled={creating || !fullName.trim() || !email.trim() || !isEmailValid}
              className="md:col-span-1 justify-self-end rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {creating ? "Creating..." : "Generate Temp Password & Create User"}
            </button>
          </form>
        </div>


        {/* One-time temp password result */}
        {tempResult && (
          <div className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 p-5 shadow-sm">
            <h3 className="text-sm font-bold text-emerald-800 dark:text-emerald-300 flex items-center gap-2">
              <KeyRound className="h-4 w-4" /> Temporary Password (shown once)
            </h3>
            <div className="mt-2 text-xs text-emerald-900 dark:text-emerald-200 space-y-1">
              <p><span className="font-semibold">Email:</span> {tempResult.user.email}</p>
              <p><span className="font-semibold">Department:</span> {tempResult.user.department || "-"}</p>
              <p><span className="font-semibold">Role:</span> {roleLabel(tempResult.user.role)}</p>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <code className="flex-1 rounded-lg bg-white dark:bg-zinc-900 border border-emerald-300 dark:border-emerald-800 px-3 py-2 text-xs font-mono text-emerald-900 dark:text-emerald-200">
                {tempResult.temporary_password}
              </code>
              <button
                type="button"
                onClick={copyTempPassword}
                className="flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-emerald-500 transition-colors"
              >
                {copied ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="mt-2 text-[10px] text-emerald-700 dark:text-emerald-400">
              This will not be shown again. Share it with the user through a secure channel; they
              will be required to set a permanent password on first login.
            </p>
            <button
              type="button"
              onClick={() => setTempResult(null)}
              className="mt-3 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Users list */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing Users</h3>
          </div>
          {legacy && legacy.convertible.length + legacy.needs_admin.length > 0 && (
            <div className="m-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-800 dark:text-amber-300">
              <span>
                <span className="font-bold">{legacy.convertible.length + legacy.needs_admin.length} account(s) use old roles</span> (Operator,
                Machine Operator, Packing, Dispatch, Manufacturing). Stage roles are now F1–FI, Packing and Dispatch Supervisor / Manager.
              </span>
              <button
                type="button"
                onClick={() => { setConvertMsg(""); setShowConvert(true); }}
                className="self-start rounded-lg bg-amber-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-amber-500"
              >
                Review &amp; convert
              </button>
            </div>
          )}
          {convertMsg && (
            <p className="mx-4 mt-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-xs font-semibold text-emerald-700 dark:text-emerald-400">{convertMsg}</p>
          )}
          {listError && (
            <div className="m-4 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{listError}</span>
            </div>
          )}
          {loading ? (
            <div className="p-4 text-xs text-zinc-500">Loading...</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Name</th>
                  <th className="text-left px-4 py-2 font-semibold">Email</th>
                  <th className="text-left px-4 py-2 font-semibold">Department</th>
                  <th className="text-left px-4 py-2 font-semibold">Role</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-left px-4 py-2 font-semibold">Password</th>
                  <th className="text-right px-4 py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2">{u.full_name}</td>
                    <td className="px-4 py-2">{u.email}</td>
                    <td className="px-4 py-2">{u.department || "-"}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold text-zinc-900 dark:text-zinc-100">{roleLabel(u.role)}</span>
                        {u.secondary_role && (
                          <span className="inline-flex items-center rounded-md bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 px-1.5 py-0.5 text-[10px] font-bold border border-purple-200 dark:border-purple-800">
                            + {roleLabel(u.secondary_role)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${u.is_active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400" : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {u.must_change_password && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-amber-100 dark:bg-amber-950/50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-700 dark:text-amber-400">
                          <ShieldAlert className="h-3 w-3" /> Force Change
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right space-x-2">
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => openEditModal(u)}
                        className="rounded-lg bg-indigo-50 dark:bg-indigo-950/40 px-2.5 py-1 text-[11px] font-semibold text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/60 disabled:opacity-50 transition-colors inline-flex items-center gap-1"
                      >
                        <Edit2 className="h-3 w-3" />
                        <span>Edit</span>
                      </button>
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => handleReset(u)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                      >
                        Reset Password
                      </button>
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => handleToggleActive(u)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                      >
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => {
                          setUserToDelete(u);
                          setConfirmEmail("");
                          setDeleteError("");
                        }}
                        className="rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-100 dark:hover:bg-rose-900/60 disabled:opacity-50 transition-colors"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Delete User Confirmation Modal */}
        <Modal
          isOpen={!!userToDelete}
          onClose={() => {
            if (!deleting) {
              setUserToDelete(null);
              setConfirmEmail("");
              setDeleteError("");
            }
          }}
          title="Delete User Account"
          subtitle="Permanent account removal"
          maxWidth="md"
        >
          {userToDelete && (
            <div className="space-y-4">
              <div className="flex items-start gap-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 p-3.5 text-xs text-rose-900 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50">
                <AlertTriangle className="h-5 w-5 shrink-0 text-rose-600 dark:text-rose-400 mt-0.5" />
                <div>
                  <p className="font-bold text-rose-950 dark:text-rose-200">Permanent Deletion Warning</p>
                  <p className="mt-1 text-[11px] leading-relaxed">
                    You are about to permanently delete the account for <strong className="font-semibold">{userToDelete.full_name}</strong>. This action cannot be undone.
                  </p>
                  <p className="mt-1.5 text-[11px] text-rose-700 dark:text-rose-400 leading-relaxed">
                    <strong>Integrity Guard:</strong> If this user has recorded production, quality, dispatch, master, or audit activity, the system will block deletion to preserve historical integrity. Deactivation should be used instead.
                  </p>
                </div>
              </div>

              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/60 p-3.5 text-xs space-y-1.5 border border-zinc-200/70 dark:border-zinc-800">
                <div className="flex justify-between"><span className="text-zinc-500 dark:text-zinc-400">Name:</span> <span className="font-semibold text-zinc-900 dark:text-zinc-100">{userToDelete.full_name}</span></div>
                <div className="flex justify-between"><span className="text-zinc-500 dark:text-zinc-400">Email:</span> <span className="font-mono text-zinc-900 dark:text-zinc-100">{userToDelete.email}</span></div>
                <div className="flex justify-between"><span className="text-zinc-500 dark:text-zinc-400">Role:</span> <span className="font-medium text-zinc-900 dark:text-zinc-100">{roleLabel(userToDelete.role)}{userToDelete.secondary_role ? ` + ${roleLabel(userToDelete.secondary_role)}` : ""}</span></div>
                <div className="flex justify-between"><span className="text-zinc-500 dark:text-zinc-400">Department:</span> <span className="font-medium text-zinc-900 dark:text-zinc-100">{userToDelete.department || "-"}</span></div>
                <div className="flex justify-between"><span className="text-zinc-500 dark:text-zinc-400">Status:</span> <span className="font-medium text-zinc-900 dark:text-zinc-100">{userToDelete.is_active ? "Active" : "Inactive"}</span></div>
              </div>

              {deleteError && (
                <div className="flex items-start gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-[11px] font-medium text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{deleteError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
                  Type <span className="font-mono font-bold text-rose-600 dark:text-rose-400 select-all">{userToDelete.email}</span> to confirm:
                </label>
                <input
                  type="email"
                  value={confirmEmail}
                  onChange={(e) => setConfirmEmail(e.target.value)}
                  placeholder={userToDelete.email}
                  disabled={deleting}
                  autoFocus
                  className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-rose-500/50 focus:border-rose-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  disabled={deleting}
                  onClick={() => {
                    setUserToDelete(null);
                    setConfirmEmail("");
                    setDeleteError("");
                  }}
                  className="rounded-xl px-3.5 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={deleting || confirmEmail.trim().toLowerCase() !== userToDelete.email.trim().toLowerCase()}
                  onClick={handleDelete}
                  className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-rose-600 transition-colors flex items-center gap-1.5 shadow-sm"
                >
                  {deleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {deleting ? "Deleting..." : "Permanently Delete User"}
                </button>
              </div>
            </div>
          )}
        </Modal>

        {/* Edit User Modal */}
        <Modal
          isOpen={!!userToEdit}
          onClose={() => {
            if (!savingEdit) {
              setUserToEdit(null);
              setEditError("");
            }
          }}
          title={userToEdit ? `Edit User: ${userToEdit.email}` : "Edit User"}
        >
          {userToEdit && (
            <form onSubmit={handleSaveEdit} className="p-5 space-y-4 text-xs">
              {editError && (
                <div className="flex items-start gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 p-3 text-[11px] font-medium text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{editError}</span>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                  Full Name
                </label>
                <input
                  type="text"
                  value={editFullName}
                  onChange={(e) => setEditFullName(e.target.value)}
                  required
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                />
              </div>

                <div>
                  <label htmlFor="edit-email" className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                    Email (sign-in)
                  </label>
                  <input
                    id="edit-email"
                    type="email"
                    value={editEmail}
                    onChange={(e) => setEditEmail(e.target.value)}
                    required
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                  />
                  <p className="mt-1 text-[10px] text-zinc-500">Changing it signs them out; they sign in with the new email.</p>
                </div>

              <div>
                <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                  Department
                </label>
                <input
                  type="text"
                  value={editDepartment}
                  onChange={(e) => setEditDepartment(e.target.value)}
                  placeholder="e.g. Dispatch / PPC, Foundry, Quality"
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                    Primary Role
                  </label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value)}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                  >
                    {!ROLES.includes(editRole) && <option value={editRole}>{roleLabel(editRole)} (old role)</option>}
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {roleLabel(r)}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                    Secondary Role (Dual-Role)
                  </label>
                  <select
                    value={editSecondaryRole}
                    onChange={(e) => setEditSecondaryRole(e.target.value)}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                  >
                    <option value="none">None (Single Role)</option>
                    {ROLES.map((r) => (
                      <option key={`sec_${r}`} value={r}>
                        + {roleLabel(r)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  disabled={savingEdit}
                  onClick={() => {
                    setUserToEdit(null);
                    setEditError("");
                  }}
                  className="rounded-xl px-3.5 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingEdit}
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50 transition-colors flex items-center gap-1.5 shadow-sm"
                >
                  {savingEdit && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {savingEdit ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </form>
          )}
        </Modal>
      </div>
      <Modal isOpen={showConvert} onClose={() => setShowConvert(false)} title="Convert old roles" subtitle="Based on each person's department" maxWidth="2xl">
        {legacy && (
          <div className="space-y-4 text-xs">
            <div>
              <p className="font-bold text-zinc-900 dark:text-zinc-100">Will be converted ({legacy.convertible.length})</p>
              {legacy.convertible.length === 0 ? (
                <p className="mt-1 text-zinc-500">None.</p>
              ) : (
                <table className="mt-2 w-full">
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {legacy.convertible.map((u) => (
                      <tr key={u.id}>
                        <td className="py-1.5 pr-2 font-semibold">{u.full_name}</td>
                        <td className="py-1.5 pr-2 text-zinc-500">{u.department || "—"}</td>
                        <td className="py-1.5 text-right">
                          {roleLabel(u.current_role)} → <span className="font-bold text-emerald-600">{roleLabel(u.new_role || "")}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div>
              <p className="font-bold text-zinc-900 dark:text-zinc-100">Need a role picked by hand ({legacy.needs_admin.length})</p>
              <p className="text-zinc-500">Their department doesn&rsquo;t name a stage. They keep working on their old role; use Edit to pick a stage role.</p>
              {legacy.needs_admin.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-zinc-600 dark:text-zinc-400">
                  {legacy.needs_admin.map((u) => (
                    <li key={u.id}>
                      {u.full_name} ({u.email}) — {roleLabel(u.current_role)}, department &ldquo;{u.department || "none"}&rdquo;
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" onClick={() => setShowConvert(false)} className="rounded-lg border border-zinc-200 dark:border-zinc-700 px-4 py-2 font-semibold">
                Cancel
              </button>
              <button
                type="button"
                disabled={converting || legacy.convertible.length === 0}
                onClick={handleConvert}
                className="rounded-lg bg-amber-600 px-4 py-2 font-bold text-white hover:bg-amber-500 disabled:opacity-50"
              >
                {converting ? "Converting…" : `Convert ${legacy.convertible.length} account(s)`}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </AppShell>
  );
}
