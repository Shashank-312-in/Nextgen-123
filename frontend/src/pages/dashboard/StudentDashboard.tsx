// Student Dashboard — subject-wise attendance % per enrolled subject,
// color-coded by band. Tap a subject to see session history inline.
// Mirrors webapp/routes/dashboard.py's student_home() view, ported to React.
import { useState, useEffect, useCallback } from "react";
import {
  type StudentDashboardData,
  type SubjectAttendance,
  type SubjectHistoryData,
  type AttendanceBand,
  getDashboard,
  getSubjectHistory,
} from "../../api/dashboard";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";

interface StudentDashboardProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

function pctClass(band: AttendanceBand): string {
  return `pct-${band}`;
}

function bandChipClass(band: AttendanceBand): string {
  return `chip chip-${band}`;
}

function bandLabel(band: AttendanceBand): string {
  if (band === "green")  return "Good";
  if (band === "yellow") return "Low";
  if (band === "red")    return "Critical";
  return "No data";
}

function fmtDate(s: string): string {
  try {
    return new Date(s + "T00:00:00").toLocaleDateString("en-IN", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch { return s; }
}

// ──────────────────────────────────────────────
// Subject card with inline history toggle
// ──────────────────────────────────────────────

interface SubjectCardProps {
  subj: SubjectAttendance;
}

function SubjectCard({ subj }: SubjectCardProps) {
  const [open, setOpen]       = useState(false);
  const [history, setHistory] = useState<SubjectHistoryData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (history) return; // already loaded
    setLoading(true);
    setError(null);
    try {
      const res = await getSubjectHistory(subj.subject_id);
      setHistory(res);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }

  const pctDisplay = subj.pct !== null ? `${subj.pct}%` : "—";

  return (
    <div
      id={`subject-card-${subj.subject_id}`}
      className={`subject-card${open ? " open" : ""}`}
      onClick={toggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") toggle(); }}
      aria-expanded={open}
    >
      <div className="subj-header">
        <div>
          <div className="subj-name">{subj.name}</div>
          <div className="subj-code">{subj.code}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className={`subj-pct ${pctClass(subj.band)}`}>{pctDisplay}</div>
          <span className={bandChipClass(subj.band)} style={{ marginTop: 4 }}>
            {bandLabel(subj.band)}
          </span>
        </div>
      </div>
      <div className="subj-meta">
        {subj.present} present / {subj.total} sessions
      </div>

      {open && (
        <div className="subj-history" onClick={(e) => e.stopPropagation()}>
          {loading && <div style={{ color: "var(--muted)", fontSize: 12, padding: "8px 0" }}>Loading…</div>}
          {error   && <div style={{ color: "var(--red)",   fontSize: 12, padding: "8px 0" }}>{error}</div>}
          {!loading && !error && history && history.sessions.length === 0 && (
            <div style={{ color: "var(--muted)", fontSize: 12, padding: "8px 0" }}>No sessions recorded.</div>
          )}
          {!loading && !error && history && history.sessions.map((sess, i) => (
            <div className="subj-history-row" key={i}>
              <span>{fmtDate(sess.attendance_date)} · {sess.session_type} ({sess.duration_hours}h)</span>
              <span
                style={{
                  color:      sess.status === "Present" ? "#047857"
                            : sess.status === "Absent"  ? "#b91c1c"
                            : "var(--muted)",
                  fontWeight: 800,
                }}
              >
                {sess.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────
// Main Student Dashboard
// ──────────────────────────────────────────────

export function StudentDashboard({ user, onLoggedOut }: StudentDashboardProps) {
  const [data,    setData]    = useState<StudentDashboardData | null>(null);
  const [error,   setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getDashboard();
      if (res.role !== "STUDENT") return;
      setData(res as StudentDashboardData);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Summary stats
  const overallPct = data && data.subjects.length > 0
    ? (() => {
        const totalSess    = data.subjects.reduce((n, s) => n + s.total,   0);
        const totalPresent = data.subjects.reduce((n, s) => n + s.present, 0);
        return totalSess > 0 ? Math.round(totalPresent * 100 / totalSess) : null;
      })()
    : null;

  const criticalCount = data
    ? data.subjects.filter((s) => s.band === "red").length
    : 0;

  const whoami = `${data?.student.name || user.username}${data?.student.roll_no ? ` · ${data.student.roll_no}` : ""}`;

  return (
    <AppShell user={user} activeNav="home" heading="My Attendance" whoami={whoami} onLoggedOut={onLoggedOut}>
      {/* 3D Stats */}
      <div className="stat-row-3d">
        <div className="stat-card-3d">
          <div className="stat-icon-3d">📊</div>
          <div className="stat-info-3d">
            <div className="stat-title">Overall attendance</div>
            <div
              className="stat-value"
              style={{
                color: overallPct === null ? undefined
                     : overallPct >= 75   ? "#059669"
                     : overallPct >= 50   ? "#d97706"
                     : "#dc2626",
              }}
            >
              {loading ? "…" : overallPct !== null ? `${overallPct}%` : "—"}
            </div>
          </div>
        </div>
        <div className="stat-card-3d">
          <div className="stat-icon-3d">📚</div>
          <div className="stat-info-3d">
            <div className="stat-title">Subjects</div>
            <div className="stat-value">{loading ? "…" : data?.subjects.length ?? 0}</div>
          </div>
        </div>
        {criticalCount > 0 && (
          <div className="stat-card-3d">
            <div className="stat-icon-3d" style={{ color: "var(--red)" }}>🔴</div>
            <div className="stat-info-3d">
              <div className="stat-title">Critical (&lt;50%)</div>
              <div className="stat-value" style={{ color: "var(--red)" }}>{criticalCount}</div>
            </div>
          </div>
        )}
      </div>

          {loading && <div className="empty-note">Loading…</div>}
          {error   && <div className="login-error">{error}</div>}
          {!loading && !error && data && data.subjects.length === 0 && (
            <div className="card card-pad empty-note">
              No attendance records found yet. Check back after sessions are recorded.
            </div>
          )}

          {!loading && !error && data && data.subjects.length > 0 && (
            <>
              <p className="welcome-line">
                Tap a subject to see your session-by-session attendance history.
              </p>
              <div className="subject-cards">
                {data.subjects.map((s) => (
                  <SubjectCard key={s.subject_id} subj={s} />
                ))}
              </div>
            </>
          )}
    </AppShell>
  );
}
