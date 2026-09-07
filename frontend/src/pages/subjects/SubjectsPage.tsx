// Group 5 — Subjects page for HOD.
// Mirrors webapp/routes/subjects.py + templates/subjects/list.html.
// Semesters are COLLAPSED BY DEFAULT, expanding on click.
// All errors/failures displayed in RED (.error-banner).
import { useState, useEffect } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  getSubjectsPage, createSubject, updateSubject, deleteSubject, toggleSubjectActive,
  assignFaculty, toggleSemesterActive,
  type SubjectsPageData, type SubjectRow, type FacultyOption, type SemesterInfo,
} from "../../api/subjects";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function SubjectsPage({ user, onLoggedOut }: Props) {
  const [data, setData] = useState<SubjectsPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Collapsed by default — tracks which semester code is expanded
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [newSemId, setNewSemId] = useState<number | "">("");
  const [newCode, setNewCode] = useState("");
  const [newName, setNewName] = useState("");
  const [newHasLab, setNewHasLab] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Edit subject modal state
  const [editingSubject, setEditingSubject] = useState<SubjectRow | null>(null);
  const [editCode, setEditCode] = useState("");
  const [editName, setEditName] = useState("");
  const [editHasLab, setEditHasLab] = useState(false);

  // Assign faculty overlay
  const [assigningSubject, setAssigningSubject] = useState<SubjectRow | null>(null);
  const [selectedFaculty, setSelectedFaculty] = useState<string[]>([]);

  async function reload() {
    setLoading(true);
    setError(null);
    try {
      const d = await getSubjectsPage();
      setData(d);
    } catch (err) {
      // Errors ALWAYS in RED (.error-banner)
      setError(err instanceof ApiClientError ? err.message : "Failed to load subjects");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSemester(code: string) {
    setExpanded(prev => ({ ...prev, [code]: !prev[code] }));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newSemId) { setActionError("Select a semester"); return; }
    setSubmitting(true); setActionError(null);
    try {
      await createSubject({ semester_id: newSemId as number, code: newCode, name: newName, has_lab: newHasLab });
      setShowCreate(false); setNewCode(""); setNewName(""); setNewHasLab(false); setNewSemId("");
      setNotice("Subject added successfully");
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to add subject");
    } finally { setSubmitting(false); }
  }

  async function handleToggleSubject(subj: SubjectRow) {
    setActionError(null);
    try {
      await toggleSubjectActive(subj.id);
      setNotice(`${subj.code} ${subj.active ? "deactivated" : "activated"}`);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to toggle subject");
    }
  }

  async function handleToggleSemester(sem: SemesterInfo, e: React.MouseEvent) {
    e.stopPropagation(); // prevent semester collapse toggle when clicking action button
    setActionError(null);
    try {
      await toggleSemesterActive(sem.id);
      setNotice(`${sem.code} ${sem.active ? "deactivated" : "activated"}`);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to toggle semester");
    }
  }

  function openEdit(subj: SubjectRow) {
    setEditingSubject(subj);
    setEditCode(subj.code);
    setEditName(subj.name);
    setEditHasLab(subj.has_lab);
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editingSubject) return;
    setSubmitting(true); setActionError(null);
    try {
      await updateSubject(editingSubject.id, { code: editCode, name: editName, has_lab: editHasLab });
      setEditingSubject(null);
      setNotice("Subject updated successfully");
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to update subject");
    } finally { setSubmitting(false); }
  }

  async function handleDelete(subj: SubjectRow) {
    if (!window.confirm(`Are you sure you want to delete ${subj.code} (${subj.name})?`)) return;
    setActionError(null);
    try {
      await deleteSubject(subj.id);
      setNotice(`Subject ${subj.code} deleted`);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to delete subject");
    }
  }

  function openAssign(subj: SubjectRow) {
    setAssigningSubject(subj);
    setSelectedFaculty(subj.faculty_usernames ?? []);
  }

  async function handleAssign(e: React.FormEvent) {
    e.preventDefault();
    if (!assigningSubject) return;
    setSubmitting(true); setActionError(null);
    try {
      await assignFaculty(assigningSubject.id, selectedFaculty);
      setAssigningSubject(null);
      setNotice("Faculty assignment saved");
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiClientError ? err.message : "Failed to assign faculty");
    } finally { setSubmitting(false); }
  }

  function toggleFacultySelect(username: string) {
    setSelectedFaculty(prev =>
      prev.includes(username) ? prev.filter(u => u !== username) : [...prev, username]
    );
  }

  if (loading) return (
    <AppShell user={user} activeNav="subjects" heading="Subjects" onLoggedOut={onLoggedOut}>
      <p className="empty-note">Loading…</p>
    </AppShell>
  );

  return (
    <AppShell user={user} activeNav="subjects" heading="Subjects" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error || actionError} onClose={() => { setError(null); setActionError(null); }} />
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      <div className="section-head">
        <h2>All Subjects by Semester</h2>
        <button className="btn" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? "✕ Cancel" : "+ Add Subject"}
        </button>
      </div>

      {showCreate && (
        <div className="detail-box">
          <h3>Add Subject</h3>
          <form onSubmit={handleCreate}>
            <div className="form-grid">
              <div className="field">
                <label>Semester *</label>
                <select value={newSemId} onChange={e => setNewSemId(Number(e.target.value))} required>
                  <option value="">— Select semester —</option>
                  {data?.all_semesters.map(s => (
                    <option key={s.id} value={s.id}>{s.name} ({s.code}){!s.active ? " [inactive]" : ""}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Subject Code *</label>
                <input type="text" value={newCode} onChange={e => setNewCode(e.target.value)} required />
              </div>
              <div className="field">
                <label>Subject Name *</label>
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)} required />
              </div>
              <div className="field" style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 22 }}>
                <input type="checkbox" id="has_lab" checked={newHasLab} onChange={e => setNewHasLab(e.target.checked)} />
                <label htmlFor="has_lab" style={{ textTransform: "none", fontSize: 14 }}>Has Lab</label>
              </div>
            </div>
            <button type="submit" className="btn" disabled={submitting}>{submitting ? "Adding…" : "Add Subject"}</button>
          </form>
        </div>
      )}

      {data && Object.keys(data.grouped).length === 0 && (
        <p className="empty-note">No subjects yet. Add the first one above.</p>
      )}

      {data && data.all_semesters.map(sem => {
        const isOpen = !!expanded[sem.code];
        const subjects = data.grouped[sem.code] ?? [];
        return (
          <div key={sem.id} className="sem-section" style={{ marginBottom: 14 }}>
            <div
              className="collapsible-trigger"
              onClick={() => toggleSemester(sem.code)}
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
            >
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, background: "none", border: "none", padding: 0 }}>
                <span style={{ marginRight: 8, fontSize: 12 }}>{isOpen ? "▼" : "▶"}</span>
                {sem.name} <span style={{ color: "var(--muted)", fontWeight: 400 }}>({sem.code})</span>
                {!sem.active && <span className="chip chip-red" style={{ marginLeft: 10 }}>Inactive</span>}
                <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400, marginLeft: 12 }}>
                  ({subjects.length} subject{subjects.length === 1 ? "" : "s"})
                </span>
              </h3>
              <button
                className={`btn btn-sm ${sem.active ? "btn-outline" : "btn-green"}`}
                onClick={(e) => handleToggleSemester(sem, e)}
              >
                {sem.active ? "Deactivate" : "Activate"}
              </button>
            </div>

            {isOpen && (
              <div className="collapsible-body">
                {subjects.length === 0 ? (
                  <p style={{ color: "var(--muted)", fontSize: 13, margin: 0 }}>No subjects in this semester.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr><th>Code</th><th>Name</th><th className="center">Lab</th><th className="center">Active</th><th>Faculty</th><th className="center">Actions</th></tr>
                      </thead>
                      <tbody>
                        {subjects.map(subj => (
                          <tr key={subj.id}>
                            <td>{subj.code}</td>
                            <td>{subj.name}</td>
                            <td className="center">{subj.has_lab ? "✓" : "—"}</td>
                            <td className="center">
                              <span className={`chip ${subj.active ? "chip-green" : "chip-red"}`}>
                                {subj.active ? "Active" : "Inactive"}
                              </span>
                            </td>
                            <td style={{ fontSize: 12, color: "var(--muted)" }}>
                              {(subj.faculty_usernames ?? []).join(", ") || "—"}
                            </td>
                            <td className="center" style={{ whiteSpace: "nowrap" }}>
                              <button className="btn btn-sm btn-outline" onClick={() => openEdit(subj)} style={{ marginRight: 6 }}>✏️ Edit</button>
                              <button className="btn btn-sm btn-outline" onClick={() => openAssign(subj)}>Assign Faculty</button>
                              <button className={`btn btn-sm ${subj.active ? "btn-warn" : "btn-green"}`} style={{ marginLeft: 6 }}
                                onClick={() => handleToggleSubject(subj)}>
                                {subj.active ? "Deactivate" : "Activate"}
                              </button>
                              <button className="btn btn-sm btn-red" style={{ marginLeft: 6 }} onClick={() => handleDelete(subj)}>
                                🗑️ Delete
                              </button>
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
        );
      })}

      {/* Edit subject modal */}
      {editingSubject && (
        <div className="modal-overlay" onClick={() => setEditingSubject(null)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <h3>✏️ Edit Subject — {editingSubject.code}</h3>
            <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 14 }}>
              Update subject code, name, or lab requirement.
            </p>
            <form onSubmit={handleUpdate}>
              <div className="field">
                <label>Subject Code *</label>
                <input type="text" className="input-field" value={editCode} onChange={e => setEditCode(e.target.value)} required />
              </div>
              <div className="field">
                <label>Subject Name *</label>
                <input type="text" className="input-field" value={editName} onChange={e => setEditName(e.target.value)} required />
              </div>
              <div className="field" style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 10, marginBottom: 20 }}>
                <input type="checkbox" id="edit_has_lab" checked={editHasLab} onChange={e => setEditHasLab(e.target.checked)} />
                <label htmlFor="edit_has_lab" style={{ textTransform: "none", fontSize: 14, fontWeight: 700 }}>Has Lab</label>
              </div>
              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                <button type="button" className="btn btn-outline" onClick={() => setEditingSubject(null)}>Cancel</button>
                <button type="submit" className="btn" disabled={submitting}>{submitting ? "Updating…" : "Save Changes"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Assign faculty modal */}
      {assigningSubject && (
        <div className="modal-overlay" onClick={() => setAssigningSubject(null)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <h3>Assign Faculty — {assigningSubject.code}</h3>
            <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 14 }}>
              Select one or more faculty members for this subject.
            </p>
            <form onSubmit={handleAssign}>
              {data?.faculty.map((f: FacultyOption) => (
                <label key={f.username} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, cursor: "pointer" }}>
                  <input type="checkbox" checked={selectedFaculty.includes(f.username)}
                    onChange={() => toggleFacultySelect(f.username)} />
                  {f.full_name || f.username} <span style={{ color: "var(--muted)", fontSize: 12 }}>({f.username})</span>
                </label>
              ))}
              {data?.faculty.length === 0 && <p style={{ color: "var(--muted)" }}>No active faculty accounts.</p>}
              <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                <button type="submit" className="btn" disabled={submitting}>{submitting ? "Saving…" : "Save"}</button>
                <button type="button" className="btn btn-outline" onClick={() => setAssigningSubject(null)}>Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}
