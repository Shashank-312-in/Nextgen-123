import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { getStudentSemesterTrackRecord, type StudentSemesterTrackRecord } from "../../api/students";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

function bandChip(band: "green" | "yellow" | "red" | "muted") {
  const cls = band === "green" ? "chip-green" : band === "yellow" ? "chip-warn" : band === "red" ? "chip-red" : "chip-muted";
  const label = band === "green" ? "Normal" : band === "yellow" ? "Shortage" : band === "red" ? "Critical" : "No data";
  return <span className={`chip ${cls}`}>{label}</span>;
}

export function StudentSemesterTrackRecordPage({ user, onLoggedOut }: Props) {
  const { studentId, semesterId } = useParams<{ studentId: string; semesterId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StudentSemesterTrackRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sId = Number(studentId);
    const semId = Number(semesterId);
    if (!Number.isFinite(sId) || !Number.isFinite(semId)) return;
    setLoading(true);
    void getStudentSemesterTrackRecord(sId, semId).then(setData)
      .catch((err) => setError(err instanceof ApiClientError ? err.message : "Failed to load semester record"))
      .finally(() => setLoading(false));
  }, [studentId, semesterId]);

  if (loading) {
    return (
      <AppShell user={user} activeNav="students" heading="Semester Record" onLoggedOut={onLoggedOut}>
        <div className="track-empty">Loading semester record…</div>
      </AppShell>
    );
  }
  if (!data) {
    return (
      <AppShell user={user} activeNav="students" heading="Semester Record" onLoggedOut={onLoggedOut}>
        <ErrorPopup message={error || "Semester record not found"} onClose={() => setError(null)} />
      </AppShell>
    );
  }

  const { student: r, semester, attendance, result } = data;
  const photo = formatPhotoUrl(r.photo_path);
  const hasAttendance = attendance.subjects.length > 0;
  const hasResult = Boolean(result);

  return (
    <AppShell
      user={user}
      activeNav="students"
      heading="Semester Record"
      whoami={`${r.name} · ${r.roll_no}`}
      onLoggedOut={onLoggedOut}
    >
      <div className="track-page">
        <ErrorPopup message={error} onClose={() => setError(null)} />
        <button
          className="btn btn-outline btn-sm"
          type="button"
          onClick={() => navigate(`/students/${r.id}/track-record`)}
          style={{ marginBottom: 12 }}
        >
          ← Semester history
        </button>

        <section className="sem-detail-hero">
          <div className="track-avatar sem-detail-avatar">
            {photo ? <img src={photo} alt={r.name} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "inherit" }} /> : r.name.slice(0, 1).toUpperCase()}
          </div>
          <div className="track-identity">
            <span className="ng-section-kicker">{semester.code} · {semester.name}</span>
            <h2>{r.name}</h2>
            <p>{r.roll_no} · {r.department}</p>
          </div>
          <div className="sem-detail-kpis">
            <div className="track-kpi">
              <span>Attendance</span>
              <strong>{attendance.overall_pct != null ? `${attendance.overall_pct}%` : "—"}</strong>
            </div>
            <div className="track-kpi">
              <span>SGPA</span>
              <strong>{result?.sgpa ?? "—"}</strong>
            </div>
            <div className="track-kpi">
              <span>Result</span>
              {result?.result_status ? (
                <span className={`chip ${result.result_status.toUpperCase() === "FAIL" ? "chip-red" : "chip-green"}`} style={{ marginTop: 5 }}>
                  {result.result_status}
                </span>
              ) : <strong>—</strong>}
            </div>
          </div>
        </section>

        <section className="track-detail sem-block">
          <div className="track-detail-head">
            <div><strong>Subject-wise attendance</strong></div>
            {hasAttendance && (
              <div className="sem-block-summary">
                {attendance.total_present} / {attendance.total_classes} classes attended
              </div>
            )}
          </div>
          <div className="track-detail-body" style={{ padding: hasAttendance ? 0 : undefined }}>
            {hasAttendance ? (
              <>
                <div className="table-wrap sem-table-desktop">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Subject</th>
                        <th className="center">Present</th>
                        <th className="center">Total</th>
                        <th style={{ width: 160 }}>Progress</th>
                        <th className="center">%</th>
                        <th className="center">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {attendance.subjects.map((sub) => {
                        const pctVal = sub.pct ?? 0;
                        const barColor = sub.band === "green" ? "var(--ng-green)" : sub.band === "yellow" ? "var(--ng-amber)" : "var(--ng-red)";
                        return (
                          <tr key={sub.subject_id}>
                            <td>
                              <strong>{sub.subject_name}</strong>
                              <div className="subtitle-muted">{sub.subject_code}</div>
                            </td>
                            <td className="center">{sub.present_sessions}</td>
                            <td className="center">{sub.total_sessions}</td>
                            <td>
                              <div className="sem-progress-track">
                                <div className="sem-progress-fill" style={{ width: `${Math.min(pctVal, 100)}%`, background: barColor }} />
                              </div>
                            </td>
                            <td className="center"><strong>{sub.pct != null ? `${sub.pct}%` : "—"}</strong></td>
                            <td className="center">{bandChip(sub.band)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="sem-cards-mobile">
                  {attendance.subjects.map((sub) => {
                    const pctVal = sub.pct ?? 0;
                    const barColor = sub.band === "green" ? "var(--ng-green)" : sub.band === "yellow" ? "var(--ng-amber)" : "var(--ng-red)";
                    return (
                      <article className="sem-subject-card" key={sub.subject_id}>
                        <div className="sem-subject-card-top">
                          <div>
                            <div className="sem-subject-card-name">{sub.subject_name}</div>
                            <div className="sem-subject-card-code">{sub.subject_code}</div>
                          </div>
                          {bandChip(sub.band)}
                        </div>
                        <div className="sem-progress-track" style={{ marginTop: 10 }}>
                          <div className="sem-progress-fill" style={{ width: `${Math.min(pctVal, 100)}%`, background: barColor }} />
                        </div>
                        <div className="sem-subject-card-stats">
                          <span>{sub.present_sessions} / {sub.total_sessions} present</span>
                          <strong>{sub.pct != null ? `${sub.pct}%` : "—"}</strong>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="track-empty">No attendance sessions have been recorded for this semester yet.</div>
            )}
          </div>
        </section>

        <section className="track-detail sem-block">
          <div className="track-detail-head">
            <div><strong>Marksheet</strong></div>
            {hasResult && <div className="sem-block-summary">Total credits {result!.total_credits}</div>}
          </div>
          <div className="track-detail-body" style={{ padding: hasResult ? 0 : undefined }}>
            {hasResult ? (
              <>
                <div className="table-wrap sem-table-desktop">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Subject</th>
                        <th className="center">Internal</th>
                        <th className="center">External</th>
                        <th className="center">Total</th>
                        <th className="center">Grade</th>
                        <th className="center">GP</th>
                        <th className="center">Credits</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result!.subjects.map((subject, i) => (
                        <tr key={`${subject.subject_code}-${i}`}>
                          <td>
                            <strong>{subject.subject_name}</strong>
                            <div className="subtitle-muted">{subject.subject_code}</div>
                          </td>
                          <td className="center">{subject.internal_marks ?? "—"}</td>
                          <td className="center">{subject.external_marks ?? "—"}</td>
                          <td className="center"><strong>{subject.marks}{subject.max_marks ? ` / ${subject.max_marks}` : ""}</strong></td>
                          <td className="center">{subject.grade || "—"}</td>
                          <td className="center">{subject.grade_point || "—"}</td>
                          <td className="center">{subject.credits ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="sem-cards-mobile">
                  {result!.subjects.map((subject, i) => (
                    <article className="sem-subject-card" key={`${subject.subject_code}-${i}`}>
                      <div className="sem-subject-card-top">
                        <div>
                          <div className="sem-subject-card-name">{subject.subject_name}</div>
                          <div className="sem-subject-card-code">{subject.subject_code}</div>
                        </div>
                        <span className="chip chip-muted">{subject.grade || "—"}</span>
                      </div>
                      <div className="sem-mark-grid">
                        <div><span>Internal</span><strong>{subject.internal_marks ?? "—"}</strong></div>
                        <div><span>External</span><strong>{subject.external_marks ?? "—"}</strong></div>
                        <div><span>Total</span><strong>{subject.marks}{subject.max_marks ? `/${subject.max_marks}` : ""}</strong></div>
                        <div><span>GP</span><strong>{subject.grade_point || "—"}</strong></div>
                        <div><span>Credits</span><strong>{subject.credits ?? "—"}</strong></div>
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="track-empty">No official result upload has been recorded for this semester.</div>
            )}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
