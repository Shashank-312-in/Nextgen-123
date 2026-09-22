import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getSetup,
  getSemesterAttendanceSummary,
  getStudentSubjectDates,
  type SemesterOption,
  type StudentSemesterSummary,
  type StudentSubjectDate,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import "../../styles/ng-flat-controls.css";
import "./attendance-insights.css";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

type Band = "green" | "yellow" | "red" | "muted";

function Chip({ pct, band }: { pct: number | null; band: Band }) {
  return <span className={`ai-chip ${band}`}>{pct == null ? "—" : `${Math.round(pct)}%`}</span>;
}

function fmtDate(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

// Subject list for one student, each subject expandable to its dated sessions.
// Dates load lazily per subject and are cached for the lifetime of the row.
function StudentDetail({ student, semesterId }: { student: StudentSemesterSummary; semesterId: number }) {
  const [openSubject, setOpenSubject] = useState<number | null>(null);
  const [cache, setCache] = useState<Record<number, StudentSubjectDate[] | "loading" | "error">>({});

  async function toggle(subjectId: number) {
    if (openSubject === subjectId) { setOpenSubject(null); return; }
    setOpenSubject(subjectId);
    if (cache[subjectId] && cache[subjectId] !== "error") return;
    setCache(c => ({ ...c, [subjectId]: "loading" }));
    try {
      const res = await getStudentSubjectDates({ rollNo: student.roll_no, subjectId, semesterId });
      setCache(c => ({ ...c, [subjectId]: res.dates }));
    } catch {
      setCache(c => ({ ...c, [subjectId]: "error" }));
    }
  }

  if (!student.subjects.length) return <div className="ai-detail"><div className="ai-state">No subjects for this semester.</div></div>;

  return (
    <div className="ai-detail">
      {student.subjects.map(s => {
        const open = openSubject === s.subject_id;
        const dates = cache[s.subject_id];
        return (
          <div key={s.subject_id}>
            <button type="button" className={`ai-subrow${s.total === 0 ? " is-empty" : ""}`} aria-expanded={open} onClick={() => void toggle(s.subject_id)}>
              <span className="ai-chev" aria-hidden="true">▸</span>
              <span>{s.subject_name}</span>
              <span className="num">{s.present}/{s.total}</span>
              <span className="num"><Chip pct={s.pct} band={s.band} /></span>
            </button>
            {open && (
              <div className="ai-dates">
                {dates === "loading" && <span className="ai-sub">Loading dates…</span>}
                {dates === "error" && <span className="ai-sub" style={{ color: "var(--ng-red)" }}>Could not load dates. Tap the subject to retry.</span>}
                {Array.isArray(dates) && dates.length === 0 && <span className="ai-sub">No sessions recorded.</span>}
                {Array.isArray(dates) && dates.map((d, i) => {
                  const absent = /^a/i.test(d.status);
                  return (
                    <span key={`${d.attendance_date}-${i}`} className={`ai-date ${absent ? "is-absent" : "is-present"}`}
                      title={`${d.session_type} · ${d.duration_hours}h · ${absent ? "Absent" : "Present"}`}>
                      {fmtDate(d.attendance_date)}{d.session_type === "LAB" ? " · Lab" : ""}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function AttendanceInsightsPage({ user, onLoggedOut }: Props) {
  const navigate = useNavigate();
  const [semesters, setSemesters] = useState<SemesterOption[]>([]);
  const [semesterId, setSemesterId] = useState<number | null>(null);
  const [students, setStudents] = useState<StudentSemesterSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [openRoll, setOpenRoll] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const setup = await getSetup();
        if (!alive) return;
        setSemesters(setup.semesters);
        setSemesterId(setup.default_semester_id ?? setup.semesters[0]?.id ?? null);
        if (!setup.semesters.length) setLoading(false);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof ApiClientError ? err.message : "Could not load attendance insights.");
        setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!semesterId) return;
    let alive = true;
    setLoading(true); setError(null); setOpenRoll(null);
    (async () => {
      try {
        const result = await getSemesterAttendanceSummary({ semesterId });
        if (alive) setStudents(result.students ?? []);
      } catch (err) {
        if (!alive) return;
        setStudents([]);
        setError(err instanceof ApiClientError ? err.message : "Could not load semester attendance.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [semesterId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? students.filter(s => `${s.roll_no} ${s.name}`.toLowerCase().includes(q)) : students;
  }, [query, students]);

  const stats = useMemo(() => {
    const eligible = students.filter(s => s.overall_pct != null);
    const avg = eligible.length ? Math.round(eligible.reduce((n, s) => n + (s.overall_pct ?? 0), 0) / eligible.length) : 0;
    const below = eligible.filter(s => (s.overall_pct ?? 0) < 75).length;
    return { total: students.length, avg, below, hasData: eligible.length > 0 };
  }, [students]);

  const toggleRow = (roll: string) => setOpenRoll(cur => (cur === roll ? null : roll));

  return (
    <AppShell user={user} activeNav="attendance" heading="Attendance Insights" onLoggedOut={onLoggedOut}>
      <div className="ai-wrap">
        <div className="ai-head">
          <div>
            <button type="button" className="ai-back" onClick={() => navigate("/attendance")}>← Back to Mark Attendance</button>
            <h2>Semester attendance</h2>
            <p className="ai-sub">Tap a student for subject-wise detail, then a subject for the dates.</p>
          </div>
          <div className="ai-ctx">
            <label htmlFor="ai-sem">Semester</label>
            <select id="ai-sem" className="ng-flat-select" value={semesterId ?? ""} onChange={e => setSemesterId(Number(e.target.value) || null)}>
              {semesters.map(s => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
            </select>
          </div>
        </div>

        <div className="ng-flat-metric-row ai-metrics">
          <div className="ng-flat-metric"><strong>{stats.total}</strong><span>Students</span></div>
          <div className="ng-flat-metric"><strong>{stats.hasData ? `${stats.avg}%` : "—"}</strong><span>Average attendance</span></div>
          <div className={`ng-flat-metric ${stats.below > 0 ? "is-warning" : ""}`}><strong>{stats.below}</strong><span>Below 75%</span></div>
        </div>

        <div className="ai-panel">
          <div className="ai-toolbar">
            <strong>Students</strong>
            <input className="ng-flat-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search name or roll no." aria-label="Search students" />
          </div>

          {error ? <div className="ai-state is-error">{error}</div>
            : loading ? <div className="ai-state">Loading attendance…</div>
            : filtered.length === 0 ? <div className="ai-state">{students.length ? "No students match your search." : "No students in this semester yet."}</div>
            : (
              <>
                <div className="ai-desktop" role="table" aria-label="Student attendance">
                  <div className="ai-headrow" role="row">
                    <span /><span>Roll No.</span><span>Student</span><span className="num">Present</span><span className="num">Classes</span><span className="num">Attendance</span>
                  </div>
                  {filtered.map(s => {
                    const open = openRoll === s.roll_no;
                    return (
                      <div key={s.roll_no} className="ai-item" role="row">
                        <button type="button" className="ai-row" aria-expanded={open} onClick={() => toggleRow(s.roll_no)}>
                          <span className="ai-chev" aria-hidden="true">▸</span>
                          <span className="ai-roll">{s.roll_no}</span>
                          <span className="ai-name">{s.name}</span>
                          <span className="num">{s.present_classes}</span>
                          <span className="num">{s.total_classes}</span>
                          <span className="num"><Chip pct={s.overall_pct} band={s.overall_band} /></span>
                        </button>
                        {open && semesterId && <StudentDetail student={s} semesterId={semesterId} />}
                      </div>
                    );
                  })}
                </div>

                <div className="ai-cards">
                  {filtered.map(s => {
                    const open = openRoll === s.roll_no;
                    return (
                      <div className="ai-card" key={s.roll_no}>
                        <button type="button" className="ai-card-top" aria-expanded={open} onClick={() => toggleRow(s.roll_no)}>
                          <span className="ai-chev" aria-hidden="true" style={{ transform: open ? "rotate(90deg)" : undefined }}>▸</span>
                          <span className="ai-card-main"><span className="ai-name">{s.name}</span><span className="ai-roll">{s.roll_no} · {s.present_classes}/{s.total_classes}</span></span>
                          <Chip pct={s.overall_pct} band={s.overall_band} />
                        </button>
                        {open && semesterId && <StudentDetail student={s} semesterId={semesterId} />}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
        </div>
      </div>
    </AppShell>
  );
}
