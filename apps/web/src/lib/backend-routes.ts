const routes: Record<string, ReadonlySet<string>> = {
  GET: new Set(["", "health", "v1/native-ai/health", "auth/me", "users/me", "users/me/usage", "users/me/quota", "admin/overview"]),
  POST: new Set([
    "auth/login",
    "auth/register",
    "auth/logout",
    "v1/native-ai/infer",
    "v1/native-ai/infer/stream",
  ]),
  PATCH: new Set(["users/me"]),
};

export function isAllowedBackendRoute(method: string, path: string): boolean {
  const normalizedMethod = method.toUpperCase();
  if (routes[normalizedMethod]?.has(path)) return true;
  const id = "[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
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
  if (new RegExp(`^users/me/api-keys/${id}/usage$`, "i").test(path)) {
    return normalizedMethod === "GET";
  }
  if (path === "admin/users" || path === "admin/audit-logs") {
    return normalizedMethod === "GET";
  }
  return (
    normalizedMethod === "POST" &&
    new RegExp(`^conversations/${id}/messages$`, "i").test(path)
  );
}
