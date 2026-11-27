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
        "PATCH",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000/auto-rotate",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "POST",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000/rotate",
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
    expect(isAllowedBackendRoute("POST", "auth/verify-email")).toBe(true);
    expect(isAllowedBackendRoute("POST", "auth/verification/resend")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/providers")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/identities")).toBe(true);
    expect(isAllowedBackendRoute("DELETE", "auth/identities/github")).toBe(true);
    expect(isAllowedBackendRoute("DELETE", "auth/identities/google")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/oauth/github/url")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/oauth/google/url")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/oauth/github/callback")).toBe(true);
    expect(isAllowedBackendRoute("GET", "auth/oauth/google/callback")).toBe(true);
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
    expect(isAllowedBackendRoute("GET", "v1/workflows/definitions")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/workflows/services/status")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/workflows/runs")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/workflows/logs")).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/workflows/runs")).toBe(true);
    expect(
      isAllowedBackendRoute(
        "GET",
        "v1/workflows/runs/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "POST",
        "v1/workflows/approvals/123e4567-e89b-42d3-a456-426614174000/decision",
      ),
    ).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/models/registry")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/models/registry/compare")).toBe(true);
    expect(
      isAllowedBackendRoute("GET", "v1/models/registry/ZYRQUEN-Native-0.1.0/lineage"),
    ).toBe(true);
    expect(
      isAllowedBackendRoute("GET", "v1/models/registry/ZYRQUEN-Native-0.1.0/artifacts/manifest"),
    ).toBe(true);
    expect(
      isAllowedBackendRoute("GET", "v1/models/registry/ZYRQUEN-Native-0.1.0/artifacts/logs"),
    ).toBe(true);
    expect(
      isAllowedBackendRoute("POST", "v1/models/registry/ZYRQUEN-Native-0.1.0/stage"),
    ).toBe(true);
    expect(
      isAllowedBackendRoute("POST", "v1/models/registry/ZYRQUEN-Native-0.1.0/promote"),
    ).toBe(true);
    expect(isAllowedBackendRoute("POST", "v1/models/registry/rollback")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/v10/closure-audit")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/datasets/status")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/datasets/0.1.0/status")).toBe(true);
    expect(isAllowedBackendRoute("GET", "v1/datasets/nagi_v11.2/status")).toBe(true);
    expect(isAllowedBackendRoute("GET", "training/readiness")).toBe(true);
    expect(isAllowedBackendRoute("GET", "training/runs")).toBe(true);
    expect(isAllowedBackendRoute("POST", "training/runs")).toBe(true);
    expect(
      isAllowedBackendRoute(
        "GET",
        "training/runs/123e4567-e89b-42d3-a456-426614174000",
      ),
    ).toBe(true);
    expect(
      isAllowedBackendRoute(
        "GET",
        "training/runs/123e4567-e89b-42d3-a456-426614174000/telemetry",
      ),
    ).toBe(true);
  });

  it("rejects unknown paths and method/path combinations", () => {
    expect(isAllowedBackendRoute("GET", "users")).toBe(false);
    expect(isAllowedBackendRoute("GET", "users/me/admin")).toBe(false);
    expect(isAllowedBackendRoute("PATCH", "users/me/usage")).toBe(false);
    expect(isAllowedBackendRoute("GET", "users/me/api-keys/unknown")).toBe(false);
    expect(
      isAllowedBackendRoute(
        "POST",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000/auto-rotate",
      ),
    ).toBe(false);
    expect(
      isAllowedBackendRoute(
        "GET",
        "users/me/api-keys/123e4567-e89b-42d3-a456-426614174000/rotate",
      ),
    ).toBe(false);
    expect(isAllowedBackendRoute("POST", "admin/overview")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "auth/login")).toBe(false);
    expect(isAllowedBackendRoute("GET", "auth/verify-email")).toBe(false);
    expect(isAllowedBackendRoute("POST", "auth/oauth/github/callback")).toBe(false);
    expect(isAllowedBackendRoute("GET", "auth/oauth/gitlab/url")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "auth/identities/gitlab")).toBe(false);
    expect(isAllowedBackendRoute("POST", "health")).toBe(false);
    expect(isAllowedBackendRoute("POST", "auth/me")).toBe(false);
    expect(isAllowedBackendRoute("GET", "auth/logout")).toBe(false);
    expect(isAllowedBackendRoute("GET", "../health")).toBe(false);
    expect(isAllowedBackendRoute("PATCH", "conversations")).toBe(false);
    expect(isAllowedBackendRoute("GET", "conversations/not-a-uuid")).toBe(false);
    expect(isAllowedBackendRoute("GET", "v1/workflows/runs/not-a-uuid")).toBe(false);
    expect(isAllowedBackendRoute("POST", "v1/workflows/services/status")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "v1/workflows/services/status")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "v1/models/registry/ZYRQUEN-Native-0.1.0/promote")).toBe(false);
    expect(isAllowedBackendRoute("POST", "v1/models/registry/../secret/promote")).toBe(false);
    expect(isAllowedBackendRoute("GET", "v1/models/registry/v1..2/lineage")).toBe(false);
    expect(
      isAllowedBackendRoute("POST", "v1/models/registry/ZYRQUEN-Native-0.1.0/artifacts/manifest"),
    ).toBe(false);
    expect(
      isAllowedBackendRoute("GET", "v1/models/registry/ZYRQUEN-Native-0.1.0/artifacts/other"),
    ).toBe(false);
    expect(isAllowedBackendRoute("GET", "v1/models/registry/ZYRQUEN-Native-0.1.0/stage")).toBe(false);
    expect(isAllowedBackendRoute("POST", "v1/v10/closure-audit")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "v1/v10/closure-audit")).toBe(false);
    expect(isAllowedBackendRoute("POST", "v1/datasets/status")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "v1/datasets/0.1.0/status")).toBe(false);
    expect(isAllowedBackendRoute("GET", "v1/datasets/0.1..2/status")).toBe(false);
    expect(isAllowedBackendRoute("GET", "v1/datasets/../etc/status")).toBe(false);
    expect(isAllowedBackendRoute("POST", "training/readiness")).toBe(false);
    expect(isAllowedBackendRoute("DELETE", "training/runs")).toBe(false);
    expect(isAllowedBackendRoute("GET", "training/runs/not-a-uuid")).toBe(false);
    expect(
      isAllowedBackendRoute(
        "POST",
        "training/runs/123e4567-e89b-42d3-a456-426614174000/telemetry",
      ),
    ).toBe(false);
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
