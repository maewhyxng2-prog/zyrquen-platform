const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]);
const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

function json(status, payload, correlationId) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-correlation-id": correlationId,
    },
  });
}

function resolveOrigin(value) {
  if (typeof value !== "string" || value.trim() === "") return null;

  try {
    const origin = new URL(value);
    if (
      origin.protocol !== "https:" ||
      !origin.hostname ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    ) {
      return null;
    }
    return origin;
  } catch {
    return null;
  }
}

function correlationIdFrom(request) {
  const supplied = request.headers.get("x-correlation-id") || "";
  if (/^[A-Za-z0-9._:-]{1,128}$/.test(supplied)) return supplied;
  return crypto.randomUUID();
}

export default {
  async fetch(request, env) {
    const correlationId = correlationIdFrom(request);
    const incoming = new URL(request.url);

    if (incoming.pathname === "/__gateway/health" && request.method === "GET") {
      return json(200, {
        service: "zyrquen-api-gateway",
        status: "healthy",
        upstream_configured: Boolean(resolveOrigin(env.ZYRQUEN_API_ORIGIN)),
      }, correlationId);
    }

    if (!ALLOWED_METHODS.has(request.method)) {
      return json(405, { error: "method_not_allowed" }, correlationId);
    }

    const origin = resolveOrigin(env.ZYRQUEN_API_ORIGIN);
    if (!origin) {
      return json(503, {
        error: "gateway_not_configured",
        message: "The HTTPS API origin has not been configured.",
      }, correlationId);
    }

    const target = new URL(incoming.pathname + incoming.search, origin);
    const headers = new Headers(request.headers);
    for (const name of HOP_BY_HOP_HEADERS) headers.delete(name);
    headers.delete("host");
    headers.set("x-correlation-id", correlationId);
    headers.set("x-forwarded-proto", "https");
    headers.set("x-forwarded-host", incoming.host);

    try {
      const upstreamRequest = new Request(target, {
        method: request.method,
        headers,
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
        redirect: "manual",
      });
      const upstream = await fetch(upstreamRequest, { redirect: "manual" });
      const responseHeaders = new Headers(upstream.headers);
      for (const name of HOP_BY_HOP_HEADERS) responseHeaders.delete(name);
      responseHeaders.set("cache-control", "no-store");
      responseHeaders.set("x-content-type-options", "nosniff");
      responseHeaders.set("x-correlation-id", correlationId);

      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: responseHeaders,
      });
    } catch {
      return json(502, {
        error: "upstream_unavailable",
        message: "The configured ZYRQUEN API origin could not be reached.",
      }, correlationId);
    }
  },
};
