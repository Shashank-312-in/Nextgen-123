import { apiFetch } from "./client";

export interface ProblemReport {
  id: number;
  username: string;
  role: string;
  category: string;
  subject: string;
  description: string;
  status: "PENDING" | "IN_PROGRESS" | "RESOLVED" | "CLOSED";
  admin_notes: string | null;
  created_at: string;
  updated_at: string;
}

export async function submitProblemReport(data: {
  category: string;
  subject: string;
  description: string;
}): Promise<{ message: string }> {
  return apiFetch<{ message: string }>("/api/reports/submit", {
    method: "POST",
    body: data,
  });
}

export async function getProblemReports(): Promise<{ reports: ProblemReport[] }> {
  return apiFetch<{ reports: ProblemReport[] }>("/api/reports", {
    method: "GET",
  });
}

export async function updateReportStatus(
  reportId: number,
  status: string,
  adminNotes?: string
): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(`/api/reports/${reportId}/status`, {
    method: "PATCH",
    body: { status, admin_notes: adminNotes },
  });
}
