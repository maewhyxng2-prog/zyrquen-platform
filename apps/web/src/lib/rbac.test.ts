import { describe, expect, it } from "vitest";
import { handleInMemoryBackendRequest } from "./in-memory-backend";

describe("In-memory backend RBAC and account roles", () => {
  it("registers standard users with role 'user' and blocks admin endpoints with 403", async () => {
    const email = `rbac-${Date.now()}-${Math.floor(Math.random() * 10000)}@zyrquen.local`;
    const password = "StrongTestPassword123!";

    const reg = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/register",
      authorizationHeader: null,
      rawBody: JSON.stringify({ email, password }),
    });
    expect(reg.status).toBe(200);
    const regBody = reg.body as { role?: string; email?: string };
    expect(regBody.role).toBe("user");
    expect(regBody.email).toBe(email);

    const login = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/login",
      authorizationHeader: null,
      rawBody: JSON.stringify({ email, password }),
    });
    expect(login.status).toBe(200);
    const { access_token: token } = login.body as { access_token: string };
    const authHeader = `Bearer ${token}`;

    const me = await handleInMemoryBackendRequest({
      method: "GET",
      path: "auth/me",
      authorizationHeader: authHeader,
      rawBody: "",
    });
    expect(me.status).toBe(200);
    expect((me.body as { role?: string }).role).toBe("user");

    for (const adminPath of [
      "admin/overview",
      "admin/users",
      "admin/audit-logs",
    ]) {
      const res = await handleInMemoryBackendRequest({
        method: "GET",
        path: adminPath,
        authorizationHeader: authHeader,
        rawBody: "",
      });
      expect(res.status).toBe(403);
    }
  });

  it("allows seeded admin account to access admin overview, users, and audit logs", async () => {
    const login = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/login",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email: "demo@zyrquen.local",
        password: "zyrquen-demo-pass",
      }),
    });
    expect(login.status).toBe(200);
    const { access_token: token } = login.body as { access_token: string };
    const authHeader = `Bearer ${token}`;

    const me = await handleInMemoryBackendRequest({
      method: "GET",
      path: "auth/me",
      authorizationHeader: authHeader,
      rawBody: "",
    });
    expect(me.status).toBe(200);
    expect((me.body as { role?: string }).role).toBe("admin");

    for (const adminPath of [
      "admin/overview",
      "admin/users",
      "admin/audit-logs",
    ]) {
      const res = await handleInMemoryBackendRequest({
        method: "GET",
        path: adminPath,
        authorizationHeader: authHeader,
        rawBody: "",
      });
      expect(res.status).toBe(200);
    }
  });
});
