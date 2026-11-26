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
  const hasExplicitUrl = hasExplicitExternalApiUrl(configuredUrl);
  const authorization = `Bearer ${accessToken}`;

  const isProduction = process.env.NODE_ENV === "production";
  if (!baseUrl) {
    const response = NextResponse.json(
      {
        authenticated: false,
        revoked: false,
        detail: hasExplicitUrl
          ? "ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ค่า ZYRQUEN_API_BASE_URL ไม่ถูกต้อง จึงไม่สามารถเพิกถอน Token ฝั่ง Backend ได้"
          : "BLOCKED: ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ยังไม่ได้กำหนด ZYRQUEN_API_BASE_URL ในโหมด Production",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(request, response);
    return response;
  }

  if (
    await shouldUseInMemoryBackend(baseUrl, hasExplicitUrl, process.env.NODE_ENV)
  ) {
    await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/logout",
      authorizationHeader: authorization,
    });
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
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
      signal: AbortSignal.timeout(hasExplicitUrl ? 10_000 : 300),
    });
  } catch {
    if (!isProduction && !hasExplicitUrl) {
      await handleInMemoryBackendRequest({
        method: "POST",
        path: "auth/logout",
        authorizationHeader: authorization,
      });
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
          "BLOCKED: ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ไม่สามารถเชื่อมต่อ Backend เพื่อเพิกถอน Token ได้",
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
