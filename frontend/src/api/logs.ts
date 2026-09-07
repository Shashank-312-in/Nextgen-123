import { apiFetch } from "./client";

export interface AuditLogRow {
  id: number;
  username: string;
  actor_role: "ADMIN" | "HOD" | "FACULTY" | "STUDENT" | string | null;
  action: string;
  entity: string;
  details: string | null;
  description: string;
  is_auth_event: boolean;
  created_at: string;
}

export interface SmsLogRow {
  id: number;
  roll_no: string;
  student_name?: string;
  parent_phone: string;
  message: string;
  status: string;
  approved?: number;
  hod_username?: string | null;
  gateway_id?: number | null;
  gateway_name?: string | null;
  gateway_mode?: string | null;
  gateway_owner_username?: string | null;
  gateway_owner_name?: string | null;
  error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface SmsAccessBatch { id: number; name: string; code: string; student_count: number; }

export interface SmsAccessMe {
  enabled: boolean;
  hod_username: string | null;
  allowed_batches: SmsAccessBatch[];
  gateway_configured: boolean;
}

export async function getMySmsAccess(): Promise<SmsAccessMe> {
  return apiFetch<SmsAccessMe>("/api/dashboard/sms-access/me", { method: "GET" });
}

export interface SmsSettings {
  sms_enabled: string;
  sms_daily_cap: string;
  sms_repeat_every_attendance?: string;
  sms_absentee_cutoff_time: string;
}

export interface SmsGateway {
  id: number;
  hod_username: string;
  owner_username?: string | null;
  gateway_name: string;
  gateway_mode: "cloud" | "local" | "modem" | string;
  device_id: string;
  device_id_masked?: string;
  device_id_configured?: boolean;
  local_url: string;
  username: string;
  password_set: boolean;
  modem_port: string;
  modem_baud: string;
  sim_number: number | null;
  active: boolean;
  auto_send?: boolean;
  updated_at: string | null;
}

export interface SmsApprovalRow {
  id: number;
  roll_no: string;
  student_name: string;
  parent_phone: string;
  message: string;
  send_date: string;
  hod_username: string | null;
  gateway_id: number | null;
  gateway_name: string | null;
  gateway_mode: string | null;
  gateway_active: boolean;
  message_type?: string;
  status?: string;
  error: string | null;
}

export async function getAuditLogs(params: { actor_type?: string; activity?: string; admin_username?: string } = {}): Promise<AuditLogRow[]> {
  const query = new URLSearchParams();
  if (params.actor_type) query.set("actor_type", params.actor_type);
  if (params.activity) query.set("activity", params.activity);
  if (params.admin_username) query.set("admin_username", params.admin_username);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<AuditLogRow[]>(`/api/dashboard/audit-log${suffix}`, { method: "GET" });
}

export async function getSmsLogs(): Promise<SmsLogRow[]> {
  return apiFetch<SmsLogRow[]>("/api/dashboard/sms-log", { method: "GET" });
}

export async function getSmsSettings(): Promise<SmsSettings> {
  return apiFetch<SmsSettings>("/api/dashboard/sms-settings", { method: "GET" });
}

export async function saveSmsSettings(settings: SmsSettings): Promise<{ ok: boolean; sms_absentee_cutoff_time?: string }> {
  return apiFetch<{ ok: boolean }>("/api/dashboard/sms-settings", {
    method: "POST",
    body: settings,
  });
}

export async function getSmsGateways(): Promise<SmsGateway[]> {
  return apiFetch<SmsGateway[]>("/api/dashboard/sms-gateways", { method: "GET" });
}

export async function createSmsGateway(body: Partial<SmsGateway> & { password?: string }): Promise<SmsGateway> {
  return apiFetch<SmsGateway>("/api/dashboard/sms-gateways", { method: "POST", body });
}

export async function updateSmsGateway(id: number, body: Partial<SmsGateway> & { password?: string }): Promise<SmsGateway> {
  return apiFetch<SmsGateway>(`/api/dashboard/sms-gateways/${id}`, { method: "PATCH", body });
}

export async function setSmsGatewayAutoSend(id: number, enabled: boolean): Promise<{ auto_send: boolean }> {
  return apiFetch<{ auto_send: boolean }>(`/api/dashboard/sms-gateways/${id}/auto-send?enabled=${enabled}`, { method: "POST" });
}

export async function approveSmsRow(id: number): Promise<{ approved_count: number; queue_id: number }> {
  return apiFetch(`/api/dashboard/sms-approval/${id}/approve`, { method: "POST" });
}

export async function rejectSmsRow(id: number): Promise<{ rejected_count: number; queue_id: number }> {
  return apiFetch(`/api/dashboard/sms-approval/${id}/reject`, { method: "POST" });
}

export interface SmsBatch { id: number; name: string; code: string; student_count: number; }

export async function getSmsBatches(): Promise<SmsBatch[]> {
  return apiFetch<SmsBatch[]>("/api/dashboard/sms-batches", { method: "GET" });
}

export async function getSmsTemplates(): Promise<Record<string, string>> {
  return apiFetch<Record<string, string>>("/api/dashboard/sms-templates", { method: "GET" });
}

export async function saveSmsTemplate(message_type: "ABSENTEE_ALERT" | "GENERAL_NOTICE", template: string): Promise<{ message_type: string; template: string }> {
  return apiFetch(`/api/dashboard/sms-templates`, { method: "POST", body: { message_type, template } });
}

export async function sendGeneralNotice(semester_id: number, message: string): Promise<{ queued_count: number; blocked_count: number }> {
  return apiFetch(`/api/dashboard/sms-general-notice`, { method: "POST", body: { semester_id, message } });
}

export async function testSmsGatewayConnection(id: number): Promise<{ ok: boolean; mode: string; device?: unknown; health?: string; message?: string }> {
  return apiFetch<{ ok: boolean; mode: string; device?: unknown; health?: string; message?: string }>(`/api/dashboard/sms-gateways/${id}/test-connection`, { method: "POST" });
}

export async function getSmsApproval(sendDate?: string): Promise<SmsApprovalRow[]> {
  const query = sendDate ? `?send_date=${encodeURIComponent(sendDate)}` : "";
  return apiFetch<SmsApprovalRow[]>(`/api/dashboard/sms-approval${query}`, { method: "GET" });
}

export async function approveSmsBatch(sendDate: string): Promise<{ approved_count: number; send_date: string; hod_username?: string }> {
  return apiFetch<{ approved_count: number; send_date: string; hod_username?: string }>(`/api/dashboard/sms-approval`, {
    method: "POST",
    body: { send_date: sendDate },
  });
}

export async function testSmsGateway(phone: string, gatewayId: number, message?: string): Promise<{ sent: boolean; message: string }> {
  return apiFetch<{ sent: boolean; message: string }>("/api/dashboard/sms-test", {
    method: "POST",
    body: { phone, gateway_id: gatewayId, message },
  });
}

export async function triggerSmsQueue(): Promise<{ sent_count: number; failed_count: number }> {
  return apiFetch<{ sent_count: number; failed_count: number }>("/api/dashboard/sms-trigger", {
    method: "POST",
  });
}
