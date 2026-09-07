// Matches api/routes_auth.py exactly — one function per route. Keep this
// file's shapes in lockstep with that module; if a route's request/response
// body changes there, update the matching type here in the same change.
import { apiFetch, setAccessToken } from "./client";

export type Role = "HOD" | "FACULTY" | "STUDENT" | "ADMIN";

export interface CurrentUser {
  username: string;
  role: Role;
  student_roll_no: string | null;
  must_change_password: boolean;
}

interface LoginResponse {
  access_token: string;
  expires_in: number;
  user: CurrentUser;
  redirect: string;
}

interface RefreshResponse {
  access_token: string;
  expires_in: number;
  user: CurrentUser;
}

interface ChangePasswordResponse {
  access_token: string;
  expires_in: number;
  redirect: string;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await apiFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: { username, password },
    skipRefreshRetry: true, // a failed login is never a stale-token situation
  });
  setAccessToken(res.access_token);
  return res;
}

export async function refresh(): Promise<RefreshResponse> {
  const res = await apiFetch<RefreshResponse>("/api/auth/refresh", {
    method: "POST",
    skipRefreshRetry: true, // refreshing IS the refresh step — no recursive retry
  });
  setAccessToken(res.access_token);
  return res;
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
  } catch (err) {
    console.warn("Logout endpoint error (ignored):", err);
  } finally {
    setAccessToken(null);
  }
}


export async function me(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/auth/me", { method: "GET" });
}

export async function changePassword(
  oldPassword: string,
  newPassword: string,
  confirmPassword: string
): Promise<ChangePasswordResponse> {
  const res = await apiFetch<ChangePasswordResponse>("/api/auth/change-password", {
    method: "POST",
    body: {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    },
  });
  setAccessToken(res.access_token);
  return res;
}

// — Registration
export interface RegisterResponse {
  message: string;
  email: string | null;
}

export async function register(
  rollNo: string,
  username: string,
  password: string,
  confirmPassword: string,
  fullName: string | undefined,
  email: string,
  phone?: string,
  yearOfStudy?: string
): Promise<RegisterResponse> {
  return apiFetch<RegisterResponse>("/api/auth/register", {
    method: "POST",
    body: {
      roll_no: rollNo,
      username,
      password,
      confirm_password: confirmPassword,
      full_name: fullName || undefined,
      email,
      phone: phone || undefined,
      year_of_study: yearOfStudy || undefined,
    },
    skipRefreshRetry: true, // no session exists yet — nothing to refresh
  });
}

// — Email OTP (shared by Register's email-verify step and Forgot Password)
export type OtpPurpose = "REGISTER" | "RESET_PASSWORD";

export interface SendOtpResponse {
  message: string;
}


export async function sendOtp(email: string, purpose: OtpPurpose): Promise<SendOtpResponse> {
  return apiFetch<SendOtpResponse>("/api/auth/send-otp", {
    method: "POST",
    body: { email, purpose },
    skipRefreshRetry: true,
  });
}

export interface VerifyOtpResponse {
  message: string;
  verified: boolean;
}

export async function verifyOtp(
  email: string,
  purpose: OtpPurpose,
  code: string
): Promise<VerifyOtpResponse> {
  return apiFetch<VerifyOtpResponse>("/api/auth/verify-otp", {
    method: "POST",
    body: { email, purpose, code },
    skipRefreshRetry: true,
  });
}

// — Forgot / Reset Password (OTP-based — see routes_auth.py's forgot_password
// docstring: the token-link route still exists server-side but isn't used
// by this frontend; Forgot Password here is send-otp + reset-password-otp)
export interface ForgotPasswordResponse {
  message: string;
}

export async function forgotPassword(email: string): Promise<ForgotPasswordResponse> {
  return sendOtp(email, "RESET_PASSWORD");
}

export interface ResetPasswordOtpResponse {
  message: string;
}

export async function resetPasswordOtp(
  email: string,
  code: string,
  newPassword: string,
  confirmPassword: string
): Promise<ResetPasswordOtpResponse> {
  return apiFetch<ResetPasswordOtpResponse>("/api/auth/reset-password-otp", {
    method: "POST",
    body: {
      email,
      code,
      new_password: newPassword,
      confirm_password: confirmPassword,
    },
    skipRefreshRetry: true,
  });
}
