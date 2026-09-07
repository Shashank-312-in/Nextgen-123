// The one thin fetch wrapper every api/*.ts file calls through — plan §4.3.
// Keeps error handling and auth-attach logic in one place instead of at
// every call site. Do not call raw fetch() from route-group api files;
// go through apiFetch() so the {data}/{error} envelope (api/envelope.py)
// and the silent-refresh-on-401 behavior stay consistent everywhere.

declare global {
  interface Window {
    __SMS_API_BASE_URL__?: string;
  }
}

const normalizeBase = (value: string): string => value.trim().replace(/\/+$/, "").replace(/\/api$/, "");

const getApiBase = (): string => {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env || {};
  const configured = env.VITE_API_BASE_URL || env.VITE_API_URL || (typeof window !== "undefined" ? window.__SMS_API_BASE_URL__ : undefined);
  if (configured) return normalizeBase(configured);

  if (typeof window !== "undefined" && window.location.hostname) {
    const host = window.location.hostname;
    const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
    if (localHosts.has(host) || host.endsWith(".local")) {
      return `${window.location.protocol}//${host}:8001`;
    }
    return window.location.origin;
  }

  return "http://localhost:8001";
};

const API_BASE = getApiBase();

// In-memory only — never localStorage/sessionStorage. Plan §3.3: this app
// handles Aadhaar/APAAR fields, and localStorage is readable by any
// injected script. A page refresh loses this and relies on the refresh
// cookie + silent refresh-on-load (see useCurrentUser) to restore it.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getAuthUrl(path: string): string {
  const token = getAccessToken();
  const base = path.startsWith("http")
    ? path
    : `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;

  if (!token) return base;
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}token=${encodeURIComponent(token)}`;
}

export function formatPhotoUrl(photoPath: string | null): string | null {
  if (!photoPath) return null;
  let p = photoPath.trim();
  if (!p) return null;

  if (p.startsWith("/static/uploads/")) {
    p = p.replace("/static/uploads/", "/files/");
  } else if (p.startsWith("static/uploads/")) {
    p = p.replace("static/uploads/", "/files/");
  } else if (p.startsWith("uploads/")) {
    p = p.replace("uploads/", "/files/");
  }

  if (!p.startsWith("/api/files/") && p.startsWith("/files/")) {
    p = `/api${p}`;
  }

  return getAuthUrl(p);
}

export class ApiClientError extends Error {
  code?: string;
  status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
  }
}

interface Envelope<T> {
  data?: T;
  error?: { message: string; code?: string };
}

let refreshInFlight: Promise<boolean> | null = null;

// Calls POST /api/auth/refresh using the httpOnly cookie (sent automatically
// via credentials:'include'). Returns true if a new access token was
// obtained. De-duped via refreshInFlight so concurrent 401s from several
// simultaneous requests don't each fire their own refresh call.
async function attemptRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) return false;
        const body = (await res.json()) as Envelope<{ access_token: string }>;
        if (body.data?.access_token) {
          setAccessToken(body.data.access_token);
          return true;
        }
        return false;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the silent-refresh-and-retry step (used by refresh itself / login). */
  skipRefreshRetry?: boolean;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { body, skipRefreshRetry, headers, ...rest } = options;

  const doFetch = async (): Promise<Response> => {
    const finalHeaders: Record<string, string> = {
      "Content-Type": "application/json",
      ...(headers as Record<string, string> | undefined),
    };
    if (accessToken) {
      finalHeaders["Authorization"] = `Bearer ${accessToken}`;
    }
    return fetch(`${API_BASE}${path}`, {
      ...rest,
      credentials: "include",
      headers: finalHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  let res = await doFetch();

  if (res.status === 401 && !skipRefreshRetry) {
    const errBody = (await res.clone().json().catch(() => null)) as Envelope<T> | null;
    if (errBody?.error?.code === "TOKEN_INVALID") {
      const refreshed = await attemptRefresh();
      if (refreshed) {
        res = await doFetch();
      }
    }
  }

  const parsed = (await res.json().catch(() => null)) as Envelope<T> | null;

  if (!res.ok || !parsed || parsed.error) {
    const message = parsed?.error?.message ?? "Request failed";
    const code = parsed?.error?.code;
    throw new ApiClientError(message, res.status, code);
  }

  return parsed.data as T;
}

// Multipart upload — same auth/refresh/envelope handling as apiFetch, but
// omits Content-Type so the browser sets its own multipart boundary (a
// manual "multipart/form-data" header with no boundary breaks parsing on
// every backend). Used by any route accepting File (e.g. student/self
// photo upload) — never build a FormData request outside this helper.
export async function apiUpload<T>(path: string, file: File, fieldName: string): Promise<T> {
  const doFetch = async (): Promise<Response> => {
    const form = new FormData();
    form.append(fieldName, file);
    const finalHeaders: Record<string, string> = {};
    if (accessToken) {
      finalHeaders["Authorization"] = `Bearer ${accessToken}`;
    }
    return fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: finalHeaders,
      body: form,
    });
  };

  let res = await doFetch();

  if (res.status === 401) {
    const errBody = (await res.clone().json().catch(() => null)) as Envelope<T> | null;
    if (errBody?.error?.code === "TOKEN_INVALID") {
      const refreshed = await attemptRefresh();
      if (refreshed) {
        res = await doFetch();
      }
    }
  }

  const parsed = (await res.json().catch(() => null)) as Envelope<T> | null;

  if (!res.ok || !parsed || parsed.error) {
    const message = parsed?.error?.message ?? "Upload failed";
    const code = parsed?.error?.code;
    throw new ApiClientError(message, res.status, code);
  }

  return parsed.data as T;
}

export {};
