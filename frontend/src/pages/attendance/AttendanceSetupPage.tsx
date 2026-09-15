import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  type SemesterOption,
  type SubjectOption,
  type SessionType,
  type SavedAttendanceSession,
  deleteAttendanceSession,
  getSavedSessions,
  getSetup,
  getSubjectsForSemester,
  openSession,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import "./attendance-p0.css";

interface AttendanceSetupPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

function Icon({ name, size = 18 }: { name: "calendar" | "clock" | "chevron" | "lock" | "edit" | "dots" | "trash" | "external"; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<string, ReactNode> = {
    calendar: <><rect x="3" y="4" width="18" height="17" rx="3"/><path d="M16 2v4M8 2v4M3 9h18"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    chevron: <path d="m7 9 5 5 5-5"/>,
    lock: <><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    edit: <><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/></>,
    dots: <><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></>,
    trash: <><path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13M9 7V4h6v3"/></>,
    external: <><path d="M14 5h5v5M19 5l-8 8"/><path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

function parseDateParts(date: string) {
  const d = new Date(`${date}T12:00:00`);
  return { day: d.getDate(), month: d.toLocaleDateString(undefined, { month: "short" }) };
}

export function AttendanceSetupPage({ user, onLoggedOut }: AttendanceSetupPageProps) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [semesters, setSemesters] = useState<SemesterOption[]>([]);
  const [subjects, setSubjects] = useState<SubjectOption[]>([]);
  const [semesterId, setSemesterId] = useState<number | null>(null);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [attendanceDate, setAttendanceDate] = useState("");
  const [sessionType, setSessionType] = useState<SessionType>("CLASS");
  const [durationHours, setDurationHours] = useState(1);
  const [topic, setTopic] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [sessions, setSessions] = useState<SavedAttendanceSession[]>([]);
  const [openMenu, setOpenMenu] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SavedAttendanceSession | null>(null);

  const selectedSemester = useMemo(() => semesters.find((s) => s.id === semesterId) ?? null, [semesters, semesterId]);
  const selectedSubject = useMemo(() => subjects.find((s) => s.id === subjectId) ?? null, [subjects, subjectId]);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const res = await getSavedSessions(30);
      setSessions(res.sessions);
    } catch (err) {
      setSessions([]);
      setError(err instanceof ApiClientError ? err.message : "Could not load saved sessions");
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await getSetup();
        if (!alive) return;
        setSemesters(res.semesters);
        setSubjects(res.subjects);
        const defSem = res.default_semester_id ?? res.semesters[0]?.id ?? null;
        setSemesterId(defSem);
        setSubjectId(res.subjects[0]?.id ?? null);
        setAttendanceDate(res.today);
      } catch (err) {
        if (alive) setError(err instanceof ApiClientError ? err.message : "Could not load attendance setup");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    loadHistory();
    return () => { alive = false; };
  }, [loadHistory]);

  useEffect(() => {
    if (sessionType === "LAB") setDurationHours(3);
    else if (durationHours === 3) setDurationHours(1);
  }, [sessionType]);

  async function handleSemesterChange(next: number) {
    setSemesterId(next);
    setSubjectId(null);
    setError(null);
    try {
      const res = await getSubjectsForSemester(next);
      setSubjects(res.subjects);
      setSubjectId(res.subjects[0]?.id ?? null);
    } catch (err) {
      setSubjects([]);
      setError(err instanceof ApiClientError ? err.message : "Could not load subjects");
    }
  }

  async function handleOpenSession(e: React.FormEvent) {
    e.preventDefault();
    if (!semesterId || !subjectId || !attendanceDate || !topic.trim()) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const session = await openSession({
        attendance_date: attendanceDate,
        semester_id: semesterId,
        subject_id: subjectId,
        session_type: sessionType,
        duration_hours: sessionType === "LAB" ? 3 : durationHours,
        topic: topic.trim(),
      });
      navigate(`/attendance/sessions/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not open attendance register");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeletingId(deleteTarget.id);
    try {
      await deleteAttendanceSession(deleteTarget.id);
      setSessions((prev) => prev.filter((s) => s.id !== deleteTarget.id));
      setSuccess("Attendance session deleted.");
      setDeleteTarget(null);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not delete attendance session");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <AppShell user={user} activeNav="attendance" heading="Mark Attendance" onLoggedOut={onLoggedOut}>
      <div className="att-p0">
        <div className="att-page-head">
          <div>
            <p className="att-eyebrow">Daily faculty workflow</p>
            <h1 className="att-title">Mark Attendance</h1>
            <p className="att-subtitle">Start a register, make the marks, then confirm once. Nothing is saved until you approve it.</p>
          </div>
          <button className="att-secondary" type="button" onClick={() => navigate("/attendance/insights")}>
            <Icon name="external" size={15} />&nbsp; Attendance insights
          </button>
        </div>

        {error && <div className="att-error">{error}</div>}
        {success && <div className="att-success" style={{ marginBottom: 14 }}>{success}</div>}

        <div className="att-shell-grid">
          <section className="att-card pad">
            <div className="att-card-head">
              <div>
                <h2 className="att-card-title">Start a new session</h2>
                <p className="att-card-caption">Choose the class once. The register opens immediately after this step.</p>
              </div>
            </div>

            {loading ? (
              <div className="att-loading"><div className="att-spinner" />Preparing your classes…</div>
            ) : (
              <form onSubmit={handleOpenSession}>
                <div className="att-form-grid">
                  <div className="att-field">
                    <label>Semester</label>
                    <select className="att-select" value={semesterId ?? ""} onChange={(e) => handleSemesterChange(Number(e.target.value))}>
                      <option value="">Select semester</option>
                      {semesters.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </div>
                  <div className="att-field">
                    <label>Date</label>
                    <input className="att-input" type="date" value={attendanceDate} onChange={(e) => setAttendanceDate(e.target.value)} />
                  </div>
                  <div className="att-field full">
                    <label>Subject <span>{selectedSemester?.code}</span></label>
                    <select className="att-select" value={subjectId ?? ""} onChange={(e) => setSubjectId(Number(e.target.value))} disabled={!subjects.length}>
                      <option value="">Select subject</option>
                      {subjects.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
                    </select>
                  </div>
                  <div className="att-field full">
                    <label>Session type</label>
                    <div className="att-segment">
                      <button type="button" className={sessionType === "CLASS" ? "active" : ""} onClick={() => setSessionType("CLASS")}>
                        <span className="k">Regular class</span><span className="v">{durationHours} hour{durationHours === 1 ? "" : "s"}</span>
                      </button>
                      <button type="button" className={sessionType === "LAB" ? "active" : ""} onClick={() => setSessionType("LAB")}>
                        <span className="k">Lab session</span><span className="v">3 hours · fixed</span>
                      </button>
                    </div>
                  </div>
                  <div className="att-field">
                    <label>Duration</label>
                    <select className="att-select" value={sessionType === "LAB" ? 3 : durationHours} onChange={(e) => setDurationHours(Number(e.target.value))} disabled={sessionType === "LAB"}>
                      <option value={1}>1 hour</option>
                      <option value={2}>2 hours</option>
                      <option value={3}>3 hours</option>
                    </select>
                    {sessionType === "LAB" && <div className="att-help">Lab duration is fixed to 3 hours.</div>}
                  </div>
                  <div className="att-field">
                    <label>Quick check</label>
                    <div className="att-inline-warning" style={{ marginTop: 0, minHeight: 46, display: "flex", alignItems: "center" }}>
                      {selectedSubject?.has_lab ? "Lab attendance is available for this subject." : "Regular class flow is ready."}
                    </div>
                  </div>
                  <div className="att-field full">
                    <label>Topic / lecture note <span>{topic.trim() ? "Ready" : "Required"}</span></label>
                    <textarea className="att-textarea" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Binary Search Trees and AVL Trees" />
                    <div className="att-help">A short topic makes later review much easier.</div>
                  </div>
                </div>
                <div style={{ marginTop: 16 }}>
                  <button className="att-primary" id="open-session-btn" type="submit" disabled={submitting || !semesterId || !subjectId || !attendanceDate || !topic.trim()}>
                    {submitting ? "Opening register…" : "Open attendance register"}
                  </button>
                </div>
              </form>
            )}
          </section>

          <section className="att-card pad">
            <div className="att-card-head">
              <div>
                <h2 className="att-card-title">Saved sessions</h2>
                <p className="att-card-caption">Only sessions you actually saved appear here. Abandoned opens are never listed.</p>
              </div>
              <button className="att-icon-btn" type="button" onClick={loadHistory} title="Refresh saved sessions" disabled={loadingHistory}>
                <span style={{ fontSize: 17, lineHeight: 1 }}>↻</span>
              </button>
            </div>

            <div className="att-history-toolbar">
              <span className="att-count">{sessions.length} saved session{sessions.length === 1 ? "" : "s"}</span>
              <span className="att-count">Faculty edit window: 24h</span>
            </div>

            {loadingHistory ? (
              <div className="att-loading"><div className="att-spinner" />Loading saved sessions…</div>
            ) : sessions.length === 0 ? (
              <div className="att-empty">No saved attendance yet. Once you confirm a register, it will appear here.</div>
            ) : (
              <div className="att-history-list">
                {sessions.map((sess) => {
                  const date = parseDateParts(sess.attendance_date);
                  return (
                    <div className="att-session-row" key={sess.id} onClick={() => setOpenMenu(null)}>
                      <div className="att-session-date"><span className="d">{date.day}</span><span className="m">{date.month}</span></div>
                      <div className="att-session-main">
                        <p className="att-session-title">{sess.subject_code} — {sess.subject_name}</p>
                        <div className="att-session-meta">
                          <span>{sess.session_type === "LAB" ? "Lab" : "Class"}</span><span className="att-dot" />
                          <span>{sess.duration_hours}h</span><span className="att-dot" />
                          <span>{sess.present_count}/{sess.total_marked} present</span>
                          {sess.topic && <><span className="att-dot" /><span>{sess.topic}</span></>}
                        </div>
                        <div style={{ marginTop: 7 }}>
                          <span className={`att-session-state ${sess.editable ? "edit" : "lock"}`}>
                            <Icon name={sess.editable ? "edit" : "lock"} size={11} />
                            {sess.editable ? "Editable" : "View only"}
                          </span>
                        </div>
                      </div>
                      <div className="att-row-actions">
                        <div className="att-session-counts"><span style={{ color: "#168a5a" }}>{sess.present_count} P</span><span style={{ color: "#c83a4a" }}>{sess.absent_count} A</span></div>
                        <button className="att-icon-btn" type="button" onClick={(e) => { e.stopPropagation(); navigate(`/attendance/sessions/${sess.id}`); }} title={sess.editable ? "Open session" : "View session"}>
                          <Icon name={sess.editable ? "edit" : "lock"} size={15} />
                        </button>
                        {user.role === "ADMIN" && (
                          <div className="att-kebab">
                            <button className="att-icon-btn" type="button" onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === sess.id ? null : sess.id); }} aria-label="More actions">
                              <Icon name="dots" size={16} />
                            </button>
                            {openMenu === sess.id && (
                              <div className="att-kebab-menu">
                                <button className="danger" type="button" onClick={() => { setDeleteTarget(sess); setOpenMenu(null); }}><Icon name="trash" size={14} />&nbsp; Delete session</button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <div style={{ marginTop: 18, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "13px 15px", background: "#f8fafc", border: "1px solid #e8edf2", borderRadius: 15 }}>
          <div>
            <div style={{ color: "#2c3a4e", fontSize: 12, fontWeight: 800 }}>Need the monthly register?</div>
            <div style={{ color: "#778394", fontSize: 11, marginTop: 3 }}>Open the existing subject calendar and semester summary without crowding the daily workflow.</div>
          </div>
          <button className="att-secondary" type="button" onClick={() => navigate("/attendance/insights")}>Open insights</button>
        </div>

        {deleteTarget && (
          <div className="att-sheet-backdrop" onClick={() => setDeleteTarget(null)}>
            <div className="att-sheet" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
              <div className="att-sheet-handle" />
              <h2 className="att-sheet-title">Delete attendance session?</h2>
              <p className="att-sheet-caption">This permanently removes the session and every attendance record attached to it. The action is audit-logged and cannot be undone.</p>
              <div className="att-confirm-card">
                <div style={{ color: "#1e2a3a", fontSize: 13, fontWeight: 850 }}>{deleteTarget.subject_code} — {deleteTarget.subject_name}</div>
                <div style={{ color: "#718092", fontSize: 11, marginTop: 5 }}>{deleteTarget.attendance_date} · {deleteTarget.session_type === "LAB" ? "Lab" : "Class"} · {deleteTarget.present_count} present · {deleteTarget.absent_count} absent</div>
              </div>
              <div className="att-sheet-actions">
                <button className="att-sheet-cancel" type="button" onClick={() => setDeleteTarget(null)}>Keep session</button>
                <button className="att-sheet-confirm" style={{ background: "#c83a4a" }} type="button" onClick={handleDelete} disabled={deletingId === deleteTarget.id}>{deletingId === deleteTarget.id ? "Deleting…" : "Delete permanently"}</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
