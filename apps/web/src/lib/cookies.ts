import type { NextRequest } from "next/server";

export const ACCESS_COOKIE = "zyrquen_access";
export const EMAIL_COOKIE = "zyrquen_email";
export const SESSION_SECONDS = 30 * 60;

function isHttpsRequest(request?: NextRequest): boolean {
  if (!request) {
    return process.env.NODE_ENV === "production";
  }
  const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim().toLowerCase();
  if (forwardedProto) {
    return forwardedProto === "https";
  }
  return request.nextUrl.protocol === "https:";
}

export function buildSessionCookieOptions(request?: NextRequest, maxAge = SESSION_SECONDS) {
  const https = isHttpsRequest(request);
  return {
    httpOnly: true,
    sameSite: (https ? "none" : "lax") as "none" | "lax",
    secure: https,
    path: "/",
    maxAge,
  };
}
