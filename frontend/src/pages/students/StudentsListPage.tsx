import { useState, useEffect, useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  listStudents,
  listStudentSemesters,
  deleteStudent,
  studentsPdfUrl,
  bulkImportStudents,
  type StudentListRow,
  type SemesterOption,
  type BulkImportResult,
} from "../../api/students";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import { ToastPopup } from "../../components/ToastPopup";

interface StudentsListPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function StudentsListPage({ user, onLoggedOut }: StudentsListPageProps) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [yearFilter, setYearFilter] = useState(""); // "", "1", "2", "3", "4"
  const [semesterFilter, setSemesterFilter] = useState(""); // "", "1", "2", ...
  const [semesters, setSemesters] = useState<SemesterOption[]>([]);
  const [rows, setRows] = useState<StudentListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Permanent Delete Modal State
  const [studentToDelete, setStudentToDelete] = useState<StudentListRow | null>(null);
  const [deletingStudent, setDeletingStudent] = useState(false);
  const [deleteKeyInput, setDeleteKeyInput] = useState("");

  // Bulk Import (Excel) Modal State
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<BulkImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  // Print Permission (HOD & ADMIN ONLY)
  const canPrint = ["HOD", "ADMIN"].includes(user.role);

  // Load semesters
  useEffect(() => {
    listStudentSemesters()
      .then((res) => setSemesters(res))
      .catch(() => {
        // Fallback default semesters if endpoint unavailable
        setSemesters([
          { id: 1, code: "I-I", name: "I Year - I Semester" },
          { id: 2, code: "I-II", name: "I Year - II Semester" },
          { id: 3, code: "II-I", name: "II Year - I Semester" },
          { id: 4, code: "II-II", name: "II Year - II Semester" },
          { id: 5, code: "III-I", name: "III Year - I Semester" },
          { id: 6, code: "III-II", name: "III Year - II Semester" },
          { id: 7, code: "IV-I", name: "IV Year - I Semester" },
          { id: 8, code: "IV-II", name: "IV Year - II Semester" },
        ]);
      });
  }, []);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await listStudents(query, "All");
      setRows(res);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load students");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(q);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    load(q);
  }

  async function handleConfirmDelete() {
    if (!studentToDelete) return;
    setDeletingStudent(true);
    setError(null);
    try {
      await deleteStudent(studentToDelete.id);
      setNotice(`Student "${studentToDelete.name}" (${studentToDelete.roll_no}) permanently deleted`);
      setRows((prev) => prev.filter((r) => r.id !== studentToDelete.id));
      setStudentToDelete(null);
      load(q);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to delete student profile");
    } finally {
      setDeletingStudent(false);
    }
  }

  async function handleImportSubmit() {
    if (!importFile) return;
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await bulkImportStudents(importFile);
      setImportResult(result);
      if (result.created_count > 0) {
        setNotice(`Imported ${result.created_count} student${result.created_count === 1 ? "" : "s"} successfully`);
        load(q);
      }
    } catch (err) {
      setImportError(err instanceof ApiClientError ? err.message : "Failed to import the sheet");
    } finally {
      setImporting(false);
    }
  }

  function closeImportModal() {
    setImportModalOpen(false);
    setImportFile(null);
    setImportResult(null);
    setImportError(null);
  }

  // Client-side year & semester filtering
  const YEAR_LABELS: Record<string, string> = {
    "1": "1st Year",
    "2": "2nd Year",
    "3": "3rd Year",
    "4": "4th Year",
  };

  // Filtered and sorted strictly in natural ascending Roll Number order
  const displayedRows = useMemo(() => {
    let list = rows;

    if (yearFilter) {
      list = list.filter((r) => r.year_of_study === YEAR_LABELS[yearFilter]);
    }

    if (semesterFilter) {
      const semId = Number(semesterFilter);
      list = list.filter((r) => r.current_semester_id === semId);
    }

    return [...list].sort((a, b) =>
      a.roll_no.localeCompare(b.roll_no, undefined, { numeric: true, sensitivity: "base" })
    );
  }, [rows, yearFilter, semesterFilter]);

  const activeSemesterObj = semesters.find((s) => s.id === Number(semesterFilter));

  return (
    <AppShell user={user} activeNav="students" heading="Students" onLoggedOut={onLoggedOut}>
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      {/* ── Toolbar & Filters ── */}
      <div
        className="no-print"
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          marginBottom: 16,
          background: "var(--bg-card)",
          padding: 14,
          borderRadius: 12,
          border: "1px solid var(--border)",
          boxShadow: "0 2px 4px rgba(0,0,0,0.02)",
        }}
      >
        <form
          onSubmit={handleSearchSubmit}
          style={{ display: "flex", gap: 10, flex: 1, flexWrap: "wrap", minWidth: 0, alignItems: "center" }}
        >
          <div style={{ position: "relative", flex: 1, minWidth: 200, maxWidth: 340 }}>
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by name, roll no, email or phone…"
              style={{
                width: "100%",
                height: 40,
                padding: "0 12px 0 34px",
                border: "1.5px solid var(--border)",
                borderRadius: 8,
                fontSize: 13.5,
                fontWeight: 500,
              }}
            />
            <span
              style={{
                position: "absolute",
                left: 10,
                top: "50%",
                transform: "translateY(-50%)",
                color: "var(--muted)",
                pointerEvents: "none",
                fontSize: 13,
              }}
            >
              🔍
            </span>
          </div>

          {/* Semester Filter */}
          <select
            value={semesterFilter}
            onChange={(e) => setSemesterFilter(e.target.value)}
            style={{
              height: 40,
              padding: "0 12px",
              border: "1.5px solid var(--border)",
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              minWidth: 190,
              background: "var(--input-bg)",
              color: "var(--text)",
            }}
          >
            <option value="">Select Semester / Year</option>
            {semesters.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} ({s.name})
              </option>
            ))}
          </select>

          {/* Year Filter */}
          <select
            value={yearFilter}
            onChange={(e) => setYearFilter(e.target.value)}
            style={{
              height: 40,
              padding: "0 10px",
              border: "1.5px solid var(--border)",
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              minWidth: 140,
              background: "var(--input-bg)",
              color: "var(--text)",
            }}
          >
            <option value="">All Years</option>
            <option value="1">1st Year (2026-2030)</option>
            <option value="2">2nd Year (2025-2029)</option>
            <option value="3">3rd Year (2024-2028)</option>
            <option value="4">4th Year (2023-2027)</option>
          </select>

          <button type="submit" className="btn btn-outline" style={{ height: 40, fontWeight: 700, padding: "0 18px" }}>
            Search
          </button>

          {/* Print Students Option — ONLY FOR HOD AND ADMIN */}
          {canPrint && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                const url = studentsPdfUrl(semesterFilter, q, yearFilter);
                window.open(url, "_blank");
              }}
              style={{
                height: 40,
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontWeight: 700,
                padding: "0 16px",
                borderRadius: 8,
                background: "var(--blue, #2563eb)",
                color: "#ffffff",
                border: "none",
                boxShadow: "0 2px 6px rgba(37, 99, 235, 0.25)",
                cursor: "pointer",
              }}
              title="Print official student list PDF for selected semester"
            >
              🖨️ Print Students
            </button>
          )}
        </form>

        {["HOD", "ADMIN"].includes(user.role) && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setImportModalOpen(true)}
              style={{ height: 40, fontWeight: 700, borderRadius: 8, padding: "0 16px", whiteSpace: "nowrap" }}
              title="Bulk-create student accounts from an Excel sheet"
            >
              📥 Import Students
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => navigate("/students/new")}
              style={{ height: 40, fontWeight: 700, borderRadius: 8, padding: "0 16px", whiteSpace: "nowrap" }}
            >
              + Add Student
            </button>
          </div>
        )}
      </div>

      {error && <div className="login-error no-print">{error}</div>}

      {/* ── Summary Badge ── */}
      <div
        className="no-print"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
          padding: "0 4px",
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--muted)" }}>
          Showing <span style={{ color: "var(--blue)" }}>{displayedRows.length}</span> students{" "}
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--subtext)" }}>
            (Sorted in Roll Number Order)
          </span>
          {semesterFilter && activeSemesterObj && (
            <span
              className="chip chip-blue"
              style={{ marginLeft: 8, fontSize: 11, padding: "2px 8px" }}
            >
              Semester: {activeSemesterObj.code} ({activeSemesterObj.name})
            </span>
          )}
        </div>
      </div>

      {/* ── Main Students Table (Roll Number Wise) ── */}
      <div className="table-wrap responsive-cards no-print">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 60, textAlign: "center" }}>Photo</th>
              <th>Roll No</th>
              <th>Name</th>
              <th>Year & Batch</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Aadhaar</th>
              <th className="center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((r) => (
              <tr key={r.id}>
                <td data-label="Photo" style={{ textAlign: "center" }}>
                  {formatPhotoUrl(r.photo_path ?? null) ? (
                    <img
                      src={formatPhotoUrl(r.photo_path ?? null)!}
                      alt={r.name}
                      style={{ width: 36, height: 36, borderRadius: "50%", objectFit: "cover" }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: "50%",
                        background: "var(--chip-bg-muted)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 12,
                        fontWeight: 700,
                        color: "var(--muted)",
                        margin: "0 auto",
                      }}
                    >
                      {r.name?.[0]?.toUpperCase() || "?"}
                    </div>
                  )}
                </td>
                <td data-label="Roll No" style={{ fontWeight: 800, color: "var(--blue)", letterSpacing: "0.5px" }}>
                  {r.roll_no.toUpperCase()}
                </td>
                <td data-label="Name" style={{ fontWeight: 700 }}>
                  <Link to={`/students/${r.id}`} style={{ color: "var(--text)" }}>
                    {r.name}
                  </Link>
                </td>
                <td data-label="Year & Batch">
                  <span className="chip chip-blue" style={{ fontSize: 11, padding: "2px 8px" }}>
                    {r.year_of_study || "1st Year"}
                  </span>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, fontWeight: 600 }}>
                    {r.batch || "2026-2030 Batch"}
                  </div>
                </td>
                <td data-label="Email">{r.email || "—"}</td>
                <td data-label="Phone">{r.phone || "—"}</td>
                <td data-label="Aadhaar">{r.aadhaar_masked || "—"}</td>
                <td data-label="Actions" className="center" style={{ whiteSpace: "nowrap" }}>
                  <Link to={`/students/${r.id}`} className="btn btn-sm btn-outline">
                    View
                  </Link>
                  {["HOD", "ADMIN"].includes(user.role) && (
                    <button
                      className="btn btn-sm btn-red"
                      style={{ marginLeft: 6, fontWeight: 700 }}
                      onClick={() => {
                        setStudentToDelete(r);
                        setDeleteKeyInput("");
                      }}
                      title="Permanently delete this student profile"
                    >
                      🗑️ Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <p className="empty-note">Loading students list…</p>}
        {!loading && displayedRows.length === 0 && (
          <p className="empty-note">No students match this search or semester filter.</p>
        )}
      </div>

      {/* ── Permanent Delete Student Confirmation Modal ── */}
      {studentToDelete && (() => {
        const isKeyValid =
          deleteKeyInput.trim().toUpperCase() === "DELETE" ||
          deleteKeyInput.trim().toLowerCase() === studentToDelete.roll_no.toLowerCase();

        return (
          <div className="modal-overlay no-print" onClick={() => !deletingStudent && setStudentToDelete(null)}>
            <div
              className="modal-box modal3dPopIn"
              style={{
                maxWidth: 490,
                width: "92%",
                background: "var(--bg-card)",
                border: "1.5px solid #fca5a5",
                borderRadius: 18,
                padding: 24,
                boxShadow: "0 25px 50px -12px rgba(220, 38, 38, 0.28)",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div
                  style={{
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
                    flexShrink: 0,
                  }}
                >
                  ⚠️
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: 18, color: "#991b1b", fontWeight: 800 }}>
                    Permanent Delete Student Profile
                  </h3>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 600, marginTop: 2 }}>
                    This action will permanently erase this student from the system.
                  </div>
                </div>
              </div>

              <div
                style={{
                  background: "var(--row-alt)",
                  border: "1px solid var(--border)",
                  borderRadius: 12,
                  padding: 14,
                  marginBottom: 16,
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 800, color: "var(--text)" }}>
                  👨‍🎓 {studentToDelete.name}
                </div>
                <div style={{ fontSize: 13, color: "var(--heading-accent)", fontWeight: 700, marginTop: 3 }}>
                  Roll No: <strong>{studentToDelete.roll_no}</strong> · Batch:{" "}
                  <strong>{studentToDelete.batch || "—"}</strong>
                </div>
                {studentToDelete.email && (
                  <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600, marginTop: 3 }}>
                    Email: {studentToDelete.email}
                  </div>
                )}
              </div>

              <div style={{ fontSize: 13.5, color: "var(--text)", lineHeight: 1.5, marginBottom: 16, fontWeight: 500 }}>
                Are you sure you want to permanently delete this student record?
                <ul style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: 12.5, color: "#b91c1c", fontWeight: 600 }}>
                  <li>Student account, credentials, and attendance records will be permanently removed.</li>
                  <li>This student will no longer appear anywhere in the application.</li>
                </ul>
              </div>

              {/* Security Confirmation Key Input */}
              <div
                style={{
                  marginBottom: 20,
                  background: "rgba(239, 68, 68, 0.06)",
                  padding: 14,
                  borderRadius: 12,
                  border: "1.5px dashed #fca5a5",
                }}
              >
                <label
                  htmlFor="confirm-list-delete-key"
                  style={{
                    display: "block",
                    fontSize: 12,
                    fontWeight: 800,
                    color: "#991b1b",
                    marginBottom: 6,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                  }}
                >
                  🔑 Enter Confirmation Key To Authorize:
                </label>
                <div style={{ fontSize: 12.5, color: "var(--text)", marginBottom: 8, fontWeight: 600 }}>
                  Type <strong style={{ color: "#dc2626" }}>DELETE</strong> or{" "}
                  <strong style={{ color: "#2563eb" }}>{studentToDelete.roll_no}</strong> below:
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    id="confirm-list-delete-key"
                    type="text"
                    placeholder={`Type "DELETE" or "${studentToDelete.roll_no}"`}
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
                      outline: "none",
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-outline"
                    onClick={() => setDeleteKeyInput(studentToDelete.roll_no)}
                    title="Insert roll number key"
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
                  onClick={() => setStudentToDelete(null)}
                  disabled={deletingStudent}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-red"
                  onClick={handleConfirmDelete}
                  disabled={deletingStudent || !isKeyValid}
                  style={{
                    minWidth: 160,
                    fontWeight: 800,
                    opacity: isKeyValid ? 1 : 0.5,
                    cursor: isKeyValid ? "pointer" : "not-allowed",
                  }}
                >
                  {deletingStudent ? "Deleting…" : "🗑️ Delete Permanently"}
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── Bulk Import Students (Excel) Modal ── */}
      {importModalOpen && (
        <div className="modal-overlay no-print" onClick={() => !importing && closeImportModal()}>
          <div
            className="modal-box modal3dPopIn"
            style={{
              maxWidth: 620,
              width: "94%",
              maxHeight: "85vh",
              overflowY: "auto",
              background: "var(--bg-card)",
              border: "1.5px solid var(--border)",
              borderRadius: 18,
              padding: 24,
              boxShadow: "0 25px 50px -12px rgba(0,0,0,0.25)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text)" }}>
                📥 Import Students from Excel
              </h3>
              <button
                className="btn btn-sm btn-outline"
                onClick={closeImportModal}
                disabled={importing}
                style={{ padding: "4px 10px" }}
              >
                ✕
              </button>
            </div>

            {!importResult && (
              <>
                <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600, marginBottom: 16, lineHeight: 1.5 }}>
                  Upload an .xlsx sheet with columns for HallTicket, Full Name, Phone, Email, Address,
                  Aadhaar Number, Father's Name and Father's Phone Number. A login is created automatically
                  for every new student (username = roll number, password = roll number + "@CSD").
                  Rows with a roll number that already exists are skipped, not overwritten.
                </div>

                <div
                  style={{
                    border: "1.5px dashed var(--border)",
                    borderRadius: 12,
                    padding: 20,
                    textAlign: "center",
                    marginBottom: 16,
                    background: "var(--row-alt)",
                  }}
                >
                  <input
                    type="file"
                    accept=".xlsx,.xlsm"
                    onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                    disabled={importing}
                    style={{ fontSize: 13, fontWeight: 600 }}
                  />
                  {importFile && (
                    <div style={{ marginTop: 10, fontSize: 12.5, fontWeight: 700, color: "var(--blue)" }}>
                      {importFile.name}
                    </div>
                  )}
                </div>

                {importError && <div className="login-error" style={{ marginBottom: 16 }}>{importError}</div>}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                  <button type="button" className="btn btn-outline" onClick={closeImportModal} disabled={importing}>
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={handleImportSubmit}
                    disabled={!importFile || importing}
                    style={{ fontWeight: 800, opacity: !importFile || importing ? 0.6 : 1 }}
                  >
                    {importing ? "Importing…" : "Import"}
                  </button>
                </div>
              </>
            )}

            {importResult && (
              <>
                <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
                  <span className="chip" style={{ background: "#dcfce7", color: "#166534", fontWeight: 800, padding: "4px 10px" }}>
                    ✅ {importResult.created_count} created
                  </span>
                  <span className="chip" style={{ background: "#fef9c3", color: "#854d0e", fontWeight: 800, padding: "4px 10px" }}>
                    ⏭️ {importResult.skipped_count} skipped
                  </span>
                  <span className="chip" style={{ background: "#fee2e2", color: "#991b1b", fontWeight: 800, padding: "4px 10px" }}>
                    ❌ {importResult.failed_count} failed
                  </span>
                </div>

                {importResult.created.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 6 }}>
                      New Logins Created
                    </div>
                    <div style={{ maxHeight: 200, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead>
                          <tr>
                            <th>Roll No</th>
                            <th>Name</th>
                            <th>Username</th>
                            <th>Password</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.created.map((r) => (
                            <tr key={r.roll_no}>
                              <td>{r.roll_no}</td>
                              <td>{r.name}</td>
                              <td>{r.username}</td>
                              <td style={{ fontFamily: "monospace" }}>{r.password}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult.skipped.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 6 }}>
                      Skipped Rows
                    </div>
                    <div style={{ maxHeight: 140, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead>
                          <tr>
                            <th>Row</th>
                            <th>Roll No</th>
                            <th>Reason</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.skipped.map((r) => (
                            <tr key={r.row}>
                              <td>{r.row}</td>
                              <td>{r.roll_no}</td>
                              <td>{r.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult.failed.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "#991b1b", marginBottom: 6 }}>
                      Failed Rows
                    </div>
                    <div style={{ maxHeight: 140, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead>
                          <tr>
                            <th>Row</th>
                            <th>Roll No</th>
                            <th>Reason</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.failed.map((r) => (
                            <tr key={r.row}>
                              <td>{r.row}</td>
                              <td>{r.roll_no}</td>
                              <td>{r.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                  <button type="button" className="btn btn-outline" onClick={closeImportModal}>
                    Close
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}