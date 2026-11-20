import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";
import { isAllowedBackendRoute } from "@/lib/backend-routes";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";
import { handleLocalBackendRequest } from "@/lib/local-backend";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function respondFromLogin(
  request: NextRequest,
  result: { access_token?: unknown },
  rawBody: string | undefined,
): NextResponse {
  let credentials: { email?: unknown };
  try {
    credentials = JSON.parse(rawBody || "{}") as { email?: unknown };
  } catch {
    return NextResponse.json(
      { detail: "บริการยืนยันตัวตนส่งข้อมูลตอบกลับไม่ถูกต้อง" },
      { status: 502 },
    );
  }

  if (typeof result.access_token !== "string" || !result.access_token) {
    return NextResponse.json(
      { detail: "บริการยืนยันตัวตนไม่ได้ส่ง Access Token กลับมา" },
      { status: 502 },
    );
  }

  const normalizedEmail =
    typeof credentials.email === "string"
      ? credentials.email.trim().toLowerCase()
      : null;
  const response = NextResponse.json({
    authenticated: true,
    email: normalizedEmail,
  });
  const cookieOpts = buildSessionCookieOptions(request);
  response.cookies.set(ACCESS_COOKIE, result.access_token, cookieOpts);
  if (normalizedEmail) {
    response.cookies.set(EMAIL_COOKIE, normalizedEmail, cookieOpts);
  }
  return response;
}

function respondFromLocalFallback(
  request: NextRequest,
  method: string,
  path: string,
  authorization: string | null,
  rawBody: string | undefined,
  accessToken: string | undefined,
): NextResponse {
  const local = handleLocalBackendRequest({
    method,
    path,
    authorization,
    rawBody,
  });

  if (path === "auth/login" && local.status >= 200 && local.status < 300) {
    return respondFromLogin(request, local.body, rawBody);
  }

  const response = NextResponse.json(local.body, {
    status: local.status,
    headers: { "cache-control": "no-store" },
  });

  if (
    local.status === 401 &&
    accessToken &&
    path !== "auth/login" &&
    path !== "auth/register"
  ) {
    const expired = buildSessionCookieOptions(request, 0);
    response.cookies.set(ACCESS_COOKIE, "", expired);
    response.cookies.set(EMAIL_COOKIE, "", expired);
  }

  return response;
}

async function proxy(request: NextRequest, context: RouteContext) {
  const { path: segments } = await context.params;
  const path = segments.join("/");
  const method = request.method.toUpperCase();

  if (!isAllowedBackendRoute(method, path)) {
    return NextResponse.json({ detail: "ไม่รองรับเส้นทาง API ที่ร้องขอ" }, { status: 404 });
  }

  const configuredUrl = process.env.ZYRQUEN_API_BASE_URL;
  const baseUrl = resolveApiBaseUrl(configuredUrl, process.env.NODE_ENV);
  const hasExplicitUrl = Boolean(configuredUrl?.trim());

  let body: string | undefined;
  const headers = new Headers({ Accept: "application/json" });
  if (method === "POST") {
    body = await request.text();
    headers.set("Content-Type", request.headers.get("content-type") || "application/json");
  }

  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  if (accessToken && path !== "auth/login" && path !== "auth/register") {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const authorization = headers.get("Authorization");

  if (!baseUrl) {
    if (hasExplicitUrl) {
      return NextResponse.json(
        {
          detail:
            "ค่า ZYRQUEN_API_BASE_URL ที่กำหนดไว้ไม่ถูกต้องสำหรับสภาพแวดล้อมนี้ กรุณาตรวจสอบการตั้งค่าฝั่งเซิร์ฟเวอร์",
        },
        { status: 503 },
      );
    }
    return respondFromLocalFallback(
      request,
      method,
      path,
      authorization,
      body,
      accessToken,
    );
  }

  const upstreamUrl = path ? `${baseUrl}/${path}` : `${baseUrl}/`;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(hasExplicitUrl ? 20_000 : 1_500),
    });
  } catch {
    if (!hasExplicitUrl) {
      return respondFromLocalFallback(
        request,
        method,
        path,
        authorization,
        body,
        accessToken,
      );
    }
    return NextResponse.json(
      {
        detail:
          "ไม่สามารถเชื่อมต่อกับ ZYRQUEN API ที่กำหนดไว้ได้ กรุณาตรวจสอบว่าบริการ API กำลังทำงานอยู่",
      },
      { status: 503 },
    );
  }

  if (path === "auth/login" && upstream.ok) {
    let result: { access_token?: unknown };
    try {
      result = (await upstream.clone().json()) as { access_token?: unknown };
    } catch {
      return NextResponse.json(
        { detail: "บริการยืนยันตัวตนส่งข้อมูลตอบกลับไม่ถูกต้อง" },
        { status: 502 },
      );
    }
    return respondFromLogin(request, result, body);
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) responseHeaders.set("content-type", contentType);
  responseHeaders.set("cache-control", "no-store");

  const response = new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });

  if (
    upstream.status === 401 &&
    accessToken &&
    path !== "auth/login" &&
    path !== "auth/register"
  ) {
    const expired = buildSessionCookieOptions(request, 0);
    response.cookies.set(ACCESS_COOKIE, "", expired);
    response.cookies.set(EMAIL_COOKIE, "", expired);
  }

  return response;
}

export const GET = proxy;
export const POST = proxy;
