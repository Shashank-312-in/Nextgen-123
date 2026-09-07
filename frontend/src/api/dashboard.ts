// Matches api/routes_dashboard.py exactly — one function per route.
// Keep this file in lockstep with that module; if a response shape changes
// there, update the types here in the same change (same rule as auth.ts).
import { apiFetch } from "./client";

// ──────────────────────────────────────────────
// Shared types
// ──────────────────────────────────────────────

export type AttendanceBand = "green" | "yellow" | "red" | "muted";

export interface SessionRow {
  id: number;
  attendance_date: string;
  session_type: "CLASS" | "LAB";
  duration_hours: number;
  created_at: string;
  topic?: string;
  subject_name: string;
  subject_code: string;
  faculty_name: string | null;
  faculty_username: string;
  semester_code: string | null;
  semester_name: string | null;
  absent_count: number;
  present_count: number;
  total_marked: number;
}

export interface SubjectAttendance {
  subject_id: number;
  code: string;
  name: string;
  pct: number | null;
  band: AttendanceBand;
  total: number;
  present: number;
}

export interface StudentInfo {
  roll_no: string;
  name: string;
  department: string;
}

export interface StudentRosterEntry {
  roll_no: string;
  name: string;
}

export interface SessionInfo {
  id: number;
  subject_name: string;
  attendance_date: string;
  session_type: "CLASS" | "LAB";
}

export interface SubjectSessionHistoryEntry {
  attendance_date: string;
  session_type: "CLASS" | "LAB";
  duration_hours: number;
  status: "Present" | "Absent" | "Late" | "Excused";
}

// ──────────────────────────────────────────────
// Response union types
// ──────────────────────────────────────────────

export type HodDashboardData = {
  role: "HOD";
  days: Record<string, SessionRow[]>; // key = "YYYY-MM-DD"
  picked_date: string | null;
  picked_semester_id?: number | null;
  picked_year?: string | null;
};

export type FacultyDashboardData = {
  role: "FACULTY";
  redirect: string;
};

export type StudentDashboardData = {
  role: "STUDENT";
  student: StudentInfo;
  subjects: SubjectAttendance[];
};

export type DashboardData = HodDashboardData | FacultyDashboardData | StudentDashboardData;

export interface SessionRosterData {
  session: SessionInfo;
  students: StudentRosterEntry[];
  kind: "present" | "absent";
}

export interface SubjectHistoryData {
  subject_id: number;
  sessions: SubjectSessionHistoryEntry[];
}

// ──────────────────────────────────────────────
// API call functions
// ──────────────────────────────────────────────

export async function getDashboard(date?: string, semesterId?: number, year?: string): Promise<DashboardData> {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (semesterId) params.set("semester_id", String(semesterId));
  if (year) params.set("year", year);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<DashboardData>(`/api/dashboard${qs}`);
}

export async function getSessionPresent(sessionId: number): Promise<SessionRosterData> {
  return apiFetch<SessionRosterData>(`/api/dashboard/session/${sessionId}/present`);
}

export async function getSessionAbsent(sessionId: number): Promise<SessionRosterData> {
  return apiFetch<SessionRosterData>(`/api/dashboard/session/${sessionId}/absent`);
}

export async function getSubjectHistory(subjectId: number): Promise<SubjectHistoryData> {
  return apiFetch<SubjectHistoryData>(`/api/dashboard/student/subject/${subjectId}/history`);
}

export interface StudentSelfEditSetting {
  student_self_edit_enabled: boolean;
  ok?: boolean;
}

export async function getStudentSelfEditSetting(): Promise<StudentSelfEditSetting> {
  return apiFetch<StudentSelfEditSetting>("/api/dashboard/settings/student-self-edit", { method: "GET" });
}

export async function updateStudentSelfEditSetting(enabled: boolean): Promise<StudentSelfEditSetting> {
  return apiFetch<StudentSelfEditSetting>("/api/dashboard/settings/student-self-edit", {
    method: "PATCH",
    body: { student_self_edit_enabled: enabled },
  });
}
