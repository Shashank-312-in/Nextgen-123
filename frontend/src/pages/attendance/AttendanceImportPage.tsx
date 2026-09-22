import { useEffect, useState } from "react";
import { AppShell } from "../../components/AppShell";
import { ApiClientError, getAuthUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import {
  getAttendanceImportOptions,
  uploadAttendanceImport,
  type AttendanceImportOptions,
  type AttendanceImportResult,
} from "../../api/attendance";
import "../../styles/ng-flat-controls.css";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

// — AttendanceImportPage —
// HOD-only historical attendance backfill. Structurally mirrors
// ResultsUploadPage.tsx (spec §3.4): options-driven dropdown, file
// picker + template link, submit, then a summary panel with metric
// tiles and two collapsible details sections. Reuses the existing
// results-upload-* classes for the summary shell so the visual
// language matches the established importer pattern; buttons use the
// flat ng-flat-btn system instead of the gradient .btn class.
export function AttendanceImportPage({ user, onLoggedOut }: Props) {
  const [options, setOptions] = useState<AttendanceImportOptions | null>(null);
  const [semesterId, setSemesterId] = useState<number | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AttendanceImportResult | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const res = await getAttendanceImportOptions();
        setOptions(res);
        const active = res.semesters.find(s => s.active);
        if (active) setSemesterId(active.id);
        else if (res.semesters.length) setSemesterId(res.semesters[0].id);
      } catch (err) {
        setError(err instanceof ApiClientError ? err.message : "Failed to load attendance import options");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function pickFile(f: File | null) {
    setFile(f);
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!semesterId || !file) { setError("Choose a semester and an Excel file."); return; }
    setUploading(true); setError(null); setResult(null);
    try {
      const res = await uploadAttendanceImport(Number(semesterId), file);
      setResult(res);
      setFile(null);
      const input = document.getElementById("attendance-import-file") as HTMLInputElement | null;
      if (input) input.value = "";
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Attendance import failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <AppShell user={user} activeNav="attendance-import" heading="Import Attendance" onLoggedOut={onLoggedOut}>
      {error && <div className="error-banner">{error}</div>}
      <div className="detail-box">
        <h2 style={{ margin: "0 0 6px", fontSize: 20 }}>Import Historical Attendance</h2>
        <p className="subtitle-muted" style={{ maxWidth: 640, margin: "0 0 20px" }}>
          Upload one row per student, date and subject. Rows sharing the same date and subject are grouped into a
          single session. Roll numbers not registered under your department are skipped and reported below —
          nothing else fails because of them.
        </p>

        {loading ? <p className="empty-note">Loading…</p> : (
          <form onSubmit={handleSubmit} style={{ maxWidth: 640 }}>
            <div className="field" style={{ maxWidth: 340, marginBottom: 18 }}>
              <label>Semester *</label>
              <select className="ng-flat-select" style={{ width: "100%" }} value={semesterId} onChange={e => setSemesterId(e.target.value ? Number(e.target.value) : "")} required>
                <option value="">— Select semester —</option>
                {options?.semesters.map(s => (
                  <option key={s.id} value={s.id}>{s.name} ({s.code}){!s.active ? " [inactive]" : ""}</option>
                ))}
              </select>
            </div>

            <div
              className="ng-flat-card"
              style={{
                margin: "0 0 18px",
                padding: 20,
                borderStyle: dragOver ? "dashed" : "solid",
                borderColor: dragOver ? "var(--ng-accent)" : "var(--ng-line)",
                background: dragOver ? "var(--ng-accent-soft)" : "var(--ng-surface-2)",
              }}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => {
                e.preventDefault();
                setDragOver(false);
                const dropped = e.dataTransfer.files?.[0];
                if (dropped) pickFile(dropped);
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontWeight: 800, marginBottom: 4 }}>Excel file *</div>
                  <div className="subtitle-muted" style={{ lineHeight: 1.55 }}>
                    {file ? file.name : "Drag a .xlsx / .xlsm file here, or choose one below."}
                  </div>
                </div>
                <a
                  className="ng-flat-btn ng-flat-btn-outline ng-flat-btn-sm"
                  href={getAuthUrl("/api/attendance/bulk-import/template")}
                  download="NextGen-attendance-template.xlsx"
                >
                  Download Template
                </a>
              </div>
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--ng-line)" }}>
                <input
                  id="attendance-import-file"
                  type="file"
                  accept=".xlsx,.xlsm"
                  onChange={e => pickFile(e.target.files?.[0] ?? null)}
                  required
                />
              </div>
              <div className="subtitle-muted" style={{ lineHeight: 1.65, marginTop: 14 }}>
                Required columns: <strong>Roll No, Date, Status</strong> (Present/Absent, or P/A, 1/0, Yes/No), and either{" "}
                <strong>Subject Code</strong> or <strong>Subject Name</strong>. Optional: Session Type (CLASS/LAB),
                Duration Hours, Topic — a missing Topic defaults to "Imported attendance".
              </div>
            </div>

            <button className="ng-flat-btn ng-flat-btn-primary ng-flat-btn-block" type="submit" disabled={uploading}>
              {uploading ? "Validating & Importing…" : "Import Attendance"}
            </button>
          </form>
        )}

        {result && (
          <section className="results-upload-summary ng-import-result" aria-live="polite">
            <div className="results-upload-summary-head">
              <div>
                <div className="results-upload-kicker">Import complete</div>
                <h3>Attendance imported successfully</h3>
                <p>{result.semester_code}</p>
              </div>
            </div>

            <div className="ng-flat-metric-row" style={{ marginBottom: 4 }}>
              <div className="ng-flat-metric">
                <strong>{result.sessions_created}</strong>
                <span>Sessions created</span>
              </div>
              <div className="ng-flat-metric">
                <strong>{result.records_written}</strong>
                <span>Records written</span>
              </div>
              <div className={`ng-flat-metric ${result.skipped_count > 0 ? "is-warning" : ""}`}>
                <strong>{result.skipped_count}</strong>
                <span>Not registered · skipped</span>
              </div>
            </div>
            <div className="subtitle-muted" style={{ margin: "10px 0 16px" }}>
              {result.sessions_updated} existing session{result.sessions_updated === 1 ? "" : "s"} updated ·{" "}
              {result.students_affected} student{result.students_affected === 1 ? "" : "s"} affected
            </div>

            {result.skipped_count > 0 && (
              <details className="results-upload-detail results-upload-warning">
                <summary>
                  <span>
                    <strong>{result.skipped_count} student{result.skipped_count === 1 ? " was" : "s were"} skipped</strong>
                    <small>These roll numbers are not registered in your department scope.</small>
                  </span>
                  <span className="results-upload-summary-chevron" aria-hidden="true">⌄</span>
                </summary>
                <div className="results-upload-skipped-list">
                  {result.skipped_students.map((student, i) => (
                    <div className="results-upload-skipped-row" key={`${student.roll_no}-${student.row}-${i}`}>
                      <code>{student.roll_no}</code>
                      <span>Excel row {student.row}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <details className="results-upload-detail">
              <summary>
                <span>
                  <strong>Import details</strong>
                  <small>Column matching and ignored headers</small>
                </span>
                <span className="results-upload-summary-chevron" aria-hidden="true">⌄</span>
              </summary>
              <div className="results-upload-details-body">
                <div className="results-upload-detail-title">Recognized columns</div>
                <div className="results-upload-chips">
                  {result.column_mapping.mapped.map((m, i) => (
                    <span key={`${m.header}-${m.field}-${i}`} className="results-upload-chip" title={m.matched_via === "fuzzy" ? "Similarity matched" : "Exact normalized match"}>
                      {m.header} → {m.field}{m.matched_via === "fuzzy" ? " ~" : ""}
                    </span>
                  ))}
                </div>
                {result.column_mapping.ignored.length > 0 && (
                  <>
                    <div className="results-upload-detail-title" style={{ marginTop: 14 }}>Ignored columns</div>
                    <div className="results-upload-chips">
                      {result.column_mapping.ignored.map((header, i) => (
                        <span key={`${header}-${i}`} className="results-upload-chip results-upload-chip-muted">{header}</span>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </details>
          </section>
        )}
      </div>
    </AppShell>
  );
}
