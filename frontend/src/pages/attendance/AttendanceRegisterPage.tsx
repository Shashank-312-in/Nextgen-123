// Group 3 — Mark Attendance: Register screen.
// GET .../sessions/{id} once on load, then pure client-state for every
// tap/quick-mark/mark-all-present — only /save commits to the DB. See
// api/routes_attendance.py's module docstring and _serialize_roster's
// docstring for why mark-all-present doesn't write to the DB itself: this
// screen calls it, then holds its returned roster as local state exactly
// like any other tap.
//
// Quick Present: ported from the old app's /quick-mark UI (see
// webapp/templates/attendance/_register_body.html and
// webapp/routes/attendance.py's quick_mark()), but implemented entirely
// client-side per plan §2 — no server route for it exists in
// api/routes_attendance.py by design (its docstring lists quick-mark among
// routes "deliberately NOT ported" as a server endpoint), so the matching
// logic (exact roll match, else unambiguous 2/4-digit suffix match) is
// reimplemented in handleQuickMark() below instead of calling an endpoint.
//
// Interaction model: single tap toggles present/absent (Boss's decision,
// this session — supersedes the old app's two-button-per-row UI. See
// SMS_15_REWRITE_HANDOFF_6.md "Open decision, not yet made").
//
// `editable` comes from the server (session_is_editable() — 24h window +
// role) and gates the marking UI here, but the server re-validates on
// /save regardless of what this screen shows/hides — this is UX only, not
// the enforcement boundary.
import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  type AttendanceSession,
  type RosterEntry,
  getSession,
  markAllPresent,
  saveRegister,
  registerPdfUrl,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";

interface AttendanceRegisterPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function AttendanceRegisterPage({ user, onLoggedOut }: AttendanceRegisterPageProps) {
  const navigate = useNavigate();
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>();
  const sessionId = Number(sessionIdParam);

  const [session, setSession] = useState<AttendanceSession | null>(null);
  const [editable, setEditable] = useState(false);
  const [roster, setRoster] = useState<RosterEntry[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [saveNote, setSaveNote] = useState<string | null>(null);

  // Quick Present — ported from the old app's /quick-mark (see
  // webapp/routes/attendance.py's quick_mark()), but purely client-side
  // here per plan §2: no server round trip, just local roster state like
  // any other tap. Accepts full roll numbers or 2/4-digit trailing
  // suffixes, comma/space/newline separated.
  const [quickRolls, setQuickRolls] = useState("");
  const [quickNote, setQuickNote] = useState<string | null>(null);

  // — InitialLoad
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSession(sessionId);
      setSession(res.session);
      setEditable(res.editable);
      setRoster(res.roster);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load register");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (Number.isFinite(sessionId)) load();
  }, [sessionId, load]);

  // — TogglePresent: pure client state, no server round trip per plan §2
  function toggleRow(rollNo: string) {
    if (!editable) return;
    setSaveNote(null);
    setRoster((prev) =>
      prev.map((r) => (r.roll_no === rollNo ? { ...r, present: !r.present } : r))
    );
  }

  // — QuickMark: same token-matching rule as the old app's quick_mark()
  // (webapp/routes/attendance.py) — exact roll match first; failing that,
  // a 2- or 4-digit numeric token matches by trailing-digits suffix, but
  // only if exactly one roll number ends with it (ambiguous suffixes are
  // silently skipped, same as the old handler). Client-side only: this
  // never calls the server, it just flips `present` in local roster state
  // like any other tap — only Save writes to the DB.
  function handleQuickMark() {
    if (!editable || !quickRolls.trim()) return;
    const allRolls = roster.map((r) => r.roll_no);
    const tokens = quickRolls
      .split(/[,;\s]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);

    const toMark = new Set<string>();
    let skipped = 0;
    for (const token of tokens) {
      let matches: string[] = allRolls.includes(token) ? [token] : [];
      if (matches.length === 0 && /^\d+$/.test(token) && (token.length === 2 || token.length === 4)) {
        matches = allRolls.filter((roll) => roll.toUpperCase().endsWith(token));
      }
      matches = Array.from(new Set(matches));
      if (matches.length === 1) {
        toMark.add(matches[0]);
      } else {
        skipped++;
      }
    }

    setSaveNote(null);
    setRoster((prev) => prev.map((r) => (toMark.has(r.roll_no) ? { ...r, present: true } : r)));
    setQuickNote(
      toMark.size === 0
        ? "No matching roll numbers found."
        : `Marked ${toMark.size} present.${skipped > 0 ? ` (${skipped} token(s) unmatched or ambiguous.)` : ""}`
    );
    setQuickRolls("");
  }

  // — MarkAllPresent: server returns the roster with every row flipped,
  // held here as local state only — does not persist until Save.
  async function handleMarkAllPresent() {
    setMarkingAll(true);
    setError(null);
    setSaveNote(null);
    setQuickNote(null);
    try {
      const res = await markAllPresent(sessionId);
      setEditable(res.editable);
      setRoster(res.roster);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to mark all present");
    } finally {
      setMarkingAll(false);
    }
  }

  // — Save: the one commit action
  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaveNote(null);
    setQuickNote(null);
    try {
      const presentRollNos = roster.filter((r) => r.present).map((r) => r.roll_no);
      const res = await saveRegister(sessionId, presentRollNos);
      setSession(res.session);
      setRoster(res.roster);
      const parts: string[] = ["Saved successfully!"];
      if ((res.sms_queued || 0) > 0) parts.push(`${res.sms_queued} absentee SMS queued for HOD approval.`);
      if ((res.sms_blocked || 0) > 0) parts.push(`${res.sms_blocked} SMS blocked — review the HOD SMS page for the reason.`);
      if ((res.sms_duplicate || 0) > 0) parts.push(`${res.sms_duplicate} duplicate SMS skipped.`);
      if ((res.sms_cap_blocked || 0) > 0) parts.push(`${res.sms_cap_blocked} SMS skipped because the daily cap was reached.`);
      setSaveNote(parts.join(" "));
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "EDIT_WINDOW_EXPIRED") {
        setEditable(false);
      }
      setError(err instanceof ApiClientError ? err.message : "Failed to save register");
    } finally {
      setSaving(false);
    }
  }

  const presentCount = useMemo(() => roster.filter((r) => r.present).length, [roster]);
  const absentCount = roster.length - presentCount;

  const heading = session ? `${session.subject_code} — ${session.subject_name}` : "Register";

  return (
    <AppShell user={user} activeNav="attendance" heading={heading} onLoggedOut={onLoggedOut}>
      {/* Register-specific back link */}
      <button
        id="nav-back-to-setup"
        className="btn btn-outline btn-sm"
        onClick={() => navigate("/attendance")}
        style={{ marginBottom: 16, display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 14px", borderRadius: 8, fontWeight: 700 }}
      >
        ← Open Another Session
      </button>

      {loading && <div className="empty-note">Loading attendance register…</div>}
      {error && <div className="login-error">{error}</div>}

      {!loading && session && (
        <>
          <div className="card card-pad" style={{ marginBottom: 20, background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 16, padding: 20, boxShadow: "0 15px 35px rgba(0,0,0,0.1)" }}>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", fontSize: 13, color: "var(--text)", fontWeight: 600, alignItems: "center" }}>
              <span style={{ background: "rgba(56, 189, 248, 0.15)", padding: "4px 10px", borderRadius: 6, color: "var(--heading-accent)" }}>📅 {session.attendance_date}</span>
              <span>{session.session_type === "LAB" ? "🧪 Lab Session" : "📚 Regular Class"} &middot; {session.duration_hours} Hour(s)</span>
              {session.topic && <span>Topic: <strong>{session.topic}</strong></span>}
              <span>Faculty: <strong>{session.faculty_name || session.faculty_username}</strong></span>
            </div>
            {!editable && (
              <div className="login-error" style={{ marginTop: 12, borderRadius: 10 }}>
                🔒 This register's 24-hour edit window has closed. Marking is disabled (HOD override available).
              </div>
            )}
          </div>

          {/* — StatRow */}
          <div className="stat-row" style={{ gridTemplateColumns: "repeat(2, 1fr)", gap: 16, marginBottom: 20 }}>
            <div className="stat-card" style={{ background: "var(--card-glass)", border: "1px solid rgba(16, 185, 129, 0.3)", borderRadius: 14, padding: 18, boxShadow: "0 10px 25px rgba(16, 185, 129, 0.1)" }}>
              <div className="stat-icon" style={{ color: "#10b981", fontSize: 28 }}>✓</div>
              <div>
                <div className="stat-title" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 700, color: "var(--muted)" }}>Present Count</div>
                <div className="stat-value" style={{ fontSize: 28, fontWeight: 800, color: "#10b981" }}>{presentCount}</div>
              </div>
            </div>
            <div className="stat-card" style={{ background: "var(--card-glass)", border: "1px solid rgba(244, 63, 94, 0.3)", borderRadius: 14, padding: 18, boxShadow: "0 10px 25px rgba(244, 63, 94, 0.1)" }}>
              <div className="stat-icon" style={{ color: "#f43f5e", fontSize: 28 }}>✗</div>
              <div>
                <div className="stat-title" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 700, color: "var(--muted)" }}>Absent Count</div>
                <div className="stat-value" style={{ fontSize: 28, fontWeight: 800, color: "#f43f5e" }}>{absentCount}</div>
              </div>
            </div>
          </div>

          {/* — Toolbar */}
          <div className="dash-toolbar" style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap", alignItems: "center" }}>
            <button
              id="mark-all-present-btn"
              type="button"
              className="btn btn-outline"
              onClick={handleMarkAllPresent}
              disabled={!editable || markingAll || saving}
              style={{ padding: "10px 16px", borderRadius: 10, fontWeight: 700, cursor: "pointer" }}
            >
              {markingAll ? "Marking All…" : "✅ Mark All Present"}
            </button>

            <button
              id="save-register-btn"
              type="button"
              className="btn btn-primary"
              onClick={handleSave}
              disabled={!editable || saving || markingAll}
              style={{
                padding: "10px 22px",
                borderRadius: 10,
                background: "linear-gradient(135deg, #0284c7, #2563eb)",
                color: "#ffffff",
                fontWeight: 800,
                border: "none",
                boxShadow: "0 8px 20px rgba(56, 189, 248, 0.35)",
                cursor: "pointer"
              }}
            >
              {saving ? "Saving Changes…" : "💾 Save Attendance Register"}
            </button>

            <a
              id="download-pdf-link"
              className="btn btn-outline"
              href={registerPdfUrl(sessionId)}
              target="_blank"
              rel="noreferrer"
              style={{ padding: "10px 16px", borderRadius: 10, fontWeight: 700, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              📄 Download Official PDF
            </a>

            {saveNote && <span style={{ color: "#10b981", fontSize: 13, fontWeight: 800, marginLeft: 8 }}>{saveNote}</span>}
          </div>

          {/* — RegisterLayout: roster table + Quick Present panel side by side */}
          <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div className="table-wrap" style={{ flex: "2 1 440px", minWidth: 280, borderRadius: 14, overflow: "hidden", border: "1px solid var(--border)" }}>
              {roster.length === 0 && <div className="empty-note">No students in this roster.</div>}
              {roster.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ padding: "12px 16px" }}>Roll No</th>
                      <th style={{ padding: "12px 16px" }}>Student Name</th>
                      <th className="center" style={{ padding: "12px 16px" }}>Attendance Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roster.map((r) => (
                      <tr
                        key={r.roll_no}
                        className={editable ? "row-link" : undefined}
                        onClick={() => toggleRow(r.roll_no)}
                        style={{ borderBottom: "1px solid var(--border-light)" }}
                      >
                        <td className="roll" style={{ fontWeight: 700, fontFamily: "monospace", fontSize: 13, color: "var(--text)", padding: "12px 16px" }}>{r.roll_no}</td>
                        <td style={{ fontWeight: 600, color: "var(--text)", padding: "12px 16px" }}>{r.name}</td>
                        <td className="center" style={{ padding: "12px 16px" }}>
                          <button
                            id={`roster-${r.roll_no}-status-btn`}
                            type="button"
                            style={{
                              padding: "6px 14px",
                              borderRadius: 8,
                              fontWeight: 800,
                              fontSize: 12,
                              cursor: editable ? "pointer" : "default",
                              border: "none",
                              background: r.present ? "linear-gradient(135deg, #10b981, #059669)" : "linear-gradient(135deg, #f43f5e, #e11d48)",
                              color: "#ffffff",
                              boxShadow: r.present ? "0 4px 12px rgba(16, 185, 129, 0.3)" : "0 4px 12px rgba(244, 63, 94, 0.3)",
                              transition: "all 0.15s ease",
                            }}
                            disabled={!editable}
                            onClick={(e) => { e.stopPropagation(); toggleRow(r.roll_no); }}
                          >
                            {r.present ? "✓ PRESENT" : "✗ ABSENT"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {editable && (
              <div className="card card-pad" style={{ flex: "1 1 260px", minWidth: 240, background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 14, padding: 20 }}>
                <h3 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 800, color: "var(--text)" }}>⚡ Quick Present Entry</h3>
                <p style={{ color: "var(--muted)", fontSize: 12, margin: "0 0 12px" }}>
                  Paste or type roll numbers / trailing 2-digits to mark present instantly.
                </p>
                <div className="field" style={{ marginBottom: 12 }}>
                  <textarea
                    id="quick-rolls-input"
                    className="input-field"
                    value={quickRolls}
                    onChange={(e) => setQuickRolls(e.target.value)}
                    placeholder="e.g. 01, 03, 17 or 6701, 6703"
                    rows={4}
                    style={{ width: "100%", padding: "10px 12px", borderRadius: 8, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontFamily: "monospace" }}
                  />
                </div>
                <div style={{ color: "var(--muted)", fontSize: 11, marginBottom: 14 }}>
                  Accepts comma, space, or newline separated roll numbers.
                </div>
                <button
                  id="quick-mark-btn"
                  type="button"
                  className="btn btn-block"
                  style={{
                    width: "100%",
                    padding: "10px",
                    borderRadius: 8,
                    background: "linear-gradient(135deg, #10b981, #059669)",
                    color: "#ffffff",
                    fontWeight: 800,
                    border: "none",
                    boxShadow: "0 6px 16px rgba(16, 185, 129, 0.3)",
                    cursor: "pointer"
                  }}
                  onClick={handleQuickMark}
                  disabled={!quickRolls.trim()}
                >
                  Apply Quick Mark
                </button>
                {quickNote && (
                  <div style={{ fontSize: 12, marginTop: 10, color: "var(--heading-accent)", fontWeight: 700 }}>{quickNote}</div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </AppShell>
  );
}
