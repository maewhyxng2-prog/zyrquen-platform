import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  hasExplicitExternalApiUrl,
  resolveApiBaseUrl,
} from "@/lib/api-config";
import { ACCESS_COOKIE, EMAIL_COOKIE, buildSessionCookieOptions } from "@/lib/cookies";
import {
  handleInMemoryBackendRequest,
  shouldUseInMemoryBackend,
} from "@/lib/in-memory-backend";
import { deriveLogsFromRuns } from "@/lib/workflow-logs";
import type { WorkflowRunItem } from "@/lib/workflow-metrics";

function clearCookiesOnUnauthorized(
  request: NextRequest,
  response: NextResponse,
  status: number,
  hadToken: boolean,
): NextResponse {
  if (status === 401 && hadToken) {
    const expired = buildSessionCookieOptions(request, 0);
    response.cookies.set(ACCESS_COOKIE, "", expired);
    response.cookies.set(EMAIL_COOKIE, "", expired);
  }
  return response;
}

export async function GET(request: NextRequest) {
  const configuredUrl = process.env.ZYRQUEN_API_BASE_URL;
  const baseUrl = resolveApiBaseUrl(configuredUrl, process.env.NODE_ENV);
  const hasExplicitUrl = hasExplicitExternalApiUrl(configuredUrl);
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
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_COOKIE)?.value;
  const authorizationHeader = accessToken ? `Bearer ${accessToken}` : null;

  let useInMemory = await shouldUseInMemoryBackend(
    baseUrl,
    hasExplicitUrl,
    process.env.NODE_ENV,
  );

  if (!useInMemory) {
    const search = request.nextUrl.search;
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (authorizationHeader) {
      headers.Authorization = authorizationHeader;
    }

    try {
      const upstream = await fetch(`${baseUrl}/v1/workflows/logs${search}`, {
        method: "GET",
        headers,
        cache: "no-store",
        signal: AbortSignal.any([
          request.signal,
          AbortSignal.timeout(hasExplicitUrl ? 20_000 : 300),
        ]),
      });

      if (upstream.status === 404) {
        const runsRes = await fetch(`${baseUrl}/v1/workflows/runs?limit=100`, {
          method: "GET",
          headers,
          cache: "no-store",
          signal: AbortSignal.any([
            request.signal,
            AbortSignal.timeout(hasExplicitUrl ? 20_000 : 300),
          ]),
        });
        if (runsRes.ok) {
          const runsPayload = (await runsRes.json()) as { items?: WorkflowRunItem[] };
          const activeOnly = request.nextUrl.searchParams.get("active_only") !== "false";
          const runId = request.nextUrl.searchParams.get("run_id");
          const rawLimit = Number(request.nextUrl.searchParams.get("limit") ?? 100);
          const derived = deriveLogsFromRuns(runsPayload.items ?? [], {
            activeOnly,
            runId,
            limit: Number.isFinite(rawLimit) ? rawLimit : 100,
          });
          return NextResponse.json(derived, {
            status: 200,
            headers: { "cache-control": "no-store" },
          });
        }
        const fallbackBody = await runsRes.text();
        const fallbackResp = new NextResponse(fallbackBody, {
          status: runsRes.status,
          headers: {
            "content-type": runsRes.headers.get("content-type") || "application/json",
            "cache-control": "no-store",
          },
        });
        return clearCookiesOnUnauthorized(request, fallbackResp, runsRes.status, Boolean(accessToken));
      }

      const upstreamBody = await upstream.text();
      const response = new NextResponse(upstreamBody, {
        status: upstream.status,
        headers: {
          "content-type": upstream.headers.get("content-type") || "application/json",
          "cache-control": "no-store",
        },
      });
      return clearCookiesOnUnauthorized(request, response, upstream.status, Boolean(accessToken));
    } catch {
      if (!isProduction && !hasExplicitUrl) {
        useInMemory = true;
      } else {
        return NextResponse.json(
          {
            status: "blocked",
            code: "BACKEND_UNAVAILABLE",
            detail:
              "BLOCKED: ไม่สามารถเชื่อมต่อกับ ZYRQUEN API เพื่อดึง Execution Logs ได้",
          },
          { status: 503, headers: { "cache-control": "no-store" } },
        );
      }
    }
  }

  const inMemory = await handleInMemoryBackendRequest({
    method: "GET",
    path: "v1/workflows/logs",
    searchParams: request.nextUrl.searchParams,
    authorizationHeader,
  });
  const response = NextResponse.json(inMemory.body, {
    status: inMemory.status,
    headers: { "cache-control": "no-store" },
  });
  return clearCookiesOnUnauthorized(request, response, inMemory.status, Boolean(accessToken));
}
