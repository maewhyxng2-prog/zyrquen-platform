import { describe, expect, it } from "vitest";
import { isAllowedBackendRoute } from "./backend-routes";
import {
  updateConversationMessage,
  withConversation,
} from "./conversation-api";
import type { Conversation } from "./types";

describe("backend proxy route allowlist", () => {
  it("allows only the existing public health, auth, and inference routes", () => {
    expect(isAllowedBackendRoute("GET", "health")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/native-ai/health")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/me")).toBe(true);
    expect(isAllowedBackendRoute("GET", "users/me")).toBe(true);
    expect(isAllowedBackendRoute("PATCH", "users/me")).toBe(true);
    expect(isAllowedBackendRoute("GET", "users/me/usage")).toBe(true);
    expect(isAllowedBackendRoute("GET", "users/me/quota")).toBe(true);
    expect(isAllowedBackendRoute("GET", "users/me/api-keys")).toBe(true);
    expect(isAllowedBackendRoute("POST", "users/me/api-keys")).toBe(true);
    expect(
      isAllowedBackendRoute(
        "DELETE",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "GET",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000/usage",
      ),
    ).toBe(true);
    expect(isAllowedBackendRoute("GET", "admin/overview")).toBe(true);
    expect(isAllowedBackendRoute("GET", "admin/users")).toBe(true);
    expect(isAllowedBackendRoute("GET", "admin/audit-logs")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/login")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/register")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/logout")).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/native-ai/infer")).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/native-ai/infer/stream")).toBe(true);
    expect(isAllowedBackendRoute("GET", "conversations")).toBe(true);
    expect(isAllowedBackendRoute("POST", "conversations")).toBe(true);
    expect(
      isAllowedBackendRoute(
        "GET",
        "conversations/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "PATCH",
        "conversations/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "DELETE",
        "conversations/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "POST",
        "conversations/123e4567-e89b-42d3-a456-426614174000/messages",
      ),
    ).toBe(true);
  });

  it("rejects unknown paths and method/path combinations", () => {
    expect(isAllowedBackendRoute("GET", "users")).toBe(false);
    expect(isAllowedBackendRoute("GET", "users/me/admin")).toBe(false);
    expect(isAllowedBackendRoute("PATCH", "users/me/usage")).toBe(false);
    expect(isAllowedBackendRoute("GET", "users/me/api-keys/unknown")).toBe(false);
    expect(isAllowedBackendRoute("POST", "admin/overview")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "auth/login")).toBe(false);
    expect(isAllowedBackendRoute("POST", "health")).toBe(false);
    expect(isAllowedBackendRoute("POST", "auth/me")).toBe(false);
    expect(isAllowedBackendRoute("GET", "auth/logout")).toBe(false);
    expect(isAllowedBackendRoute("GET", "../health")).toBe(false);
    expect(isAllowedBackendRoute("PATCH", "conversations")).toBe(false);
    expect(isAllowedBackendRoute("GET", "conversations/not-a-uuid")).toBe(false);
  });
});

describe("conversation state", () => {
  const conversation = (id: string, updatedAt: string): Conversation => ({
    id,
    title: id,
    createdAt: updatedAt,
    updatedAt,
    messageCount: 0,
    messages: [],
  });

  it("keeps the most recently updated conversation first", () => {
    const older = conversation("older", "2026-01-01T00:00:00Z");
    const newer = conversation("newer", "2026-01-02T00:00:00Z");
    expect(withConversation([newer], older).map((item) => item.id)).toEqual([
      "newer",
      "older",
    ]);
  });

  it("adds a persisted message only once and updates the message count", () => {
    const initial = conversation("one", "2026-01-01T00:00:00Z");
    const message = {
      id: "message-id",
      role: "user" as const,
      content: "hello",
      createdAt: "2026-01-02T00:00:00Z",
    };
    const once = updateConversationMessage([initial], initial.id, message);
    const twice = updateConversationMessage(once, initial.id, message);
    expect(twice[0].messages).toEqual([message]);
    expect(twice[0].messageCount).toBe(1);
  });
});
