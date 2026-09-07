// Group 5 — Academic Calendar API client. Mirrors api/routes_academic_calendar.py.
import { apiFetch, apiUpload } from "./client";

export interface CalendarSemester {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  timetable_path: string | null;
  calendar_path: string | null;
}

export interface CalendarPageData {
  semesters: CalendarSemester[];
  can_edit: boolean;
}

export async function getCalendarPage(): Promise<CalendarPageData> {
  return apiFetch<CalendarPageData>("/api/academic-calendar", { method: "GET" });
}

export async function uploadCalendarFile(
  semesterId: number,
  kind: "timetable" | "calendar",
  file: File
): Promise<{ path: string; semester_id: number; kind: string }> {
  return apiUpload(
    `/api/academic-calendar/${semesterId}/upload/${kind}`,
    file,
    "file"
  );
}

export async function deleteCalendarFile(
  semesterId: number,
  kind: "timetable" | "calendar"
): Promise<{ semester_id: number; kind: string; deleted: boolean }> {
  return apiFetch(
    `/api/academic-calendar/${semesterId}/delete/${kind}`,
    { method: "POST" }
  );
}
