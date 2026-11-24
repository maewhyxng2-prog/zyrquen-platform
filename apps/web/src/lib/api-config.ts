const LOCAL_DEVELOPMENT_API = "http://localhost:8000";

const METADATA_HOSTNAMES = new Set([
  "metadata",
  "metadata.google.internal",
  "metadata.goog",
  "instance-data",
]);

function normalizeHost(hostname: string): string {
  return hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
}

function isLoopbackHostname(hostname: string): boolean {
  const host = normalizeHost(hostname);
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "::1" ||
    host === "0.0.0.0" ||
    host.startsWith("127.")
  );
}

function isPrivateOrLinkLocalIp(hostname: string): boolean {
  const host = normalizeHost(hostname);
  if (host.startsWith("169.254.") || host.startsWith("10.")) return true;
  if (host.startsWith("192.168.")) return true;
  const match172 = host.match(/^172\.(\d{1,3})\./);
  if (match172) {
    const second = Number(match172[1]);
    if (second >= 16 && second <= 31) return true;
  }
  const matchCgnat = host.match(/^100\.(\d{1,3})\./);
  if (matchCgnat) {
    const second = Number(matchCgnat[1]);
    if (second >= 64 && second <= 127) return true;
  }
  if (
    host.startsWith("fe80:") ||
    host.startsWith("fc") ||
    host.startsWith("fd") ||
    host === "::"
  ) {
    return true;
  }
  return false;
}

export function isSsrfRestrictedUrl(url: URL, allowLoopback: boolean): boolean {
  if (url.username || url.password) return true;
  const host = normalizeHost(url.hostname);
  if (!host) return true;
  if (METADATA_HOSTNAMES.has(host)) return true;
  if (host.startsWith("169.254.") || host.startsWith("fe80:")) return true;
  if (!allowLoopback && isLoopbackHostname(host)) return true;
  return false;
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
    if (isSsrfRestrictedUrl(url, !isProduction)) return null;
    if (isProduction && isPrivateOrLinkLocalIp(url.hostname)) return null;
    return url.toString().replace(/\/+$/, "");
  } catch {
    return null;
  }
}

export function hasExplicitExternalApiUrl(
  configuredUrl: string | undefined,
): boolean {
  const value = configuredUrl?.trim();
  if (!value) return false;
  try {
    const url = new URL(value);
    return !isLoopbackHostname(url.hostname);
  } catch {
    return true;
  }
}

export function validateOutboundResearchUrl(rawUrl: string): {
  valid: boolean;
  reason: string;
} {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return { valid: false, reason: "empty_url" };
  }
  try {
    const url = new URL(trimmed);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return { valid: false, reason: "unsupported_protocol" };
    }
    const host = normalizeHost(url.hostname);
    if (
      !host ||
      !host.includes(".") ||
      isLoopbackHostname(host) ||
      isPrivateOrLinkLocalIp(host) ||
      METADATA_HOSTNAMES.has(host) ||
      host.endsWith(".local") ||
      host.endsWith(".internal") ||
      host.endsWith(".invalid") ||
      host.endsWith(".test") ||
      url.username ||
      url.password
    ) {
      return { valid: false, reason: "ssrf_or_untrusted_host" };
    }
    return { valid: true, reason: "ok" };
  } catch {
    return { valid: false, reason: "malformed_url" };
  }
}

