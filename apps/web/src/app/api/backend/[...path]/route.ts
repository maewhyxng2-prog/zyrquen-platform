import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";
import { isAllowedBackendRoute } from "@/lib/backend-routes";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

async function readBoundedBody(
  request: NextRequest,
  maxBytes: number,
): Promise<string | null> {
  const reader = request.body?.getReader();
  if (!reader) return "";
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalBytes += value.byteLength;
    if (totalBytes > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(body);
}

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
  const isInferenceStream = path === "v1/native-ai/infer/stream";
  const isInferenceRequest =
    path === "v1/native-ai/infer" || isInferenceStream;
  const isUserDataRequest =
    path === "users/me" || path.startsWith("users/me/");
  const isConversationRequest =
    path === "conversations" || path.startsWith("conversations/");
  const requiresExpectedIdentity =
    isInferenceRequest || isUserDataRequest || isConversationRequest;
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  if (
    accessToken &&
    !["GET", "HEAD", "OPTIONS"].includes(method) &&
    request.headers.get("origin") !== request.nextUrl.origin
  ) {
    return NextResponse.json(
      { detail: "คำขอไม่ผ่านการตรวจสอบแหล่งที่มา" },
      { status: 403 },
    );
  }

  let body: string | undefined;
  const headers = new Headers({
    Accept: isInferenceStream ? "text/event-stream" : "application/json",
  });
  if (["POST", "PATCH", "PUT"].includes(method)) {
    const declaredLength = Number(request.headers.get("content-length") ?? 0);
    if (declaredLength > 65_536) {
      return NextResponse.json(
        { detail: "คำขอมีขนาดใหญ่เกินขีดจำกัด" },
        { status: 413 },
      );
    }
    body = await readBoundedBody(request, 65_536) ?? undefined;
    if (body === undefined) {
      return NextResponse.json(
        { detail: "คำขอมีขนาดใหญ่เกินขีดจำกัด" },
        { status: 413 },
      );
    }
    headers.set("Content-Type", request.headers.get("content-type") || "application/json");
  }

  if (accessToken && path !== "auth/login" && path !== "auth/register") {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (!baseUrl) {
    return NextResponse.json(
      {
        detail:
          "บริการ ZYRQUEN API ยังไม่ได้กำหนดค่าปลายทางที่ใช้งานได้",
      },
      { status: 503 },
    );
  }

  if (requiresExpectedIdentity) {
    const expectedUserId = request.headers
      .get("x-zyrquen-expected-user-id")
      ?.trim();
    const authorizationHeader = headers.get("Authorization");
    if (!expectedUserId || !authorizationHeader) {
      return NextResponse.json(
        { detail: "ยืนยันบัญชีผู้ใช้ก่อนดำเนินการ" },
        { status: 401 },
      );
    }

    let identityResponse: Response;
    try {
      identityResponse = await fetch(`${baseUrl}/auth/me`, {
        method: "GET",
        headers: {
          Authorization: authorizationHeader,
          Accept: "application/json",
        },
        cache: "no-store",
        signal: AbortSignal.any([
          request.signal,
          AbortSignal.timeout(hasExplicitUrl ? 10_000 : 1_500),
        ]),
      });
    } catch {
      return NextResponse.json(
        { detail: "ไม่สามารถยืนยันบัญชีกับ ZYRQUEN API ได้" },
        { status: 503 },
      );
    }

    if (!identityResponse.ok) {
      const response = new NextResponse(await identityResponse.text(), {
        status: identityResponse.status,
        headers: {
          "content-type":
            identityResponse.headers.get("content-type") ?? "application/json",
          "cache-control": "no-store",
        },
      });
      if (identityResponse.status === 401 || identityResponse.status === 403) {
        const expired = buildSessionCookieOptions(request, 0);
        response.cookies.set(ACCESS_COOKIE, "", expired);
        response.cookies.set(EMAIL_COOKIE, "", expired);
      }
      return response;
    }

    const identityPayload = (await identityResponse.json().catch(() => null)) as
      | { id?: unknown; is_active?: unknown }
      | null;
    if (
      typeof identityPayload?.id !== "string" ||
      identityPayload.is_active !== true
    ) {
      return NextResponse.json(
        { detail: "ข้อมูลบัญชีจาก ZYRQUEN API ไม่สมบูรณ์" },
        { status: 502 },
      );
    }
    if (identityPayload.id !== expectedUserId) {
      return NextResponse.json(
        {
          code: "session_mismatch",
          detail: "บัญชีผู้ใช้เปลี่ยนระหว่างส่งข้อความ กรุณาลองอีกครั้ง",
        },
        { status: 409 },
      );
    }
  }

  const upstreamUrl = path ? `${baseUrl}/${path}` : `${baseUrl}/`;

  let upstream: Response;
  try {
    const timeoutMs = isInferenceRequest
      ? 120_000
      : hasExplicitUrl
        ? 20_000
        : 1_500;
    upstream = await fetch(upstreamUrl, {
      method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.any([
        request.signal,
        AbortSignal.timeout(timeoutMs),
      ]),
    });
  } catch {
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
  if (isInferenceStream) {
    responseHeaders.set("x-accel-buffering", "no");
  }

  const response = new NextResponse(upstream.body, {
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
export const PATCH = proxy;
export const DELETE = proxy;
