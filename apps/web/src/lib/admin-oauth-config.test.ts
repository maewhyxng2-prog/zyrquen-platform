import { describe, expect, it } from "vitest";
import { handleInMemoryBackendRequest } from "./in-memory-backend";

async function loginDemoAdmin(): Promise<string> {
  const res = await handleInMemoryBackendRequest({
    method: "POST",
    path: "auth/login",
    authorizationHeader: null,
    rawBody: JSON.stringify({
      email: "demo@zyrquen.local",
      password: "zyrquen-demo-pass",
    }),
  });
  expect(res.status).toBe(200);
  const token = (res.body as { access_token?: string }).access_token;
  if (!token) throw new Error("Missing demo admin token");
  return token;
}

describe("admin manual OAuth configuration", () => {
  it("requires authentication and allows admin to save masked Google and GitHub credentials", async () => {
    const unauthed = await handleInMemoryBackendRequest({
      method: "GET",
      path: "admin/oauth/config",
      authorizationHeader: null,
    });
    expect(unauthed.status).toBe(401);

    const adminToken = await loginDemoAdmin();

    const saveGoogle = await handleInMemoryBackendRequest({
      method: "PUT",
      path: "admin/oauth/config/google",
      authorizationHeader: `Bearer ${adminToken}`,
      rawBody: JSON.stringify({
        clientId: "1234567890-test.apps.googleusercontent.com",
        clientSecret: "GOCSPX-super-secret-value-9876",
      }),
    });
    expect(saveGoogle.status).toBe(200);
    const bodyText = JSON.stringify(saveGoogle.body);
    expect(bodyText).not.toContain("GOCSPX-super-secret-value-9876");

    const googleEntry = (
      saveGoogle.body as {
        providers: {
          google: {
            configured: boolean;
            source: string;
            clientId: string;
            hasSecret: boolean;
            secretMasked: string;
          };
        };
      }
    ).providers.google;
    expect(googleEntry.configured).toBe(true);
    expect(googleEntry.source).toBe("manual");
    expect(googleEntry.clientId).toBe("1234567890-test.apps.googleusercontent.com");
    expect(googleEntry.hasSecret).toBe(true);
    expect(googleEntry.secretMasked).toBe("••••••••9876");

    const providersRes = await handleInMemoryBackendRequest({
      method: "GET",
      path: "auth/providers",
      authorizationHeader: null,
    });
    expect(providersRes.status).toBe(200);
    expect(
      (providersRes.body as { providers: { google: { configured: boolean } } }).providers
        .google.configured,
    ).toBe(true);

    // Updating only Client ID preserves existing stored secret without exposing it
    const updateClientId = await handleInMemoryBackendRequest({
      method: "PUT",
      path: "admin/oauth/config/google",
      authorizationHeader: `Bearer ${adminToken}`,
      rawBody: JSON.stringify({
        clientId: "updated-client-id-12345.apps.googleusercontent.com",
      }),
    });
    expect(updateClientId.status).toBe(200);
    expect(JSON.stringify(updateClientId.body)).not.toContain(
      "GOCSPX-super-secret-value-9876",
    );

    const cleared = await handleInMemoryBackendRequest({
      method: "DELETE",
      path: "admin/oauth/config/google",
      authorizationHeader: `Bearer ${adminToken}`,
    });
    expect(cleared.status).toBe(200);
    expect(
      (
        cleared.body as {
          providers: { google: { configured: boolean; source: string } };
        }
      ).providers.google.source,
    ).toBe("none");
  });
});
