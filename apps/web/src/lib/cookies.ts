import type { NextRequest } from "next/server";

export const ACCESS_COOKIE = "zyrquen_access";
export const EMAIL_COOKIE = "zyrquen_email";
export const SESSION_SECONDS = 30 * 60;

function isHttpsRequest(request?: NextRequest): boolean {
  if (request) {
    const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim().toLowerCase();
    if (forwardedProto) {
      return forwardedProto === "https";
    }
    if (request.nextUrl.protocol === "https:") {
      return true;
    }
    const hostname = request.nextUrl.hostname.toLowerCase();
    if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0") {
      return false;
    }
  }
  return process.env.NODE_ENV === "production";
}

export function buildSessionCookieOptions(request?: NextRequest, maxAge = SESSION_SECONDS) {
  const https = isHttpsRequest(request);
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: https,
    path: "/",
    maxAge,
  };
}
