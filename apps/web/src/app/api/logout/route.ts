import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { resolveApiBaseUrl } from "@/lib/api-config";

const ACCESS_COOKIE = "zyrquen_access";
const EMAIL_COOKIE = "zyrquen_email";

function clearCookies(response: NextResponse) {
  const expired = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  };
  response.cookies.set(ACCESS_COOKIE, "", expired);
  response.cookies.set(EMAIL_COOKIE, "", expired);
}

export async function POST() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;

  if (!accessToken) {
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(response);
    return response;
  }

  const baseUrl = resolveApiBaseUrl(
    process.env.ZYRQUEN_API_BASE_URL,
    process.env.NODE_ENV,
  );

  if (!baseUrl) {
    const response = NextResponse.json(
      {
        authenticated: false,
        revoked: false,
        detail:
          "ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ยังไม่ได้กำหนดค่า ZYRQUEN_API_BASE_URL จึงไม่สามารถเพิกถอน Token ฝั่ง Backend ได้",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(response);
    return response;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${baseUrl}/auth/logout`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "application/json",
      },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    const response = NextResponse.json(
      {
        authenticated: false,
        revoked: false,
        detail:
          "ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่ไม่สามารถเชื่อมต่อ Backend เพื่อเพิกถอน Token ได้",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(response);
    return response;
  }

  if (upstream.ok || upstream.status === 401) {
    const response = NextResponse.json(
      { authenticated: false, revoked: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearCookies(response);
    return response;
  }

  const response = NextResponse.json(
    {
      authenticated: false,
      revoked: false,
      detail: `ล้างคุกกี้ในเบราว์เซอร์แล้ว แต่บริการ Backend ตอบกลับรหัสสถานะ ${upstream.status} ระหว่างเพิกถอน Token`,
    },
    { status: 502, headers: { "Cache-Control": "no-store" } },
  );
  clearCookies(response);
  return response;
}
