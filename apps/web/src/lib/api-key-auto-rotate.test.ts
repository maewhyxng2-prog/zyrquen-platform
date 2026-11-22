import { afterEach, describe, expect, it, vi } from "vitest";
import { validateAutoRotateInterval } from "./api-access";
import { handleInMemoryBackendRequest } from "./in-memory-backend";

async function registerAndLogin(email: string): Promise<{ token: string }> {
  const password = "StrongTestPassword123!";
  await handleInMemoryBackendRequest({
    method: "POST",
    path: "auth/register",
    authorizationHeader: null,
    rawBody: JSON.stringify({ email, password }),
  });
  const login = await handleInMemoryBackendRequest({
    method: "POST",
    path: "auth/login",
    authorizationHeader: null,
    rawBody: JSON.stringify({ email, password }),
  });
  const body = login.body as { access_token: string };
  return { token: body.access_token };
}

describe("API key auto-rotate validation", () => {
  it("accepts disabled schedule and valid 1..365 day integer schedules", () => {
    expect(validateAutoRotateInterval(false, null)).toBeNull();
    expect(validateAutoRotateInterval(false, Number.NaN)).toBeNull();
    expect(validateAutoRotateInterval(true, 1)).toBeNull();
    expect(validateAutoRotateInterval(true, 30)).toBeNull();
    expect(validateAutoRotateInterval(true, 365)).toBeNull();
  });

  it("rejects out-of-range or non-integer intervals when enabled", () => {
    expect(validateAutoRotateInterval(true, 0)).not.toBeNull();
    expect(validateAutoRotateInterval(true, 366)).not.toBeNull();
    expect(validateAutoRotateInterval(true, 7.5)).not.toBeNull();
    expect(validateAutoRotateInterval(true, null)).not.toBeNull();
  });
});

describe("API key auto-rotate backend lifecycle", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates, schedules, rotates due keys automatically, enforces ownership, and blocks revoked keys", async () => {
    vi.useFakeTimers();
    const baseTime = new Date("2026-11-22T12:00:00.000Z");
    vi.setSystemTime(baseTime);

    const owner = await registerAndLogin("rotate-owner@zyrquen.test");
    const other = await registerAndLogin("rotate-other@zyrquen.test");
    const ownerAuth = `Bearer ${owner.token}`;
    const otherAuth = `Bearer ${other.token}`;

    const expiresAt = new Date(baseTime.getTime() + 60 * 86_400_000).toISOString();
    const createdRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: "users/me/api-keys",
      authorizationHeader: ownerAuth,
      rawBody: JSON.stringify({
        name: "long-running-worker",
        expires_at: expiresAt,
        auto_rotate_enabled: true,
        auto_rotate_interval_days: 30,
      }),
    });
    expect(createdRes.status).toBe(201);
    const created = createdRes.body as {
      id: string;
      key: string;
      key_prefix: string;
      auto_rotate_enabled: boolean;
      auto_rotate_interval_days: number;
      next_rotation_at: string;
      rotation_count: number;
    };
    expect(created.key).toMatch(/^zq_live_/);
    expect(created.auto_rotate_enabled).toBe(true);
    expect(created.auto_rotate_interval_days).toBe(30);
    expect(created.rotation_count).toBe(0);
    expect(created.next_rotation_at).toBe(
      new Date(baseTime.getTime() + 30 * 86_400_000).toISOString(),
    );

    const crossSchedule = await handleInMemoryBackendRequest({
      method: "PATCH",
      path: `users/me/api-keys/${created.id}/auto-rotate`,
      authorizationHeader: otherAuth,
      rawBody: JSON.stringify({
        auto_rotate_enabled: false,
        auto_rotate_interval_days: null,
      }),
    });
    expect(crossSchedule.status).toBe(404);

    const invalidSchedule = await handleInMemoryBackendRequest({
      method: "PATCH",
      path: `users/me/api-keys/${created.id}/auto-rotate`,
      authorizationHeader: ownerAuth,
      rawBody: JSON.stringify({
        auto_rotate_enabled: true,
        auto_rotate_interval_days: 400,
      }),
    });
    expect(invalidSchedule.status).toBe(422);

    const updatedSchedule = await handleInMemoryBackendRequest({
      method: "PATCH",
      path: `users/me/api-keys/${created.id}/auto-rotate`,
      authorizationHeader: ownerAuth,
      rawBody: JSON.stringify({
        auto_rotate_enabled: true,
        auto_rotate_interval_days: 7,
      }),
    });
    expect(updatedSchedule.status).toBe(200);
    const updatedBody = updatedSchedule.body as {
      auto_rotate_interval_days: number;
      next_rotation_at: string;
    };
    expect(updatedBody.auto_rotate_interval_days).toBe(7);

    const manualRotate = await handleInMemoryBackendRequest({
      method: "POST",
      path: `users/me/api-keys/${created.id}/rotate`,
      authorizationHeader: ownerAuth,
    });
    expect(manualRotate.status).toBe(200);
    const manualBody = manualRotate.body as {
      key: string;
      key_prefix: string;
      rotation_count: number;
      last_rotated_at: string;
    };
    expect(manualBody.key).toMatch(/^zq_live_/);
    expect(manualBody.key).not.toBe(created.key);
    expect(manualBody.rotation_count).toBe(1);
    expect(manualBody.last_rotated_at).toBe(baseTime.toISOString());

    // Advance 8 days so the 7-day auto-rotation schedule becomes due
    vi.setSystemTime(new Date(baseTime.getTime() + 8 * 86_400_000));
    const freshLogin = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/login",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email: "rotate-owner@zyrquen.test",
        password: "StrongTestPassword123!",
      }),
    });
    const freshToken = (freshLogin.body as { access_token: string }).access_token;
    const freshOwnerAuth = `Bearer ${freshToken}`;

    const listedAfterDue = await handleInMemoryBackendRequest({
      method: "GET",
      path: "users/me/api-keys",
      authorizationHeader: freshOwnerAuth,
    });
    expect(listedAfterDue.status).toBe(200);
    const keysAfterDue = listedAfterDue.body as Array<{
      id: string;
      key_prefix: string;
      rotation_count: number;
      key?: string;
    }>;
    const autoRotated = keysAfterDue.find((item) => item.id === created.id);
    expect(autoRotated).toBeDefined();
    expect(autoRotated?.rotation_count).toBe(2);
    // Secrets must never be exposed in GET listing
    expect(autoRotated?.key).toBeUndefined();

    // Revoke and verify rotation / schedule changes are rejected cleanly
    const revokeRes = await handleInMemoryBackendRequest({
      method: "DELETE",
      path: `users/me/api-keys/${created.id}`,
      authorizationHeader: freshOwnerAuth,
    });
    expect(revokeRes.status).toBe(200);

    const rotateRevoked = await handleInMemoryBackendRequest({
      method: "POST",
      path: `users/me/api-keys/${created.id}/rotate`,
      authorizationHeader: freshOwnerAuth,
    });
    expect(rotateRevoked.status).toBe(409);

    const scheduleRevoked = await handleInMemoryBackendRequest({
      method: "PATCH",
      path: `users/me/api-keys/${created.id}/auto-rotate`,
      authorizationHeader: freshOwnerAuth,
      rawBody: JSON.stringify({
        auto_rotate_enabled: true,
        auto_rotate_interval_days: 30,
      }),
    });
    expect(scheduleRevoked.status).toBe(409);
  });
});
