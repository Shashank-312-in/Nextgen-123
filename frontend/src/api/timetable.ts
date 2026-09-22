import { apiFetch } from "./client";

export type TimetableBlockType =
  | "THEORY"
  | "LAB"
  | "PE"
  | "OE"
  | "TUTORIAL"
  | "ACTIVITY"
  | "OTHER";
export type TimetableSection = "MORNING" | "AFTERNOON";

export interface TimetablePeriod {
  key: string;
  label: string;
  start: string;
  end: string;
  section: TimetableSection;
}

export interface TimetableSemester {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  active: number;
}

export interface TimetableSubject {
  id: number;
  code: string;
  name: string;
  has_lab: number;
}

export interface TimetableFaculty {
  username: string;
  full_name: string;
}

export interface TimetableEntry {
  id: number;
  day: string;
  section: TimetableSection;
  start_slot: number;
  duration: number;
  block_type: TimetableBlockType;
  subject_id: number | null;
  subject_code: string | null;
  subject_name: string | null;
  custom_label: string;
  faculty_username: string | null;
  faculty_name: string | null;
  room: string;
}

export interface TimetableRecord {
  id: number;
  semester_id: number;
  semester_code: string;
  semester_name: string;
  section_name: string;
  academic_year: string;
  hod_username: string;
  status: "DRAFT" | "PUBLISHED";
  periods: TimetablePeriod[];
  entries: TimetableEntry[];
}

export interface TimetablePageData {
  mode: "builder" | "viewer";
  periods_default: TimetablePeriod[];
  semesters: TimetableSemester[];
  subjects: TimetableSubject[];
  faculty: TimetableFaculty[];
  timetables: TimetableRecord[];
}

export interface TimetableEntryInput {
  id?: string | null;
  day: string;
  section: TimetableSection;
  start_slot: number;
  duration: number;
  block_type: TimetableBlockType;
  subject_id: number | null;
  custom_label: string;
  faculty_username: string | null;
  room: string;
}

export interface SaveTimetableInput {
  id?: number | null;
  semester_id: number;
  section_name: string;
  academic_year: string;
  periods: TimetablePeriod[];
  entries: TimetableEntryInput[];
  status: "DRAFT" | "PUBLISHED";
}

export async function getTimetables(params: {
  semester_id?: number;
  section?: string;
  academic_year?: string;
} = {}): Promise<TimetablePageData> {
  const search = new URLSearchParams();
  if (params.semester_id) search.set("semester_id", String(params.semester_id));
  if (params.section) search.set("section", params.section);
  if (params.academic_year) search.set("academic_year", params.academic_year);
  const qs = search.toString();
  return apiFetch<TimetablePageData>(`/api/timetables${qs ? `?${qs}` : ""}`, { method: "GET" });
}

export async function saveTimetable(input: SaveTimetableInput): Promise<{ timetable: TimetableRecord }> {
  return apiFetch<{ timetable: TimetableRecord }>("/api/timetables", {
    method: "POST",
    body: input,
  });
}

export async function deleteTimetable(id: number): Promise<{ deleted: boolean; id: number }> {
  return apiFetch<{ deleted: boolean; id: number }>(`/api/timetables/${id}`, {
    method: "DELETE",
  });
}

// ── Day schedule + substitute overrides (HOD) ───────────────────────
export interface DayScheduleEntry {
  timetable_entry_id: number;
  timetable_id: number;
  target_date: string;
  section_name: string;
  section: TimetableSection;
  start_slot: number;
  duration: number;
  period: string | number | null;
  start_time: string | null;
  end_time: string | null;
  block_type: TimetableBlockType;
  subject_code: string | null;
  subject_name: string | null;
  custom_label: string | null;
  room: string | null;
  regular_faculty_username: string | null;
  regular_faculty_name: string | null;
  substitute_faculty_username: string | null;
  substitute_faculty_name: string | null;
  override_id: number | null;
  override_reason: string | null;
}

export function getDaySchedule(targetDate: string) {
  return apiFetch<{ date: string; entries: DayScheduleEntry[] }>(
    `/api/timetables/today?target_date=${encodeURIComponent(targetDate)}`,
  );
}

export function createOverride(body: {
  timetable_entry_id: number;
  override_date: string;
  substitute_faculty_username: string;
  reason: string;
}) {
  return apiFetch<{ override: { id: number } }>("/api/timetables/overrides", {
    method: "POST",
    body,
  });
}

export function deleteOverride(overrideId: number) {
  return apiFetch<{ deleted: boolean; id: number }>(`/api/timetables/overrides/${overrideId}`, { method: "DELETE" });
}
