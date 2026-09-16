// Group 4 — Students. Matches api/routes_students.py exactly — one function
// per route, same rule as auth.ts/dashboard.ts. Field lists mirror
// webapp/routes/students.py's FIELD_SPECS/EDUCATION_SPECS (label, key)
// tuples 1:1 so the form page can render generically from the same order
// HOD sees in the OG app, without hardcoding 19 separate <input> blocks.
import { apiFetch, apiUpload, getAuthUrl } from "./client";

// ──────────────────────────────────────────────
// Field specs — label/key pairs, same order as OG's students.py
// ──────────────────────────────────────────────

export const FIELD_SPECS: Array<[label: string, key: string]> = [
  ["Roll Number", "roll_no"], ["Full Name", "name"], ["Father Name", "father_name"],
  ["Email", "email"], ["Student Phone Number", "phone"], ["Parent Phone Number", "parent_phone"],
  ["Date of Birth (YYYY-MM-DD)", "dob"],
  ["Category", "category"], ["Gender", "gender"], ["Seat Category", "seat_category"],
  ["APAAR ID", "apaar_id"], ["Aadhaar Number", "aadhaar_number"],
  ["Certificates Submitted", "certificates_submitted"], ["Certificates Due", "certificates_due"],
  ["Consultant Name", "consultant_name"], ["Address", "address"],
];

export const EDUCATION_SPECS: Array<[label: string, key: string]> = [
  ["10th School Name", "tenth_school"], ["10th Year of Passing", "tenth_year"], ["10th Marks (%)", "tenth_marks"],
  ["12th / Junior College Name", "twelfth_school"], ["12th Year of Passing", "twelfth_year"], ["12th Marks (%)", "twelfth_marks"],
  ["Diploma College Name (if applicable)", "diploma_college"], ["Diploma Year of Passing", "diploma_year"], ["Diploma Marks (%)", "diploma_marks"],
];

// WHY: reuses FIELD_SPECS/EDUCATION_SPECS (single source of truth for
// label<->key already established above) so the bulk-import mapping report
// shows the same friendly labels as the manual add/edit student form,
// instead of a second hardcoded label list drifting out of sync with it.
const IMPORT_FIELD_LABELS: Record<string, string> = Object.fromEntries(
  [...FIELD_SPECS, ...EDUCATION_SPECS].map(([label, key]) => [key, label])
);
IMPORT_FIELD_LABELS.match_roll_no = "Previous Roll Number";

export function importFieldLabel(fieldKey: string): string {
  return IMPORT_FIELD_LABELS[fieldKey] ?? fieldKey;
}

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

export interface StudentListRow {
  id: number;
  roll_no: string;
  name: string;
  email: string | null;
  phone: string | null;
  parent_phone?: string | null;
  gender?: string | null;
  category?: string | null;
  seat_category?: string | null;
  current_semester_id?: number | null;
  aadhaar_masked: string; // backend applies mask_aadhaar() — never send full number in list responses
  year_of_study?: string;
  batch?: string;
  active: boolean;
  photo_path?: string | null;
}

export interface SemesterOption {
  id: number;
  code: string;
  name: string;
}

// Full student record — every FIELD_SPECS/EDUCATION_SPECS key, plus
// non-form fields. aadhaar_number/apaar_id arrive decrypted (HOD-only
// view/edit routes, matches OG's _decrypt_student_row).
export interface StudentRecord {
  id: number;
  roll_no: string;
  name: string;
  department: string;
  email: string | null;
  phone: string | null;
  parent_phone: string | null;
  dob: string | null;
  address: string | null;
  father_name: string | null;
  category: string | null;
  gender: string | null;
  seat_category: string | null;
  apaar_id: string | null;
  aadhaar_number: string | null;
  certificates_submitted: string | null;
  certificates_due: string | null;
  consultant_name: string | null;
  tenth_school: string | null;
  tenth_year: string | null;
  tenth_marks: string | null;
  twelfth_school: string | null;
  twelfth_year: string | null;
  twelfth_marks: string | null;
  diploma_college: string | null;
  diploma_year: string | null;
  diploma_marks: string | null;
  current_semester_id: number | null;
  active: boolean;
  photo_path: string | null;
}

export interface StudentSubjectAttendance {
  subject_id: number;
  subject_code: string;
  subject_name: string;
  present_sessions: number;
  total_sessions: number;
  absent_sessions: number;
  pct: number | null;
  band: "green" | "yellow" | "red" | "muted";
}

export interface StudentAttendanceSummary {
  subjects: StudentSubjectAttendance[];
  total_classes: number;
  total_present: number;
  total_absent: number;
  overall_pct: number | null;
  overall_band: "green" | "yellow" | "red" | "muted";
}

export interface StudentDetail {
  student: StudentRecord;
  semester: { code: string; name: string } | null;
  attendance?: StudentAttendanceSummary;
}

export interface StudentFormData {
  student: StudentRecord | null; // null for the "new" form
  semesters: SemesterOption[];
}

export interface CreatedCredentials {
  username: string;
  password: string;
}

export interface SaveStudentResult {
  id: number;
  created_credentials: CreatedCredentials | null; // set only on create, mirrors ensure_student_login()
}

// ──────────────────────────────────────────────
// Routes
// ──────────────────────────────────────────────

export async function listStudentSemesters(): Promise<SemesterOption[]> {
  return apiFetch<SemesterOption[]>("/api/students/semesters", { method: "GET" });
}

export async function listStudents(q: string, status: "Active" | "Inactive" | "All", semesterId?: number | null): Promise<StudentListRow[]> {
  const params = new URLSearchParams({ q, status });
  if (semesterId) {
    params.set("semester_id", String(semesterId));
  }
  return apiFetch<StudentListRow[]>(`/api/students?${params.toString()}`, { method: "GET" });
}

export async function getStudent(id: number): Promise<StudentDetail> {
  return apiFetch<StudentDetail>(`/api/students/${id}`, { method: "GET" });
}

export async function getNewStudentForm(): Promise<StudentFormData> {
  return apiFetch<StudentFormData>("/api/students/new", { method: "GET" });
}

export async function getEditStudentForm(id: number): Promise<StudentFormData> {
  return apiFetch<StudentFormData>(`/api/students/${id}/edit`, { method: "GET" });
}

// `data` keys are every FIELD_SPECS + EDUCATION_SPECS key (string values,
// possibly empty) plus current_semester_id. Matches _save_student's form
// parsing exactly, just JSON instead of multipart form fields.
export async function createStudent(data: Record<string, string>, currentSemesterId: number | null): Promise<SaveStudentResult> {
  return apiFetch<SaveStudentResult>("/api/students", {
    method: "POST",
    body: { ...data, current_semester_id: currentSemesterId },
  });
}

export async function updateStudent(id: number, data: Record<string, string>, currentSemesterId: number | null): Promise<SaveStudentResult> {
  return apiFetch<SaveStudentResult>(`/api/students/${id}`, {
    method: "PATCH",
    body: { ...data, current_semester_id: currentSemesterId },
  });
}

export async function toggleStudentStatus(id: number): Promise<{ active: boolean }> {
  return apiFetch<{ active: boolean }>(`/api/students/${id}/toggle-status`, { method: "POST" });
}

// Photo upload stays multipart (binary), not JSON — see client.ts's
// apiUpload, which omits Content-Type so the browser sets its own
// multipart boundary.
export async function uploadStudentPhoto(id: number, file: File): Promise<{ photo_path: string }> {
  return apiUpload<{ photo_path: string }>(`/api/students/${id}/photo`, file, "photo");
}

export async function deleteStudentPhoto(id: number): Promise<{ photo_path: null }> {
  return apiFetch<{ photo_path: null }>(`/api/students/${id}/photo/delete`, { method: "POST" });
}

export async function deleteStudent(id: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch<{ deleted: boolean; id: number }>(`/api/students/${id}`, { method: "DELETE" });
}

// ──────────────────────────────────────────────
// Guided Bulk Import (Excel) — matches api/routes_students.py student_bulk_import/options
// ──────────────────────────────────────────────

export interface BulkImportCreatedRow {
  row: number;
  roll_no: string;
  name: string;
  username: string;
  password: string;
}

export interface BulkImportUpdatedRow {
  row: number;
  roll_no: string;
  name: string;
}

export interface BulkImportSkippedRow {
  row: number;
  roll_no: string;
  reason: string;
}

export interface BulkImportFailedRow {
  row: number;
  roll_no: string;
  reason: string;
}

export interface BulkImportOption { value: string | number; label: string; }

// WHY: mirrors excel_import.MatchReport.as_dict() (excel_import.py) — every
// header from the sheet lands in exactly one of these two buckets so the UI
// can show precisely what was recognized vs. ignored. Never omit rendering
// this: an empty `ignored` array is a real, useful signal ("nothing was
// skipped"), not a reason to hide the whole mapping section.
export interface BulkImportMappedColumn { header: string; field: string; matched_via: "exact" | "fuzzy"; }

export interface BulkImportColumnMapping {
  mapped: BulkImportMappedColumn[];
  ignored: string[];
}

export interface BulkImportOptions {
  branches: BulkImportOption[];
  years: BulkImportOption[];
  semesters: Array<SemesterOption & { active: boolean }>;
}

export interface BulkImportResult {
  total_rows: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
  created: BulkImportCreatedRow[];
  updated: BulkImportUpdatedRow[];
  skipped: BulkImportSkippedRow[];
  failed: BulkImportFailedRow[];
  // WHY: the backend echoes back the resolved import scope (routes_students.py
  // student_bulk_import's final `return ok({...})`) so the summary banner
  // above the results table can confirm what was actually imported.
  branch: string;
  year: number;
  semester: number | null;
  semester_id: number;
  mode: "merge" | "create_only";
  column_mapping: BulkImportColumnMapping;
}

// Multipart upload stays inside apiUpload(). Scope/mode are sent as query
// parameters so the shared upload helper remains responsible for auth/boundaries.
export async function getBulkImportOptions(): Promise<BulkImportOptions> {
  return apiFetch<BulkImportOptions>("/api/students/bulk-import/options", { method: "GET" });
}

export async function bulkImportStudents(
  file: File,
  options: { branch: string; year: number; semesterId: number; mode?: "merge" | "create_only" }
): Promise<BulkImportResult> {
  // The semester dropdown stores the REAL academic_semesters.id.
  // Send it explicitly as semester_id; also keep `semester` as a backwards-
  // compatible alias for older API deployments.
  const params = new URLSearchParams({
    branch: options.branch,
    year: String(options.year),
    semester_id: String(options.semesterId),
    semester: String(options.semesterId),
    mode: options.mode ?? "merge",
  });
  return apiUpload<BulkImportResult>(`/api/students/bulk-import?${params.toString()}`, file, "file");
}

export function studentsPdfUrl(
  semesterId?: number | string | null,
  q?: string,
  year?: string
): string {
  const params = new URLSearchParams();
  if (semesterId) params.set("semester_id", String(semesterId));
  if (q && q.trim()) params.set("q", q.trim());
  if (year && year.trim()) params.set("year", year.trim());
  const qs = params.toString() ? `?${params.toString()}` : "";
  return getAuthUrl(`/api/students/pdf${qs}`);
}
export interface StudentTrackRecord {
  student: StudentRecord;
  current_semester_id: number | null;
  semesters: SemesterOption[];
  attendance_by_semester: Record<string, {
    total_classes: number;
    present_classes: number;
    absent_classes: number;
    pct: number | null;
    band: "green" | "yellow" | "red" | "muted";
  }>;
  results: Array<{
    batch: {
      id: number;
      title: string;
      created_at: string;
      source_filename: string | null;
      semester_code: string;
      semester_name: string;
    };
    subjects: Array<{
      subject_code: string;
      subject_name: string;
      marks: number;
      max_marks: number;
      internal_marks: number | null;
      external_marks: number | null;
      credits: number | null;
      grade: string;
      grade_point: string;
      result_status: string;
      sgpa: string;
      percentage: string;
    }>;
    total_credits: number;
    sgpa: string | null;
    result_status: string | null;
  }>;
}

export async function getStudentTrackRecord(id: number): Promise<StudentTrackRecord> {
  return apiFetch<StudentTrackRecord>(`/api/students/${id}/track-record`, { method: "GET" });
}
