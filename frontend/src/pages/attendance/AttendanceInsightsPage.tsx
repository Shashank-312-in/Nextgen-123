import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getSetup,
  getSemesterAttendanceSummary,
  type SemesterOption,
  type StudentSemesterSummary,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";

interface AttendanceInsightsPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function AttendanceInsightsPage({ user, onLoggedOut }: AttendanceInsightsPageProps) {
  const navigate = useNavigate();
  const [semesters, setSemesters] = useState<SemesterOption[]>([]);
  const [semesterId, setSemesterId] = useState<number | null>(null);
  const [students, setStudents] = useState<StudentSemesterSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const setup = await getSetup();
        if (!alive) return;
        setSemesters(setup.semesters);
        const initial = setup.default_semester_id ?? setup.semesters[0]?.id ?? null;
        setSemesterId(initial);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof ApiClientError ? err.message : "Could not load attendance insights.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!semesterId) return;
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await getSemesterAttendanceSummary({ semesterId });
        if (!alive) return;
        setStudents(result.students ?? []);
      } catch (err) {
        if (!alive) return;
        setStudents([]);
        setError(err instanceof ApiClientError ? err.message : "Could not load semester attendance.");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [semesterId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return students;
    return students.filter((student) =>
      `${student.roll_no} ${student.name}`.toLowerCase().includes(q),
    );
  }, [query, students]);

  const stats = useMemo(() => {
    if (!students.length) return { avg: 0, shortage: 0, total: 0 };
    const eligible = students.filter((student) => student.overall_pct != null);
    const avg = eligible.length
      ? Math.round(eligible.reduce((sum, student) => sum + (student.overall_pct ?? 0), 0) / eligible.length)
      : 0;
    const shortage = students.filter((student) => (student.overall_pct ?? 0) < 75).length;
    return { avg, shortage, total: students.length };
  }, [students]);

  return (
    <AppShell user={user} activeNav="attendance" heading="Attendance Insights" onLoggedOut={onLoggedOut}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "8px 0 28px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, marginBottom: 20 }}>
          <div>
            <button
              type="button"
              onClick={() => navigate("/attendance")}
              style={{ border: 0, background: "transparent", padding: 0, color: "#2563eb", fontWeight: 750, cursor: "pointer", marginBottom: 8 }}
            >
              ← Back to Mark Attendance
            </button>
            <h1 style={{ margin: 0, color: "#172033", fontSize: 28, letterSpacing: "-0.03em" }}>Attendance Insights</h1>
            <p style={{ margin: "6px 0 0", color: "#738095", fontSize: 14 }}>
              A quiet overview of semester attendance. Daily marking stays on the main screen.
            </p>
          </div>

          <select
            value={semesterId ?? ""}
            onChange={(e) => setSemesterId(Number(e.target.value) || null)}
            style={{ minWidth: 210, border: "1px solid #d9e0e8", borderRadius: 12, padding: "11px 13px", background: "#fff", color: "#263246", fontWeight: 700, outline: "none" }}
          >
            {semesters.map((semester) => (
              <option key={semester.id} value={semester.id}>
                {semester.code} — {semester.name}
              </option>
            ))}
          </select>
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 12, background: "#fff6f6", border: "1px solid #f5cccc", color: "#a52828", fontSize: 13 }}>
            {error}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 16 }}>
          {[
            ["Students", stats.total],
            ["Average attendance", `${stats.avg}%`],
            ["Below 75%", stats.shortage],
          ].map(([label, value]) => (
            <div key={String(label)} style={{ background: "#fff", border: "1px solid #e8edf2", borderRadius: 16, padding: "18px 18px 16px" }}>
              <div style={{ color: "#7b8798", fontSize: 12, fontWeight: 750, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
              <div style={{ marginTop: 6, color: "#182235", fontSize: 26, fontWeight: 850 }}>{value}</div>
            </div>
          ))}
        </div>

        <div style={{ background: "#fff", border: "1px solid #e8edf2", borderRadius: 18, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: 16, borderBottom: "1px solid #edf1f5" }}>
            <div>
              <div style={{ color: "#1e293b", fontSize: 15, fontWeight: 850 }}>Student attendance</div>
              <div style={{ color: "#8390a0", fontSize: 12, marginTop: 3 }}>Subject-wise detail is available inside each student row.</div>
            </div>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search student or roll no."
              style={{ width: 240, border: "1px solid #dce3eb", borderRadius: 10, padding: "10px 12px", outline: "none", fontSize: 13 }}
            />
          </div>

          {loading ? (
            <div style={{ padding: 42, textAlign: "center", color: "#7b8798", fontSize: 13 }}>Loading attendance…</div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 42, textAlign: "center", color: "#7b8798", fontSize: 13 }}>No students found.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {['#', 'Roll No.', 'Student', 'Classes', 'Present', 'Attendance'].map((label) => (
                      <th key={label} style={{ padding: "12px 14px", textAlign: label === "Student" ? "left" : "center", color: "#7c8797", background: "#fafbfc", borderBottom: "1px solid #edf1f5", fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((student, index) => {
                    const pct = student.overall_pct;
                    const low = pct != null && pct < 75;
                    return (
                      <tr key={student.roll_no}>
                        <td style={{ padding: "13px 14px", textAlign: "center", borderBottom: "1px solid #f0f3f6", color: "#8a95a4", fontSize: 12 }}>{index + 1}</td>
                        <td style={{ padding: "13px 14px", textAlign: "center", borderBottom: "1px solid #f0f3f6", color: "#475569", fontSize: 12, fontWeight: 700 }}>{student.roll_no}</td>
                        <td style={{ padding: "13px 14px", borderBottom: "1px solid #f0f3f6", color: "#1f2937", fontSize: 13, fontWeight: 750 }}>{student.name}</td>
                        <td style={{ padding: "13px 14px", textAlign: "center", borderBottom: "1px solid #f0f3f6", color: "#566274", fontSize: 12 }}>{student.total_classes}</td>
                        <td style={{ padding: "13px 14px", textAlign: "center", borderBottom: "1px solid #f0f3f6", color: "#566274", fontSize: 12 }}>{student.present_classes}</td>
                        <td style={{ padding: "13px 14px", textAlign: "center", borderBottom: "1px solid #f0f3f6" }}>
                          <span style={{ display: "inline-flex", minWidth: 58, justifyContent: "center", padding: "5px 8px", borderRadius: 999, background: low ? "#fff1f1" : "#eefaf3", color: low ? "#bf2f39" : "#14834b", fontSize: 12, fontWeight: 850 }}>
                            {pct == null ? "—" : `${Math.round(pct)}%`}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
