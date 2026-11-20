import type { Session } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const body = payload as { detail?: unknown; error?: unknown } | null;
    const rawMessage =
      typeof body?.detail === "string"
        ? body.detail
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
      response.status === 401 &&
      !rawMessage.includes("Missing Authorization header")
    ) {
      window.dispatchEvent(new Event("zyrquen:session-change"));
    }
    throw new ApiError(message, response.status);
  }

  return payload as T;
}

export async function readSession(): Promise<Session> {
  const response = await fetch("/api/session", { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError("ไม่สามารถอ่านข้อมูลเซสชันปัจจุบันได้", response.status);
  }
  return response.json();
}

export function conversationStorageKey(session: Session | null): string | null {
  if (!session?.authenticated) {
    return null;
  }
  const owner = session.userId?.trim() || session.email?.trim().toLowerCase();
  if (!owner) {
    return null;
  }
  return `zyrquen.local-conversations.v2.${owner}`;
}
