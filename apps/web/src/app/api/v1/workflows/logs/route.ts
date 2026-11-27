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
import {
  buildWorkflowLogsQuery,
  deriveLogsFromRuns,
  isValidWorkflowRunId,
  normalizeWorkflowLogLevel,
} from "@/lib/workflow-logs";
import type { WorkflowRunItem } from "@/lib/workflow-metrics";

function clearCookiesOnUnauthorized(
  request: NextRequest,
  response: NextResponse,
  status: number,
  hadCookieToken: boolean,
): NextResponse {
  if (status === 401 && hadCookieToken) {
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
  const cookieToken = cookieStore.get(ACCESS_COOKIE)?.value;
  const authHeaderRaw = request.headers.get("authorization")?.trim() ?? "";
  const bearerToken = /^Bearer\s+(\S+)$/i.exec(authHeaderRaw)?.[1] ?? "";
  const accessToken = cookieToken || bearerToken;
  if (!accessToken) {
    return NextResponse.json(
      { detail: "Not authenticated" },
      { status: 401, headers: { "cache-control": "no-store" } },
    );
  }
  const hadCookieToken = Boolean(cookieToken);
  const authorizationHeader = `Bearer ${accessToken}`;

  const rawRunId = request.nextUrl.searchParams.get("run_id")?.trim() ?? "";
  if (rawRunId && !isValidWorkflowRunId(rawRunId)) {
    return NextResponse.json(
      { detail: "Invalid workflow run_id format" },
      { status: 400, headers: { "cache-control": "no-store" } },
    );
  }
  const rawLevel = request.nextUrl.searchParams.get("level");
  const normalizedLevel = normalizeWorkflowLogLevel(rawLevel);
  if (rawLevel !== null && rawLevel.trim() !== "" && normalizedLevel === null) {
    return NextResponse.json(
      { detail: "Invalid workflow log level" },
      { status: 400, headers: { "cache-control": "no-store" } },
    );
  }
  const rawSearch = (
    request.nextUrl.searchParams.get("search") ??
    request.nextUrl.searchParams.get("q") ??
    ""
  )
    .trim()
    .slice(0, 160);
  const activeOnly = request.nextUrl.searchParams.get("active_only") !== "false";
  const parsedLimit = Number(request.nextUrl.searchParams.get("limit") ?? 100);
  const clampedLimit = Number.isFinite(parsedLimit)
    ? Math.max(1, Math.min(500, Math.round(parsedLimit)))
    : 100;
  const sanitizedQuery = buildWorkflowLogsQuery({
    activeOnly,
    runId: rawRunId || undefined,
    limit: clampedLimit,
    level: normalizedLevel ?? undefined,
    search: rawSearch || undefined,
  });

  let useInMemory = await shouldUseInMemoryBackend(
    baseUrl,
    hasExplicitUrl,
    process.env.NODE_ENV,
  );

  if (!useInMemory) {
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: authorizationHeader,
    };

    try {
      const upstream = await fetch(`${baseUrl}/v1/workflows/logs?${sanitizedQuery}`, {
        method: "GET",
        headers,
        cache: "no-store",
        signal: AbortSignal.any([
          request.signal,
          AbortSignal.timeout(hasExplicitUrl ? 20_000 : 300),
        ]),
      });

      if (upstream.status === 404) {
        if (rawRunId) {
          const singleRunRes = await fetch(
            `${baseUrl}/v1/workflows/runs/${encodeURIComponent(rawRunId)}`,
            {
              method: "GET",
              headers,
              cache: "no-store",
              signal: AbortSignal.any([
                request.signal,
                AbortSignal.timeout(hasExplicitUrl ? 20_000 : 300),
              ]),
            },
          );
          if (singleRunRes.ok) {
            const singleRun = (await singleRunRes.json()) as WorkflowRunItem;
            const derived = deriveLogsFromRuns([singleRun], {
              activeOnly: false,
              runId: rawRunId,
              limit: clampedLimit,
              level: normalizedLevel ?? undefined,
              search: rawSearch || undefined,
            });
            return NextResponse.json(derived, {
              status: 200,
              headers: { "cache-control": "no-store" },
            });
          }
          const singleBody = await singleRunRes.text();
          const singleResp = new NextResponse(singleBody, {
            status: singleRunRes.status,
            headers: {
              "content-type":
                singleRunRes.headers.get("content-type") || "application/json",
              "cache-control": "no-store",
            },
          });
          return clearCookiesOnUnauthorized(
            request,
            singleResp,
            singleRunRes.status,
            hadCookieToken,
          );
        }

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
          const derived = deriveLogsFromRuns(runsPayload.items ?? [], {
            activeOnly,
            runId: null,
            limit: clampedLimit,
            level: normalizedLevel ?? undefined,
            search: rawSearch || undefined,
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
        return clearCookiesOnUnauthorized(request, fallbackResp, runsRes.status, hadCookieToken);
      }

      const upstreamBody = await upstream.text();
      const response = new NextResponse(upstreamBody, {
        status: upstream.status,
        headers: {
          "content-type": upstream.headers.get("content-type") || "application/json",
          "cache-control": "no-store",
        },
      });
      return clearCookiesOnUnauthorized(request, response, upstream.status, hadCookieToken);
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

  const sanitizedSearchParams = new URLSearchParams(sanitizedQuery);
  const inMemory = await handleInMemoryBackendRequest({
    method: "GET",
    path: "v1/workflows/logs",
    searchParams: sanitizedSearchParams,
    authorizationHeader,
  });
  const response = NextResponse.json(inMemory.body, {
    status: inMemory.status,
    headers: { "cache-control": "no-store" },
  });
  return clearCookiesOnUnauthorized(request, response, inMemory.status, hadCookieToken);
}
