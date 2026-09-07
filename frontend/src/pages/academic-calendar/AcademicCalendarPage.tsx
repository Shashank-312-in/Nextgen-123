// Group 5 — Academic Calendar page for all roles.
// Mirrors webapp/routes/academic_calendar.py + templates/academic_calendar/list.html.
// Semesters are COLLAPSED BY DEFAULT, expanding on click.
// Upload/load errors are shown in RED (.error-banner), NOT green.
import { useState, useEffect } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  getCalendarPage, uploadCalendarFile, deleteCalendarFile,
  type CalendarPageData, type CalendarSemester,
} from "../../api/academicCalendar";
import { ApiClientError, getAuthUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function AcademicCalendarPage({ user, onLoggedOut }: Props) {
  const [data, setData] = useState<CalendarPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null); // `${semId}-${kind}`
  // Collapsed by default — tracks which semester IDs are expanded
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  async function reload() {
    setLoading(true); setError(null);
    try {
      setData(await getCalendarPage());
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load calendar");
    } finally { setLoading(false); }
  }

  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSemester(id: number) {
    setExpanded(prev => ({ ...prev, [id]: !prev[id] }));
  }

  async function handleUpload(sem: CalendarSemester, kind: "timetable" | "calendar", file: File) {
    const key = `${sem.id}-${kind}`;
    setUploading(key);
    setError(null);
    try {
      await uploadCalendarFile(sem.id, kind, file);
      setNotice(`${kind === "timetable" ? "Timetable" : "Academic Calendar"} updated for ${sem.code}`);
      await reload();
    } catch (err) {
      // Error MUST be in RED (.error-banner), NOT green notice
      setError(err instanceof ApiClientError ? err.message : "Upload failed");
    } finally { setUploading(null); }
  }

  async function handleDelete(sem: CalendarSemester, kind: "timetable" | "calendar") {
    const label = kind === "timetable" ? "Timetable" : "Academic Calendar";
    if (!window.confirm(`Delete ${label} for ${sem.code}?`)) return;
    const key = `${sem.id}-${kind}`;
    setUploading(key);
    setError(null);
    try {
      await deleteCalendarFile(sem.id, kind);
      setNotice(`${label} deleted for ${sem.code}`);
      await reload();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Delete failed");
    } finally { setUploading(null); }
  }

  if (loading) return (
    <AppShell user={user} activeNav="academic-calendar" heading="Academic Calendar" onLoggedOut={onLoggedOut}>
      <p className="empty-note">Loading…</p>
    </AppShell>
  );

  return (
    <AppShell user={user} activeNav="academic-calendar" heading="Academic Calendar" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />
      {notice && <ToastPopup type="success" message={notice} onClose={() => setNotice(null)} />}

      {(!data || data.semesters.length === 0) && (
        <p className="empty-note">No calendar documents available for your current semester.</p>
      )}

      {data?.semesters.map((sem) => {
        const isOpen = !!expanded[sem.id];
        return (
          <div key={sem.id} className="cal-semester">
            <div className="cal-sem-head" onClick={() => toggleSemester(sem.id)}>
              <h3>
                <span style={{ marginRight: 8, fontSize: 12 }}>{isOpen ? "▼" : "▶"}</span>
                {sem.name} <span style={{ fontWeight: 400, color: "var(--muted)" }}>({sem.code})</span>
              </h3>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                {isOpen ? "Click to collapse" : "Click to view documents"}
              </span>
            </div>
            {isOpen && (
              <div className="cal-docs">
                {/* Timetable */}
                <DocPanel
                  label="Timetable"
                  path={sem.timetable_path}
                  canEdit={!!data.can_edit}
                  uploading={uploading === `${sem.id}-timetable`}
                  onUpload={file => handleUpload(sem, "timetable", file)}
                  onDelete={() => handleDelete(sem, "timetable")}
                />
                {/* Academic Calendar */}
                <DocPanel
                  label="Academic Calendar"
                  path={sem.calendar_path}
                  canEdit={!!data.can_edit}
                  uploading={uploading === `${sem.id}-calendar`}
                  onUpload={file => handleUpload(sem, "calendar", file)}
                  onDelete={() => handleDelete(sem, "calendar")}
                />
              </div>
            )}
          </div>
        );
      })}
    </AppShell>
  );
}

interface DocPanelProps {
  label: string;
  path: string | null;
  canEdit: boolean;
  uploading: boolean;
  onUpload: (file: File) => void;
  onDelete: () => void;
}

function DocPanel({ label, path, canEdit, uploading, onUpload, onDelete }: DocPanelProps) {
  const fileUrl = path ? getAuthUrl(`/api${path}`) : null;

  return (
    <div className="cal-doc">
      <h4>{label}</h4>
      {fileUrl ? (
        <div style={{ marginBottom: canEdit ? 12 : 0 }}>
          <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-outline">
            📄 View / Download
          </a>
        </div>
      ) : (
        <p style={{ color: "var(--muted)", fontSize: 13, margin: "0 0 8px" }}>Not uploaded yet</p>
      )}
      {canEdit && (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ cursor: "pointer", margin: 0 }}>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              style={{ display: "none" }}
              onChange={e => {
                const file = e.target.files?.[0];
                if (file) onUpload(file);
                e.target.value = "";
              }}
              disabled={uploading}
            />
            <span className={`btn btn-sm ${path ? "btn-outline" : "btn"}`} aria-disabled={uploading}>
              {uploading ? "Uploading…" : path ? "Replace" : "Upload"}
            </span>
          </label>
          {path && (
            <button
              type="button"
              className="btn btn-sm btn-outline"
              style={{ color: "var(--red)", borderColor: "var(--red)" }}
              onClick={onDelete}
              disabled={uploading}
            >
              Remove
            </button>
          )}
        </div>
      )}
    </div>
  );
}
