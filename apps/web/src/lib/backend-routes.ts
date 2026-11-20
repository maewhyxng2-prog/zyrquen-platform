const routes: Record<string, ReadonlySet<string>> = {
  GET: new Set(["", "health", "v1/native-ai/health", "auth/me"]),
  POST: new Set(["auth/login", "auth/register", "auth/logout", "v1/native-ai/infer"]),
};

export function isAllowedBackendRoute(method: string, path: string): boolean {
  return routes[method.toUpperCase()]?.has(path) ?? false;
}
