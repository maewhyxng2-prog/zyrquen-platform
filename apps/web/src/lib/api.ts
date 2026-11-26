import type { Session } from "./types";

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

export async function readSession(signal?: AbortSignal): Promise<Session> {
  const response = await fetch("/api/session", {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new ApiError("ไม่สามารถอ่านข้อมูลเซสชันปัจจุบันได้", response.status);
  }
  return response.json();
}

export async function downloadBackendFile(
  path: string,
  fallbackFilename: string,
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
  const filename = match?.[1] || fallbackFilename;
  const contentType = response.headers.get("content-type") || "application/octet-stream";
  const text = await response.text();
  const blob = new Blob([text], { type: contentType });
  if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
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
