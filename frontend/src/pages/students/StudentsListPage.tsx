import { useState, useEffect, useCallback, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  listStudents,
  listStudentSemesters,
  deleteStudent,
  studentsPdfUrl,
  bulkImportStudents,
  getBulkImportOptions,
  importFieldLabel,
  type StudentListRow,
  type SemesterOption,
  type BulkImportResult,
  type BulkImportOptions,
} from "../../api/students";
import { ApiClientError, formatPhotoUrl, getAuthUrl } from "../../api/client";
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const [sortBy, setSortBy] = useState<"roll" | "name" | "year">("roll");
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
  const [importOptions, setImportOptions] = useState<BulkImportOptions | null>(null);
  const [importBranch, setImportBranch] = useState("");
  const [importYear, setImportYear] = useState(0);
  const [importSemester, setImportSemester] = useState(0);
  const [importMode, setImportMode] = useState<"merge" | "create_only">("merge");

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

  async function openImportModal() {
    setImportModalOpen(true);
    setImportError(null);
    setImportResult(null);
    try {
      const options = await getBulkImportOptions();
      setImportOptions(options);
      // Preselect the first available branch so the guided flow is immediately usable.
      // The previous empty state made the Semester control remain disabled even when
      // the UI appeared to show a branch selection.
      setImportBranch(options.branches.length ? String(options.branches[0].value) : "");
      setImportYear(0);
      setImportSemester(0);
    } catch (err) {
      setImportError(err instanceof ApiClientError ? err.message : "Could not load import options");
    }
  }

  function semesterForYear(year: number, semesterNumber: number) {
    const roman = ["", "I", "II", "III", "IV"][year] ?? "";
    const code = `${roman}-${semesterNumber === 2 ? "II" : "I"}`;
    return importOptions?.semesters.find((s) => s.active && s.code === code);
  }

  async function handleImportSubmit() {
    if (!importFile || !importBranch || !importYear || !importSemester) return;
    // WHY: importSemester is just "1" or "2" from the dropdown, not a real
    // academic_semesters.id. bulkImportStudents() needs the actual row id,
    // so resolve it here the same way the semester filter dropdown does.
    // Previously this passed `semester: importSemester` — a key the upload
    // function doesn't accept — so semesterId was always undefined and the
    // request was sent with semester_id=undefined, which FastAPI rejects
    // with a 422 before the file is ever read.
    const resolvedSemester = semesterForYear(importYear, importSemester);
    if (!resolvedSemester) {
      setImportError("Could not resolve that semester for the selected year. Please reselect.");
      return;
    }
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      const result = await bulkImportStudents(importFile, {
        branch: importBranch,
        year: importYear,
        semesterId: resolvedSemester.id,
        mode: importMode,
      });
      setImportResult(result);
      if (result.created_count || result.updated_count) {
        setNotice(`${result.created_count} created · ${result.updated_count} updated successfully`);
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
    setImportOptions(null);
    setImportBranch("");
    setImportYear(0);
    setImportSemester(0);
    setImportMode("merge");
  }

  // Client-side year & semester filtering
  const YEAR_LABELS: Record<string, string> = {
    "1": "1st Year",
    "2": "2nd Year",
    "3": "3rd Year",
    "4": "4th Year",
  };

  const displayedRows = useMemo(() => {
    let list = rows;

    if (yearFilter) {
      list = list.filter((r) => r.year_of_study === YEAR_LABELS[yearFilter]);
    }

    if (semesterFilter) {
      const semId = Number(semesterFilter);
      list = list.filter((r) => r.current_semester_id === semId);
    }

    return [...list].sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
      if (sortBy === "year") {
        const yearA = Number((a.year_of_study || "").match(/\d+/)?.[0] || 0);
        const yearB = Number((b.year_of_study || "").match(/\d+/)?.[0] || 0);
        return yearA - yearB || a.roll_no.localeCompare(b.roll_no, undefined, { numeric: true, sensitivity: "base" });
      }
      return a.roll_no.localeCompare(b.roll_no, undefined, { numeric: true, sensitivity: "base" });
    });
  }, [rows, yearFilter, semesterFilter, sortBy]);

  const hasActiveFilters = Boolean(yearFilter || semesterFilter);
  const sortLabel = sortBy === "name" ? "Name order" : sortBy === "year" ? "Year order" : "Roll Number order";

  return (
    <AppShell user={user} activeNav="students" heading="Students" onLoggedOut={onLoggedOut}>
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      {/* ── Quiet Students controls ── */}
      <div className="students-toolbar no-print">
        <div className="students-toolbar-main">
          <form className={`students-search ${searchOpen ? "is-open" : ""}`} onSubmit={handleSearchSubmit}>
            <button
              type="button"
              className="students-tool-button students-search-toggle"
              onClick={() => setSearchOpen(true)}
              aria-label="Open student search"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
              <span>Search</span>
            </button>
            <div className="students-search-field">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search students…"
                aria-label="Search students"
                autoFocus={searchOpen}
              />
              <button
                type="button"
                className="students-search-close"
                onClick={() => { setSearchOpen(false); setQ(""); load(""); }}
                aria-label="Close search"
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
          </form>

          <button type="button" className={`students-tool-button ${hasActiveFilters ? "is-active" : ""}`} onClick={() => setFiltersOpen(true)}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4"/></svg>
            <span>Filters</span>
            {hasActiveFilters && <span className="students-tool-dot" aria-hidden="true" />}
          </button>

          <div className="students-sort-wrap">
            <button type="button" className={`students-tool-button ${sortOpen ? "is-active" : ""}`} onClick={() => setSortOpen((open) => !open)} aria-expanded={sortOpen}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h12M8 12h9M8 18h6"/><path d="m4 7 2-2 2 2M6 5v14"/></svg>
              <span>Sort</span>
            </button>
            {sortOpen && (
              <>
                <button className="students-popover-backdrop" aria-label="Close sort menu" onClick={() => setSortOpen(false)} />
                <div className="students-sort-menu">
                  <div className="students-menu-label">Sort students</div>
                  {([[
                    "roll", "Roll Number"
                  ], ["name", "Name"], ["year", "Year"]] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={sortBy === value ? "selected" : ""}
                      onClick={() => { setSortBy(value); setSortOpen(false); }}
                    >
                      <span>{label}</span>
                      {sortBy === value && <span aria-hidden="true">✓</span>}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {(canPrint || ["HOD", "ADMIN"].includes(user.role)) && (
          <div className="students-admin-actions">
            {canPrint && (
              <button
                type="button"
                className="students-admin-button"
                onClick={() => window.open(studentsPdfUrl(semesterFilter, q, yearFilter), "_blank")}
                title="Print official student list PDF for selected semester"
              >
                <span aria-hidden="true">🖨</span> Print
              </button>
            )}
            { ["HOD", "ADMIN"].includes(user.role) && (
              <>
                <button type="button" className="students-admin-button" onClick={openImportModal} title="Bulk-create student accounts from an Excel sheet">
                  <span aria-hidden="true">＋</span> Import
                </button>
                <button type="button" className="students-admin-button primary" onClick={() => navigate("/students/new")}>
                  + Add Student
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {error && <div className="login-error no-print">{error}</div>}

      <div className="students-summary no-print">
        <span><strong>{displayedRows.length}</strong> students</span>
        <span aria-hidden="true">·</span>
        <span>{sortLabel}</span>
        {hasActiveFilters && <span className="students-summary-filter">Filtered</span>}
      </div>

      {filtersOpen && (
        <div className="students-filter-sheet-backdrop no-print" onClick={() => setFiltersOpen(false)}>
          <div className="students-filter-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="student-filter-title">
            <div className="students-sheet-handle" aria-hidden="true" />
            <div className="students-sheet-head">
              <div>
                <span>Students</span>
                <h2 id="student-filter-title">Filters</h2>
              </div>
              <button type="button" className="students-sheet-close" onClick={() => setFiltersOpen(false)} aria-label="Close filters">×</button>
            </div>
            <div className="students-filter-fields">
              <label>
                <span>Semester</span>
                <select value={semesterFilter} onChange={(e) => setSemesterFilter(e.target.value)}>
                  <option value="">All semesters</option>
                  {semesters.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
                </select>
              </label>
              <label>
                <span>Year</span>
                <select value={yearFilter} onChange={(e) => setYearFilter(e.target.value)}>
                  <option value="">All years</option>
                  <option value="1">1st Year</option>
                  <option value="2">2nd Year</option>
                  <option value="3">3rd Year</option>
                  <option value="4">4th Year</option>
                </select>
              </label>
            </div>
            <div className="students-sheet-actions">
              <button type="button" className="students-admin-button" onClick={() => { setYearFilter(""); setSemesterFilter(""); }}>Clear</button>
              <button type="button" className="students-admin-button primary" onClick={() => setFiltersOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}

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

      {/* ── Guided Bulk Import Students (Excel) Modal ── */}
      {importModalOpen && (
        <div className="modal-overlay no-print" onClick={() => !importing && closeImportModal()}>
          <div
            className="modal-box modal3dPopIn"
            style={{
              maxWidth: 700,
              width: "94%",
              maxHeight: "88vh",
              overflowY: "auto",
              background: "var(--bg-card)",
              border: "1.5px solid var(--border)",
              borderRadius: 18,
              padding: 24,
              boxShadow: "0 25px 50px -12px rgba(0,0,0,0.25)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 800, color: "var(--blue)", letterSpacing: 0.8, textTransform: "uppercase" }}>
                  Step 1 · Choose Scope
                </div>
                <h3 style={{ margin: "4px 0 0", fontSize: 19, fontWeight: 850, color: "var(--text)" }}>
                  📥 Import Students
                </h3>
              </div>
              <button className="btn btn-sm btn-outline" onClick={closeImportModal} disabled={importing} style={{ padding: "4px 10px" }}>
                ✕
              </button>
            </div>

            {!importResult && (
              <>
                <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600, marginBottom: 18, lineHeight: 1.55 }}>
                  Select exactly where this sheet belongs. New students are created; existing students are merged by Roll Number.
                  Blank cells never erase existing values. To rename a roll number, add a <strong>Previous Roll Number</strong> column.
                </div>

                {!importOptions && importError && <div className="login-error" style={{ marginBottom: 16 }}>{importError}</div>}

                {importOptions && (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 18 }}>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 11.5, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase" }}>Branch</span>
                        <select
                          value={importBranch}
                          onChange={(e) => {
                            setImportBranch(e.target.value);
                            setImportYear(0);
                            setImportSemester(0);
                          }}
                          disabled={importing}
                          style={{ height: 42, padding: "0 11px", border: "1.5px solid var(--border)", borderRadius: 9, fontSize: 13.5, fontWeight: 700, background: "var(--input-bg)", color: "var(--text)" }}
                        >
                          {importOptions.branches.map((b) => <option key={String(b.value)} value={String(b.value)}>{b.label}</option>)}
                        </select>
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 11.5, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase" }}>Year</span>
                        <select
                          value={importYear || ""}
                          onChange={(e) => {
                            const y = Number(e.target.value);
                            setImportYear(y);
                            setImportSemester(0);
                          }}
                          disabled={importing}
                          style={{ height: 42, padding: "0 11px", border: "1.5px solid var(--border)", borderRadius: 9, fontSize: 13.5, fontWeight: 700, background: "var(--input-bg)", color: "var(--text)" }}
                        >
                          <option value="">Select year…</option>
                          {importOptions.years.map((y) => <option key={String(y.value)} value={String(y.value)}>{y.label}</option>)}
                        </select>
                      </label>

                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={{ fontSize: 11.5, fontWeight: 800, color: "var(--muted)", textTransform: "uppercase" }}>Semester</span>
                        <select
                          value={importSemester || ""}
                          onChange={(e) => setImportSemester(Number(e.target.value))}
                          disabled={importing || !importYear}
                          style={{ height: 42, padding: "0 11px", border: "1.5px solid var(--border)", borderRadius: 9, fontSize: 13.5, fontWeight: 700, background: "var(--input-bg)", color: "var(--text)" }}
                        >
                          <option value="">Select semester…</option>
                          {importYear && importOptions.semesters.filter((s) => s.code.startsWith(["", "I", "II", "III", "IV"][importYear] + "-")).map((s) => (
                            <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 14, marginBottom: 14, background: "var(--row-alt)" }}>
                      <div style={{ fontSize: 12, fontWeight: 800, color: "var(--text)", marginBottom: 9 }}>Import behavior</div>
                      <label style={{ display: "flex", alignItems: "flex-start", gap: 10, cursor: "pointer" }}>
                        <input type="radio" name="student-import-mode" checked={importMode === "merge"} onChange={() => setImportMode("merge")} disabled={importing} />
                        <span>
                          <strong style={{ fontSize: 13 }}>Merge / update existing</strong>
                          <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 2 }}>Recommended. Existing Roll Numbers are updated; new Roll Numbers are created.</span>
                        </span>
                      </label>
                      <label style={{ display: "flex", alignItems: "flex-start", gap: 10, cursor: "pointer", marginTop: 10 }}>
                        <input type="radio" name="student-import-mode" checked={importMode === "create_only"} onChange={() => setImportMode("create_only")} disabled={importing} />
                        <span>
                          <strong style={{ fontSize: 13 }}>Create only</strong>
                          <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 2 }}>Never overwrite existing students; duplicates are reported as skipped.</span>
                        </span>
                      </label>
                    </div>

                    <div style={{ border: "1.5px dashed var(--border)", borderRadius: 12, padding: 18, textAlign: "center", marginBottom: 16, background: "var(--bg-card)" }}>
                      <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 7, color: "var(--muted)" }}>Step 2 · Choose Excel file</div>
                      <input type="file" accept=".xlsx,.xlsm" onChange={(e) => setImportFile(e.target.files?.[0] ?? null)} disabled={importing} style={{ fontSize: 13, fontWeight: 600 }} />
                      {importFile && <div style={{ marginTop: 9, fontSize: 12.5, fontWeight: 800, color: "var(--blue)" }}>{importFile.name}</div>}
                    </div>

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 14, padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 10, background: "var(--card-glass)" }}>
                      <div>
                        <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)" }}>Need a zero-guesswork sheet?</div>
                        <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 2 }}>Download the pre-filled Excel template; custom header variants still work.</div>
                      </div>
                      <a className="btn btn-outline" href={getAuthUrl("/api/students/bulk-import/template")} download="NextGen-students-template.xlsx" style={{ whiteSpace: "nowrap", textDecoration: "none" }}>Download Template</a>
                    </div>

                    <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.55, marginBottom: 14 }}>
                      Recognized columns include <strong>Roll Number, Name, Parent Phone, Student Phone, Email, Address</strong> and the other student fields.
                      Column names don't need to match exactly — close variants (like "Rollnumber" or "Aadhaar No") are matched automatically.
                      Existing data is preserved when a matching cell is blank. Any column that isn't recognized is listed after import, not silently dropped.
                    </div>

                    {importError && <div className="login-error" style={{ marginBottom: 16 }}>{importError}</div>}

                    <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                      <button type="button" className="btn btn-outline" onClick={closeImportModal} disabled={importing}>Cancel</button>
                      <button type="button" className="btn" onClick={handleImportSubmit} disabled={!importFile || !importBranch || !importYear || !importSemester || importing} style={{ fontWeight: 800, opacity: !importFile || !importBranch || !importYear || !importSemester || importing ? 0.6 : 1 }}>
                        {importing ? "Importing…" : importMode === "merge" ? "Import & Merge" : "Import New Students"}
                      </button>
                    </div>
                  </>
                )}
              </>
            )}

            {importResult && (
              <>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>
                  {importResult.branch} · Year {importResult.year} · Semester {importResult.semester} · {importResult.mode === "merge" ? "Merge mode" : "Create-only mode"}
                </div>
                <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
                  <span className="chip" style={{ background: "#dcfce7", color: "#166534", fontWeight: 800, padding: "4px 10px" }}>✅ {importResult.created_count} created</span>
                  <span className="chip" style={{ background: "#dbeafe", color: "#1d4ed8", fontWeight: 800, padding: "4px 10px" }}>↻ {importResult.updated_count} updated</span>
                  <span className="chip" style={{ background: "#fef9c3", color: "#854d0e", fontWeight: 800, padding: "4px 10px" }}>⏭️ {importResult.skipped_count} skipped</span>
                  <span className="chip" style={{ background: "#fee2e2", color: "#991b1b", fontWeight: 800, padding: "4px 10px" }}>❌ {importResult.failed_count} failed</span>
                </div>

                {/* WHY: per Boss — a clean run with zero failed rows must not
                    read as "the whole sheet was used" when a column was
                    actually ignored. This section is never hidden purely
                    because ignored.length is 0 — an empty ignored list is
                    itself the useful confirmation that nothing was skipped. */}
                <div style={{ marginBottom: 16, border: "1px solid var(--border)", borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 8 }}>Column Mapping</div>
                  {importResult.column_mapping.mapped.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: importResult.column_mapping.ignored.length > 0 ? 10 : 0 }}>
                      {importResult.column_mapping.mapped.map((m) => (
                        <span key={m.header} className="chip" style={{ background: "#dcfce7", color: "#166534", fontWeight: 700, padding: "3px 9px", fontSize: 11.5 }} title={m.matched_via === "fuzzy" ? "Matched by similarity" : "Exact match"}>
                          "{m.header}" → {importFieldLabel(m.field)}{m.matched_via === "fuzzy" ? " ~" : ""}
                        </span>
                      ))}
                    </div>
                  )}
                  {importResult.column_mapping.ignored.length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {importResult.column_mapping.ignored.map((header) => (
                        <span key={header} className="chip" style={{ background: "#f1f5f9", color: "var(--muted)", fontWeight: 700, padding: "3px 9px", fontSize: 11.5 }}>
                          "{header}" ignored
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontSize: 11.5, color: "var(--muted)" }}>Every column in the sheet was recognized — nothing was ignored.</div>
                  )}
                </div>

                {importResult.created.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 6 }}>New Logins Created</div>
                    <div style={{ maxHeight: 180, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead><tr><th>Roll No</th><th>Name</th><th>Username</th><th>Password</th></tr></thead>
                        <tbody>{importResult.created.map((r) => <tr key={r.roll_no}><td>{r.roll_no}</td><td>{r.name}</td><td>{r.username}</td><td style={{ fontFamily: "monospace" }}>{r.password}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult.updated.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 6 }}>Updated Students</div>
                    <div style={{ maxHeight: 150, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead><tr><th>Row</th><th>Roll No</th><th>Name</th></tr></thead>
                        <tbody>{importResult.updated.map((r) => <tr key={`${r.row}-${r.roll_no}`}><td>{r.row}</td><td>{r.roll_no}</td><td>{r.name}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult.skipped.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "var(--text)", marginBottom: 6 }}>Skipped Rows</div>
                    <div style={{ maxHeight: 140, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead><tr><th>Row</th><th>Roll No</th><th>Reason</th></tr></thead>
                        <tbody>{importResult.skipped.map((r) => <tr key={`${r.row}-${r.roll_no}`}><td>{r.row}</td><td>{r.roll_no}</td><td>{r.reason}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                {importResult.failed.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 800, color: "#991b1b", marginBottom: 6 }}>Failed Rows</div>
                    <div style={{ maxHeight: 150, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <table className="data-table" style={{ fontSize: 12.5 }}>
                        <thead><tr><th>Row</th><th>Roll No</th><th>Reason</th></tr></thead>
                        <tbody>{importResult.failed.map((r) => <tr key={`${r.row}-${r.roll_no}`}><td>{r.row}</td><td>{r.roll_no}</td><td>{r.reason}</td></tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                  <button type="button" className="btn btn-outline" onClick={closeImportModal}>Close</button>
                  <button type="button" className="btn" onClick={openImportModal} style={{ fontWeight: 800 }}>Import Another File</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}