import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "./api-config";

describe("API base URL configuration", () => {
  it("uses localhost only for an unconfigured development server", () => {
    expect(resolveApiBaseUrl(undefined, "development")).toBe("http://localhost:8000");
  });

  it("requires a configured, non-loopback API URL in production", () => {
    expect(resolveApiBaseUrl(undefined, "production")).toBeNull();
    expect(resolveApiBaseUrl("http://localhost:8000", "production")).toBeNull();
    expect(resolveApiBaseUrl("http://127.0.0.1:8000", "production")).toBeNull();
    expect(resolveApiBaseUrl("http://[::1]:8000", "production")).toBeNull();
    expect(resolveApiBaseUrl("https://api.example.com/", "production")).toBe(
      "https://api.example.com",
    );
    expect(resolveApiBaseUrl("http://api:8000", "production")).toBe("http://api:8000");
  });

  it("rejects malformed or unsupported URLs", () => {
    expect(resolveApiBaseUrl("not a URL", "production")).toBeNull();
    expect(resolveApiBaseUrl("file:///etc/passwd", "development")).toBeNull();
  });
});
