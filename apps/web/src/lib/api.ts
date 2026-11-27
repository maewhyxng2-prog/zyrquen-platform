import type { AuditEntry, Session } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const body = payload as
    | { detail?: unknown; error?: unknown }
    | null;
  const detail = body?.detail;
  const detailMessage =
    detail && typeof detail === "object" && !Array.isArray(detail)
      ? (detail as { message?: unknown }).message
      : undefined;
  const errorCode = (payload as { code?: unknown } | null)?.code;
  const rawMessage =
    typeof detail === "string"
      ? detail
      : typeof detailMessage === "string"
        ? detailMessage
      : typeof body?.error === "string"
        ? body.error
        : "";
  const message =
    response.status === 401 && rawMessage.includes("Missing Authorization header")
      ? "ปลายทางพอร์ตที่เชื่อมต่ออยู่ไม่ใช่บริการ ZYRQUEN API (รหัสสถานะ 401) กรุณาตรวจสอบค่า ZYRQUEN_API_BASE_URL"
      : rawMessage
        ? rawMessage
        : response.status === 503
          ? "บริการ API หรือ Native Model ไม่พร้อมใช้งานในขณะนี้ กรุณาตรวจสอบสถานะการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
          : `คำขอไม่สำเร็จ (รหัสสถานะ ${response.status}) กรุณาลองใหม่อีกครั้ง`;

  if (
    typeof window !== "undefined" &&
    ((response.status === 401 &&
      !rawMessage.includes("Missing Authorization header")) ||
      errorCode === "session_mismatch")
  ) {
    window.dispatchEvent(new Event("zyrquen:session-change"));
  }

  return new ApiError(message, response.status);
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  return payload as T;
}

export async function apiStreamRequest(
  path: string,
  init: RequestInit,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "text/event-stream");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers,
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  if (
    !response.body ||
    !response.headers.get("content-type")?.toLowerCase().includes("text/event-stream")
  ) {
    throw new ApiError("Native inference did not return an event stream", 502);
  }

  return response;
}

export function normalizeSessionPayload(payload: unknown): Session {
  const root =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  const nestedUser =
    root.user && typeof root.user === "object" && !Array.isArray(root.user)
      ? (root.user as Record<string, unknown>)
      : null;
  const candidate = nestedUser ?? root;

  const rawUserId = candidate.userId ?? candidate.id ?? root.userId ?? root.id;
  const userId =
    typeof rawUserId === "string" && rawUserId.trim()
      ? rawUserId.trim()
      : null;

  const rawEmail = candidate.email ?? root.email;
  const email =
    typeof rawEmail === "string" && rawEmail.trim()
      ? rawEmail.trim().toLowerCase()
      : null;

  const rawRole = candidate.role ?? root.role;
  const role =
    typeof rawRole === "string" && rawRole.trim()
      ? rawRole.trim().toLowerCase()
      : null;

  const isActive =
    typeof candidate.is_active === "boolean"
      ? candidate.is_active
      : typeof candidate.isActive === "boolean"
        ? candidate.isActive
        : true;

  const rawEmailVerified =
    candidate.emailVerified ??
    candidate.email_verified ??
    root.emailVerified ??
    root.email_verified;
  const emailVerified =
    typeof rawEmailVerified === "boolean"
      ? rawEmailVerified
      : typeof candidate.verified === "boolean"
        ? candidate.verified
        : typeof root.verified === "boolean"
          ? root.verified
          : true;

  const explicitAuth =
    typeof root.authenticated === "boolean"
      ? root.authenticated
      : typeof candidate.authenticated === "boolean"
        ? candidate.authenticated
        : undefined;

  const authenticated = Boolean(
    userId &&
      isActive &&
      (explicitAuth === true || explicitAuth === undefined),
  );

  const expired = Boolean(root.expired ?? candidate.expired);
  const rawError = root.error ?? root.detail ?? candidate.error;
  const error =
    typeof rawError === "string" && rawError.trim() ? rawError.trim() : null;

  return {
    authenticated,
    userId: authenticated ? userId : null,
    email: authenticated ? email : null,
    role: authenticated ? role : null,
    verified: authenticated ? emailVerified : false,
    emailVerified: authenticated ? emailVerified : false,
    expired,
    error,
  };
}

export function normalizeAuditLogEntry(
  raw: unknown,
  session?: Session | null,
  userIdByEmail?: ReadonlyMap<string, string>,
): AuditEntry {
  const row =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  const id = typeof row.id === "string" ? row.id : "";
  const action =
    typeof row.action === "string" && row.action.trim()
      ? row.action.trim()
      : "unknown";
  const rawEmail =
    typeof row.actor_email === "string" && row.actor_email.trim()
      ? row.actor_email.trim().toLowerCase()
      : null;
  const rawActorId = row.actor_user_id ?? row.actor_id ?? null;
  let actorUserId =
    typeof rawActorId === "string" && rawActorId.trim()
      ? rawActorId.trim()
      : null;

  if (!actorUserId && rawEmail) {
    if (session?.authenticated && session.userId && session.email === rawEmail) {
      actorUserId = session.userId;
    } else if (userIdByEmail?.has(rawEmail)) {
      actorUserId = userIdByEmail.get(rawEmail) ?? null;
    }
  }

  const rawResourceId = row.resource_id ?? row.target ?? null;
  const resourceId =
    typeof rawResourceId === "string" && rawResourceId.trim()
      ? rawResourceId.trim()
      : null;

  const outcome =
    typeof row.outcome === "string" && row.outcome.trim()
      ? row.outcome.trim()
      : null;

  const createdAt =
    typeof row.created_at === "string" && row.created_at
      ? row.created_at
      : new Date(0).toISOString();

  return {
    id,
    actor_user_id: actorUserId,
    actor_email: rawEmail,
    action,
    resource_id: resourceId,
    outcome,
    created_at: createdAt,
  };
}

export async function readSession(signal?: AbortSignal): Promise<Session> {
  const response = await fetch("/api/session", {
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (response.status === 401 || response.status === 403) {
    const base =
      payload && typeof payload === "object" && !Array.isArray(payload)
        ? (payload as Record<string, unknown>)
        : {};
    return normalizeSessionPayload({
      ...base,
      authenticated: false,
      expired: response.status === 401 ? true : Boolean(base.expired),
    });
  }

  if (!response.ok) {
    throw new ApiError("ไม่สามารถอ่านข้อมูลเซสชันปัจจุบันได้", response.status);
  }

  return normalizeSessionPayload(payload);
}

export function buildModelRegistryMetadataFilename(
  version: string,
  exportedAt: Date = new Date(),
): string {
  const safeVersion =
    version
      .trim()
      .replace(/[^A-Za-z0-9._-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "unknown-version";
  const dateStamp = Number.isNaN(exportedAt.getTime())
    ? new Date().toISOString().slice(0, 10)
    : exportedAt.toISOString().slice(0, 10);
  return `zyrquen-model-registry-${safeVersion}-metadata-${dateStamp}.json`;
}

export async function downloadBackendFile(
  path: string,
  fallbackFilename: string,
  options?: { overrideFilename?: boolean },
): Promise<string> {
  const response = await fetch(`/api/backend/${path}`, {
    method: "GET",
    cache: "no-store",
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";\n]+)"?/i);
  const filename = options?.overrideFilename
    ? fallbackFilename
    : match?.[1] || fallbackFilename;
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const text = await response.text();
  const blob = new Blob([text], { type: contentType });
  if (
    typeof document !== "undefined" &&
    typeof URL !== "undefined" &&
    typeof URL.createObjectURL === "function"
  ) {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }
  return filename;
}
