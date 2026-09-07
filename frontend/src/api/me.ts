// Group 6 — Self-service API client. Mirrors api/routes_me.py.
// HOD/FACULTY: /api/me/account (GET, PATCH, photo, change-password)
// STUDENT: /api/me/profile (GET, PATCH, photo)
import { apiFetch, apiUpload } from "./client";

// ─── Shared ──────────────────────────────────────

export interface ChangePasswordBody {
  old_password: string;
  new_password: string;
  confirm_password: string;
}

// ─── HOD / FACULTY ───────────────────────────────

export interface StaffUser {
  id: number;
  username: string;
  full_name: string;
  role: "HOD" | "FACULTY" | "ADMIN";
  department: string | null;
  designation: string | null;
  employee_id: string | null;
  email: string | null;
  phone: string | null;
  qualification: string | null;
  date_of_joining: string | null;
  photo_path: string | null;
  active: boolean;
}

export interface AccountPageData {
  user: StaffUser;
  specs: Array<{ label: string; key: string }>;
}

export async function getMyAccount(): Promise<AccountPageData> {
  return apiFetch<AccountPageData>("/api/me/account", { method: "GET" });
}

export async function updateMyAccount(data: {
  full_name?: string;
  department?: string;
  designation?: string;
  employee_id?: string;
  email?: string;
  phone?: string;
  qualification?: string;
  date_of_joining?: string;
}): Promise<{ user: StaffUser }> {
  return apiFetch("/api/me/account", { method: "PATCH", body: data });
}

export async function uploadMyAccountPhoto(file: File): Promise<{ photo_path: string }> {
  return apiUpload("/api/me/account/photo", file, "photo");
}

export async function deleteMyAccountPhoto(): Promise<{ photo_path: null }> {
  return apiFetch("/api/me/account/photo/delete", { method: "POST" });
}

export async function changeMyAccountPassword(body: ChangePasswordBody): Promise<{ ok: boolean }> {
  return apiFetch("/api/me/account/change-password", { method: "POST", body });
}

// ─── STUDENT ─────────────────────────────────────

export interface StudentSelf {
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
  active: boolean;
  photo_path: string | null;
  current_semester_id: number | null;
}

export interface MyProfileData {
  student: StudentSelf;
  student_self_edit_enabled?: boolean;
}

export async function getMyProfile(): Promise<MyProfileData> {
  return apiFetch<MyProfileData>("/api/me/profile", { method: "GET" });
}

export async function updateMyProfile(data: {
  name?: string;
  father_name?: string;
  email?: string;
  phone?: string;
  parent_phone?: string;
  dob?: string;
  category?: string;
  gender?: string;
  seat_category?: string;
  address?: string;
}): Promise<MyProfileData> {
  return apiFetch("/api/me/profile", { method: "PATCH", body: data });
}

export async function uploadMyProfilePhoto(file: File): Promise<{ photo_path: string }> {
  return apiUpload("/api/me/profile/photo", file, "photo");
}

export async function deleteMyProfilePhoto(): Promise<{ photo_path: null }> {
  return apiFetch("/api/me/profile/photo/delete", { method: "POST" });
}

export async function changeMyProfilePassword(body: ChangePasswordBody): Promise<{ ok: boolean }> {
  return apiFetch("/api/me/change-password", { method: "POST", body });
}
