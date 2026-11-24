import { describe, expect, it } from "vitest";
import { handleInMemoryBackendRequest } from "./in-memory-backend";

describe("Registered Native Model variant selection in inference", () => {
  it("runs inference with a selected registered compatible native model version and rejects unknown variants", async () => {
    const email = `model-select-${Date.now()}-${Math.floor(Math.random() * 10000)}@zyrquen.local`;
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
    const { access_token: token } = login.body as { access_token: string };
    const authHeader = `Bearer ${token}`;

    const registryRes = await handleInMemoryBackendRequest({
      method: "GET",
      path: "v1/models/registry",
      authorizationHeader: authHeader,
      rawBody: "",
    });
    expect(registryRes.status).toBe(200);
    const registryBody = registryRes.body as {
      configured: boolean;
      versions: Array<{ version: string }>;
    };
    expect(registryBody.configured).toBe(true);
    expect(registryBody.versions.some((v) => v.version === "ZYRQUEN-Native-v9")).toBe(
      true,
    );

    const inferValid = await handleInMemoryBackendRequest({
      method: "POST",
      path: "v1/native-ai/infer",
      authorizationHeader: authHeader,
      rawBody: JSON.stringify({
        prompt: "ทดสอบการสลับรุ่น Native Model",
        request_id: crypto.randomUUID(),
        model_version: "ZYRQUEN-Native-v9",
      }),
    });
    expect(inferValid.status).toBe(200);
    const validBody = inferValid.body as { model_version: string; result: string };
    expect(validBody.model_version).toBe("ZYRQUEN-Native-v9");
    expect(validBody.result).toContain("ZYRQUEN-Native-v9");

    const inferInvalid = await handleInMemoryBackendRequest({
      method: "POST",
      path: "v1/native-ai/infer",
      authorizationHeader: authHeader,
      rawBody: JSON.stringify({
        prompt: "ทดสอบโมเดลที่ไม่ได้ลงทะเบียน",
        request_id: crypto.randomUUID(),
        model_version: "external-gpt-model",
      }),
    });
    expect(inferInvalid.status).toBe(422);
  });
});
