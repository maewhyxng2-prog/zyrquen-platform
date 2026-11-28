const routes: Record<string, ReadonlySet<string>> = {
  GET: new Set([
    "",
    "health",
    "v1/native-ai/health",
    "auth/me",
    "auth/providers",
    "auth/identities",
    "auth/oauth/google/url",
    "auth/oauth/github/url",
    "auth/oauth/google/callback",
    "auth/oauth/github/callback",
    "users/me",
    "users/me/usage",
    "users/me/quota",
    "admin/overview",
    "v1/workflows/definitions",
    "v1/workflows/services/status",
    "v1/workflows/runs",
    "v1/workflows/approvals",
    "v1/workflows/audit-logs",
    "v1/workflows/logs",
    "v1/models/registry",
    "v1/models/registry/compare",
    "v1/v10/closure-audit",
    "v1/datasets/status",
    "training/readiness",
    "training/runs",
  ]),
  POST: new Set([
    "auth/login",
    "auth/register",
    "auth/logout",
    "auth/verify-email",
    "auth/verification/resend",
    "users/me/api-keys/bulk-revoke",
    "v1/native-ai/infer",
    "v1/native-ai/infer/stream",
    "v1/workflows/runs",
    "v1/models/registry/rollback",
    "training/runs",
  ]),
  PATCH: new Set(["users/me"]),
  DELETE: new Set([
    "auth/identities/google",
    "auth/identities/github",
  ]),
};

export function isAllowedBackendRoute(method: string, path: string): boolean {
  if (path.includes("..")) return false;
  const normalizedMethod = method.toUpperCase();
  if (routes[normalizedMethod]?.has(path)) return true;
  const id = "[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
  const version = "[A-Za-z0-9][A-Za-z0-9._-]{0,63}";
  if (path === "conversations") {
    return normalizedMethod === "GET" || normalizedMethod === "POST";
  }
  if (new RegExp(`^conversations/${id}$`, "i").test(path)) {
    return ["GET", "PATCH", "DELETE"].includes(normalizedMethod);
  }
  if (path === "users/me/api-keys") {
    return ["GET", "POST"].includes(normalizedMethod);
  }
  if (new RegExp(`^users/me/api-keys/${id}$`, "i").test(path)) {
    return normalizedMethod === "DELETE";
  }
  if (new RegExp(`^users/me/api-keys/${id}/auto-rotate$`, "i").test(path)) {
    return normalizedMethod === "PATCH";
  }
  if (new RegExp(`^users/me/api-keys/${id}/rotate$`, "i").test(path)) {
    return normalizedMethod === "POST";
  }
  if (new RegExp(`^users/me/api-keys/${id}/usage$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (path === "admin/users" || path === "admin/audit-logs" || path === "admin/oauth/config") {
    return normalizedMethod === "GET";
  }
  if (/^admin\/oauth\/config\/(google|github)$/i.test(path)) {
    return normalizedMethod === "PUT" || normalizedMethod === "DELETE";
  }
  if (new RegExp(`^v1/workflows/runs/${id}$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (new RegExp(`^v1/workflows/runs/${id}/cancel$`, "i").test(path)) {
    return normalizedMethod === "POST";
  }
  if (new RegExp(`^v1/workflows/approvals/${id}/decision$`, "i").test(path)) {
    return normalizedMethod === "POST";
  }
  if (new RegExp(`^v1/models/registry/${version}/lineage$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (new RegExp(`^v1/models/registry/${version}/verify$`, "i").test(path)) {
    return normalizedMethod === "GET" || normalizedMethod === "POST";
  }
  if (new RegExp(`^v1/models/registry/${version}/artifacts/(logs|manifest)$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (new RegExp(`^v1/models/registry/${version}/stage$`, "i").test(path)) {
    return normalizedMethod === "POST";
  }
  if (new RegExp(`^v1/models/registry/${version}/promote$`, "i").test(path)) {
    return normalizedMethod === "POST";
  }
  if (new RegExp(`^v1/datasets/${version}/status$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (new RegExp(`^training/runs/${id}$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (new RegExp(`^training/runs/${id}/telemetry$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  return (
    normalizedMethod === "POST" &&
    new RegExp(`^conversations/${id}/messages$`, "i").test(path)
  );
}
