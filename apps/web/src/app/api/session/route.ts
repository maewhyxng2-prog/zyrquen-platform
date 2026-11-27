import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  hasExplicitExternalApiUrl,
  resolveApiBaseUrl,
} from "@/lib/api-config";
import {
  handleInMemoryBackendRequest,
  shouldUseInMemoryBackend,
} from "@/lib/in-memory-backend";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";
function clearSessionCookies(request: NextRequest, response: NextResponse) {
  const expiredCookie = buildSessionCookieOptions(request, 0);
  response.cookies.set(ACCESS_COOKIE, "", expiredCookie);
  response.cookies.set(EMAIL_COOKIE, "", expiredCookie);
}

function buildSessionResponse(
  request: NextRequest,
  status: number,
  payload: Record<string, unknown>,
): NextResponse {
  if (status === 401 || status === 403) {
    const rawDetail =
      typeof payload.detail === "string"
        ? payload.detail
        : typeof payload.error === "string"
          ? payload.error
          : "";

    const response = NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
        expired: status === 401,
        error:
          status === 403
            ? "บัญชีนี้ถูกระงับการใช้งาน"
            : rawDetail.includes("Missing Authorization header")
              ? "ปลายทางที่เชื่อมต่ออยู่ไม่ใช่บริการยืนยันตัวตนของ ZYRQUEN"
              : null,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearSessionCookies(request, response);
    return response;
  }

  if (status < 200 || status >= 300) {
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
        error: `ตรวจสอบเซสชันไม่สำเร็จ (รหัสสถานะ ${status})`,
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const nested =
    payload.user && typeof payload.user === "object" && !Array.isArray(payload.user)
      ? (payload.user as Record<string, unknown>)
      : payload;

  const user = nested as {
    id?: unknown;
    userId?: unknown;
    email?: unknown;
    role?: unknown;
    is_active?: unknown;
    isActive?: unknown;
    email_verified?: unknown;
    emailVerified?: unknown;
  };

  const resolvedId =
    typeof user.id === "string" && user.id.trim()
      ? user.id.trim()
      : typeof user.userId === "string" && user.userId.trim()
        ? user.userId.trim()
        : null;
  const resolvedEmail =
    typeof user.email === "string" && user.email.trim()
      ? user.email.trim().toLowerCase()
      : null;
  const isActive =
    typeof user.is_active === "boolean"
      ? user.is_active
      : typeof user.isActive === "boolean"
        ? user.isActive
        : false;
  const emailVerified =
    typeof user.emailVerified === "boolean"
      ? user.emailVerified
      : typeof user.email_verified === "boolean"
        ? user.email_verified
        : false;

  if (!resolvedId || !resolvedEmail || !isActive) {
    const response = NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
        error: "ข้อมูลเซสชันจากบริการยืนยันตัวตนไม่สมบูรณ์",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearSessionCookies(request, response);
    return response;
  }

  return NextResponse.json(
    {
      authenticated: true,
      userId: resolvedId,
      email: resolvedEmail,
      role: typeof user.role === "string" && user.role.trim() ? user.role.trim().toLowerCase() : null,
      verified: emailVerified,
      emailVerified,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  const staleEmail = cookieStore.get(EMAIL_COOKIE)?.value;

  if (!accessToken) {
    const response = NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
    if (staleEmail) {
      clearSessionCookies(request, response);
    }
    return response;
  }

  const configuredUrl = process.env.ZYRQUEN_API_BASE_URL;
  const baseUrl = resolveApiBaseUrl(configuredUrl, process.env.NODE_ENV);
  const hasExplicitUrl = hasExplicitExternalApiUrl(configuredUrl);
  const authorization = `Bearer ${accessToken}`;

  const isProduction = process.env.NODE_ENV === "production";
  if (!baseUrl) {
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
        error: hasExplicitUrl
          ? "ค่า ZYRQUEN_API_BASE_URL ไม่ถูกต้องสำหรับตรวจสอบเซสชัน"
          : "BLOCKED: ยังไม่ได้กำหนดค่า ZYRQUEN_API_BASE_URL สำหรับตรวจสอบเซสชันในโหมด Production",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (
    await shouldUseInMemoryBackend(baseUrl, hasExplicitUrl, process.env.NODE_ENV)
  ) {
    const inMemory = await handleInMemoryBackendRequest({
      method: "GET",
      path: "auth/me",
      authorizationHeader: authorization,
    });
    return buildSessionResponse(
      request,
      inMemory.status,
      (inMemory.body ?? {}) as Record<string, unknown>,
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${baseUrl}/auth/me`, {
      method: "GET",
      headers: {
        Authorization: authorization,
        Accept: "application/json",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(hasExplicitUrl ? 10_000 : 300),
    });
  } catch {
    if (!isProduction && !hasExplicitUrl) {
      const inMemory = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/me",
        authorizationHeader: authorization,
      });
      return buildSessionResponse(
        request,
        inMemory.status,
        (inMemory.body ?? {}) as Record<string, unknown>,
      );
    }
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
        error: "BLOCKED: ไม่สามารถเชื่อมต่อบริการ ZYRQUEN API เพื่อยืนยันเซสชันได้",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const body = ((await upstream.json().catch(() => null)) ?? {}) as Record<string, unknown>;
  return buildSessionResponse(request, upstream.status, body);
}
