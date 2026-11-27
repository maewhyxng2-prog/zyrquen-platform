import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  hasExplicitExternalApiUrl,
  resolveApiBaseUrl,
} from "@/lib/api-config";
import { isAllowedBackendRoute } from "@/lib/backend-routes";
import {
  handleInMemoryBackendRequest,
  shouldUseInMemoryBackend,
} from "@/lib/in-memory-backend";
import {
  ACCESS_COOKIE,
  EMAIL_COOKIE,
  buildSessionCookieOptions,
} from "@/lib/cookies";
type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function isSameOriginRequest(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  if (origin === request.nextUrl.origin) return true;
  const host =
    request.headers.get("x-forwarded-host")?.split(",")[0]?.trim() ||
    request.headers.get("host")?.trim();
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ||
    request.nextUrl.protocol.replace(/:$/, "");
  return Boolean(host && proto && origin === `${proto}://${host}`);
}

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

function resolveClientOrigin(request: NextRequest): string {
  const host =
    request.headers.get("x-forwarded-host")?.split(",")[0]?.trim() ||
    request.headers.get("host")?.trim();
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ||
    request.nextUrl.protocol.replace(/:$/, "");
  if (host && proto) {
    return `${proto}://${host}`;
  }
  return request.nextUrl.origin;
}

function respondFromOAuthCallback(
  request: NextRequest,
  provider: string,
  status: number,
  payload: Record<string, unknown>,
  contentType: string | null,
): NextResponse {
  const clientOrigin = resolveClientOrigin(request);
  const accept = (request.headers.get("accept") || "").toLowerCase();
  const prefersJson =
    accept.includes("application/json") && !accept.includes("text/html");

  const accessToken =
    typeof payload.access_token === "string" && payload.access_token
      ? payload.access_token
      : null;
  const intent = payload.intent === "link" ? "link" : "login";
  const userObj =
    payload.user && typeof payload.user === "object"
      ? (payload.user as Record<string, unknown>)
      : null;
  const rawEmail =
    typeof payload.email === "string"
      ? payload.email
      : typeof userObj?.email === "string"
        ? userObj.email
        : null;
  const normalizedEmail = rawEmail ? rawEmail.trim().toLowerCase() : null;

  const isSuccess = status >= 200 && status < 300;
  let response: NextResponse;

  if (!prefersJson) {
    if (isSuccess) {
      const targetPath =
        intent === "link"
          ? `/settings?oauth_linked=${encodeURIComponent(provider)}`
          : "/workspace";
      response = NextResponse.redirect(new URL(targetPath, clientOrigin), 302);
    } else {
      const errorMessage =
        (typeof payload.detail === "string" && payload.detail.trim()) ||
        (typeof payload.error === "string" && payload.error.trim()) ||
        `การเข้าสู่ระบบด้วย ${provider === "github" ? "GitHub" : "Google"} ไม่สำเร็จ`;
      const targetPath =
        intent === "link"
          ? `/settings?oauth_error=${encodeURIComponent(errorMessage)}`
          : `/login?oauth_error=${encodeURIComponent(errorMessage)}`;
      response = NextResponse.redirect(new URL(targetPath, clientOrigin), 302);
    }
  } else {
    response = NextResponse.json(payload, {
      status,
      headers: {
        "cache-control": "no-store",
        ...(contentType ? { "content-type": contentType } : {}),
      },
    });
  }

  if (isSuccess && intent === "login" && accessToken) {
    const cookieOpts = buildSessionCookieOptions(request);
    response.cookies.set(ACCESS_COOKIE, accessToken, cookieOpts);
    if (normalizedEmail) {
      response.cookies.set(EMAIL_COOKIE, normalizedEmail, cookieOpts);
    }
  }
  response.headers.set("cache-control", "no-store");
  return response;
}

function buildInMemoryHttpResponse(
  request: NextRequest,
  path: string,
  method: string,
  accessToken: string | undefined,
  body: string | undefined,
  isInferenceStream: boolean,
  inMemory: Awaited<ReturnType<typeof handleInMemoryBackendRequest>>,
): NextResponse {
  if (path === "auth/login" && inMemory.status >= 200 && inMemory.status < 300) {
    return respondFromLogin(
      request,
      (inMemory.body ?? {}) as { access_token?: unknown },
      body,
    );
  }

  const oauthCbMatch = path.match(/^auth\/oauth\/(google|github)\/callback$/i);
  if (oauthCbMatch && method === "GET") {
    return respondFromOAuthCallback(
      request,
      oauthCbMatch[1].toLowerCase(),
      inMemory.status,
      (inMemory.body && typeof inMemory.body === "object"
        ? inMemory.body
        : {}) as Record<string, unknown>,
      "application/json",
    );
  }

  if (inMemory.stream) {
    const headers = new Headers(inMemory.headers);
    headers.set("cache-control", "no-store");
    if (isInferenceStream) {
      headers.set("x-accel-buffering", "no");
    }
    return new NextResponse(inMemory.stream, {
      status: inMemory.status,
      headers,
    });
  }

  const inMemHeaders = new Headers(inMemory.headers);
  inMemHeaders.set("cache-control", "no-store");
  const response =
    typeof inMemory.body === "string"
      ? new NextResponse(inMemory.body, {
          status: inMemory.status,
          headers: inMemHeaders,
        })
      : NextResponse.json(inMemory.body, {
          status: inMemory.status,
          headers: inMemHeaders,
        });
  if (
    inMemory.status === 401 &&
    accessToken &&
    path !== "auth/login" &&
    path !== "auth/register" &&
    method !== "OPTIONS"
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
  const hasExplicitUrl = hasExplicitExternalApiUrl(configuredUrl);
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
    !isSameOriginRequest(request)
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
  const isProduction = process.env.NODE_ENV === "production";
  if (!baseUrl) {
    return NextResponse.json(
      {
        status: "blocked",
        code: hasExplicitUrl ? "BACKEND_INVALID_URL" : "BACKEND_NOT_CONFIGURED",
        detail: hasExplicitUrl
          ? "บริการ ZYRQUEN API ยังไม่ได้กำหนดค่าปลายทางที่ใช้งานได้"
          : "BLOCKED: บริการ ZYRQUEN API ยังไม่ได้กำหนดค่า ZYRQUEN_API_BASE_URL ในโหมด Production",
      },
      { status: 503 },
    );
  }

  let useInMemory = await shouldUseInMemoryBackend(
    baseUrl,
    hasExplicitUrl,
    process.env.NODE_ENV,
  );

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

    let identityStatus = 200;
    let identityPayload: { id?: unknown; is_active?: unknown } | null = null;
    let identityErrorText = "";
    let identityContentType = "application/json";

    if (!useInMemory && baseUrl) {
      try {
        const identityResponse = await fetch(`${baseUrl}/auth/me`, {
          method: "GET",
          headers: {
            Authorization: authorizationHeader,
            Accept: "application/json",
          },
          cache: "no-store",
          signal: AbortSignal.any([
            request.signal,
            AbortSignal.timeout(hasExplicitUrl ? 10_000 : 300),
          ]),
        });
        identityStatus = identityResponse.status;
        identityContentType =
          identityResponse.headers.get("content-type") ?? "application/json";
        if (identityResponse.ok) {
          identityPayload = (await identityResponse.json().catch(() => null)) as
            | { id?: unknown; is_active?: unknown }
            | null;
        } else {
          identityErrorText = await identityResponse.text();
        }
      } catch {
        if (!isProduction && !hasExplicitUrl) {
          useInMemory = true;
        } else {
          return NextResponse.json(
            {
              status: "blocked",
              code: "BACKEND_UNAVAILABLE",
              detail: "BLOCKED: ไม่สามารถยืนยันบัญชีกับ ZYRQUEN API ได้",
            },
            { status: 503 },
          );
        }
      }
    }

    if (useInMemory) {
      const identityRes = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/me",
        authorizationHeader,
      });
      identityStatus = identityRes.status;
      if (identityRes.status >= 200 && identityRes.status < 300) {
        identityPayload = identityRes.body as { id?: unknown; is_active?: unknown };
      } else {
        identityErrorText = JSON.stringify(identityRes.body ?? {});
      }
    }

    if (identityStatus < 200 || identityStatus >= 300) {
      const response = new NextResponse(identityErrorText, {
        status: identityStatus,
        headers: {
          "content-type": identityContentType,
          "cache-control": "no-store",
        },
      });
      if (identityStatus === 401 || identityStatus === 403) {
        const expired = buildSessionCookieOptions(request, 0);
        response.cookies.set(ACCESS_COOKIE, "", expired);
        response.cookies.set(EMAIL_COOKIE, "", expired);
      }
      return response;
    }

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

  let upstream: Response | null = null;
  const clientOrigin = resolveClientOrigin(request);
  const effectiveParams = new URLSearchParams(request.nextUrl.searchParams);
  if (
    /^auth\/oauth\/(google|github)\/url$/i.test(path) &&
    !effectiveParams.get("origin")
  ) {
    effectiveParams.set("origin", clientOrigin);
  }
  const searchStr = effectiveParams.toString();
  const search = searchStr ? `?${searchStr}` : "";
  const upstreamUrl = baseUrl
    ? path
      ? `${baseUrl}/${path}${search}`
      : `${baseUrl}/${search}`
    : "";
  if (!useInMemory && upstreamUrl) {
    try {
      const timeoutMs = isInferenceRequest
        ? 120_000
        : hasExplicitUrl
          ? 20_000
          : 300;
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
      if (!isProduction && !hasExplicitUrl) {
        useInMemory = true;
      } else {
        return NextResponse.json(
          {
            status: "blocked",
            code: "BACKEND_UNAVAILABLE",
            detail:
              "BLOCKED: ไม่สามารถเชื่อมต่อกับ ZYRQUEN API ที่กำหนดไว้ได้ กรุณาตรวจสอบว่าบริการ API กำลังทำงานอยู่",
          },
          { status: 503 },
        );
      }
    }
  }

  if (useInMemory) {
    const inMemory = await handleInMemoryBackendRequest({
      method,
      path,
      searchParams: effectiveParams,
      authorizationHeader: headers.get("Authorization"),
      rawBody: body,
      origin: clientOrigin,
    });
    return buildInMemoryHttpResponse(
      request,
      path,
      method,
      accessToken,
      body,
      isInferenceStream,
      inMemory,
    );
  }

  if (!upstream) {
    return NextResponse.json({ detail: "backend_not_configured" }, { status: 503 });
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

  const upstreamOAuthCbMatch = path.match(
    /^auth\/oauth\/(google|github)\/callback$/i,
  );
  if (upstreamOAuthCbMatch && method === "GET") {
    const payload = (await upstream.clone().json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    return respondFromOAuthCallback(
      request,
      upstreamOAuthCbMatch[1].toLowerCase(),
      upstream.status,
      payload,
      upstream.headers.get("content-type"),
    );
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) responseHeaders.set("content-type", contentType);
  const contentDisposition = upstream.headers.get("content-disposition");
  if (contentDisposition) responseHeaders.set("content-disposition", contentDisposition);
  const contentTypeOptions = upstream.headers.get("x-content-type-options");
  if (contentTypeOptions) responseHeaders.set("x-content-type-options", contentTypeOptions);
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
