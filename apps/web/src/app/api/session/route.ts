import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";

const ACCESS_COOKIE = "zyrquen_access";
const EMAIL_COOKIE = "zyrquen_email";

function clearSessionCookies(response: NextResponse) {
  const expiredCookie = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  };
  response.cookies.set(ACCESS_COOKIE, "", expiredCookie);
  response.cookies.set(EMAIL_COOKIE, "", expiredCookie);
}

export async function GET() {
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
      clearSessionCookies(response);
    }
    return response;
  }

  const baseUrl = resolveApiBaseUrl(
    process.env.ZYRQUEN_API_BASE_URL,
    process.env.NODE_ENV,
  );

  if (!baseUrl) {
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        verified: false,
        error: "ยังไม่ได้กำหนดค่า ZYRQUEN_API_BASE_URL สำหรับตรวจสอบเซสชัน",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${baseUrl}/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
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

  if (upstream.status === 401 || upstream.status === 403) {
    const body = (await upstream.json().catch(() => null)) as {
      detail?: unknown;
      error?: unknown;
    } | null;
    const rawDetail =
      typeof body?.detail === "string"
        ? body.detail
        : typeof body?.error === "string"
          ? body.error
          : "";

    const response = NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        verified: true,
        expired: upstream.status === 401,
        error:
          upstream.status === 403
            ? "บัญชีนี้ถูกระงับการใช้งาน"
            : rawDetail.includes("Missing Authorization header")
              ? "ปลายทางที่เชื่อมต่ออยู่ไม่ใช่บริการยืนยันตัวตนของ ZYRQUEN"
              : null,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearSessionCookies(response);
    return response;
  }

  if (!upstream.ok) {
    return NextResponse.json(
      {
        authenticated: false,
        email: null,
        userId: null,
        verified: false,
        error: `ตรวจสอบเซสชันไม่สำเร็จ (รหัสสถานะ ${upstream.status})`,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  const user = (await upstream.json().catch(() => null)) as {
    id?: unknown;
    email?: unknown;
    is_active?: unknown;
  } | null;

  if (
    !user ||
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
    clearSessionCookies(response);
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
