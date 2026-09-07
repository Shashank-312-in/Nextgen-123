// HOD Dashboard — 15-day (or picked-date) session log.
// Mirrors webapp/routes/dashboard.py's hod_home() view,
// ported to React + JSON as Group 2 of the rewrite plan.
import { useState, useEffect, useCallback } from "react";
import {
  type HodDashboardData,
  type SessionRow,
  type SessionRosterData,
  getDashboard,
  getSessionPresent,
  getSessionAbsent,
} from "../../api/dashboard";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { registerPdfUrl, getSetup, type SemesterOption } from "../../api/attendance";
import { AppShell } from "../../components/AppShell";

interface HodDashboardProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

// ──────────────────────────────────────────────
// Roster overlay panel (present/absent list)
// ──────────────────────────────────────────────

interface RosterPanelProps {
  data: SessionRosterData | null;
  loading: boolean;
  onClose: () => void;
}

function RosterPanel({ data, loading, onClose }: RosterPanelProps) {
  // Close on Escape key
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const title = data
    ? `${data.kind === "present" ? "Present" : "Absent"} · ${data.session.subject_name}`
    : "";
  const subtitle = data
    ? `${data.session.attendance_date} · ${data.session.session_type}`
    : "";

  return (
    <div className="roster-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="roster-panel" onClick={(e) => e.stopPropagation()}>
        <div className="roster-panel-head">
          <div>
            <h3>{loading ? "Loading…" : title}</h3>
            {subtitle && (
              <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>{subtitle}</div>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!loading && data && (
              <a
                href={registerPdfUrl(data.session.id, data.kind)}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-outline btn-sm"
                style={{ textDecoration: "none" }}
              >
                🖨️ Print PDF
              </a>
            )}
            <button
              id="roster-close-btn"
              className="btn btn-outline btn-sm"
              onClick={onClose}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="roster-panel-body">
          {loading && (
            <div className="empty-note">Loading…</div>
          )}
          {!loading && data && data.students.length === 0 && (
            <div className="empty-note">No students in this list.</div>
          )}
          {!loading && data && data.students.map((s) => (
            <div className="roster-entry" key={s.roll_no}>
              <span className="roll">{s.roll_no}</span>
              <span>{s.name}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Session Info Modal (Detailed Breakdown View)
// ──────────────────────────────────────────────

interface SessionInfoModalProps {
  session: SessionRow;
  onClose: () => void;
  onShowPresent: (id: number) => void;
  onShowAbsent: (id: number) => void;
}

function SessionInfoModal({ session, onClose, onShowPresent, onShowAbsent }: SessionInfoModalProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const total = session.total_marked || (session.present_count + session.absent_count);
  const pct = total > 0 ? Math.round((session.present_count / total) * 100) : 0;
  const facultyLabel = session.faculty_name || session.faculty_username;

  return (
    <div className="modal-overlay-3d" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card-3d" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={{
          padding: "20px 24px",
          background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
          color: "white",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start"
        }}>
          <div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
              <span className={`chip ${session.session_type === "LAB" ? "chip-yellow" : "chip-green"}`} style={{ fontSize: 11 }}>
                {session.session_type === "LAB" ? `LAB · ${session.duration_hours}h` : `CLASS · ${session.duration_hours}h`}
              </span>
              <span style={{ fontSize: 12, color: "#94a3b8", fontWeight: 600 }}>{session.subject_code}</span>
            </div>
            <h3 style={{ margin: 0, fontSize: 19, fontWeight: 800, color: "#ffffff" }}>{session.subject_name}</h3>
            <div style={{ color: "#94a3b8", fontSize: 13, marginTop: 4 }}>
              📅 {session.attendance_date}
            </div>
          </div>
          <button
            className="btn btn-outline btn-sm"
            onClick={onClose}
            style={{ color: "white", borderColor: "rgba(255,255,255,0.3)", borderRadius: "50%", width: 32, height: 32, padding: 0 }}
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: "22px 24px", overflowY: "auto", flex: 1 }}>
          {/* Details Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
            <div style={{ background: "var(--chip-bg-muted)", padding: 14, borderRadius: 12, border: "1px solid var(--border)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Faculty</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text)", marginTop: 4 }}>{facultyLabel}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>@{session.faculty_username}</div>
            </div>
            <div style={{ background: "var(--chip-bg-muted)", padding: 14, borderRadius: 12, border: "1px solid var(--border)" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Turnout Rate</div>
              <div style={{ fontSize: 24, fontWeight: 800, color: pct >= 75 ? "#059669" : pct >= 50 ? "#d97706" : "#dc2626", marginTop: 2 }}>
                {pct}%
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{session.present_count} / {total} Attended</div>
            </div>
          </div>

          {/* Topic Section */}
          <div style={{ marginBottom: 20, background: "var(--chip-bg-muted)", padding: 16, borderRadius: 12, border: "1px solid var(--border)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--heading-accent)", textTransform: "uppercase", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
              📝 Session Topic / Coverage
            </div>
            <div style={{ fontSize: 14, color: "var(--text)", lineHeight: 1.5, fontWeight: 500 }}>
              {session.topic || "No specific topic detail entered for this session."}
            </div>
          </div>

          {/* Progress Bar */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
              <span>Attendance Distribution</span>
              <span>{pct}% Present</span>
            </div>
            <div style={{ height: 10, borderRadius: 5, background: "#e2e8f0", overflow: "hidden", display: "flex" }}>
              <div style={{ width: `${pct}%`, background: "#10b981", transition: "width 0.5s ease" }} />
              <div style={{ width: `${100 - pct}%`, background: "#ef4444", transition: "width 0.5s ease" }} />
            </div>
          </div>

          {/* Action Links */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", paddingTop: 10, borderTop: "1px solid #e2e8f0" }}>
            <button
              className="btn-3d btn-3d-present"
              style={{ flex: 1, minWidth: 140 }}
              onClick={() => { onClose(); onShowPresent(session.id); }}
            >
              ✓ {session.present_count} Present
            </button>
            <button
              className="btn-3d btn-3d-absent"
              style={{ flex: 1, minWidth: 140 }}
              onClick={() => { onClose(); onShowAbsent(session.id); }}
            >
              ✗ {session.absent_count} Absent
            </button>
            <a
              href={registerPdfUrl(session.id, "present")}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-3d btn-3d-info"
              style={{ textDecoration: "none", width: "100%", justifyContent: "center" }}
            >
              🖨️ Download PDF Register
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Single 3D session row
// ──────────────────────────────────────────────

interface SessionCardProps {
  session: SessionRow;
  onShowPresent: (id: number) => void;
  onShowAbsent:  (id: number) => void;
  onShowInfo:    (session: SessionRow) => void;
}

function SessionCard({ session, onShowPresent, onShowAbsent, onShowInfo }: SessionCardProps) {
  const typeLabel = session.session_type === "LAB"
    ? `Lab · ${session.duration_hours}h`
    : `Class · ${session.duration_hours}h`;

  const facultyLabel = session.faculty_name || session.faculty_username;

  return (
    <div className="session-row-3d">
      <div style={{ flex: 1, minWidth: 200 }}>
        <div className="session-title-3d">
          <span className={`chip ${session.session_type === "LAB" ? "chip-yellow" : "chip-green"}`} style={{ fontSize: 10, padding: "2px 8px" }}>
            {session.session_type}
          </span>
          {session.subject_name}
        </div>
        <div className="session-meta-3d">
          <span>{typeLabel}</span>
          <span>•</span>
          <span>👤 {facultyLabel}</span>
          {session.topic && (
            <>
              <span>•</span>
              <span style={{ fontStyle: "italic", color: "#475467" }}>
                "{session.topic.length > 40 ? session.topic.substring(0, 40) + '…' : session.topic}"
              </span>
            </>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
        {/* NEW: 3D Info Icon Button */}
        <button
          className="btn-3d btn-3d-info"
          onClick={() => onShowInfo(session)}
          title="View detailed information"
        >
          👁️ Info
        </button>
        <button
          id={`session-${session.id}-present-btn`}
          className="btn-3d btn-3d-present"
          onClick={() => onShowPresent(session.id)}
          title="Show present students"
        >
          ✓ {session.present_count} Present
        </button>
        <button
          id={`session-${session.id}-absent-btn`}
          className={session.absent_count > 0 ? "btn-3d btn-3d-absent" : "btn-3d btn-3d-muted"}
          onClick={() => onShowAbsent(session.id)}
          title="Show absent students"
        >
          ✗ {session.absent_count} Absent
        </button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Main HOD Dashboard
// ──────────────────────────────────────────────

export function HodDashboard({ user, onLoggedOut }: HodDashboardProps) {
  const [data, setData]                 = useState<HodDashboardData | null>(null);
  const [error, setError]               = useState<string | null>(null);
  const [loading, setLoading]           = useState(true);
  const [pickedDate, setPickedDate]       = useState<string>("");
  const [pickedSemId, setPickedSemId]   = useState<number | "">("");
  const [pickedYear, setPickedYear]     = useState<string>(""); // "" | "1" | "2" | "3" | "4"
  const [semesters, setSemesters]       = useState<SemesterOption[]>([]);

  // Roster panel state
  const [rosterData, setRosterData]       = useState<SessionRosterData | null>(null);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterOpen, setRosterOpen]       = useState(false);

  // Info modal state
  const [activeSessionInfo, setActiveSessionInfo] = useState<SessionRow | null>(null);

  // Load semesters list on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await getSetup();
        setSemesters(res.semesters);
      } catch {
        // ignore setup error on dashboard
      }
    })();
  }, []);

  const load = useCallback(async (date?: string, semId?: number, year?: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getDashboard(date || undefined, semId || undefined, year || undefined);
      if (res.role !== "HOD") return; // shouldn't happen
      setData(res as HodDashboardData);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not connect to the server. Please check your connection.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleDateChange(e: React.ChangeEvent<HTMLInputElement>) {
    const d = e.target.value;
    setPickedDate(d);
    load(d || undefined, pickedSemId === "" ? undefined : pickedSemId, pickedYear || undefined);
  }

  function handleSemesterChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value ? Number(e.target.value) : "";
    setPickedSemId(val);
    if (val !== "") {
      const chosenSem = semesters.find((s) => s.id === val);
      if (chosenSem) {
        const y = semYearNumber(chosenSem.code);
        if (y > 0) setPickedYear(String(y));
      }
    }
    load(pickedDate || undefined, val === "" ? undefined : val, undefined);
  }

  function handleYearChange(year: string) {
    const newYear = pickedYear === year ? "" : year; // toggle
    setPickedYear(newYear);
    setPickedSemId(""); // clear semester when year chosen
    load(pickedDate || undefined, undefined, newYear || undefined);
  }

  function semYearNumber(code: string): number {
    if (/^IV-/.test(code)) return 4;
    if (/^III-/.test(code)) return 3;
    if (/^II-/.test(code)) return 2;
    if (/^I-/.test(code)) return 1;
    return 0;
  }

  const visibleSemesters = semesters.filter((s) => {
    if (pickedYear === "") return true;
    return semYearNumber(s.code) === Number(pickedYear);
  });

  function getBatchLabel(code: string): string {
    const y = semYearNumber(code);
    if (y === 1) return "2026-2030 Batch";
    if (y === 2) return "2025-2029 Batch";
    if (y === 3) return "2024-2028 Batch";
    if (y === 4) return "2023-2027 Batch";
    return "";
  }

  function handleClearDate() {
    setPickedDate("");
    load(undefined, pickedSemId === "" ? undefined : pickedSemId, pickedYear || undefined);
  }

  function handleClearFilters() {
    setPickedDate("");
    setPickedSemId("");
    setPickedYear("");
    load();
  }

  async function openRoster(sessionId: number, kind: "present" | "absent") {
    setRosterData(null);
    setRosterLoading(true);
    setRosterOpen(true);
    try {
      const res = kind === "present"
        ? await getSessionPresent(sessionId)
        : await getSessionAbsent(sessionId);
      setRosterData(res);
    } catch {
      setRosterData(null);
    } finally {
      setRosterLoading(false);
    }
  }

  // Count all sessions across all days for the stats bar
  const totalSessions = data ? Object.values(data.days).reduce((n, rows) => n + rows.length, 0) : 0;
  const totalAbsent   = data ? Object.values(data.days).flat().reduce((n, r) => n + r.absent_count, 0) : 0;
  const totalPresent  = data ? Object.values(data.days).flat().reduce((n, r) => n + r.present_count, 0) : 0;
  const dayCount      = data ? Object.keys(data.days).length : 0;

  const totalStudentsMarked = totalPresent + totalAbsent;
  const overallTurnoutPct   = totalStudentsMarked > 0 ? Math.round((totalPresent / totalStudentsMarked) * 100) : 100;

  const dayKeys = data ? Object.keys(data.days).sort((a, b) => b.localeCompare(a)) : [];

  // Format "2026-07-25" → "Fri, 25 Jul 2026"
  function fmtDate(s: string): string {
    try {
      return new Date(s + "T00:00:00").toLocaleDateString("en-IN", {
        weekday: "short", day: "numeric", month: "short", year: "numeric",
      });
    } catch { return s; }
  }

  return (
    <AppShell user={user} activeNav="home" heading="Attendance" onLoggedOut={onLoggedOut}>
      {/* 3D Stat Cards */}
      <div className="stat-row-3d">
        <div className="stat-card-3d">
          <div className="stat-icon-3d">📅</div>
          <div className="stat-info-3d">
            <div className="stat-title">Days with sessions</div>
            <div className="stat-value">{loading ? "…" : dayCount}</div>
          </div>
        </div>
        <div className="stat-card-3d">
          <div className="stat-icon-3d">📰</div>
          <div className="stat-info-3d">
            <div className="stat-title">Total sessions</div>
            <div className="stat-value">{loading ? "…" : totalSessions}</div>
          </div>
        </div>
        <div className="stat-card-3d">
          <div className="stat-icon-3d" style={{ color: "var(--red)" }}>🔴</div>
          <div className="stat-info-3d">
            <div className="stat-title">Total absences</div>
            <div className="stat-value" style={{ color: totalAbsent > 0 ? "var(--red)" : undefined }}>
              {loading ? "…" : totalAbsent}
            </div>
          </div>
        </div>
        <div className="stat-card-3d">
          <div className="stat-icon-3d">📊</div>
          <div className="stat-info-3d">
            <div className="stat-title">Turnout Rate</div>
            <div className="stat-value" style={{ color: overallTurnoutPct >= 75 ? "#10b981" : "#f59e0b" }}>
              {loading ? "…" : `${overallTurnoutPct}%`}
            </div>
          </div>
        </div>
      </div>

      {/* Date, Year & Semester toolbar */}
      <div className="dash-toolbar">

        {/* Year segment control */}
        <span className="toolbar-label">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/></svg>
          Year
        </span>
        <div className="year-filter-group">
          {[
            { label: "All",  value: "" },
            { label: "1st",  value: "1" },
            { label: "2nd",  value: "2" },
            { label: "3rd",  value: "3" },
            { label: "4th",  value: "4" },
          ].map(({ label, value }) => (
            <button
              key={value}
              type="button"
              className={`year-filter-btn${pickedYear === value ? " active" : ""}`}
              onClick={() => value === "" ? handleClearFilters() : handleYearChange(value)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="toolbar-divider" />

        {/* Date filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="toolbar-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            Date
          </span>
          <input
            id="date-picker"
            type="date"
            value={pickedDate}
            onChange={handleDateChange}
            style={{ height: 36, padding: "0 12px", border: "1.5px solid var(--border)", borderRadius: 10, fontSize: 13, fontWeight: 700, background: "var(--input-bg)", color: "var(--text)", outline: "none" }}
          />
        </div>

        <div className="toolbar-divider" />

        {/* Semester filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="toolbar-label">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
            Sem
          </span>
          <select
            id="semester-filter"
            value={pickedSemId}
            onChange={handleSemesterChange}
            className="input-field"
            style={{ height: 36, fontSize: 13, fontWeight: 700, width: "auto", minWidth: 160 }}
          >
            <option value="">— All —</option>
            {visibleSemesters.map((s) => {
              const batch = getBatchLabel(s.code);
              return (
                <option key={s.id} value={s.id}>
                  {s.code} — {s.name} {batch ? `(${batch})` : ""}
                </option>
              );
            })}
          </select>
        </div>

        {(pickedDate || pickedSemId !== "" || pickedYear !== "") && (
          <button id="clear-filters-btn" className="btn-3d btn-3d-info" style={{ height: 36, marginLeft: "auto" }} onClick={handleClearFilters}>
            ✕ Clear
          </button>
        )}
      </div>


      {/* Session list */}
      {loading && <div className="empty-note">Loading…</div>}
      {error && (
        <div className="dash-error-card">
          <span className="dash-error-icon">⚠️</span>
          <div>
            <strong>Could not load dashboard</strong>
            <div style={{ fontSize: 13, marginTop: 4, opacity: 0.8 }}>{error}</div>
          </div>
          <button className="btn btn-outline btn-sm" onClick={() => load(pickedDate || undefined)}>
            🔄 Try Again
          </button>
        </div>
      )}
      {!loading && !error && dayKeys.length === 0 && (
        <div className="card card-pad empty-note">
          No sessions recorded in this period.
        </div>
      )}
      {!loading && !error && dayKeys.map((date) => (
        <div className="day-group-3d" key={date}>
          <div className="day-label-3d">{fmtDate(date)}</div>
          {(data!.days[date]).map((sess) => (
            <SessionCard
              key={sess.id}
              session={sess}
              onShowPresent={(id) => openRoster(id, "present")}
              onShowAbsent={(id) => openRoster(id, "absent")}
              onShowInfo={(s) => setActiveSessionInfo(s)}
            />
          ))}
        </div>
      ))}

      {/* Roster overlay */}
      {rosterOpen && (
        <RosterPanel
          data={rosterData}
          loading={rosterLoading}
          onClose={() => setRosterOpen(false)}
        />
      )}

      {/* Detailed Info Modal */}
      {activeSessionInfo && (
        <SessionInfoModal
          session={activeSessionInfo}
          onClose={() => setActiveSessionInfo(null)}
          onShowPresent={(id) => openRoster(id, "present")}
          onShowAbsent={(id) => openRoster(id, "absent")}
        />
      )}
    </AppShell>
  );
}
