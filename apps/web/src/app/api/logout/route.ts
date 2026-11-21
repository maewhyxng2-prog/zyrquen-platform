import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";
import { revokeMockSession, shouldUseMockBackend } from "@/lib/mock-backend";

function clearCookies(request: NextRequest, response: NextResponse) {
  const expired = buildSessionCookieOptions(request, 0);
  response.cookies.set(ACCESS_COOKIE, "", expired);
  response.cookies.set(EMAIL_COOKIE, "", expired);
}

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;

  if (!accessToken) {
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  const configuredUrl = process.env.ZYRQUEN_API_BASE_URL;
  const baseUrl = resolveApiBaseUrl(configuredUrl, process.env.NODE_ENV);
  const hasExplicitUrl = Boolean(configuredUrl?.trim());
  const authorization = `Bearer ${accessToken}`;

  if (await shouldUseMockBackend(baseUrl, hasExplicitUrl)) {
    revokeMockSession(authorization);
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  if (!baseUrl) {
    const response = NextResponse.json(
      {
        authenticated: false,
        revoked: false,
        detail:
          "ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ค่า ZYRQUEN_API_BASE_URL ไม่ถูกต้อง จึงไม่สามารถเพิกถอน Token ฝั่ง Backend ได้",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${baseUrl}/auth/logout`, {
      method: "POST",
      headers: {
        Authorization: authorization,
        Accept: "application/json",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(hasExplicitUrl ? 10_000 : 1_500),
    });
  } catch {
    if (!hasExplicitUrl) {
      revokeMockSession(authorization);
      const response = NextResponse.json(
        { authenticated: false, revoked: true },
        { headers: { "Cache-Control": "no-store" } },
      );
      clearCookies(request, response);
      return response;
    }
    const response = NextResponse.json(
      {
        authenticated: false,
        revoked: false,
        detail:
          "ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ไม่สามารถเชื่อมต่อ Backend เพื่อเพิกถอน Token ได้",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  if (upstream.ok || upstream.status === 401) {
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  const response = NextResponse.json(
    {
      authenticated: false,
      revoked: false,
      detail: `Backend ปฏิเสธการเพิกถอน Token (รหัสสถานะ ${upstream.status})`,
    },
    { status: 502, headers: { "Cache-Control": "no-store" } },
  );
  clearCookies(request, response);
  return response;
}
