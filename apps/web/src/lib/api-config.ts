const LOCAL_DEVELOPMENT_API = "http://localhost:8000";

function isLoopbackHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "::1" ||
    host === "0.0.0.0" ||
    host.startsWith("127.")
  );
}

export function resolveApiBaseUrl(
  configuredUrl: string | undefined,
  nodeEnvironment: string | undefined,
): string | null {
  const isProduction = nodeEnvironment === "production";
  const value = configuredUrl?.trim();

  if (!value) {
    return isProduction ? null : LOCAL_DEVELOPMENT_API;
  }

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (isProduction && isLoopbackHostname(url.hostname)) return null;
    return url.toString().replace(/\/+$/, "");
  } catch {
    return null;
  }
}
