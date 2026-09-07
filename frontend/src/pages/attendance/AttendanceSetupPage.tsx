// Group 3 — Mark Attendance: Setup screen.
// Mirrors webapp/routes/attendance.py's attendance_setup() + the old
// /attendance/subjects-for-semester HTMX partial, ported to one JSON call
// (GET /api/attendance/setup) plus a refetch on semester change
// (GET /api/attendance/subjects?semester_id=).
//
// Flow: semester picker -> subject picker (refetches on semester change) ->
// date, session type (Class/Lab), duration, topic -> Open button
// (POST /api/attendance/sessions) -> navigate to the register screen with
// the returned session id.
import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  type SemesterOption,
  type SubjectOption,
  type SessionType,
  type MonthlyAttendanceRegister,
  type SemesterAttendanceSummaryResponse,
  type StudentSemesterSummary,
  getSetup,
  getSubjectsForSemester,
  getMonthlyRegister,
  monthlyRegisterPdfUrl,
  getSemesterAttendanceSummary,
  openSession,
} from "../../api/attendance";
import { getDashboard, type SessionRow } from "../../api/dashboard";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";

interface AttendanceSetupPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function AttendanceSetupPage({ user, onLoggedOut }: AttendanceSetupPageProps) {
  const navigate = useNavigate();

  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState<string | null>(null);
  const [submitting, setSubmitting]   = useState(false);

  const [semesters, setSemesters]     = useState<SemesterOption[]>([]);
  const [subjects, setSubjects]       = useState<SubjectOption[]>([]);

  const [semesterId, setSemesterId]   = useState<number | null>(null);
  const [subjectId, setSubjectId]     = useState<number | null>(null);
  const [attendanceDate, setAttendanceDate] = useState("");
  const [sessionType, setSessionType] = useState<SessionType>("CLASS");
  const [durationHours, setDurationHours]   = useState(1);
  const [topic, setTopic]             = useState("");

  // Semester view history list
  const [semesterSessions, setSemesterSessions] = useState<SessionRow[]>([]);
  const [loadingSessions, setLoadingSessions]   = useState(false);

  // — Load semester session history helper
  const loadSemesterHistory = useCallback(async (semId: number) => {
    setLoadingSessions(true);
    try {
      const dash = await getDashboard(undefined, semId);
      if (dash.role === "HOD" && dash.days) {
        const allRows = Object.values(dash.days).flat();
        setSemesterSessions(allRows);
      }
    } catch {
      setSemesterSessions([]);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  // — InitialLoad
  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await getSetup();
        setSemesters(res.semesters);
        setSubjects(res.subjects);
        const defSem = res.default_semester_id ?? res.semesters[0]?.id ?? null;
        setSemesterId(defSem);
        setSubjectId(res.subjects[0]?.id ?? null);
        setAttendanceDate(res.today);
        if (defSem) {
          loadSemesterHistory(defSem);
        }
      } catch (err) {
        setError(err instanceof ApiClientError ? err.message : "Failed to load setup data");
      } finally {
        setLoading(false);
      }
    })();
  }, [loadSemesterHistory]);

  // — SemesterChange: refetch subjects + semester history
  const handleSemesterChange = useCallback(async (newSemId: number | null) => {
    setSemesterId(newSemId);
    setSubjectId(null);
    setSemesterSessions([]);
    if (!newSemId) {
      setSubjects([]);
      return;
    }
    try {
      const res = await getSubjectsForSemester(newSemId);
      setSubjects(res.subjects);
      setSubjectId(res.subjects[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load subjects");
    }
    loadSemesterHistory(newSemId);
  }, [loadSemesterHistory]);

  const selectedSubject = subjects.find((s) => s.id === subjectId) ?? null;
  const selectedSemester = semesters.find((s) => s.id === semesterId) ?? null;

  // Lock duration to 3 hours for LAB sessions
  useEffect(() => {
    if (sessionType === "LAB") {
      setDurationHours(3);
    }
  }, [sessionType]);

  // — Monthly Attendance Register & Semester Summary state
  const [viewMode, setViewMode] = useState<"register" | "summary">("register");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [studentSearch, setStudentSearch] = useState("");
  const [register, setRegister] = useState<MonthlyAttendanceRegister | null>(null);
  const [loadingRegister, setLoadingRegister] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [selectedGridDate, setSelectedGridDate] = useState<string | null>(null);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);

  // Semester All-Subjects Matrix state
  const [semesterSummary, setSemesterSummary] = useState<SemesterAttendanceSummaryResponse | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [selectedStudentDrilldown, setSelectedStudentDrilldown] = useState<StudentSemesterSummary | null>(null);

  const [regYear, regMonthNum] = useMemo(() => {
    const parts = month.split("-").map(Number);
    return [parts[0] || new Date().getFullYear(), parts[1] || new Date().getMonth() + 1];
  }, [month]);

  // Month stepping helpers
  const handlePrevMonth = () => {
    const d = new Date(regYear, regMonthNum - 2, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  const handleNextMonth = () => {
    const d = new Date(regYear, regMonthNum, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  const handleCurrentMonth = () => {
    const d = new Date();
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  // Fetch monthly register for selected semester and subject
  useEffect(() => {
    if (!semesterId || !subjectId || !regYear || !regMonthNum) {
      setRegister(null);
      return;
    }
    let cancelled = false;
    setLoadingRegister(true);
    setRegisterError(null);
    getMonthlyRegister({
      semesterId,
      subjectId,
      year: regYear,
      month: regMonthNum,
    })
      .then((data) => {
        if (!cancelled) setRegister(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setRegister(null);
          setRegisterError(err instanceof ApiClientError ? err.message : "Failed to load monthly register");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingRegister(false);
      });
    return () => {
      cancelled = true;
    };
  }, [semesterId, subjectId, regYear, regMonthNum]);

  // Fetch semester-wide attendance summary across all subjects
  useEffect(() => {
    if (!semesterId) {
      setSemesterSummary(null);
      return;
    }
    let cancelled = false;
    setLoadingSummary(true);
    setSummaryError(null);
    getSemesterAttendanceSummary({
      semesterId,
      year: regYear,
      month: regMonthNum,
    })
      .then((data) => {
        if (!cancelled) setSemesterSummary(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setSemesterSummary(null);
          setSummaryError(err instanceof ApiClientError ? err.message : "Failed to load semester attendance summary");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingSummary(false);
      });
    return () => {
      cancelled = true;
    };
  }, [semesterId, regYear, regMonthNum]);

  const printPdfUrl = (register && semesterId && subjectId)
    ? monthlyRegisterPdfUrl({ semesterId, subjectId, year: regYear, month: regMonthNum })
    : "";

  const selectedDayInfo = register?.days.find((d) => d.date === selectedGridDate) ?? null;

  // Filter roster by studentSearch
  const filteredRoster = useMemo(() => {
    if (!register) return [];
    if (!studentSearch.trim()) return register.roster;
    const q = studentSearch.trim().toLowerCase();
    return register.roster.filter(
      (r) => r.roll_no.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
    );
  }, [register, studentSearch]);

  // Filter semester summary students by studentSearch
  const filteredSemesterStudents = useMemo(() => {
    if (!semesterSummary) return [];
    if (!studentSearch.trim()) return semesterSummary.students;
    const q = studentSearch.trim().toLowerCase();
    return semesterSummary.students.filter(
      (s) => s.roll_no.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
    );
  }, [semesterSummary, studentSearch]);

  const semesterSummaryStats = useMemo(() => {
    if (!semesterSummary || semesterSummary.students.length === 0) {
      return { totalStudents: 0, eligibleCount: 0, shortageCount: 0, avgPct: 0 };
    }
    const totalStudents = semesterSummary.students.length;
    const eligibleCount = semesterSummary.students.filter((s) => (s.overall_pct ?? 0) >= 75).length;
    const shortageCount = totalStudents - eligibleCount;
    const sumPct = semesterSummary.students.reduce((acc, s) => acc + (s.overall_pct ?? 0), 0);
    const avgPct = totalStudents > 0 ? Math.round(sumPct / totalStudents) : 0;
    return { totalStudents, eligibleCount, shortageCount, avgPct };
  }, [semesterSummary]);

  // Derived statistics for the register
  const registerStats = useMemo(() => {
    if (!register || register.roster.length === 0) {
      return { totalStudents: 0, totalSessions: 0, classAvgPct: 0, eligibleCount: 0, shortageCount: 0 };
    }
    const teachingDays = register.days.filter((d) => d.session_count > 0);
    const totalSessions = teachingDays.length;
    const studentStats = register.roster.map((row) => {
      let present = 0;
      row.cells.forEach((cell, idx) => {
        const day = register.days[idx];
        if (day && day.session_count > 0 && cell.status === "P") {
          present += 1;
        }
      });
      const pct = totalSessions > 0 ? Math.round((present / totalSessions) * 100) : 100;
      return { present, totalSessions, pct };
    });

    const totalStudents = studentStats.length;
    const sumPct = studentStats.reduce((acc, s) => acc + s.pct, 0);
    const classAvgPct = totalStudents > 0 ? Math.round(sumPct / totalStudents) : 0;
    const eligibleCount = studentStats.filter((s) => s.pct >= 75).length;
    const shortageCount = totalStudents - eligibleCount;

    return { totalStudents, totalSessions, classAvgPct, eligibleCount, shortageCount };
  }, [register]);

  // Per-day summary calculations (for table footer)
  const dailyAttendanceSummary = useMemo(() => {
    if (!register || register.roster.length === 0) return [];
    return register.days.map((day, dIdx) => {
      if (day.session_count === 0) return null;
      let pCount = 0;
      register.roster.forEach((row) => {
        if (row.cells[dIdx]?.status === "P") pCount += 1;
      });
      const pct = Math.round((pCount / register.roster.length) * 100);
      return { presentCount: pCount, total: register.roster.length, pct };
    });
  }, [register]);

  // — OpenSession
  async function handleOpen(e: React.FormEvent) {
    e.preventDefault();
    if (!semesterId || !subjectId || !attendanceDate || !topic.trim()) {
      setError("Enter today's topic / lecture notes.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const session = await openSession({
        attendance_date: attendanceDate,
        semester_id: semesterId,
        subject_id: subjectId,
        session_type: sessionType,
        duration_hours: durationHours,
        topic,
      });
      navigate(`/attendance/sessions/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to open session");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell user={user} activeNav="attendance" heading="Mark Student Attendance" onLoggedOut={onLoggedOut}>
      {loading && <div className="empty-note">Loading attendance setup data…</div>}
      {error && <div className="login-error">{error}</div>}

      {!loading && (
        <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>

          {/* ── Main Setup Card ── */}
          <div style={{
            background: "#ffffff",
            border: "1px solid var(--border)",
            borderRadius: 16,
            overflow: "hidden",
            boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
          }}>
            {/* Card header strip */}
            <div style={{
              background: "linear-gradient(135deg, rgba(2, 132, 199, 0.08) 0%, rgba(37, 99, 235, 0.06) 100%)",
              borderBottom: "1px solid var(--border)",
              padding: "18px 24px",
              display: "flex",
              alignItems: "center",
              gap: 14,
            }}>
              <div style={{
                width: 44, height: 44, borderRadius: 12,
                background: "linear-gradient(135deg, #0284c7, #2563eb)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 22, color: "#fff",
                boxShadow: "0 6px 16px rgba(56, 189, 248, 0.35)",
                flexShrink: 0,
              }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="18" rx="2"/>
                  <line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                  <line x1="8" y1="14" x2="8" y2="14"/>
                  <line x1="12" y1="14" x2="12" y2="14"/>
                </svg>
              </div>
              <div>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text)" }}>Open Attendance Session</h2>
                <p style={{ margin: "3px 0 0 0", color: "var(--muted)", fontSize: 13 }}>
                  Select semester, subject, session type &amp; date to mark student attendance.
                </p>
              </div>
            </div>

            <div style={{ padding: "24px" }}>
              <form onSubmit={handleOpen}>
                {/* Row 1: Semester + Subject */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginBottom: 16 }}>

                  <div className="field">
                    <label htmlFor="semester-select" style={{ fontSize: 12, fontWeight: 700 }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/></svg>
                        Semester *
                      </span>
                    </label>
                    <select
                      id="semester-select"
                      className="input-field"
                      value={semesterId ?? ""}
                      onChange={(e) => {
                        const val = e.target.value;
                        handleSemesterChange(val ? Number(val) : null);
                      }}
                      style={{ height: 42, borderRadius: 10, fontSize: 13 }}
                    >
                      <option value="">— Select Semester —</option>
                      {semesters.map((s) => (
                        <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
                      ))}
                    </select>
                  </div>

                  <div className="field">
                    <label htmlFor="subject-select" style={{ fontSize: 12, fontWeight: 700 }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
                        Subject *
                      </span>
                    </label>
                    <select
                      id="subject-select"
                      className="input-field"
                      value={subjectId ?? ""}
                      onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : null)}
                      disabled={subjects.length === 0}
                      style={{ height: 42, borderRadius: 10, fontSize: 13 }}
                    >
                      {subjects.length === 0 ? (
                        <option value="">No subjects for this semester</option>
                      ) : (
                        <>
                          <option value="">— Select Subject —</option>
                          {subjects.map((s) => (
                            <option key={s.id} value={s.id}>{s.code} — {s.name}</option>
                          ))}
                        </>
                      )}
                    </select>
                  </div>
                </div>

                {/* Session Type Pills */}
                <div className="field" style={{ marginBottom: 16 }}>
                  <label style={{ fontSize: 12, fontWeight: 700 }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                      Session Type *
                    </span>
                  </label>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    {[
                      { type: "CLASS", label: "Regular Class", sub: "Theory Session · 1 Hour", icon: (
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
                      )},
                      { type: "LAB", label: "Lab Session", sub: "Practical Lab · Fixed 3 Hours", icon: (
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v11l-5 5h16l-5-5V3"/></svg>
                      )},
                    ].map(({ type, label, sub, icon }) => {
                      const isLab = type === "LAB";
                      const active = sessionType === type;
                      return (
                        <button
                          key={type}
                          type="button"
                          onClick={() => {
                            setSessionType(type as "CLASS" | "LAB");
                            setDurationHours(isLab ? 3 : 1);
                          }}
                          style={{
                            padding: "12px 16px",
                            borderRadius: 12,
                            fontWeight: 700,
                            fontSize: 13,
                            cursor: "pointer",
                            border: active ? "2px solid #0284c7" : "1px solid var(--border)",
                            background: active
                              ? "linear-gradient(135deg, rgba(2, 132, 199, 0.1), rgba(37, 99, 235, 0.08))"
                              : "#ffffff",
                            color: "var(--text)",
                            boxShadow: active
                              ? "0 0 0 3px rgba(56, 189, 248, 0.2), 0 4px 12px rgba(56, 189, 248, 0.12)"
                              : "0 1px 3px rgba(0,0,0,0.04)",
                            transition: "all 0.18s ease",
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            textAlign: "left",
                          }}
                        >
                          <div style={{
                            width: 34, height: 34, borderRadius: 8, flexShrink: 0,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            background: active ? "#0284c7" : "var(--chip-bg-muted)",
                            color: active ? "#fff" : "var(--muted)",
                            transition: "all 0.18s ease",
                          }}>
                            {icon}
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 800, fontSize: 13, color: active ? "#0284c7" : "var(--text)" }}>{label}</div>
                            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1 }}>{sub}</div>
                          </div>
                          {active && (
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Row 2: Date + Duration */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginBottom: 16 }}>
                  <div className="field">
                    <label htmlFor="date-input" style={{ fontSize: 12, fontWeight: 700 }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                        Attendance Date *
                      </span>
                    </label>
                    <input
                      id="date-input"
                      type="date"
                      className="input-field"
                      value={attendanceDate}
                      onChange={(e) => setAttendanceDate(e.target.value)}
                      style={{ height: 42, borderRadius: 10, fontSize: 13 }}
                      required
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="duration-input" style={{ fontSize: 12, fontWeight: 700 }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                        Duration (Hours) {sessionType === "LAB" ? "· Locked 3h for Lab" : "*"}
                      </span>
                    </label>
                    <input
                      id="duration-input"
                      type="number"
                      className="input-field"
                      min={1}
                      max={8}
                      value={sessionType === "LAB" ? 3 : durationHours}
                      disabled={sessionType === "LAB"}
                      onChange={(e) => setDurationHours(Number(e.target.value))}
                      style={{
                        height: 42,
                        borderRadius: 10,
                        fontSize: 13,
                        background: sessionType === "LAB" ? "rgba(2, 132, 199, 0.06)" : undefined,
                        borderColor: sessionType === "LAB" ? "#0284c7" : undefined,
                        color: sessionType === "LAB" ? "#0284c7" : undefined,
                        fontWeight: 700,
                      }}
                      required
                    />
                  </div>
                </div>

                {/* Topic */}
                <div className="field" style={{ marginBottom: 20 }}>
                  <label htmlFor="topic-input" style={{ fontSize: 12, fontWeight: 700 }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                      Topic / Lecture Notes *
                    </span>
                  </label>
                  <input
                    id="topic-input"
                    type="text"
                    className="input-field"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g. Binary Search Trees & AVL Trees (Required)"
                    style={{ height: 42, borderRadius: 10, fontSize: 13 }}
                    required
                  />
                </div>

                {/* Submit button */}
                <button
                  id="open-session-btn"
                  type="submit"
                  className="btn btn-block"
                  style={{
                    width: "100%",
                    height: 46,
                    borderRadius: 12,
                    background: "linear-gradient(135deg, #0284c7 0%, #2563eb 100%)",
                    color: "#ffffff",
                    fontWeight: 700,
                    fontSize: 15,
                    border: "none",
                    boxShadow: "0 8px 20px rgba(56, 189, 248, 0.3)",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                  }}
                  disabled={submitting || !semesterId || !subjectId || !attendanceDate || !topic.trim()}
                >
                  {submitting ? (
                    <>
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: "spin 1s linear infinite" }}><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></svg>
                      Opening Session Register…
                    </>
                  ) : (
                    <>
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                      Open Attendance Register
                    </>
                  )}
                </button>
              </form>
            </div>
          </div>


          {/* ── Monthly Attendance Register Card ── */}
          <div
            style={{
              background: "#ffffff",
              border: "1px solid var(--border)",
              borderRadius: 16,
              padding: 24,
              boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
              display: "flex",
              flexDirection: "column",
              gap: 20,
            }}
          >
            {/* Header & Controls */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{
                    width: 44, height: 44, borderRadius: 12,
                    background: "linear-gradient(135deg, #059669, #10b981)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    color: "#fff", fontSize: 20,
                    boxShadow: "0 6px 16px rgba(16, 185, 129, 0.35)",
                    flexShrink: 0,
                  }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                      <line x1="16" y1="2" x2="16" y2="6"/>
                      <line x1="8" y1="2" x2="8" y2="6"/>
                      <line x1="3" y1="10" x2="21" y2="10"/>
                    </svg>
                  </div>
                  <div>
                    <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text)" }}>
                      {viewMode === "register"
                        ? `Monthly Attendance Register ${selectedSubject ? `— ${selectedSubject.code}` : ""}`
                        : `Semester Subject-Wise Attendance Matrix ${selectedSemester ? `— ${selectedSemester.code}` : ""}`}
                    </h3>
                    <p style={{ margin: "2px 0 0 0", color: "var(--muted)", fontSize: 13 }}>
                      {viewMode === "register"
                        ? `${register?.month_label || "Select semester and subject"} · ${user.role === "HOD" ? `Department Scope (HOD: ${user.full_name || user.username})` : `Faculty: ${register?.faculty_name || user.full_name || user.username}`}`
                        : `${selectedSemester?.code ? `${selectedSemester.code} (${selectedSemester.name})` : "Selected Semester"} · All Subjects Attendance Matrix for Students`}
                    </p>
                  </div>
                </div>
              </div>

              {/* Controls: View Mode Switch + Month Stepper + Print */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                {/* View Mode Toggle Buttons */}
                <div style={{
                  display: "inline-flex",
                  background: "#f1f5f9",
                  padding: 3,
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                }}>
                  <button
                    type="button"
                    onClick={() => setViewMode("register")}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 8,
                      border: "none",
                      fontWeight: 700,
                      fontSize: 12,
                      cursor: "pointer",
                      background: viewMode === "register" ? "#ffffff" : "transparent",
                      color: viewMode === "register" ? "#0f172a" : "var(--muted)",
                      boxShadow: viewMode === "register" ? "0 2px 6px rgba(0,0,0,0.08)" : "none",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    📅 Subject Calendar
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("summary")}
                    style={{
                      padding: "5px 12px",
                      borderRadius: 8,
                      border: "none",
                      fontWeight: 700,
                      fontSize: 12,
                      cursor: "pointer",
                      background: viewMode === "summary" ? "#ffffff" : "transparent",
                      color: viewMode === "summary" ? "#0f172a" : "var(--muted)",
                      boxShadow: viewMode === "summary" ? "0 2px 6px rgba(0,0,0,0.08)" : "none",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    📊 All Subjects Matrix
                  </button>
                </div>

                {/* Month stepper buttons */}
                <div style={{
                  display: "inline-flex",
                  alignItems: "center",
                  background: "var(--chip-bg-muted)",
                  padding: "3px 6px",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  gap: 4,
                }}>
                  <button
                    type="button"
                    onClick={handlePrevMonth}
                    title="Previous Month"
                    style={{
                      background: "#ffffff", border: "1px solid var(--border)", borderRadius: 6,
                      width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer", color: "var(--text)", fontWeight: 800, fontSize: 13,
                    }}
                  >
                    ◀
                  </button>

                  <input
                    id="month-picker"
                    type="month"
                    className="input-field"
                    style={{
                      width: 155, height: 30, padding: "2px 8px", borderRadius: 6,
                      fontSize: 12, fontWeight: 700, border: "none", background: "transparent",
                    }}
                    value={month}
                    onChange={(e) => setMonth(e.target.value)}
                  />

                  <button
                    type="button"
                    onClick={handleNextMonth}
                    title="Next Month"
                    style={{
                      background: "#ffffff", border: "1px solid var(--border)", borderRadius: 6,
                      width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer", color: "var(--text)", fontWeight: 800, fontSize: 13,
                    }}
                  >
                    ▶
                  </button>

                  <button
                    type="button"
                    onClick={handleCurrentMonth}
                    title="Jump to current month"
                    style={{
                      background: "#ffffff", border: "1px solid var(--border)", borderRadius: 6,
                      padding: "0 8px", height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer", color: "var(--text)", fontWeight: 700, fontSize: 11,
                    }}
                  >
                    Current
                  </button>
                </div>

                {/* Print Button */}
                {viewMode === "register" ? (
                  <button
                    type="button"
                    className="btn btn-outline"
                    disabled={!printPdfUrl}
                    onClick={() => {
                      if (printPdfUrl) {
                        window.open(printPdfUrl, "_blank", "noopener,noreferrer");
                      }
                    }}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      height: 38,
                      padding: "0 14px",
                      borderRadius: 10,
                      fontWeight: 700,
                      fontSize: 13,
                      opacity: !printPdfUrl ? 0.5 : 1,
                      cursor: !printPdfUrl ? "not-allowed" : "pointer",
                      background: "#ffffff",
                    }}
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                    Print Register (PDF)
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={() => window.print()}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      height: 38,
                      padding: "0 14px",
                      borderRadius: 10,
                      fontWeight: 700,
                      fontSize: 13,
                      background: "#ffffff",
                    }}
                  >
                    🖨️ Print Matrix
                  </button>
                )}
              </div>
            </div>

            {/* ══════════════════════════════════════════════════════ */}
            {/* VIEW MODE 1: SUBJECT MONTHLY REGISTER CALENDAR GRID   */}
            {/* ══════════════════════════════════════════════════════ */}
            {viewMode === "register" && (
              <>
                {/* KPI Stat Badges & Search Filter */}
                {register && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 12,
                    }}>
                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>👥</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Total Students</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text)" }}>{registerStats.totalStudents}</div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>📅</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Teaching Days</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text)" }}>{registerStats.totalSessions}</div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>📊</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Avg Attendance</div>
                          <div style={{
                            fontSize: 18, fontWeight: 800,
                            color: registerStats.classAvgPct >= 75 ? "#15803d" : registerStats.classAvgPct >= 60 ? "#b45309" : "#b91c1c",
                          }}>
                            {registerStats.classAvgPct}%
                          </div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>🎯</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Eligible (≥75%)</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "#15803d" }}>
                            {registerStats.eligibleCount} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>students</span>
                          </div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>⚠️</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Shortage (&lt;75%)</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: registerStats.shortageCount > 0 ? "#b91c1c" : "#15803d" }}>
                            {registerStats.shortageCount} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>students</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Search / Filter bar + Legend */}
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      flexWrap: "wrap",
                      gap: 12,
                      padding: "10px 14px",
                      background: "#f8fafc",
                      borderRadius: 12,
                      border: "1px solid var(--border)",
                    }}>
                      {/* Search box */}
                      <div style={{ position: "relative", minWidth: 240, flex: "1 1 240px", maxWidth: 360 }}>
                        <input
                          type="text"
                          className="input-field"
                          placeholder="🔍 Search roll no or student name…"
                          value={studentSearch}
                          onChange={(e) => setStudentSearch(e.target.value)}
                          style={{
                            height: 34,
                            padding: "0 28px 0 10px",
                            fontSize: 12,
                            borderRadius: 8,
                            background: "#ffffff",
                          }}
                        />
                        {studentSearch && (
                          <button
                            type="button"
                            onClick={() => setStudentSearch("")}
                            style={{
                              position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                              background: "none", border: "none", color: "var(--muted)", cursor: "pointer",
                              fontSize: 12, fontWeight: 700,
                            }}
                          >
                            ✕
                          </button>
                        )}
                      </div>

                      {/* Status Legend */}
                      <div style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        flexWrap: "wrap",
                        fontSize: 12,
                        fontWeight: 600,
                        color: "var(--muted)",
                      }}>
                        <span style={{ fontWeight: 800, color: "var(--text)" }}>Legend:</span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                          <span style={{ width: 20, height: 20, borderRadius: 5, background: "#dcfce7", color: "#15803d", border: "1px solid #bbf7d0", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 900 }}>P</span>
                          Present
                        </span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                          <span style={{ width: 20, height: 20, borderRadius: 5, background: "#fee2e2", color: "#b91c1c", border: "1px solid #fecaca", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 900 }}>A</span>
                          Absent
                        </span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                          <span style={{ width: 20, height: 20, borderRadius: 5, background: "#fef3c7", color: "#b45309", border: "1px solid #fde68a", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 900 }}>H</span>
                          Holiday / Sunday
                        </span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                          <span style={{ width: 20, height: 20, borderRadius: 5, background: "#f1f5f9", color: "#94a3b8", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 900 }}>·</span>
                          No Class
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Selected Date Inspector Banner */}
                {selectedGridDate && selectedDayInfo && (
                  <div style={{
                    background: "linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)",
                    border: "1.5px solid #38bdf8",
                    borderRadius: 12,
                    padding: "14px 18px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 12,
                    boxShadow: "0 4px 14px rgba(56, 189, 248, 0.15)",
                  }}>
                    <div>
                      <div style={{ fontWeight: 800, fontSize: 14, color: "#0369a1", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span>📅 {selectedDayInfo.date} ({selectedDayInfo.weekday})</span>
                        {selectedDayInfo.holiday && (
                          <span style={{ background: "#fef3c7", color: "#b45309", border: "1px solid #fde68a", padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 800 }}>
                            🎉 Holiday: {selectedDayInfo.holiday_name || "Holiday"}
                          </span>
                        )}
                        {selectedDayInfo.session_id && (
                          <span style={{ background: "#dcfce7", color: "#15803d", border: "1px solid #bbf7d0", padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 800 }}>
                            ✅ {selectedDayInfo.session_type || "CLASS"} ({selectedDayInfo.duration_hours}h)
                          </span>
                        )}
                      </div>
                      {selectedDayInfo.topic && (
                        <div style={{ fontSize: 12, color: "#334155", marginTop: 4 }}>
                          Topic: <strong>"{selectedDayInfo.topic}"</strong>
                        </div>
                      )}
                      {!selectedDayInfo.holiday && !selectedDayInfo.session_id && (
                        <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
                          No attendance session was recorded on this day.
                        </div>
                      )}
                    </div>

                    <div style={{ display: "flex", gap: 10 }}>
                      {selectedDayInfo.session_id && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => navigate(`/attendance/sessions/${selectedDayInfo.session_id}`)}
                          style={{
                            padding: "6px 14px", borderRadius: 8, fontWeight: 700, fontSize: 13,
                            background: "#0284c7", color: "#fff", border: "none", cursor: "pointer",
                          }}
                        >
                          👁️ Open Saved Session
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => setSelectedGridDate(null)}
                        style={{ padding: "6px 12px", borderRadius: 8, fontSize: 12, background: "#fff" }}
                      >
                        Close
                      </button>
                    </div>
                  </div>
                )}

                {/* Error / Loading States */}
                {registerError && <div className="login-error">{registerError}</div>}
                {loadingRegister && <div className="empty-note">Loading monthly register data…</div>}

                {/* Empty state if no subject/semester selected */}
                {!loadingRegister && !register && !registerError && (
                  <div className="empty-note" style={{ padding: 32, background: "#f8fafc", borderRadius: 12, textAlign: "center" }}>
                    {!semesterId || !subjectId
                      ? "Please select a semester and subject from the form above to view the monthly register."
                      : "No attendance register data found for this selection."}
                  </div>
                )}

                {/* Register Grid Table */}
                {!loadingRegister && register && (
                  <div
                    style={{
                      position: "relative",
                      width: "100%",
                      overflowX: "auto",
                      border: "1px solid var(--border)",
                      borderRadius: 12,
                      boxShadow: "0 2px 6px rgba(0,0,0,0.04)",
                      background: "#ffffff",
                    }}
                  >
                    <table
                      style={{
                        width: "max-content",
                        minWidth: "100%",
                        borderCollapse: "separate",
                        borderSpacing: 0,
                        fontSize: 12,
                      }}
                    >
                      <thead>
                        <tr style={{ background: "#f8fafc" }}>
                          {/* Column 1: # */}
                          <th style={{
                            position: "sticky",
                            left: 0,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 44,
                            minWidth: 44,
                            maxWidth: 44,
                            padding: "10px 4px",
                            textAlign: "center",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--muted)",
                          }}>
                            #
                          </th>

                          {/* Column 2: Hall Ticket */}
                          <th style={{
                            position: "sticky",
                            left: 44,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 125,
                            minWidth: 125,
                            maxWidth: 125,
                            padding: "10px 10px",
                            textAlign: "left",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                            textTransform: "uppercase",
                            letterSpacing: "0.03em",
                          }}>
                            Hall Ticket
                          </th>

                          {/* Column 3: Student Name */}
                          <th style={{
                            position: "sticky",
                            left: 169,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 190,
                            minWidth: 190,
                            maxWidth: 190,
                            padding: "10px 12px",
                            textAlign: "left",
                            borderRight: "2px solid #cbd5e1",
                            borderBottom: "2px solid var(--border)",
                            boxShadow: "4px 0 8px -2px rgba(15, 23, 42, 0.08)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Student Name
                          </th>

                          {/* Date Columns 01..31 */}
                          {register.days.map((d) => {
                            const isSunday = d.weekday === "Sunday";
                            const isHoliday = d.holiday;
                            const hasSession = d.session_count > 0;
                            const isSelected = selectedGridDate === d.date;
                            return (
                              <th
                                key={d.date}
                                onClick={() => setSelectedGridDate(d.date)}
                                title={d.holiday_name || d.topic || (hasSession ? `${d.session_type} session (${d.duration_hours}h)` : "No session recorded")}
                                style={{
                                  width: 36,
                                  minWidth: 36,
                                  maxWidth: 36,
                                  padding: "6px 2px",
                                  textAlign: "center",
                                  cursor: "pointer",
                                  background: isSelected
                                    ? "#e0f2fe"
                                    : isHoliday
                                    ? "#fffbeb"
                                    : hasSession
                                    ? "#f0fdf4"
                                    : "#f8fafc",
                                  borderRight: "1px solid var(--border)",
                                  borderBottom: "2px solid var(--border)",
                                  transition: "all 0.15s ease",
                                }}
                              >
                                <div style={{
                                  fontWeight: 800,
                                  fontSize: 12,
                                  color: isHoliday ? "#b45309" : hasSession ? "#15803d" : "var(--text)",
                                }}>
                                  {String(d.day).padStart(2, "0")}
                                </div>
                                <div style={{
                                  fontSize: 9,
                                  fontWeight: 700,
                                  color: isSunday ? "#dc2626" : isHoliday ? "#b45309" : hasSession ? "#16a34a" : "var(--muted)",
                                  textTransform: "uppercase",
                                }}>
                                  {d.weekday.slice(0, 2)}
                                </div>
                                {hasSession && (
                                  <div style={{
                                    width: 4, height: 4, borderRadius: "50%", background: "#16a34a",
                                    margin: "2px auto 0 auto",
                                  }} />
                                )}
                              </th>
                            );
                          })}

                          {/* Right Summary Columns */}
                          <th style={{
                            position: "sticky",
                            right: 70,
                            top: 0,
                            zIndex: 28,
                            background: "#f8fafc",
                            width: 70,
                            minWidth: 70,
                            padding: "10px 6px",
                            textAlign: "center",
                            borderLeft: "2px solid #cbd5e1",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Attd
                          </th>
                          <th style={{
                            position: "sticky",
                            right: 0,
                            top: 0,
                            zIndex: 28,
                            background: "#f8fafc",
                            width: 70,
                            minWidth: 70,
                            padding: "10px 6px",
                            textAlign: "center",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            % Attd
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredRoster.map((row, rowIdx) => {
                          const isHovered = hoveredRow === rowIdx;
                          const isAlt = rowIdx % 2 === 1;
                          const rowBg = isHovered ? "#f0f7ff" : isAlt ? "#f8fafc" : "#ffffff";

                          // Calculate student metrics
                          const teachingDays = register.days.filter((d) => d.session_count > 0);
                          const totalSessions = teachingDays.length;
                          let presentCount = 0;
                          row.cells.forEach((cell, idx) => {
                            const day = register.days[idx];
                            if (day && day.session_count > 0 && cell.status === "P") {
                              presentCount += 1;
                            }
                          });
                          const studentPct = totalSessions > 0 ? Math.round((presentCount / totalSessions) * 100) : 100;

                          return (
                            <tr
                              key={row.roll_no}
                              onMouseEnter={() => setHoveredRow(rowIdx)}
                              onMouseLeave={() => setHoveredRow(null)}
                              style={{
                                background: rowBg,
                                transition: "background 0.1s ease",
                              }}
                            >
                              {/* Column 1: # */}
                              <td style={{
                                position: "sticky",
                                left: 0,
                                zIndex: 20,
                                background: rowBg,
                                textAlign: "center",
                                fontSize: 11,
                                fontWeight: 600,
                                color: "var(--muted)",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                                width: 44,
                                minWidth: 44,
                                maxWidth: 44,
                                padding: "6px 2px",
                              }}>
                                {rowIdx + 1}
                              </td>

                              {/* Column 2: Hall Ticket */}
                              <td style={{
                                position: "sticky",
                                left: 44,
                                zIndex: 20,
                                background: rowBg,
                                fontWeight: 700,
                                fontSize: 12,
                                fontFamily: "monospace",
                                color: "var(--text)",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                                width: 125,
                                minWidth: 125,
                                maxWidth: 125,
                                padding: "6px 10px",
                                whiteSpace: "nowrap",
                              }}>
                                {row.roll_no}
                              </td>

                              {/* Column 3: Student Name */}
                              <td style={{
                                position: "sticky",
                                left: 169,
                                zIndex: 20,
                                background: rowBg,
                                fontSize: 12,
                                fontWeight: 600,
                                color: "var(--text)",
                                borderRight: "2px solid #cbd5e1",
                                borderBottom: "1px solid var(--border)",
                                boxShadow: "4px 0 8px -2px rgba(15, 23, 42, 0.08)",
                                width: 190,
                                minWidth: 190,
                                maxWidth: 190,
                                padding: "6px 12px",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                                  <span>{row.name}</span>
                                  {semesterSummary && (() => {
                                    const match = semesterSummary.students.find((s) => s.roll_no === row.roll_no);
                                    return match ? (
                                      <button
                                        type="button"
                                        title="View All Subjects Attendance"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setSelectedStudentDrilldown(match);
                                        }}
                                        style={{
                                          background: "#e0f2fe", border: "1px solid #bae6fd",
                                          color: "#0284c7", borderRadius: 6, padding: "2px 6px",
                                          fontSize: 10, fontWeight: 700, cursor: "pointer",
                                        }}
                                      >
                                        📊 All
                                      </button>
                                    ) : null;
                                  })()}
                                </div>
                              </td>

                              {/* Date Cells */}
                              {row.cells.map((cell, cIdx) => {
                                const dayObj = register.days[cIdx];
                                const isHoliday = cell.status === "H" || dayObj?.holiday;
                                const isSelected = selectedGridDate === dayObj?.date;

                                return (
                                  <td
                                    key={cIdx}
                                    onClick={() => dayObj && setSelectedGridDate(dayObj.date)}
                                    title={dayObj ? `${dayObj.date} (${dayObj.weekday}): ${cell.status === "P" ? "Present" : cell.status === "A" ? "Absent" : cell.status === "H" ? `Holiday (${dayObj.holiday_name || "Holiday"})` : "No class"}` : ""}
                                    style={{
                                      textAlign: "center",
                                      padding: "4px 2px",
                                      cursor: "pointer",
                                      width: 36,
                                      minWidth: 36,
                                      maxWidth: 36,
                                      borderRight: "1px solid var(--border)",
                                      borderBottom: "1px solid var(--border)",
                                      background: isSelected
                                        ? "#e0f2fe"
                                        : isHoliday
                                        ? "#fffdf5"
                                        : undefined,
                                    }}
                                  >
                                    {cell.status === "P" ? (
                                      <span style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        width: 24,
                                        height: 24,
                                        borderRadius: 6,
                                        background: "#dcfce7",
                                        color: "#15803d",
                                        border: "1px solid #bbf7d0",
                                        fontWeight: 800,
                                        fontSize: 11,
                                      }}>
                                        P
                                      </span>
                                    ) : cell.status === "A" ? (
                                      <span style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        width: 24,
                                        height: 24,
                                        borderRadius: 6,
                                        background: "#fee2e2",
                                        color: "#b91c1c",
                                        border: "1px solid #fecaca",
                                        fontWeight: 800,
                                        fontSize: 11,
                                      }}>
                                        A
                                      </span>
                                    ) : isHoliday ? (
                                      <span style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        width: 24,
                                        height: 24,
                                        borderRadius: 6,
                                        background: "#fef3c7",
                                        color: "#b45309",
                                        border: "1px solid #fde68a",
                                        fontWeight: 800,
                                        fontSize: 10,
                                      }}>
                                        H
                                      </span>
                                    ) : (
                                      <span style={{ color: "#cbd5e1", fontSize: 16, fontWeight: 700, lineHeight: 1 }}>
                                        ·
                                      </span>
                                    )}
                                  </td>
                                );
                              })}

                              {/* Right Summary Columns */}
                              <td style={{
                                position: "sticky",
                                right: 70,
                                zIndex: 18,
                                background: rowBg,
                                textAlign: "center",
                                padding: "6px 4px",
                                fontSize: 12,
                                fontWeight: 700,
                                color: "var(--text)",
                                borderLeft: "2px solid #cbd5e1",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                                width: 70,
                                minWidth: 70,
                              }}>
                                {presentCount} / {totalSessions}
                              </td>

                              <td style={{
                                position: "sticky",
                                right: 0,
                                zIndex: 18,
                                background: rowBg,
                                textAlign: "center",
                                padding: "6px 4px",
                                borderBottom: "1px solid var(--border)",
                                width: 70,
                                minWidth: 70,
                              }}>
                                <span style={{
                                  display: "inline-block",
                                  padding: "2px 6px",
                                  borderRadius: 6,
                                  fontSize: 11,
                                  fontWeight: 800,
                                  background: studentPct >= 75 ? "#dcfce7" : studentPct >= 60 ? "#fef3c7" : "#fee2e2",
                                  color: studentPct >= 75 ? "#15803d" : studentPct >= 60 ? "#b45309" : "#b91c1c",
                                  border: studentPct >= 75 ? "1px solid #bbf7d0" : studentPct >= 60 ? "1px solid #fde68a" : "1px solid #fecaca",
                                }}>
                                  {studentPct}%
                                </span>
                              </td>
                            </tr>
                          );
                        })}

                        {filteredRoster.length === 0 && (
                          <tr>
                            <td
                              colSpan={register.days.length + 5}
                              style={{ textAlign: "center", padding: 32, color: "var(--muted)", background: "#ffffff" }}
                            >
                              {studentSearch
                                ? `No students matching "${studentSearch}".`
                                : "No students are assigned to this semester / HOD scope."}
                            </td>
                          </tr>
                        )}
                      </tbody>

                      {/* Daily Total Summary Footer */}
                      {filteredRoster.length > 0 && (
                        <tfoot>
                          <tr style={{ background: "#f1f5f9", fontWeight: 800 }}>
                            <td
                              colSpan={3}
                              style={{
                                position: "sticky",
                                left: 0,
                                zIndex: 25,
                                background: "#f1f5f9",
                                padding: "10px 14px",
                                textAlign: "right",
                                borderTop: "2px solid #cbd5e1",
                                borderRight: "2px solid #cbd5e1",
                                boxShadow: "4px 0 8px -2px rgba(15, 23, 42, 0.08)",
                                color: "var(--text)",
                                fontSize: 12,
                              }}
                            >
                              Daily Attendance (Present):
                            </td>

                            {dailyAttendanceSummary.map((sum, sIdx) => {
                              return (
                                <td
                                  key={sIdx}
                                  style={{
                                    textAlign: "center",
                                    padding: "6px 2px",
                                    borderTop: "2px solid #cbd5e1",
                                    borderRight: "1px solid var(--border)",
                                    fontSize: 10,
                                    fontWeight: 800,
                                    color: sum ? (sum.pct >= 75 ? "#15803d" : "#b45309") : "var(--muted)",
                                    background: sum ? "#f8fafc" : "#f1f5f9",
                                  }}
                                >
                                  {sum ? `${sum.presentCount}` : "—"}
                                </td>
                              );
                            })}

                            <td
                              style={{
                                position: "sticky",
                                right: 70,
                                zIndex: 22,
                                background: "#f1f5f9",
                                textAlign: "center",
                                padding: "8px 4px",
                                fontSize: 11,
                                fontWeight: 800,
                                borderTop: "2px solid #cbd5e1",
                                borderLeft: "2px solid #cbd5e1",
                                borderRight: "1px solid var(--border)",
                                color: "var(--text)",
                              }}
                            >
                              Avg
                            </td>

                            <td
                              style={{
                                position: "sticky",
                                right: 0,
                                zIndex: 22,
                                background: "#f1f5f9",
                                textAlign: "center",
                                padding: "8px 4px",
                                fontSize: 11,
                                fontWeight: 800,
                                borderTop: "2px solid #cbd5e1",
                                color: registerStats.classAvgPct >= 75 ? "#15803d" : "#b45309",
                              }}
                            >
                              {registerStats.classAvgPct}%
                            </td>
                          </tr>
                        </tfoot>
                      )}
                    </table>
                  </div>
                )}
              </>
            )}

            {/* ══════════════════════════════════════════════════════ */}
            {/* VIEW MODE 2: SEMESTER ALL-SUBJECTS ATTENDANCE MATRIX */}
            {/* ══════════════════════════════════════════════════════ */}
            {viewMode === "summary" && (
              <>
                {/* Semester Summary KPI Cards */}
                {semesterSummary && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                      gap: 12,
                    }}>
                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>👥</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Total Students</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text)" }}>{semesterSummaryStats.totalStudents}</div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>📚</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Subjects</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text)" }}>{semesterSummary.subjects.length}</div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>📊</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Overall Avg %</div>
                          <div style={{
                            fontSize: 18, fontWeight: 800,
                            color: semesterSummaryStats.avgPct >= 75 ? "#15803d" : semesterSummaryStats.avgPct >= 60 ? "#b45309" : "#b91c1c",
                          }}>
                            {semesterSummaryStats.avgPct}%
                          </div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>🎯</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Eligible (≥75%)</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: "#15803d" }}>
                            {semesterSummaryStats.eligibleCount} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>students</span>
                          </div>
                        </div>
                      </div>

                      <div style={{
                        padding: "12px 14px", borderRadius: 12, background: "#f8fafc",
                        border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10,
                      }}>
                        <div style={{ fontSize: 20 }}>⚠️</div>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase" }}>Shortage (&lt;75%)</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: semesterSummaryStats.shortageCount > 0 ? "#b91c1c" : "#15803d" }}>
                            {semesterSummaryStats.shortageCount} <span style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)" }}>students</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Search box */}
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      flexWrap: "wrap",
                      gap: 12,
                      padding: "10px 14px",
                      background: "#f8fafc",
                      borderRadius: 12,
                      border: "1px solid var(--border)",
                    }}>
                      <div style={{ position: "relative", minWidth: 260, flex: "1 1 260px", maxWidth: 400 }}>
                        <input
                          type="text"
                          className="input-field"
                          placeholder="🔍 Search roll no or student name…"
                          value={studentSearch}
                          onChange={(e) => setStudentSearch(e.target.value)}
                          style={{
                            height: 34,
                            padding: "0 28px 0 10px",
                            fontSize: 12,
                            borderRadius: 8,
                            background: "#ffffff",
                          }}
                        />
                        {studentSearch && (
                          <button
                            type="button"
                            onClick={() => setStudentSearch("")}
                            style={{
                              position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                              background: "none", border: "none", color: "var(--muted)", cursor: "pointer",
                              fontSize: 12, fontWeight: 700,
                            }}
                          >
                            ✕
                          </button>
                        )}
                      </div>
                      <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}>
                        Showing {filteredSemesterStudents.length} of {semesterSummary.students.length} students under HOD
                      </div>
                    </div>
                  </div>
                )}

                {/* Loading / Error states */}
                {summaryError && <div className="login-error">{summaryError}</div>}
                {loadingSummary && <div className="empty-note">Loading semester attendance matrix…</div>}

                {!loadingSummary && !semesterSummary && !summaryError && (
                  <div className="empty-note" style={{ padding: 32, background: "#f8fafc", borderRadius: 12, textAlign: "center" }}>
                    Select a semester above to view the all-subjects attendance matrix.
                  </div>
                )}

                {/* All-Subjects Matrix Table */}
                {!loadingSummary && semesterSummary && (
                  <div
                    style={{
                      position: "relative",
                      width: "100%",
                      overflowX: "auto",
                      border: "1px solid var(--border)",
                      borderRadius: 12,
                      boxShadow: "0 2px 6px rgba(0,0,0,0.04)",
                      background: "#ffffff",
                    }}
                  >
                    <table
                      style={{
                        width: "max-content",
                        minWidth: "100%",
                        borderCollapse: "separate",
                        borderSpacing: 0,
                        fontSize: 12,
                      }}
                    >
                      <thead>
                        <tr style={{ background: "#f8fafc" }}>
                          {/* Col 1: # */}
                          <th style={{
                            position: "sticky",
                            left: 0,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 44,
                            minWidth: 44,
                            padding: "10px 4px",
                            textAlign: "center",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--muted)",
                          }}>
                            #
                          </th>

                          {/* Col 2: Hall Ticket */}
                          <th style={{
                            position: "sticky",
                            left: 44,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 125,
                            minWidth: 125,
                            padding: "10px 10px",
                            textAlign: "left",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                            textTransform: "uppercase",
                          }}>
                            Hall Ticket
                          </th>

                          {/* Col 3: Student Name */}
                          <th style={{
                            position: "sticky",
                            left: 169,
                            top: 0,
                            zIndex: 30,
                            background: "#f8fafc",
                            width: 200,
                            minWidth: 200,
                            padding: "10px 12px",
                            textAlign: "left",
                            borderRight: "2px solid #cbd5e1",
                            borderBottom: "2px solid var(--border)",
                            boxShadow: "4px 0 8px -2px rgba(15, 23, 42, 0.08)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Student Name
                          </th>

                          {/* Subject Columns */}
                          {semesterSummary.subjects.map((sub) => (
                            <th
                              key={sub.id}
                              title={`${sub.code} - ${sub.name}`}
                              style={{
                                width: 110,
                                minWidth: 110,
                                padding: "8px 6px",
                                textAlign: "center",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "2px solid var(--border)",
                              }}
                            >
                              <div style={{ fontWeight: 800, fontSize: 12, color: "var(--text)" }}>{sub.code}</div>
                              <div style={{
                                fontSize: 10,
                                color: "var(--muted)",
                                fontWeight: 600,
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                maxWidth: 100,
                                margin: "0 auto",
                              }}>
                                {sub.name}
                              </div>
                            </th>
                          ))}

                          {/* Summary Columns */}
                          <th style={{
                            position: "sticky",
                            right: 170,
                            top: 0,
                            zIndex: 28,
                            background: "#f8fafc",
                            width: 85,
                            minWidth: 85,
                            padding: "10px 6px",
                            textAlign: "center",
                            borderLeft: "2px solid #cbd5e1",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Attd / Tot
                          </th>

                          <th style={{
                            position: "sticky",
                            right: 85,
                            top: 0,
                            zIndex: 28,
                            background: "#f8fafc",
                            width: 85,
                            minWidth: 85,
                            padding: "10px 6px",
                            textAlign: "center",
                            borderRight: "1px solid var(--border)",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Overall %
                          </th>

                          <th style={{
                            position: "sticky",
                            right: 0,
                            top: 0,
                            zIndex: 28,
                            background: "#f8fafc",
                            width: 85,
                            minWidth: 85,
                            padding: "10px 6px",
                            textAlign: "center",
                            borderBottom: "2px solid var(--border)",
                            fontWeight: 800,
                            color: "var(--text)",
                          }}>
                            Status
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredSemesterStudents.map((st, idx) => {
                          const isHovered = hoveredRow === idx;
                          const isAlt = idx % 2 === 1;
                          const rowBg = isHovered ? "#f0f7ff" : isAlt ? "#f8fafc" : "#ffffff";
                          const ovPct = st.overall_pct ?? 0;
                          const isEligible = ovPct >= 75;

                          return (
                            <tr
                              key={st.roll_no}
                              onMouseEnter={() => setHoveredRow(idx)}
                              onMouseLeave={() => setHoveredRow(null)}
                              onClick={() => setSelectedStudentDrilldown(st)}
                              style={{
                                background: rowBg,
                                cursor: "pointer",
                                transition: "background 0.1s ease",
                              }}
                            >
                              {/* # */}
                              <td style={{
                                position: "sticky",
                                left: 0,
                                zIndex: 20,
                                background: rowBg,
                                textAlign: "center",
                                fontSize: 11,
                                fontWeight: 600,
                                color: "var(--muted)",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                                padding: "8px 2px",
                              }}>
                                {idx + 1}
                              </td>

                              {/* Hall Ticket */}
                              <td style={{
                                position: "sticky",
                                left: 44,
                                zIndex: 20,
                                background: rowBg,
                                fontWeight: 700,
                                fontSize: 12,
                                fontFamily: "monospace",
                                color: "var(--text)",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                                padding: "8px 10px",
                                whiteSpace: "nowrap",
                              }}>
                                {st.roll_no}
                              </td>

                              {/* Student Name */}
                              <td style={{
                                position: "sticky",
                                left: 169,
                                zIndex: 20,
                                background: rowBg,
                                fontSize: 12,
                                fontWeight: 700,
                                color: "#0f172a",
                                borderRight: "2px solid #cbd5e1",
                                borderBottom: "1px solid var(--border)",
                                boxShadow: "4px 0 8px -2px rgba(15, 23, 42, 0.08)",
                                padding: "8px 12px",
                                whiteSpace: "nowrap",
                              }}>
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                                  <span>{st.name}</span>
                                  <span style={{ fontSize: 11, color: "#2563eb", fontWeight: 700 }}>🔍</span>
                                </div>
                              </td>

                              {/* Subject cells */}
                              {st.subjects.map((sub) => {
                                const subPct = sub.pct;
                                const cellBg = sub.total === 0
                                  ? undefined
                                  : sub.band === "green"
                                  ? "rgba(16, 185, 129, 0.06)"
                                  : sub.band === "yellow"
                                  ? "rgba(245, 158, 11, 0.08)"
                                  : "rgba(239, 68, 68, 0.08)";
                                return (
                                  <td
                                    key={sub.subject_id}
                                    style={{
                                      textAlign: "center",
                                      padding: "6px 4px",
                                      borderRight: "1px solid var(--border)",
                                      borderBottom: "1px solid var(--border)",
                                      background: cellBg,
                                    }}
                                  >
                                    {sub.total > 0 ? (
                                      <div>
                                        <div style={{
                                          fontWeight: 800,
                                          fontSize: 11.5,
                                          color: sub.band === "green" ? "#15803d" : sub.band === "yellow" ? "#b45309" : "#b91c1c",
                                        }}>
                                          {subPct !== null ? `${subPct}%` : "—"}
                                        </div>
                                        <div style={{ fontSize: 10, color: "var(--muted)", fontWeight: 600 }}>
                                          {sub.present}/{sub.total}
                                        </div>
                                      </div>
                                    ) : (
                                      <span style={{ color: "#cbd5e1", fontSize: 14, fontWeight: 700 }}>—</span>
                                    )}
                                  </td>
                                );
                              })}

                              {/* Attd / Tot */}
                              <td style={{
                                position: "sticky",
                                right: 170,
                                zIndex: 18,
                                background: rowBg,
                                textAlign: "center",
                                padding: "8px 4px",
                                fontSize: 12,
                                fontWeight: 700,
                                color: "var(--text)",
                                borderLeft: "2px solid #cbd5e1",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                              }}>
                                {st.present_classes} / {st.total_classes}
                              </td>

                              {/* Overall % */}
                              <td style={{
                                position: "sticky",
                                right: 85,
                                zIndex: 18,
                                background: rowBg,
                                textAlign: "center",
                                padding: "8px 4px",
                                borderRight: "1px solid var(--border)",
                                borderBottom: "1px solid var(--border)",
                              }}>
                                <span style={{
                                  display: "inline-block",
                                  padding: "2px 8px",
                                  borderRadius: 6,
                                  fontSize: 11.5,
                                  fontWeight: 800,
                                  background: ovPct >= 75 ? "#dcfce7" : ovPct >= 60 ? "#fef3c7" : "#fee2e2",
                                  color: ovPct >= 75 ? "#15803d" : ovPct >= 60 ? "#b45309" : "#b91c1c",
                                  border: ovPct >= 75 ? "1px solid #bbf7d0" : ovPct >= 60 ? "1px solid #fde68a" : "1px solid #fecaca",
                                }}>
                                  {st.overall_pct !== null ? `${st.overall_pct}%` : "—"}
                                </span>
                              </td>

                              {/* Status */}
                              <td style={{
                                position: "sticky",
                                right: 0,
                                zIndex: 18,
                                background: rowBg,
                                textAlign: "center",
                                padding: "8px 4px",
                                borderBottom: "1px solid var(--border)",
                              }}>
                                <span className={`chip ${isEligible ? "chip-green" : "chip-red"}`} style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 6px" }}>
                                  {isEligible ? "Eligible" : "Shortage"}
                                </span>
                              </td>
                            </tr>
                          );
                        })}

                        {filteredSemesterStudents.length === 0 && (
                          <tr>
                            <td
                              colSpan={semesterSummary.subjects.length + 6}
                              style={{ textAlign: "center", padding: 32, color: "var(--muted)", background: "#ffffff" }}
                            >
                              {studentSearch
                                ? `No students matching "${studentSearch}".`
                                : "No students found in this semester."}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}

            {/* ══════════════════════════════════════════════════════ */}
            {/* QUICK STUDENT SUBJECT ATTENDANCE DRILLDOWN MODAL      */}
            {/* ══════════════════════════════════════════════════════ */}
            {selectedStudentDrilldown && (
              <div
                className="modal-overlay"
                onClick={() => setSelectedStudentDrilldown(null)}
                style={{
                  position: "fixed",
                  top: 0, left: 0, right: 0, bottom: 0,
                  background: "rgba(15, 23, 42, 0.6)",
                  backdropFilter: "blur(4px)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 9999,
                  padding: 16,
                }}
              >
                <div
                  className="modal-box modal3dPopIn"
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    background: "#ffffff",
                    borderRadius: 18,
                    padding: 24,
                    width: "100%",
                    maxWidth: 640,
                    maxHeight: "90vh",
                    overflowY: "auto",
                    boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{
                          width: 40, height: 40, borderRadius: 10,
                          background: "linear-gradient(135deg, #2563eb, #3b82f6)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "#fff", fontSize: 18,
                        }}>
                          👤
                        </div>
                        <div>
                          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text)" }}>
                            {selectedStudentDrilldown.name}
                          </h3>
                          <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600 }}>
                            Roll No: <strong>{selectedStudentDrilldown.roll_no}</strong>
                          </div>
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedStudentDrilldown(null)}
                      style={{
                        background: "none", border: "none", fontSize: 20,
                        cursor: "pointer", color: "var(--muted)", fontWeight: 800,
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  {/* Summary Metric Cards */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 18 }}>
                    <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: 10, border: "1px solid var(--border)" }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 700 }}>Total Classes</div>
                      <div style={{ fontSize: 18, fontWeight: 800, marginTop: 2 }}>{selectedStudentDrilldown.total_classes}</div>
                    </div>
                    <div style={{ background: "rgba(16, 185, 129, 0.08)", padding: "10px 14px", borderRadius: 10, border: "1px solid rgba(16, 185, 129, 0.2)" }}>
                      <div style={{ fontSize: 11, color: "#059669", fontWeight: 700 }}>Attended</div>
                      <div style={{ fontSize: 18, fontWeight: 800, color: "#059669", marginTop: 2 }}>{selectedStudentDrilldown.present_classes}</div>
                    </div>
                    <div style={{ background: "rgba(37, 99, 235, 0.08)", padding: "10px 14px", borderRadius: 10, border: "1px solid rgba(37, 99, 235, 0.2)" }}>
                      <div style={{ fontSize: 11, color: "#2563eb", fontWeight: 700 }}>Overall Attendance</div>
                      <div style={{ fontSize: 18, fontWeight: 800, color: "#2563eb", marginTop: 2 }}>
                        {selectedStudentDrilldown.overall_pct !== null ? `${selectedStudentDrilldown.overall_pct}%` : "—"}
                      </div>
                    </div>
                  </div>

                  {/* Breakdown Table */}
                  <h4 style={{ margin: "0 0 10px 0", fontSize: 14, fontWeight: 800 }}>Subject Breakdown:</h4>
                  <div className="table-wrap" style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
                    <table className="data-table" style={{ fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: "#f8fafc" }}>
                          <th>Subject</th>
                          <th style={{ textAlign: "center", width: 70 }}>Present</th>
                          <th style={{ textAlign: "center", width: 70 }}>Total</th>
                          <th style={{ textAlign: "right", width: 80 }}>%</th>
                          <th style={{ textAlign: "center", width: 90 }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedStudentDrilldown.subjects.map((s) => (
                          <tr key={s.subject_id}>
                            <td>
                              <span className="code-badge" style={{ marginRight: 6, fontWeight: 700 }}>{s.subject_code}</span>
                              <strong>{s.subject_name}</strong>
                            </td>
                            <td style={{ textAlign: "center", color: "#059669", fontWeight: 700 }}>{s.present}</td>
                            <td style={{ textAlign: "center", color: "var(--muted)", fontWeight: 600 }}>{s.total}</td>
                            <td style={{ textAlign: "right", fontWeight: 800 }}>
                              {s.pct !== null ? `${s.pct}%` : "—"}
                            </td>
                            <td style={{ textAlign: "center" }}>
                              <span className={`chip ${s.band === "green" ? "chip-green" : s.band === "yellow" ? "chip-warn" : s.band === "red" ? "chip-red" : "chip-muted"}`} style={{ fontSize: 10.5, fontWeight: 700 }}>
                                {s.band === "green" ? "Normal" : s.band === "yellow" ? "Shortage" : s.band === "red" ? "Critical" : "No Class"}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 18 }}>
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => setSelectedStudentDrilldown(null)}
                      style={{ padding: "6px 16px", borderRadius: 8 }}
                    >
                      Close
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>


          {/* Semester View - Attendance History for Selected Semester */}
          <div
            style={{
              background: "#ffffff",
              border: "1px solid var(--border)",
              borderRadius: 16,
              padding: 24,
              boxShadow: "0 10px 30px rgba(0,0,0,0.06)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: "var(--text)" }}>
                  📋 Semester Attendance View {selectedSemester ? `— ${selectedSemester.code}` : ""}
                </h3>
                <p style={{ margin: "3px 0 0 0", color: "var(--muted)", fontSize: 13 }}>
                  {selectedSemester ? `Recent sessions recorded for ${selectedSemester.name}` : "Select a semester above to view its attendance history."}
                </p>
              </div>
              {semesterSessions.length > 0 && (
                <span className="chip chip-green" style={{ fontSize: 12, padding: "4px 12px" }}>
                  {semesterSessions.length} Session(s)
                </span>
              )}
            </div>

            {loadingSessions && <div className="empty-note">Loading semester sessions…</div>}

            {!loadingSessions && semesterSessions.length === 0 && (
              <div className="empty-note" style={{ padding: 24, background: "#f8fafc", borderRadius: 10, textAlign: "center" }}>
                {semesterId
                  ? `No attendance sessions recorded yet for ${selectedSemester?.code ?? "this semester"}.`
                  : "Please select a semester from the dropdown to view sessions."}
              </div>
            )}

            {!loadingSessions && semesterSessions.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {semesterSessions.map((sess) => {
                  const total = sess.total_marked || (sess.present_count + sess.absent_count);
                  const pct = total > 0 ? Math.round((sess.present_count / total) * 100) : 0;
                  return (
                    <div
                      key={sess.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "14px 18px",
                        background: "#f8fafc",
                        borderRadius: 12,
                        border: "1px solid var(--border)",
                        flexWrap: "wrap",
                        gap: 12,
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                          <span className={`chip ${sess.session_type === "LAB" ? "chip-yellow" : "chip-green"}`} style={{ fontSize: 10, padding: "2px 8px" }}>
                            {sess.session_type}
                          </span>
                          <strong style={{ fontSize: 14, color: "var(--text)" }}>{sess.subject_name}</strong>
                          <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}>({sess.subject_code})</span>
                        </div>
                        <div style={{ fontSize: 12, color: "var(--muted)", display: "flex", gap: 10, flexWrap: "wrap" }}>
                          <span>📅 {sess.attendance_date}</span>
                          <span>•</span>
                          <span>👤 {sess.faculty_name || sess.faculty_username}</span>
                          {sess.topic && (
                            <>
                              <span>•</span>
                              <span style={{ fontStyle: "italic" }}>"{sess.topic.length > 30 ? sess.topic.substring(0, 30) + '…' : sess.topic}"</span>
                            </>
                          )}
                        </div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 14, fontWeight: 800, color: pct >= 75 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#ef4444" }}>
                            {pct}% Present
                          </div>
                          <div style={{ fontSize: 11, color: "var(--muted)" }}>
                            {sess.present_count} / {total} Attended
                          </div>
                        </div>

                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => navigate(`/attendance/sessions/${sess.id}`)}
                          style={{ padding: "6px 14px", borderRadius: 8, fontWeight: 700, fontSize: 13, background: "#ffffff" }}
                        >
                          👁️ View Register
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

