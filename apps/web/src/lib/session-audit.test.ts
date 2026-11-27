import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  normalizeAuditLogEntry,
  normalizeSessionPayload,
  readSession,
} from "./api";
import {
  getInMemoryVerificationTokenForTesting,
  handleInMemoryBackendRequest,
} from "./in-memory-backend";

async function startMockOAuthServer(): Promise<{
  baseUrl: string;
  close: () => Promise<void>;
}> {
  const server: Server = createServer(async (req, res) => {
    const url = req.url || "/";
    if (req.method === "POST" && url === "/github/token") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ access_token: "gh-mock-token" }));
      return;
    }
    if (req.method === "GET" && url === "/github/user") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          id: 90125,
          login: "octoz",
          name: "Octo Zyrquen",
          avatar_url: "https://avatars.example.test/octoz.png",
        }),
      );
      return;
    }
    if (req.method === "GET" && url === "/github/emails") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify([
          { email: "octoz@zyrquen.test", primary: true, verified: true },
        ]),
      );
      return;
    }
    if (req.method === "POST" && url === "/google/token") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ access_token: "google-mock-token" }));
      return;
    }
    if (req.method === "GET" && url === "/google/userinfo") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          sub: "google-sub-777",
          email: "guser@zyrquen.test",
          email_verified: true,
          name: "Google User",
          picture: "https://lh3.example.test/avatar.png",
        }),
      );
      return;
    }
    res.writeHead(404);
    res.end();
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as AddressInfo;
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: () =>
      new Promise<void>((resolve, reject) =>
        server.close((err) => (err ? reject(err) : resolve())),
      ),
  };
}

describe("session normalization and readSession", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("normalizes flat /api/session, FastAPI /auth/me, and nested Express /api/auth/me payloads", () => {
    const nextPayload = normalizeSessionPayload({
      authenticated: true,
      userId: "user-1",
      email: "Admin@Zyrquen.Local ",
      role: "ADMIN",
      emailVerified: false,
    });
    expect(nextPayload).toEqual({
      authenticated: true,
      userId: "user-1",
      email: "admin@zyrquen.local",
      role: "admin",
      verified: false,
      emailVerified: false,
      expired: false,
      error: null,
    });

    const fastApiPayload = normalizeSessionPayload({
      id: "user-2",
      email: "user@zyrquen.local",
      role: "user",
      is_active: true,
      email_verified: true,
    });
    expect(fastApiPayload.authenticated).toBe(true);
    expect(fastApiPayload.userId).toBe("user-2");
    expect(fastApiPayload.role).toBe("user");
    expect(fastApiPayload.emailVerified).toBe(true);

    const expressPayload = normalizeSessionPayload({
      authenticated: true,
      user: {
        id: "user-3",
        email: "express@zyrquen.local",
        role: "admin",
        email_verified: false,
      },
    });
    expect(expressPayload.authenticated).toBe(true);
    expect(expressPayload.userId).toBe("user-3");
    expect(expressPayload.role).toBe("admin");
    expect(expressPayload.emailVerified).toBe(false);

    const inactive = normalizeSessionPayload({
      authenticated: true,
      userId: "user-4",
      email: "disabled@zyrquen.local",
      is_active: false,
    });
    expect(inactive.authenticated).toBe(false);
    expect(inactive.userId).toBeNull();
  });

  it("readSession resolves explicit authenticated boolean on 200 and 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          user: {
            id: "u-100",
            email: "dev@zyrquen.test",
            role: "admin",
            email_verified: false,
          },
        }),
      }),
    );

    const okSession = await readSession();
    expect(okSession.authenticated).toBe(true);
    expect(okSession.userId).toBe("u-100");
    expect(okSession.role).toBe("admin");
    expect(okSession.emailVerified).toBe(false);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Expired" }),
      }),
    );
    const expiredSession = await readSession();
    expect(expiredSession.authenticated).toBe(false);
    expect(expiredSession.expired).toBe(true);
    expect(expiredSession.userId).toBeNull();
  });
});

describe("audit log standardization", () => {
  it("populates actor_user_id from centralized session or user directory", () => {
    const session = normalizeSessionPayload({
      authenticated: true,
      userId: "admin-uuid-1",
      email: "admin@zyrquen.local",
      role: "admin",
      emailVerified: true,
    });
    const userIdByEmail = new Map([["other@zyrquen.local", "user-uuid-2"]]);

    const fromActorEmail = normalizeAuditLogEntry(
      {
        id: "aud-1",
        actor_email: "admin@zyrquen.local",
        action: "AUTH_OAUTH_LOGIN",
        target: "github:90125",
        outcome: "SUCCESS",
        created_at: "2026-11-27T00:00:00Z",
      },
      session,
      userIdByEmail,
    );
    expect(fromActorEmail.actor_user_id).toBe("admin-uuid-1");
    expect(fromActorEmail.resource_id).toBe("github:90125");
    expect(fromActorEmail.outcome).toBe("SUCCESS");

    const fromUserMap = normalizeAuditLogEntry(
      {
        id: "aud-2",
        actor_email: "other@zyrquen.local",
        action: "api_key.created",
        resource_id: "key-1",
        created_at: "2026-11-27T00:00:00Z",
      },
      session,
      userIdByEmail,
    );
    expect(fromUserMap.actor_user_id).toBe("user-uuid-2");
  });
});

describe("email verification & OAuth 2.0 in-memory backend flows", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("issues verification link on registration and verifies email via token", async () => {
    const email = `verify-${Date.now()}@zyrquen.test`;
    const reg = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/register",
      authorizationHeader: null,
      rawBody: JSON.stringify({
        email,
        password: "StrongPassword123456!",
      }),
      origin: "http://localhost:3000",
    });
    expect(reg.status).toBe(200);
    const regBody = reg.body as {
      id: string;
      email_verified: boolean;
      verification: { required: boolean; emailSent: boolean };
    };
    expect(regBody.email_verified).toBe(false);
    expect(regBody.verification.required).toBe(true);

    const token = getInMemoryVerificationTokenForTesting(email);
    expect(token).toBeTruthy();

    const verified = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/verify-email",
      authorizationHeader: null,
      rawBody: JSON.stringify({ token }),
    });
    expect(verified.status).toBe(200);
    expect((verified.body as { email_verified: boolean }).email_verified).toBe(
      true,
    );

    const reused = await handleInMemoryBackendRequest({
      method: "POST",
      path: "auth/verify-email",
      authorizationHeader: null,
      rawBody: JSON.stringify({ token }),
    });
    expect(reused.status).toBe(400);
  });

  it("supports GitHub and Google OAuth 2.0 login and ZYRQUEN account linking", async () => {
    const mockOAuth = await startMockOAuthServer();
    try {
      vi.stubEnv("ZYRQUEN_OAUTH_ALLOW_TEST_ENDPOINTS", "1");
      vi.stubEnv("GITHUB_OAUTH_CLIENT_ID", "gh-client-id");
      vi.stubEnv("GITHUB_OAUTH_CLIENT_SECRET", "gh-client-secret");
      vi.stubEnv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id");
      vi.stubEnv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret");
      vi.stubEnv("ZYRQUEN_GITHUB_AUTH_URL", `${mockOAuth.baseUrl}/github/auth`);
      vi.stubEnv("ZYRQUEN_GITHUB_TOKEN_URL", `${mockOAuth.baseUrl}/github/token`);
      vi.stubEnv("ZYRQUEN_GITHUB_USER_URL", `${mockOAuth.baseUrl}/github/user`);
      vi.stubEnv(
        "ZYRQUEN_GITHUB_EMAILS_URL",
        `${mockOAuth.baseUrl}/github/emails`,
      );
      vi.stubEnv("ZYRQUEN_GOOGLE_AUTH_URL", `${mockOAuth.baseUrl}/google/auth`);
      vi.stubEnv("ZYRQUEN_GOOGLE_TOKEN_URL", `${mockOAuth.baseUrl}/google/token`);
      vi.stubEnv(
        "ZYRQUEN_GOOGLE_USERINFO_URL",
        `${mockOAuth.baseUrl}/google/userinfo`,
      );

      const providersResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/providers",
        authorizationHeader: null,
      });
      expect(providersResp.status).toBe(200);
      expect(providersResp.body).toEqual({
        providers: {
          google: { configured: true, name: "Google" },
          github: { configured: true, name: "GitHub" },
        },
      });

      const ghUrlResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/oauth/github/url",
        authorizationHeader: null,
        origin: "http://localhost:3000",
      });
      expect(ghUrlResp.status).toBe(200);
      const ghAuthUrl = new URL((ghUrlResp.body as { url: string }).url);
      const ghState = ghAuthUrl.searchParams.get("state")!;
      expect(ghState).toBeTruthy();

      const ghCbResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/oauth/github/callback",
        searchParams: new URLSearchParams({ code: "gh-code", state: ghState }),
        authorizationHeader: null,
      });
      expect(ghCbResp.status).toBe(200);
      const ghLogin = ghCbResp.body as {
        ok: boolean;
        access_token: string;
        email: string;
        user: { id: string; email_verified: boolean };
      };
      expect(ghLogin.ok).toBe(true);
      expect(ghLogin.email).toBe("octoz@zyrquen.test");
      expect(ghLogin.user.email_verified).toBe(true);

      // Link Google OAuth account onto the GitHub-authenticated ZYRQUEN account
      const gLinkUrlResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/oauth/google/url",
        searchParams: new URLSearchParams({ intent: "link" }),
        authorizationHeader: `Bearer ${ghLogin.access_token}`,
        origin: "http://localhost:3000",
      });
      expect(gLinkUrlResp.status).toBe(200);
      const gState = new URL(
        (gLinkUrlResp.body as { url: string }).url,
      ).searchParams.get("state")!;

      const gLinkCbResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/oauth/google/callback",
        searchParams: new URLSearchParams({
          code: "google-code",
          state: gState,
        }),
        authorizationHeader: null,
      });
      expect(gLinkCbResp.status).toBe(200);
      expect((gLinkCbResp.body as { intent: string }).intent).toBe("link");

      const identitiesResp = await handleInMemoryBackendRequest({
        method: "GET",
        path: "auth/identities",
        authorizationHeader: `Bearer ${ghLogin.access_token}`,
      });
      expect(identitiesResp.status).toBe(200);
      const providers = (
        identitiesResp.body as { identities: Array<{ provider: string }> }
      ).identities.map((i) => i.provider);
      expect(providers.sort()).toEqual(["github", "google"]);
    } finally {
      await mockOAuth.close();
    }
  });
});
