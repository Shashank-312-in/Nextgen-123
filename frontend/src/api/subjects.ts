// Group 5 — Subjects API client. Mirrors api/routes_subjects.py.
import { apiFetch } from "./client";

export interface SemesterInfo {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  active: boolean;
}

export interface FacultyOption {
  username: string;
  full_name: string;
}

export interface SubjectRow {
  id: number;
  semester_id: number;
  code: string;
  name: string;
  has_lab: boolean;
  active: boolean;
  faculty_usernames?: string[];
}

export interface SubjectsPageData {
  semesters: SemesterInfo[];      // active semesters
  all_semesters: SemesterInfo[];  // all semesters including inactive
  grouped: Record<string, SubjectRow[]>;  // keyed by semester code
  faculty: FacultyOption[];
}

export async function getSubjectsPage(): Promise<SubjectsPageData> {
  return apiFetch<SubjectsPageData>("/api/subjects", { method: "GET" });
}

export async function createSubject(body: {
  semester_id: number;
  code: string;
  name: string;
  has_lab: boolean;
}): Promise<{ ok: boolean }> {
  return apiFetch("/api/subjects", { method: "POST", body });
}

export async function updateSubject(
  subjectId: number,
  body: { code: string; name: string; has_lab: boolean }
): Promise<{ ok: boolean }> {
  return apiFetch(`/api/subjects/${subjectId}`, { method: "PATCH", body });
}

export async function toggleSubjectActive(subjectId: number): Promise<{ active: boolean }> {
  return apiFetch(`/api/subjects/${subjectId}/toggle-active`, { method: "POST" });
}

export async function assignFaculty(
  subjectId: number,
  faculty_usernames: string[]
): Promise<{ ok: boolean }> {
  return apiFetch(`/api/subjects/${subjectId}/assign-faculty`, {
    method: "POST",
    body: { faculty_usernames },
  });
}

export async function deleteSubject(subjectId: number): Promise<{ ok: boolean }> {
  return apiFetch(`/api/subjects/${subjectId}`, { method: "DELETE" });
}

export async function toggleSemesterActive(semesterId: number): Promise<{ active: boolean }> {
  return apiFetch(`/api/semesters/${semesterId}/toggle-active`, { method: "POST" });
}

