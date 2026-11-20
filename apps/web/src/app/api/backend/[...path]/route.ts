import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";
import { isAllowedBackendRoute } from "@/lib/backend-routes";

const ACCESS_COOKIE = "zyrquen_access";
const EMAIL_COOKIE = "zyrquen_email";
const SESSION_SECONDS = 30 * 60;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_SECONDS,
  };
}

async function proxy(request: NextRequest, context: RouteContext) {
  const { path: segments } = await context.params;
  const path = segments.join("/");
  const method = request.method.toUpperCase();

  if (!isAllowedBackendRoute(method, path)) {
    return NextResponse.json({ detail: "ไม่รองรับเส้นทาง API ที่ร้องขอ" }, { status: 404 });
  }

  const baseUrl = resolveApiBaseUrl(
    process.env.ZYRQUEN_API_BASE_URL,
    process.env.NODE_ENV,
  );
  if (!baseUrl) {
    return NextResponse.json(
      {
        detail:
          "ยังไม่ได้กำหนดค่า ZYRQUEN_API_BASE_URL สำหรับสภาพแวดล้อมนี้ กรุณาตั้งค่าการเชื่อมต่อ API ฝั่งเซิร์ฟเวอร์",
      },
      { status: 503 },
    );
  }
  const upstreamUrl = path ? `${baseUrl}/${path}` : `${baseUrl}/`;
  const headers = new Headers({ Accept: "application/json" });
  let body: string | undefined;

  if (method === "POST") {
    body = await request.text();
    headers.set("Content-Type", request.headers.get("content-type") || "application/json");
  }

  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  if (accessToken && path !== "auth/login" && path !== "auth/register") {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
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
    let credentials: { email?: unknown };
    try {
      result = await upstream.clone().json();
      credentials = JSON.parse(body || "{}") as { email?: unknown };
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

    const response = NextResponse.json({
      authenticated: true,
      email:
        typeof credentials.email === "string"
          ? credentials.email.trim().toLowerCase()
          : null,
    });
    response.cookies.set(ACCESS_COOKIE, result.access_token, cookieOptions());
    if (typeof credentials.email === "string") {
      response.cookies.set(
        EMAIL_COOKIE,
        credentials.email.trim().toLowerCase(),
        cookieOptions(),
      );
    }
    return response;
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) responseHeaders.set("content-type", contentType);
  responseHeaders.set("cache-control", "no-store");

  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
