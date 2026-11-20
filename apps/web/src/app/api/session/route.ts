import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";
import { handleLocalBackendRequest } from "@/lib/local-backend";

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
        verified: true,
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
        verified: false,
        error: `ตรวจสอบเซสชันไม่สำเร็จ (รหัสสถานะ ${status})`,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const user = payload as {
    id?: unknown;
    email?: unknown;
    is_active?: unknown;
  };

  if (
    typeof user.id !== "string" ||
    !user.id ||
    typeof user.email !== "string" ||
    !user.email ||
    user.is_active !== true
  ) {
    const response = NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        verified: false,
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
      userId: user.id,
      email: user.email.trim().toLowerCase(),
      verified: true,
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
        verified: true,
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
  const hasExplicitUrl = Boolean(configuredUrl?.trim());
  const authorization = `Bearer ${accessToken}`;

  if (!baseUrl) {
    if (hasExplicitUrl) {
      return NextResponse.json(
        {
          authenticated: false,
          email: null,
          userId: null,
          verified: false,
          error: "ค่า ZYRQUEN_API_BASE_URL ไม่ถูกต้องสำหรับตรวจสอบเซสชัน",
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    const local = handleLocalBackendRequest({
      method: "GET",
      path: "auth/me",
      authorization,
    });
    return buildSessionResponse(request, local.status, local.body);
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
      signal: AbortSignal.timeout(hasExplicitUrl ? 10_000 : 1_500),
    });
  } catch {
    if (!hasExplicitUrl) {
      const local = handleLocalBackendRequest({
        method: "GET",
        path: "auth/me",
        authorization,
      });
      return buildSessionResponse(request, local.status, local.body);
    }
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        verified: false,
        error: "ไม่สามารถเชื่อมต่อบริการ ZYRQUEN API เพื่อยืนยันเซสชันได้",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const body = ((await upstream.json().catch(() => null)) ?? {}) as Record<string, unknown>;
  return buildSessionResponse(request, upstream.status, body);
}
