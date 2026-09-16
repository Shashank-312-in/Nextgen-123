import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { getStudentTrackRecord, type StudentTrackRecord } from "../../api/students";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

type Tab = "attendance" | "marksheet";

export function StudentTrackRecordPage({ user, onLoggedOut }: Props) {
  const { studentId } = useParams<{ studentId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StudentTrackRecord | null>(null);
  const [selectedSemesterId, setSelectedSemesterId] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("attendance");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = Number(studentId);
    if (!Number.isFinite(id)) return;
    void getStudentTrackRecord(id).then((res) => {
      setData(res);
      setSelectedSemesterId(res.current_semester_id ?? res.semesters[res.semesters.length - 1]?.id ?? null);
    }).catch((err) => setError(err instanceof ApiClientError ? err.message : "Failed to load student track record"))
      .finally(() => setLoading(false));
  }, [studentId]);

  const resultByCode = useMemo(() => new Map((data?.results ?? []).map((r) => [r.batch.semester_code, r])), [data]);
  const selectedSemester = data?.semesters.find((s) => s.id === selectedSemesterId) ?? null;
  const selectedAttendance = selectedSemesterId ? data?.attendance_by_semester[String(selectedSemesterId)] : undefined;
  const selectedResult = selectedSemester ? resultByCode.get(selectedSemester.code) : undefined;
  const attendedSemesters = Object.keys(data?.attendance_by_semester ?? {}).length;
  const completedResults = data?.results.length ?? 0;
  const totalCredits = (data?.results ?? []).reduce((sum, result) => sum + Number(result.total_credits || 0), 0);

  if (loading) return <AppShell user={user} activeNav="students" heading="Student Track Record" onLoggedOut={onLoggedOut}><div className="track-empty">Loading academic history…</div></AppShell>;
  if (!data) return <AppShell user={user} activeNav="students" heading="Student Track Record" onLoggedOut={onLoggedOut}><ErrorPopup message={error || "Student not found"} onClose={() => setError(null)} /></AppShell>;

  const r = data.student;
  const photo = formatPhotoUrl(r.photo_path);

  return (
    <AppShell user={user} activeNav="students" heading="Student Track Record" whoami={`${r.name} · ${r.roll_no}`} onLoggedOut={onLoggedOut}>
      <div className="track-page">
        <ErrorPopup message={error} onClose={() => setError(null)} />
        <button className="btn btn-outline btn-sm" type="button" onClick={() => navigate(`/students/${r.id}`)} style={{ marginBottom: 12 }}>← Student profile</button>

        <section className="track-hero">
          <div className="track-avatar">{photo ? <img src={photo} alt={r.name} style={{ width:"100%", height:"100%", objectFit:"cover", borderRadius:"inherit" }} /> : r.name.slice(0,1).toUpperCase()}</div>
          <div className="track-identity">
            <span className="ng-section-kicker">Academic record</span>
            <h2>{r.name}</h2>
            <p>{r.roll_no} · {r.department} · {data.semesters.find(s => s.id === r.current_semester_id)?.name || "Semester not set"}</p>
          </div>
          <div className="track-kpis">
            <div className="track-kpi"><span>Overall attendance</span><strong>{(() => { const t = Object.values(data.attendance_by_semester).reduce((a,b)=>a+b.total_classes,0); const p=Object.values(data.attendance_by_semester).reduce((a,b)=>a+b.present_classes,0); return t ? `${Math.round(p/t*100)}%` : "—"; })()}</strong></div>
            <div className="track-kpi"><span>Semesters attended</span><strong>{attendedSemesters || "—"}</strong></div>
            <div className="track-kpi"><span>Results recorded</span><strong>{completedResults || "—"}</strong></div>
            <div className="track-kpi"><span>Total credits</span><strong>{totalCredits ? totalCredits.toFixed(1).replace(/\.0$/,"") : "—"}</strong></div>
          </div>
        </section>

        <section className="track-section">
          <div className="track-section-head"><div><h3>Semester history</h3><p>Attendance and official result records available in NextGen.</p></div></div>
          <div className="semester-grid">
            {data.semesters.map((semester) => {
              const att = data.attendance_by_semester[String(semester.id)];
              const result = resultByCode.get(semester.code);
              return (
                <button type="button" key={semester.id} className="semester-card" onClick={() => { setSelectedSemesterId(semester.id); setTab("attendance"); }}>
                  <div className="semester-card-top"><span className="semester-code">{semester.code}</span><span aria-hidden="true">→</span></div>
                  <h4>{semester.name}</h4>
                  <div className="semester-metrics">
                    <div className="semester-metric"><span>Attendance</span><strong>{att?.pct != null ? `${att.pct}%` : "—"}</strong></div>
                    <div className="semester-metric"><span>SGPA</span><strong>{result?.sgpa ?? "—"}</strong></div>
                    <div className="semester-metric"><span>Record</span><strong>{result ? "Marksheet" : att ? "Attendance" : "No data"}</strong></div>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        {selectedSemester && (
          <section className="track-detail">
            <div className="track-detail-head">
              <div><div className="semester-code">{selectedSemester.code}</div><strong>{selectedSemester.name}</strong></div>
              <div className="track-tabs">
                <button className={`track-tab${tab === "attendance" ? " active" : ""}`} onClick={() => setTab("attendance")} type="button">Attendance</button>
                <button className={`track-tab${tab === "marksheet" ? " active" : ""}`} onClick={() => setTab("marksheet")} type="button">Marksheet</button>
              </div>
            </div>
            <div className="track-detail-body">
              {tab === "attendance" ? (
                selectedAttendance ? (
                  <>
                    <div className="track-att-grid">
                      <div className="track-mini"><span>Overall</span><strong>{selectedAttendance.pct != null ? `${selectedAttendance.pct}%` : "—"}</strong></div>
                      <div className="track-mini"><span>Classes attended</span><strong>{selectedAttendance.present_classes}</strong></div>
                      <div className="track-mini"><span>Classes conducted</span><strong>{selectedAttendance.total_classes}</strong></div>
                    </div>
                    <div className="track-empty" style={{ marginTop:10 }}>{selectedAttendance.absent_classes > 0 ? `${selectedAttendance.absent_classes} absence${selectedAttendance.absent_classes === 1 ? "" : "s"} recorded this semester.` : "No absences recorded in the available attendance data."}</div>
                  </>
                ) : <div className="track-empty">No attendance record is available for this semester.</div>
              ) : selectedResult ? (
                <div className="table-wrap">
                  <table className="data-table"><thead><tr><th>Subject</th><th className="center">Marks</th><th className="center">Grade</th><th className="center">Credits</th></tr></thead><tbody>
                    {selectedResult.subjects.map((subject, i) => <tr key={`${subject.subject_code}-${i}`}><td><strong>{subject.subject_name}</strong><div className="subtitle-muted">{subject.subject_code}</div></td><td className="center">{subject.marks}{subject.max_marks ? ` / ${subject.max_marks}` : ""}</td><td className="center">{subject.grade || "—"}</td><td className="center">{subject.credits ?? "—"}</td></tr>)}
                  </tbody></table>
                  <div className="track-empty" style={{ marginTop:10, textAlign:"left" }}>SGPA <strong>{selectedResult.sgpa ?? "—"}</strong> · Total credits <strong>{selectedResult.total_credits}</strong> · {selectedResult.result_status || "Result status unavailable"}</div>
                </div>
              ) : <div className="track-empty"><strong>Marksheet not available</strong><br />No official result upload has been recorded for this semester.</div>}
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
