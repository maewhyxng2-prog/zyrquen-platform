import { describe, expect, it } from "vitest";
import { isAllowedBackendRoute } from "./backend-routes";

describe("backend proxy route allowlist", () => {
  it("allows only the existing public health, auth, and inference routes", () => {
    expect(isAllowedBackendRoute("GET", "health")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/native-ai/health")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/login")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/register")).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/native-ai/infer")).toBe(true);
  });

  it("rejects unknown paths and method/path combinations", () => {
    expect(isAllowedBackendRoute("GET", "users")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "auth/login")).toBe(false);
    expect(isAllowedBackendRoute("POST", "health")).toBe(false);
    expect(isAllowedBackendRoute("GET", "../health")).toBe(false);
  });
});
