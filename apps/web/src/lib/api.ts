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
    const body = payload as { detail?: unknown } | null;
    const message =
      typeof body?.detail === "string"
        ? body.detail
        : response.status === 503
          ? "บริการ API หรือ Native Model ไม่พร้อมใช้งานในขณะนี้ กรุณาตรวจสอบสถานะการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
          : `คำขอไม่สำเร็จ (รหัสสถานะ ${response.status}) กรุณาลองใหม่อีกครั้ง`;
    throw new ApiError(message, response.status);
  }

  return payload as T;
}

export async function readSession(): Promise<{
  authenticated: boolean;
  email: string | null;
}> {
  const response = await fetch("/api/session", { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError("ไม่สามารถอ่านข้อมูลเซสชันปัจจุบันได้", response.status);
  }
  return response.json();
}
