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
          ? "The API or native runtime is currently unavailable."
          : `The request failed with status ${response.status}.`;
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
    throw new ApiError("Unable to read the current session.", response.status);
  }
  return response.json();
}
