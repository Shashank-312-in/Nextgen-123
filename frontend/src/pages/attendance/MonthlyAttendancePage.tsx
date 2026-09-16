import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getMonthlyRegister,
  getSetup,
  getSubjectsForSemester,
  monthlyRegisterPdfUrl,
  type MonthlyAttendanceDay,
  type MonthlyAttendanceRegister,
  type MonthlyAttendanceRow,
  type SemesterOption,
  type SubjectOption,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import "./monthly-attendance.css";

interface MonthlyAttendancePageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function isoToday() {
  const d = new Date();
  return { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate() };
}

function pctLabel(pct: number | undefined) {
  return pct == null ? "—" : `${Math.round(pct)}%`;
}

function statusLabel(status: "P" | "A" | "H" | null) {
  if (status === "P") return "Present";
  if (status === "A") return "Absent";
  if (status === "H") return "Holiday";
  return "No class";
}

function StatusMark({ status }: { status: "P" | "A" | "H" | null }) {
  return (
    <span className={`mar-status mar-status-${status ?? "none"}`} title={statusLabel(status)} aria-label={statusLabel(status)}>
      <span aria-hidden="true">{status === "P" ? "✓" : status === "A" ? "A" : status === "H" ? "H" : "—"}</span>
    </span>
  );
}

function formatDayMeta(day: MonthlyAttendanceDay) {
  if (day.holiday) return day.holiday_name || "Holiday";
  if (!day.session_count) return "No class";
  return `${day.session_count} session${day.session_count > 1 ? "s" : ""}`;
}

function weekdayIndex(name: string) {
  const key = name.trim().toLowerCase().slice(0, 3);
  return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].indexOf(key);
}

function isFutureDay(year: number, month: number, day: number) {
  const value = new Date(year, month - 1, day);
  const now = new Date();
  const todayValue = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return value > todayValue;
}

export function MonthlyAttendancePage({ user, onLoggedOut }: MonthlyAttendancePageProps) {
  const navigate = useNavigate();
  const today = useMemo(isoToday, []);
  const [semesters, setSemesters] = useState<SemesterOption[]>([]);
  const [subjects, setSubjects] = useState<SubjectOption[]>([]);
  const [semesterId, setSemesterId] = useState<number | null>(null);
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const [year, setYear] = useState(today.year);
  const [month, setMonth] = useState(today.month);
  const [register, setRegister] = useState<MonthlyAttendanceRegister | null>(null);
  const [selectedDay, setSelectedDay] = useState<number | null>(today.day);
  const [selectedStudent, setSelectedStudent] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [studentQuery, setStudentQuery] = useState("");
  const [studentPickerOpen, setStudentPickerOpen] = useState(false);
  const [loadingSetup, setLoadingSetup] = useState(true);
  const [loadingSubjects, setLoadingSubjects] = useState(false);
  const [loadingRegister, setLoadingRegister] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileDay, setMobileDay] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const setup = await getSetup();
        if (!alive) return;
        setSemesters(setup.semesters);
        const initial = setup.default_semester_id ?? setup.semesters[0]?.id ?? null;
        setSemesterId(initial);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof ApiClientError ? err.message : "Could not load attendance setup.");
      } finally {
        if (alive) setLoadingSetup(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!semesterId) return;
    let alive = true;
    (async () => {
      try {
        setLoadingSubjects(true);
        setError(null);
        const result = await getSubjectsForSemester(semesterId);
        if (!alive) return;
        setSubjects(result.subjects ?? []);
        setSubjectId((current) => (current && result.subjects.some((s) => s.id === current) ? current : result.subjects[0]?.id ?? null));
      } catch (err) {
        if (!alive) return;
        setSubjects([]);
        setSubjectId(null);
        setError(err instanceof ApiClientError ? err.message : "Could not load subjects.");
      } finally {
        if (alive) setLoadingSubjects(false);
      }
    })();
    return () => { alive = false; };
  }, [semesterId]);

  useEffect(() => {
    if (!semesterId || !subjectId) return;
    let alive = true;
    (async () => {
      try {
        setLoadingRegister(true);
        setError(null);
        const result = await getMonthlyRegister({ semesterId, subjectId, year, month });
        if (!alive) return;
        setRegister(result);
        const inMonthToday = year === today.year && month === today.month;
        const defaultDay = inMonthToday ? today.day : 1;
        setSelectedDay(defaultDay);
        setMobileDay(null);
        setSelectedStudent((current) => {
          if (current && result.roster.some((r) => r.roll_no === current)) return current;
          return result.roster[0]?.roll_no ?? null;
        });
      } catch (err) {
        if (!alive) return;
        setRegister(null);
        setSelectedStudent(null);
        setError(err instanceof ApiClientError ? err.message : "Could not load the monthly register.");
      } finally {
        if (alive) setLoadingRegister(false);
      }
    })();
    return () => { alive = false; };
  }, [semesterId, subjectId, year, month, today.day, today.month, today.year]);

  const selectedSubject = subjects.find((s) => s.id === subjectId) ?? register?.subject;
  const selectedSemester = semesters.find((s) => s.id === semesterId) ?? register?.semester;
  const visibleRoster = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!register || !q) return register?.roster ?? [];
    return register.roster.filter((row) => `${row.roll_no} ${row.name}`.toLowerCase().includes(q));
  }, [register, query]);
  const mobileStudents = useMemo(() => {
    const q = studentQuery.trim().toLowerCase();
    const roster = register?.roster ?? [];
    if (!q) return roster;
    return roster.filter((row) => `${row.roll_no} ${row.name}`.toLowerCase().includes(q));
  }, [register, studentQuery]);
  const selectedStudentRow = register?.roster.find((row) => row.roll_no === selectedStudent) ?? null;
  const selectedDayData = register?.days.find((d) => d.day === selectedDay) ?? null;
  const selectedMobileDay = register?.days.find((d) => d.day === mobileDay) ?? selectedDayData;
  const selectedMobileStatus = selectedStudentRow && selectedMobileDay
    ? selectedStudentRow.cells.find((c) => c.day === selectedMobileDay.day)?.status ?? null
    : null;

  const changeMonth = (delta: number) => {
    const next = new Date(year, month - 1 + delta, 1);
    setYear(next.getFullYear());
    setMonth(next.getMonth() + 1);
  };

  const goToToday = () => {
    setYear(today.year);
    setMonth(today.month);
    setSelectedDay(today.day);
    setMobileDay(today.day);
  };

  const selectDate = (day: number, row?: MonthlyAttendanceRow) => {
    setSelectedDay(day);
    setMobileDay(day);
    if (row) setSelectedStudent(row.roll_no);
  };

  return (
    <AppShell user={user} activeNav="attendance" heading="Monthly Attendance" onLoggedOut={onLoggedOut}>
      <div className="monthly-page">
        <div className="monthly-topbar">
          <div className="monthly-heading">
            <button
              type="button"
              className="monthly-back"
              onClick={() => navigate("/attendance")}
              aria-label="Back to Attendance"
            >
              <span aria-hidden="true" className="monthly-back-icon">‹</span>
              <span>Attendance</span>
            </button>
            <div>
              <div className="monthly-kicker">Monthly register</div>
              <h1>Monthly attendance</h1>
              <p className="monthly-heading-desktop-copy">Review a subject month at a time. Select a date to inspect the class session without leaving the register.</p>
            </div>
          </div>
          {register && (
            <a
              className="monthly-export"
              href={monthlyRegisterPdfUrl({ semesterId: register.semester.id, subjectId: register.subject.id, year: register.year, month: register.month })}
              target="_blank"
              rel="noreferrer"
            >
              <span aria-hidden="true">↓</span> Export PDF
            </a>
          )}
        </div>

        <section className="monthly-controls" aria-label="Register controls">
          <div className="monthly-context-selectors">
            <div className="monthly-context-selectors-label">Attendance context</div>
            <div className="monthly-selector-grid">
          <div className="monthly-field">
            <label htmlFor="monthly-semester">Semester</label>
            <select id="monthly-semester" value={semesterId ?? ""} onChange={(e) => setSemesterId(Number(e.target.value) || null)} disabled={loadingSetup}>
              {semesters.map((semester) => <option key={semester.id} value={semester.id}>{semester.code} · {semester.name}</option>)}
            </select>
          </div>
          <div className="monthly-field monthly-field-subject">
            <label htmlFor="monthly-subject">Subject</label>
            <select id="monthly-subject" value={subjectId ?? ""} onChange={(e) => setSubjectId(Number(e.target.value) || null)} disabled={!semesterId || loadingSubjects}>
              {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.code} · {subject.name}</option>)}
            </select>
          </div>
            </div>
          </div>
          <div className="monthly-month-control">
            <div className="monthly-month-label"><span>Month</span><strong>{MONTHS[month - 1]} {year}</strong></div>
            <div className="monthly-month-actions">
              <button type="button" onClick={() => changeMonth(-1)} aria-label="Previous month">‹</button>
              <button type="button" onClick={goToToday} className="monthly-today" aria-label="Go to current month">Today</button>
              <button type="button" onClick={() => changeMonth(1)} aria-label="Next month">›</button>
            </div>
          </div>
        </section>

        {error && <div className="monthly-alert" role="alert">{error}</div>}

        {register && (
          <>
            <section className="monthly-context">
              <div className="monthly-context-main">
                <div className="monthly-subject-code">{selectedSubject?.code ?? register.subject.code}</div>
                <div>
                  <h2>{selectedSubject?.name ?? register.subject.name}</h2>
                  <p>{selectedSemester?.code ?? register.semester.code} · {register.faculty_name}</p>
                </div>
              </div>
              <div className="monthly-context-note">Saved sessions only</div>
            </section>

            <section className="monthly-summary" aria-label="Monthly summary">
              <div className="summary-students"><span>Students</span><strong>{register.stats?.total_students ?? register.roster.length}</strong></div>
              <div><span>Sessions</span><strong>{register.stats?.total_sessions ?? 0}</strong></div>
              <div className="summary-average"><span>Average</span><strong>{Math.round(register.stats?.class_avg_pct ?? 0)}%</strong></div>
              <div className={(register.stats?.shortage_count ?? 0) > 0 ? "attention" : ""}><span>Below 75%</span><strong>{register.stats?.shortage_count ?? 0}</strong></div>
            </section>

            <div className="monthly-desktop-only">
              <section className="monthly-register-shell">
                <div className="monthly-register-toolbar">
                  <div>
                    <h2>Student register</h2>
                    <p>{register.roster.length} students · {register.days.length} calendar days</p>
                  </div>
                  <label className="monthly-search">
                    <span aria-hidden="true">⌕</span>
                    <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search student or roll no." aria-label="Search student or roll number" />
                  </label>
                </div>

                <div className="monthly-grid-wrap">
                  <table className="monthly-grid">
                    <thead>
                      <tr>
                        <th className="monthly-student-col" scope="col">Student</th>
                        {register.days.map((day) => (
                          <th key={day.day} scope="col" className={`${day.holiday ? "is-holiday" : ""} ${day.session_count ? "has-session" : ""}`}>
                            <button type="button" onClick={() => selectDate(day.day)} className={selectedDay === day.day ? "is-selected" : ""} aria-label={`${day.weekday}, ${day.day} ${MONTHS[month - 1]}`}>
                              <small>{day.weekday.slice(0, 3)}</small>
                              <span>{day.day}</span>
                            </button>
                          </th>
                        ))}
                        <th className="monthly-total-col" scope="col">Attendance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleRoster.length === 0 ? (
                        <tr><td className="monthly-no-results" colSpan={register.days.length + 2}>No students match “{query}”.</td></tr>
                      ) : visibleRoster.map((row) => (
                        <tr key={row.roll_no} className={selectedStudent === row.roll_no ? "is-focused" : ""}>
                          <th className="monthly-student-col" scope="row">
                            <button type="button" className="monthly-student-cell" onClick={() => setSelectedStudent(row.roll_no)}>
                              <span className="monthly-student-name">{row.name}</span>
                              <span className="monthly-roll">{row.roll_no}</span>
                            </button>
                          </th>
                          {register.days.map((day) => {
                            const cell = row.cells.find((c) => c.day === day.day);
                            const status = cell?.status ?? null;
                            return (
                              <td key={day.day} className={`${day.holiday ? "is-holiday" : ""} ${day.session_count ? "has-session" : ""} ${selectedDay === day.day ? "is-day-selected" : ""}`}>
                                <button type="button" className="monthly-cell-button" onClick={() => selectDate(day.day, row)} aria-label={`${row.name}, ${day.day}: ${statusLabel(status)}`}>
                                  <StatusMark status={status} />
                                </button>
                              </td>
                            );
                          })}
                          <td className="monthly-total-cell">
                            <span className={`monthly-pct ${row.band ?? "muted"}`}>{pctLabel(row.pct)}</span>
                            <small>{row.present_count ?? 0}/{row.total_count ?? 0}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <aside className="monthly-day-panel" aria-label="Selected day details">
                {selectedDayData ? (
                  <>
                    <div className="monthly-day-head">
                      <div>
                        <span>{selectedDayData.weekday}</span>
                        <h2>{selectedDayData.day} {MONTHS[month - 1]}</h2>
                      </div>
                      <button type="button" className="monthly-close-desktop" onClick={() => setSelectedDay(null)} aria-label="Clear selected day">×</button>
                    </div>
                    {selectedDayData.holiday ? (
                      <div className="monthly-detail-empty">
                        <div className="monthly-detail-mark holiday">H</div>
                        <strong>{selectedDayData.holiday_name || "Holiday"}</strong>
                        <span>No attendance session is expected for this date.</span>
                      </div>
                    ) : selectedDayData.session_count ? (
                      <>
                        <div className="monthly-session-summary">
                          <div><span>Session</span><strong>{selectedDayData.session_count > 1 ? `${selectedDayData.session_count} sessions` : selectedDayData.session_type === "LAB" ? "Lab" : "Regular class"}</strong></div>
                          <div><span>Duration</span><strong>{selectedDayData.duration_hours ?? 0}h</strong></div>
                        </div>
                        <div className="monthly-topic">
                          <span>Topic</span>
                          <strong>{selectedDayData.topic || "Topic not recorded"}</strong>
                        </div>
                        {selectedStudentRow && (
                          <div className="monthly-student-detail">
                            <div>
                              <span>{selectedStudentRow.name}</span>
                              <small>{selectedStudentRow.roll_no}</small>
                            </div>
                            <div className="monthly-student-day-stat">
                              <strong>{selectedStudentRow.cells.find((c) => c.day === selectedDayData.day)?.status ?? "—"}</strong>
                              <span>that day</span>
                            </div>
                          </div>
                        )}
                        {selectedDayData.session_ids.length === 1 && (
                          <button type="button" className="monthly-session-link" onClick={() => navigate(`/attendance/sessions/${selectedDayData.session_ids[0]}`)}>Open session <span>→</span></button>
                        )}
                        {selectedDayData.session_ids.length > 1 && (
                          <div className="monthly-session-note">This date contains multiple saved sessions. Attendance is summarized together in the month view.</div>
                        )}
                      </>
                    ) : (
                      <div className="monthly-detail-empty">
                        <div className="monthly-detail-mark none">—</div>
                        <strong>No class</strong>
                        <span>No saved attendance session exists for this day.</span>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="monthly-detail-empty panel-empty"><strong>Select a date</strong><span>Choose any day in the register to inspect its session context.</span></div>
                )}
              </aside>
            </div>

            <section className="monthly-mobile-only">
              <div className="mobile-student-picker-head">
                <div>
                  <span>Student</span>
                  <strong>{selectedStudentRow?.name ?? "Select a student"}</strong>
                  <small>{selectedStudentRow?.roll_no ?? ""}</small>
                </div>
                <div className="mobile-student-picker-actions">
                  <span className={`mobile-student-pct ${selectedStudentRow?.band ?? "muted"}`}>{pctLabel(selectedStudentRow?.pct)}</span>
                  <button type="button" className="mobile-change-student" onClick={() => { setStudentPickerOpen((open) => !open); if (studentPickerOpen) setStudentQuery(""); }} aria-label="Change student">Change</button>
                </div>
              </div>
              <div className={`mobile-student-picker-popover ${studentPickerOpen ? "open" : ""}`}>
                <label className="monthly-search monthly-search-mobile">
                  <span aria-hidden="true">⌕</span>
                  <input autoFocus={studentQuery !== ""} value={studentQuery.trim()} onChange={(e) => { setStudentQuery(e.target.value); setStudentPickerOpen(true); }} placeholder="Search 49 students" aria-label="Search students" />
                </label>
                <div className="mobile-student-list" aria-label="Students">
                  {mobileStudents.slice(0, 12).map((student) => (
                    <button key={student.roll_no} type="button" className={student.roll_no === selectedStudent ? "selected" : ""} onClick={() => { setSelectedStudent(student.roll_no); setStudentQuery(""); setStudentPickerOpen(false); }}>
                      <span><strong>{student.name}</strong><small>{student.roll_no}</small></span>
                      <b>{pctLabel(student.pct)}</b>
                    </button>
                  ))}
                  {mobileStudents.length === 0 && <div className="mobile-student-overflow">No matching student.</div>}
                </div>
              </div>

              <div className="mobile-month-strip">
                <button type="button" onClick={() => changeMonth(-1)} aria-label="Previous month">‹</button>
                <div><span>Attendance calendar</span><strong>{MONTHS[month - 1]} {year}</strong><small>{register.stats?.total_sessions ?? 0} sessions</small></div>
                <button type="button" onClick={() => changeMonth(1)} aria-label="Next month">›</button>
              </div>

              <div className="mobile-weekdays" aria-hidden="true">
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <span key={day}>{day}</span>)}
              </div>

              <div className="mobile-calendar" aria-label="Monthly attendance calendar">
                {register.days.length > 0 && Array.from({ length: Math.max(0, weekdayIndex(register.days[0].weekday)) }).map((_, index) => (
                  <span key={`blank-${index}`} className="mobile-calendar-blank" aria-hidden="true" />
                ))}
                {register.days.map((day) => {
                  const cell = selectedStudentRow?.cells.find((c) => c.day === day.day);
                  const status = cell?.status ?? null;
                  const future = isFutureDay(year, month, day.day);
                  return (
                    <button key={day.day} type="button" aria-label={`${day.weekday}, ${day.day} ${MONTHS[month - 1]}: ${future ? "Future date" : statusLabel(status)}`} className={`mobile-day-cell status-${status ?? "none"} ${day.holiday ? "holiday" : ""} ${day.session_count ? "session" : ""} ${future ? "future" : ""} ${mobileDay === day.day ? "selected" : ""}`} onClick={() => { setMobileDay(day.day); setSelectedDay(day.day); }}>
                      <span className="mobile-day-number">{day.day}</span>
                      <StatusMark status={status} />
                      <small className="mobile-day-state">{future ? "Future" : day.holiday ? "Holiday" : day.session_count ? (status ?? "—") : "No class"}</small>
                    </button>
                  );
                })}
              </div>
              <div className="mobile-calendar-legend" aria-label="Attendance legend">
                <span><b>✓</b> Present</span><span><b>A</b> Absent</span><span><b>H</b> Holiday</span><span><b>—</b> No class</span>
              </div>

              {selectedMobileDay && (
                <button type="button" className="mobile-day-summary" onClick={() => setMobileDay(selectedMobileDay.day)}>
                  <div>
                    <span>{selectedMobileDay.weekday} · {selectedMobileDay.day} {MONTHS[month - 1]}</span>
                    <strong>{formatDayMeta(selectedMobileDay)}</strong>
                    {selectedMobileDay.topic && <small>{selectedMobileDay.topic}</small>}
                  </div>
                  <div className="mobile-day-summary-status">
                    <StatusMark status={selectedMobileStatus} />
                    <span>Details</span>
                  </div>
                </button>
              )}
            </section>
          </>
        )}

        {(loadingSetup || loadingSubjects || loadingRegister) && (
          <div className="monthly-loading" aria-live="polite">
            <div className="monthly-spinner" />
            <div><strong>{loadingRegister ? "Refreshing the register" : "Preparing attendance"}</strong><span>Keeping the month context while the latest data loads.</span></div>
          </div>
        )}

        {!loadingRegister && register && register.roster.length === 0 && (
          <div className="monthly-empty"><strong>No students in this semester</strong><span>There is no active roster for the selected semester yet.</span></div>
        )}
      </div>

      {mobileDay != null && selectedMobileDay && (
        <div className="monthly-mobile-sheet-backdrop" onClick={() => setMobileDay(null)}>
          <section className="monthly-mobile-sheet" onClick={(e) => e.stopPropagation()} aria-label="Selected day details">
            <div className="monthly-sheet-handle" />
            <div className="monthly-day-head">
              <div><span>{selectedMobileDay.weekday}</span><h2>{selectedMobileDay.day} {MONTHS[month - 1]}</h2></div>
              <button type="button" className="monthly-close-desktop" onClick={() => setMobileDay(null)} aria-label="Close day details">×</button>
            </div>
            {selectedMobileDay.holiday ? (
              <div className="monthly-detail-empty"><div className="monthly-detail-mark holiday">H</div><strong>{selectedMobileDay.holiday_name || "Holiday"}</strong><span>No attendance session is expected for this date.</span></div>
            ) : selectedMobileDay.session_count ? (
              <>
                <div className="monthly-sheet-status"><StatusMark status={selectedMobileStatus} /><div><span>{selectedStudentRow?.name ?? "Selected student"}</span><strong>{statusLabel(selectedMobileStatus)}</strong></div></div>
                <div className="monthly-session-summary"><div><span>Session</span><strong>{selectedMobileDay.session_count > 1 ? `${selectedMobileDay.session_count} sessions` : selectedMobileDay.session_type === "LAB" ? "Lab" : "Regular class"}</strong></div><div><span>Duration</span><strong>{selectedMobileDay.duration_hours ?? 0}h</strong></div></div>
                <div className="monthly-topic"><span>Topic</span><strong>{selectedMobileDay.topic || "Topic not recorded"}</strong></div>
                {selectedMobileDay.session_ids.length === 1 && <button type="button" className="monthly-session-link" onClick={() => navigate(`/attendance/sessions/${selectedMobileDay.session_ids[0]}`)}>Open session <span>→</span></button>}
              </>
            ) : (
              <div className="monthly-detail-empty"><div className="monthly-detail-mark none">—</div><strong>No class</strong><span>No saved attendance session exists for this day.</span></div>
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}
