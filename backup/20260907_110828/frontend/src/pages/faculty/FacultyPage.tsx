// Group 5 — Faculty page for HOD.
// Mirrors webapp/routes/faculty.py + templates/faculty/list.html.
// Sections are COLLAPSED BY DEFAULT, expanding on click.
// All errors/failures displayed in RED (.error-banner)
import { useState, useEffect } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  getFacultyPage, createAccount, toggleAccountStatus, resetStudentPassword, deleteAccount,
  saveRolePermissions, getUserPermissions, saveUserPermissions,
  type FacultyPageData, type UserAccount, type RolePermission, type UserPermission,
} from "../../api/faculty";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function FacultyPage({ user, onLoggedOut }: Props) {
  const [data, setData] = useState<FacultyPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Collapsible state — collapsed by default
  const [showHours, setShowHours] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showPermissions, setShowPermissions] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [revealedCreds, setRevealedCreds] = useState<{ username: string; password: string } | null>(null);

  // Profile Access Selector Modal State
  const [selectedAccount, setSelectedAccount] = useState<UserAccount | null>(null);
  const [userPerms, setUserPerms] = useState<UserPermission | null>(null);
  const [loadingUserPerms, setLoadingUserPerms] = useState(false);
  const [savingUserPerms, setSavingUserPerms] = useState(false);

  // Permanent Delete Modal State
  const [accountToDelete, setAccountToDelete] = useState<UserAccount | null>(null);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [deleteKeyInput, setDeleteKeyInput] = useState("");

  // Create form state
  const [formUsername, setFormUsername] = useState("");
  const [formFullName, setFormFullName] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState<"ADMIN" | "HOD" | "FACULTY">("FACULTY");

  // Permissions state
  const [facultyPerms, setFacultyPerms] = useState<RolePermission>({
    role: "FACULTY",
    can_view_student_phone: 1,
    can_edit_students: 0,
    can_delete_students: 0,
    can_view_audit_logs: 0,
    can_view_sms_logs: 0,
    can_manage_calendar: 1,
    can_manage_subjects: 1,
  });

  async function reload() {
    setLoading(true);
    setError(null);
    try {
      const d = await getFacultyPage();
      setData(d);
      if (d.permissions) {
        const fac = d.permissions.find(p => p.role === "FACULTY");
        if (fac) setFacultyPerms(fac);
      }
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load faculty page");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleOpenProfilePermissions(acc: UserAccount) {
    setSelectedAccount(acc);
    setLoadingUserPerms(true);
    setError(null);
    try {
      const res = await getUserPermissions(acc.username);
      setUserPerms(res.permissions);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load profile permissions");
    } finally {
      setLoadingUserPerms(false);
    }
  }

  async function handleToggleUserPermission(key: keyof UserPermission) {
    if (!userPerms || key === "username") return;
    const updated = { ...userPerms, [key]: userPerms[key] ? 0 : 1 };
    setUserPerms(updated);
  }

  async function handleSaveProfilePermissions() {
    if (!selectedAccount || !userPerms) return;
    setSavingUserPerms(true);
    setError(null);
    try {
      await saveUserPermissions(selectedAccount.username, userPerms);
      setNotice(`Access permissions saved for ${selectedAccount.full_name || selectedAccount.username}`);
      setSelectedAccount(null);
      setUserPerms(null);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to save user permissions");
    } finally {
      setSavingUserPerms(false);
    }
  }

  async function handleTogglePermission(key: keyof RolePermission) {
    if (key === "role") return;
    const newVal = facultyPerms[key] ? 0 : 1;
    const updated = { ...facultyPerms, [key]: newVal };
    setFacultyPerms(updated);
    try {
      await saveRolePermissions(updated);
      setNotice(`Faculty permission updated successfully`);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to save permission");
      setFacultyPerms(facultyPerms);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createAccount({
        username: formUsername,
        full_name: formFullName,
        password: formPassword,
        role: formRole,
      });
      setFormUsername(""); setFormFullName(""); setFormPassword("");
      setFormRole("FACULTY");
      setShowCreateForm(false);
      setNotice("Account created successfully");
      await reload();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to create account");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggle(account: UserAccount) {
    setError(null);
    try {
      await toggleAccountStatus(account.id);
      setNotice(`${account.username} ${account.active ? "deactivated" : "activated"}`);
      await reload();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to toggle status");
    }
  }

  async function handleResetPassword(account: UserAccount) {
    if (!window.confirm(`Reset password for ${account.username}? A new temporary password will be set.`)) return;
    setError(null);
    try {
      const res = await resetStudentPassword(account.id);
      setRevealedCreds({ username: res.username, password: res.password });
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to reset password");
    }
  }

  async function handleConfirmDeleteAccount() {
    if (!accountToDelete) return;
    setDeletingAccount(true);
    setError(null);
    try {
      await deleteAccount(accountToDelete.id);
      setNotice(`User account "${accountToDelete.username}" has been permanently deleted.`);
      // Immediately remove from data.accounts in React state so UI updates instantly
      setData((prev) => prev ? { ...prev, accounts: prev.accounts.filter(a => a.id !== accountToDelete.id) } : prev);
      setAccountToDelete(null);
      await reload();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to delete account");
    } finally {
      setDeletingAccount(false);
    }
  }

  if (loading) return (
    <AppShell user={user} activeNav="faculty" heading="Faculty" onLoggedOut={onLoggedOut}>
      <p className="empty-note">Loading…</p>
    </AppShell>
  );

  return (
    <AppShell user={user} activeNav="faculty" heading="Faculty" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      {/* ── Teaching hours (Collapsible, collapsed by default) ── */}
      <div className="collapsible" style={{ marginBottom: 14 }}>
        <div className="collapsible-trigger" onClick={() => setShowHours(!showHours)}>
          <span>
            <span style={{ marginRight: 8, fontSize: 12 }}>{showHours ? "▼" : "▶"}</span>
            FACULTY TEACHING HOURS
          </span>
          <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
            {showHours ? "Click to collapse" : "Click to expand"}
          </span>
        </div>
        {showHours && (
          <div className="collapsible-body">
            {data?.hours.length === 0 ? (
              <p className="subtitle-muted">No sessions recorded yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>Name</th><th>Username</th><th className="center">Hours</th></tr>
                  </thead>
                  <tbody>
                    {data?.hours.map((h) => (
                      <tr key={h.faculty_username}>
                        <td>{h.full_name || h.faculty_username}</td>
                        <td style={{ color: "var(--muted)", fontSize: 12 }}>{h.faculty_username}</td>
                        <td className="center">{h.total_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Faculty Permission Matrix Control Panel (Collapsible) ── */}
      <div className="collapsible" style={{ marginBottom: 18 }}>
        <div className="collapsible-trigger" onClick={() => setShowPermissions(!showPermissions)}>
          <span>
            <span style={{ marginRight: 8, fontSize: 12 }}>{showPermissions ? "▼" : "▶"}</span>
            🔑 FACULTY ACCESS CONTROL
          </span>
          <span style={{ fontSize: 12, color: "#38bdf8", fontWeight: 700 }}>
            {showPermissions ? "Click to collapse" : "Manage Faculty Access"}
          </span>
        </div>
        {showPermissions && (
          <div className="collapsible-body" style={{ padding: 20 }}>
            <p className="subtitle-muted" style={{ marginBottom: 16 }}>
              Configure what <strong>Faculty</strong> members are permitted to view and modify. ADMIN can manage this globally; an HOD can manage Faculty in that HOD's scope only. ADMIN permissions are protected.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_view_student_phone)}
                  onChange={() => handleTogglePermission("can_view_student_phone")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>📱 View Student Phone & Contact Info</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to see student phone numbers</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_edit_students)}
                  onChange={() => handleTogglePermission("can_edit_students")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>✏️ Edit Student Profiles & Records</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to edit student data</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_delete_students)}
                  onChange={() => handleTogglePermission("can_delete_students")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>🗑️ Delete Student Profiles</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to delete student accounts</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_view_audit_logs)}
                  onChange={() => handleTogglePermission("can_view_audit_logs")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>📜 View System Audit Logs</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to view administrative audit trails</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_view_sms_logs)}
                  onChange={() => handleTogglePermission("can_view_sms_logs")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>📲 Access SMS Logs & Gateway</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to trigger absentee SMS alerts</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_manage_calendar)}
                  onChange={() => handleTogglePermission("can_manage_calendar")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>📅 Academic Calendar & Timetables</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to upload timetables</span>
                </div>
              </label>

              <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", background: "rgba(56, 189, 248, 0.06)", padding: "12px 16px", borderRadius: 10, border: "1px solid rgba(56, 189, 248, 0.2)" }}>
                <input
                  type="checkbox"
                  checked={Boolean(facultyPerms.can_manage_subjects)}
                  onChange={() => handleTogglePermission("can_manage_subjects")}
                />
                <div>
                  <strong style={{ display: "block", fontSize: 13 }}>📚 Manage Subjects & Allocations</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>Permit Faculty to edit course subjects</span>
                </div>
              </label>
            </div>
          </div>
        )}
      </div>

      {/* ── Create Account (Collapsible, collapsed by default) ── */}
      <div className="section-head">
        <h2>Faculty & User Accounts</h2>
        <button className="btn" onClick={() => setShowCreateForm(!showCreateForm)}>
          {showCreateForm ? "✕ Cancel" : "+ Create Account"}
        </button>
      </div>

      {showCreateForm && (
        <div className="detail-box" style={{ background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 16, padding: 24, marginBottom: 20 }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 18, fontWeight: 800, color: "var(--text)" }}>➕ Create Faculty / User Account</h3>
          <form onSubmit={handleCreate}>
            <div className="form-grid" style={{ marginBottom: 16 }}>
              <div className="field">
                <label style={{ fontWeight: 700, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>Username *</label>
                <input type="text" className="input-field" value={formUsername} onChange={e => setFormUsername(e.target.value)} style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }} required />
              </div>
              <div className="field">
                <label style={{ fontWeight: 700, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>Full Name</label>
                <input type="text" className="input-field" value={formFullName} onChange={e => setFormFullName(e.target.value)} style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }} />
              </div>
              <div className="field">
                <label style={{ fontWeight: 700, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>Password *</label>
                <input type="password" className="input-field" value={formPassword} onChange={e => setFormPassword(e.target.value)} style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }} required />
              </div>
              <div className="field">
                <label style={{ fontWeight: 700, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>Role *</label>
                <select className="input-field" value={formRole} onChange={e => setFormRole(e.target.value as "ADMIN" | "HOD" | "FACULTY")} style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }}>
                  <option value="FACULTY">FACULTY</option>
            {user.role === "ADMIN" && <option value="HOD">HOD</option>}
            {user.role === "ADMIN" && <option value="ADMIN">ADMIN</option>}
                </select>
              </div>
            </div>
            <button type="submit" className="btn btn-primary" style={{ background: "linear-gradient(135deg, #0284c7, #2563eb)", color: "#ffffff", fontWeight: 700, padding: "10px 22px", borderRadius: 10, border: "none", boxShadow: "0 8px 20px rgba(56, 189, 248, 0.35)", cursor: "pointer" }} disabled={submitting}>
              {submitting ? "Creating Account…" : "💾 Save New Account"}
            </button>
          </form>
        </div>
      )}

      {/* ── Faculty Accounts List ── */}
      <div className="table-wrap" style={{ marginTop: 10 }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th><th>Full Name</th><th>Role</th>
              <th className="center">Active</th><th className="center">Access Options</th><th className="center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.accounts.map((acc) => (
              <tr key={acc.id}>
                <td>{acc.username}</td>
                <td>{acc.full_name || <span style={{ color: "var(--muted)" }}>—</span>}</td>
                <td>
                  <span className={`chip ${acc.role === "ADMIN" ? "chip-purple" : acc.role === "HOD" ? "chip-yellow" : "chip-muted"}`}>
                    {acc.role}
                  </span>
                </td>
                <td className="center">
                  <span className={`chip ${acc.active ? "chip-green" : "chip-red"}`}>
                    {acc.active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="center" style={{ whiteSpace: "nowrap" }}>
                  <button
                    className="btn btn-sm btn-primary"
                    style={{
                      background: "linear-gradient(135deg, #0284c7, #2563eb)",
                      border: "none",
                      color: "#fff",
                      fontWeight: 700,
                      fontSize: 12,
                      padding: "6px 12px",
                      borderRadius: 8,
                      whiteSpace: "nowrap",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4
                    }}
                    onClick={() => handleOpenProfilePermissions(acc)}
                  >
                    ⚙️ Edit Access
                  </button>
                </td>
                <td className="center" style={{ whiteSpace: "nowrap" }}>
                  {acc.role !== "HOD" && acc.role !== "ADMIN" && acc.username !== user.username && acc.username !== "admin" ? (
                    <>
                      <button className={`btn btn-sm ${acc.active ? "btn-outline" : "btn-green"}`}
                        onClick={() => handleToggle(acc)}>
                        {acc.active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        className="btn btn-sm btn-red"
                        style={{ marginLeft: 6, fontWeight: 700 }}
                        onClick={() => setAccountToDelete(acc)}
                        title="Permanently delete this user account"
                      >
                        🗑️ Delete
                      </button>
                    </>
                  ) : (
                    <span style={{ color: "var(--muted)", fontSize: 12 }}>—</span>
                  )}
                  {acc.role === "STUDENT" && acc.student_roll_no && (
                    <button className="btn btn-sm btn-warn" style={{ marginLeft: 6 }}
                      onClick={() => handleResetPassword(acc)}>
                      Reset PW
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.accounts.length === 0 && <p className="empty-note">No faculty accounts found.</p>}
      </div>

      {/* Profile Access Selection Modal */}
      {selectedAccount && (
        <div className="modal-overlay" onClick={() => setSelectedAccount(null)}>
          <div className="modal-box modal3dPopIn" style={{ maxWidth: 640, width: "94%", maxHeight: "90vh", overflowY: "auto", background: "var(--bg-card)", border: "1px solid var(--border)", boxShadow: "0 25px 60px rgba(0,0,0,0.25)" }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 20, color: "var(--text)", fontWeight: 800 }}>
                ⚙️ Access Control: {selectedAccount.full_name || selectedAccount.username}
              </h3>
              <button className="btn btn-sm btn-outline" onClick={() => setSelectedAccount(null)}>✕</button>
            </div>

            {/* 👤 Faculty Name Dropdown Selector */}
            <div style={{ marginBottom: 16, background: "rgba(56, 189, 248, 0.08)", padding: "14px 18px", borderRadius: 12, border: "1px solid var(--input-border)" }}>
              <label style={{ display: "block", fontSize: 12, fontWeight: 800, color: "var(--heading-accent)", marginBottom: 8, letterSpacing: "0.5px" }}>
                👤 SELECT FACULTY / USER NAME TO GIVE ACCESS:
              </label>
              <select
                value={selectedAccount.username}
                onChange={(e) => {
                  const target = data?.accounts.find(a => a.username === e.target.value);
                  if (target) handleOpenProfilePermissions(target);
                }}
                style={{
                  width: "100%",
                  padding: "10px 14px",
                  borderRadius: 8,
                  background: "var(--input-bg)",
                  color: "var(--text)",
                  border: "1px solid var(--input-border)",
                  fontWeight: 700,
                  fontSize: 14,
                  outline: "none",
                  cursor: "pointer",
                }}
              >
                {data?.accounts.map((acc) => (
                  <option key={acc.username} value={acc.username}>
                    {acc.full_name ? `${acc.full_name} (@${acc.username})` : `@${acc.username}`} — [{acc.role}]
                  </option>
                ))}
              </select>
            </div>

            {/* 🎯 Quick Select Faculty Buttons */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 18, alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                Quick Select Faculty:
              </span>
              {data?.accounts.map((acc) => (
                <button
                  key={acc.username}
                  type="button"
                  onClick={() => handleOpenProfilePermissions(acc)}
                  className={`btn btn-sm ${acc.username === selectedAccount.username ? "btn-primary" : "btn-outline"}`}
                  style={{
                    fontSize: 12,
                    padding: "4px 10px",
                    borderRadius: 6,
                    fontWeight: acc.username === selectedAccount.username ? 700 : 500,
                    background: acc.username === selectedAccount.username ? "linear-gradient(135deg, #0284c7, #2563eb)" : undefined,
                    color: acc.username === selectedAccount.username ? "#ffffff" : undefined,
                  }}
                >
                  {acc.full_name || acc.username} ({acc.role})
                </button>
              ))}
            </div>

            <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 18 }}>
              Check/uncheck permissions below to give specific access to <strong>{selectedAccount.full_name || selectedAccount.username}</strong> (@{selectedAccount.username}).
            </p>

            {loadingUserPerms ? (
              <p className="empty-note">Loading permissions…</p>
            ) : userPerms ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10, marginBottom: 24 }}>
                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_view_students ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_view_students ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_view_students)}
                    onChange={() => handleToggleUserPermission("can_view_students")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>👨‍🎓 View Student Profiles & Directory</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_edit_students ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_edit_students ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_edit_students)}
                    onChange={() => handleToggleUserPermission("can_edit_students")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>✏️ Edit Student Data & Information</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_delete_students ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_delete_students ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_delete_students)}
                    onChange={() => handleToggleUserPermission("can_delete_students")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>🗑️ Delete Student Records</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_manage_attendance ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_manage_attendance ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_manage_attendance)}
                    onChange={() => handleToggleUserPermission("can_manage_attendance")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>📊 Mark & Manage Student Attendance</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_manage_subjects ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_manage_subjects ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_manage_subjects)}
                    onChange={() => handleToggleUserPermission("can_manage_subjects")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>📚 Manage Subjects & Faculty Mapping</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_manage_calendar ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_manage_calendar ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_manage_calendar)}
                    onChange={() => handleToggleUserPermission("can_manage_calendar")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>📅 Manage Academic Calendar & Timetables</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_view_sms_logs ? "rgba(56, 189, 248, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_view_sms_logs ? "1px solid rgba(56, 189, 248, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_view_sms_logs)}
                    onChange={() => handleToggleUserPermission("can_view_sms_logs")}
                    style={{ width: 18, height: 18, accentColor: "#38bdf8", cursor: "pointer" }}
                  />
                  <span>📲 View Absentee SMS Logs & Phone Gateway</span>
                </label>

                <label className="checkbox-field" style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", background: userPerms.can_view_audit_logs ? "rgba(37, 99, 235, 0.12)" : "var(--chip-bg-muted)", padding: "12px 16px", borderRadius: 10, border: userPerms.can_view_audit_logs ? "1px solid rgba(37, 99, 235, 0.4)" : "1px solid var(--border)", color: "var(--text)", fontWeight: 600, fontSize: 14 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(userPerms.can_view_audit_logs)}
                    onChange={() => handleToggleUserPermission("can_view_audit_logs")}
                    style={{ width: 18, height: 18, accentColor: "#2563eb", cursor: "pointer" }}
                  />
                  <span>📜 View System Audit Trail & Logs</span>
                </label>
              </div>
            ) : null}

            {selectedAccount.role !== "HOD" && selectedAccount.username !== user.username && (
              <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1.5px dashed var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 800, color: "#dc2626" }}>
                    ⚠️ Danger Zone: Permanent Profile Removal
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 600 }}>
                    Permanently delete @{selectedAccount.username}'s account, mappings, and permissions.
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-red"
                  style={{ fontWeight: 800 }}
                  onClick={() => {
                    const target = selectedAccount;
                    setSelectedAccount(null);
                    setAccountToDelete(target);
                    setDeleteKeyInput("");
                  }}
                >
                  🗑️ Delete Account
                </button>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
              <button className="btn btn-outline" onClick={() => setSelectedAccount(null)}>Cancel</button>
              <button className="btn btn-primary" style={{ background: "linear-gradient(135deg, #0284c7, #2563eb)", border: "none" }} onClick={handleSaveProfilePermissions} disabled={savingUserPerms || !userPerms}>
                {savingUserPerms ? "Saving Access…" : "Save Access Permissions"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Credential reveal modal */}
      {revealedCreds && (
        <div className="modal-overlay" onClick={() => setRevealedCreds(null)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <h3>🔑 Password Reset</h3>
            <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 14 }}>
              Share these credentials with the user.
            </p>
            <div className="credential-row">
              <label>Username</label>
              {revealedCreds.username}
            </div>
            <div className="credential-row">
              <label>Temporary Password</label>
              {revealedCreds.password}
            </div>
            <button className="btn btn-block" onClick={() => setRevealedCreds(null)}>Done</button>
          </div>
        </div>
      )}

      {/* ── Permanent Delete Confirmation Modal ── */}
      {accountToDelete && (() => {
        const isKeyValid = deleteKeyInput.trim().toUpperCase() === "DELETE" ||
          deleteKeyInput.trim().toLowerCase() === accountToDelete.username.toLowerCase();

        return (
          <div className="modal-overlay" onClick={() => !deletingAccount && setAccountToDelete(null)}>
            <div
              className="modal-box modal3dPopIn"
              style={{
                maxWidth: 490,
                width: "92%",
                background: "var(--bg-card)",
                border: "1.5px solid #fca5a5",
                borderRadius: 18,
                padding: 24,
                boxShadow: "0 25px 50px -12px rgba(220, 38, 38, 0.28)"
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div style={{
                  width: 46,
                  height: 46,
                  borderRadius: 12,
                  background: "linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)",
                  border: "1px solid #fca5a5",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 22,
                  color: "#dc2626",
                  flexShrink: 0
                }}>
                  ⚠️
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: 18, color: "#991b1b", fontWeight: 800 }}>
                    Permanent Delete Confirmation
                  </h3>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 600, marginTop: 2 }}>
                    This action will permanently erase this profile from the system.
                  </div>
                </div>
              </div>

              <div style={{
                background: "var(--row-alt)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: 14,
                marginBottom: 16
              }}>
                <div style={{ fontSize: 15, fontWeight: 800, color: "var(--text)" }}>
                  👤 {accountToDelete.full_name || accountToDelete.username}
                </div>
                <div style={{ fontSize: 13, color: "var(--heading-accent)", fontWeight: 700, marginTop: 3 }}>
                  Username: <strong>@{accountToDelete.username}</strong> · Role: <strong>{accountToDelete.role}</strong>
                </div>
                {accountToDelete.department && (
                  <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600, marginTop: 3 }}>
                    Department: {accountToDelete.department}
                  </div>
                )}
              </div>

              <div style={{ fontSize: 13.5, color: "var(--text)", lineHeight: 1.5, marginBottom: 16, fontWeight: 500 }}>
                Are you sure you want to permanently delete this user account?
                <ul style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: 12.5, color: "#b91c1c", fontWeight: 600 }}>
                  <li>Account credentials and login will be permanently deleted.</li>
                  <li>Subject-faculty mappings and user permissions will be cleared.</li>
                  <li>The user will be immediately removed and will never appear in the application again.</li>
                </ul>
              </div>

              {/* 🔑 Security Confirmation Key Input */}
              <div style={{ marginBottom: 20, background: "rgba(239, 68, 68, 0.06)", padding: 14, borderRadius: 12, border: "1.5px dashed #fca5a5" }}>
                <label htmlFor="confirm-delete-key" style={{ display: "block", fontSize: 12, fontWeight: 800, color: "#991b1b", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  🔑 Enter Confirmation Key To Authorize:
                </label>
                <div style={{ fontSize: 12.5, color: "var(--text)", marginBottom: 8, fontWeight: 600 }}>
                  Type <strong style={{ color: "#dc2626" }}>DELETE</strong> or <strong style={{ color: "#2563eb" }}>{accountToDelete.username}</strong> below:
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    id="confirm-delete-key"
                    type="text"
                    placeholder={`Type "DELETE" or "${accountToDelete.username}"`}
                    value={deleteKeyInput}
                    onChange={(e) => setDeleteKeyInput(e.target.value)}
                    autoFocus
                    style={{
                      flex: 1,
                      height: 40,
                      padding: "0 12px",
                      borderRadius: 8,
                      border: isKeyValid ? "2px solid #10b981" : "1.5px solid var(--border)",
                      background: "#ffffff",
                      color: "var(--text)",
                      fontWeight: 700,
                      fontSize: 14,
                      outline: "none"
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-outline"
                    onClick={() => setDeleteKeyInput(accountToDelete.username)}
                    title="Insert profile key"
                    style={{ fontSize: 12, whiteSpace: "nowrap", fontWeight: 700 }}
                  >
                    🔑 Fill Key
                  </button>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => setAccountToDelete(null)}
                  disabled={deletingAccount}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-red"
                  onClick={handleConfirmDeleteAccount}
                  disabled={deletingAccount || !isKeyValid}
                  style={{
                    minWidth: 160,
                    fontWeight: 800,
                    opacity: isKeyValid ? 1 : 0.5,
                    cursor: isKeyValid ? "pointer" : "not-allowed"
                  }}
                >
                  {deletingAccount ? "Deleting…" : "🗑️ Delete Permanently"}
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </AppShell>
  );
}
