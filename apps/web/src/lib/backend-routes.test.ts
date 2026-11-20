import { describe, expect, it } from "vitest";
import { conversationStorageKey } from "./api";
import { isAllowedBackendRoute } from "./backend-routes";

describe("backend proxy route allowlist", () => {
  it("allows only the existing public health, auth, and inference routes", () => {
    expect(isAllowedBackendRoute("GET", "health")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/native-ai/health")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/me")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/login")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/register")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/logout")).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/native-ai/infer")).toBe(true);
  });

  it("rejects unknown paths and method/path combinations", () => {
    expect(isAllowedBackendRoute("GET", "users")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "auth/login")).toBe(false);
    expect(isAllowedBackendRoute("POST", "health")).toBe(false);
    expect(isAllowedBackendRoute("POST", "auth/me")).toBe(false);
    expect(isAllowedBackendRoute("GET", "auth/logout")).toBe(false);
    expect(isAllowedBackendRoute("GET", "../health")).toBe(false);
  });
});

describe("multi-user local conversation key isolation", () => {
  it("isolates storage keys per authenticated user and rejects unauthenticated sessions", () => {
    expect(conversationStorageKey(null)).toBeNull();
    expect(
      conversationStorageKey({ authenticated: false, email: "a@example.com" }),
    ).toBeNull();
    const keyA = conversationStorageKey({
      authenticated: true,
      userId: "user-a-uuid",
      email: "a@example.com",
    });
    const keyB = conversationStorageKey({
      authenticated: true,
      userId: "user-b-uuid",
      email: "b@example.com",
    });
    expect(keyA).toBe("zyrquen.local-conversations.v2.user-a-uuid");
    expect(keyB).toBe("zyrquen.local-conversations.v2.user-b-uuid");
    expect(keyA).not.toBe(keyB);
  });
});
