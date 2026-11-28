import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAndVerifyLatestCheckpoint,
  selectLatestRegistryVersion,
  verifyRegistryVersionIntegrity,
} from "./checkpoint-integrity";
import { handleInMemoryBackendRequest } from "./in-memory-backend";
import type { CheckpointIntegrityResult, NativeModelRegistryResponse } from "./types";

async function loginAsDemoAdmin(): Promise<string> {
  const res = await handleInMemoryBackendRequest({
    method: "POST",
    path: "auth/login",
    rawBody: JSON.stringify({
      email: "demo@zyrquen.local",
      password: "zyrquen-demo-pass",
    }),
  });
  if (res.status !== 200 || !res.body || typeof res.body !== "object") {
    throw new Error(`Demo admin login failed with status ${res.status}`);
  }
  const token = (res.body as { access_token?: string }).access_token;
  if (!token) {
    throw new Error("Demo admin login response missing access_token");
  }
  return token;
}

describe("checkpoint-integrity helpers", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("selects the latest checkpoint by created_at timestamp and step", () => {
    const registry: NativeModelRegistryResponse = {
      configured: true,
      active_version: "ZYRQUEN-Native-10.0.0",
      versions: [
        {
          version: "ZYRQUEN-Native-10.0.0",
          created_at: "2026-11-10T08:00:00.000Z",
          checkpoint: { step: 500 },
        },
        {
          version: "ZYRQUEN-Native-10.0.2",
          created_at: "2026-11-28T08:00:00.000Z",
          checkpoint: { step: 1200 },
        },
        {
          version: "ZYRQUEN-Native-10.0.1",
          created_at: "2026-11-20T08:00:00.000Z",
          checkpoint: { step: 800 },
        },
      ],
    };
    expect(selectLatestRegistryVersion(registry)?.version).toBe("ZYRQUEN-Native-10.0.2");
  });

  it("fetches latest checkpoint and verifies it against .sha256 sidecar", async () => {
    const mockVerify: CheckpointIntegrityResult = {
      version: "ZYRQUEN-Native-10.0.1",
      status: "Verified",
      verified: true,
      checkpoint_path: "artifacts/ZYRQUEN-Native-10.0.1/checkpoint.pt",
      sidecar_path: "artifacts/ZYRQUEN-Native-10.0.1/checkpoint.pt.sha256",
      sidecar_present: true,
      expected_sha256: "a".repeat(64),
      actual_sha256: "a".repeat(64),
      checked_at: "2026-11-28T10:00:00.000Z",
      detail: "Checkpoint SHA-256 matches .sha256 sidecar file.",
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/backend/v1/models/registry")) {
        return new Response(
          JSON.stringify({
            configured: true,
            active_version: "ZYRQUEN-Native-10.0.0",
            versions: [
              {
                version: "ZYRQUEN-Native-10.0.0",
                created_at: "2026-11-15T00:00:00.000Z",
              },
              {
                version: "ZYRQUEN-Native-10.0.1",
                created_at: "2026-11-28T00:00:00.000Z",
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/api/backend/v1/models/registry/ZYRQUEN-Native-10.0.1/verify")) {
        return new Response(JSON.stringify(mockVerify), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const snapshot = await fetchAndVerifyLatestCheckpoint();
    expect(snapshot.configured).toBe(true);
    expect(snapshot.latestVersion?.version).toBe("ZYRQUEN-Native-10.0.1");
    expect(snapshot.verification?.status).toBe("Verified");

    const manual = await verifyRegistryVersionIntegrity("ZYRQUEN-Native-10.0.1");
    expect(manual.verified).toBe(true);
  });
});

describe("in-memory-backend checkpoint verification endpoint", () => {
  const originalRoot = process.env.ZYRQUEN_MODEL_REGISTRY_ROOT;
  let tempRoot: string | null = null;

  beforeEach(() => {
    delete process.env.ZYRQUEN_MODEL_REGISTRY_ROOT;
  });

  afterEach(() => {
    if (originalRoot === undefined) {
      delete process.env.ZYRQUEN_MODEL_REGISTRY_ROOT;
    } else {
      process.env.ZYRQUEN_MODEL_REGISTRY_ROOT = originalRoot;
    }
    if (tempRoot) {
      rmSync(tempRoot, { recursive: true, force: true });
      tempRoot = null;
    }
  });

  it("fails closed to Corrupted in preview sandbox without disk .sha256 sidecar", async () => {
    const token = await loginAsDemoAdmin();
    const res = await handleInMemoryBackendRequest({
      method: "POST",
      path: "v1/models/registry/ZYRQUEN-Native-V10/verify",
      authorizationHeader: `Bearer ${token}`,
    });
    expect(res.status).toBe(200);
    const body = res.body as CheckpointIntegrityResult;
    expect(body.status).toBe("Corrupted");
    expect(body.verified).toBe(false);
    expect(body.sidecar_present).toBe(false);
  });

  it("verifies disk registry checkpoint against .sha256 and detects tampering or missing sidecar", async () => {
    const token = await loginAsDemoAdmin();
    tempRoot = mkdtempSync(join(tmpdir(), "zyrquen-reg-verify-"));
    const version = "ZYRQUEN-Native-10.0.0";
    const artifactDir = join(tempRoot, "artifacts", version);
    mkdirSync(artifactDir, { recursive: true });

    const payload = Buffer.from("verified-checkpoint-bytes-v10");
    const digest = createHash("sha256").update(payload).digest("hex");
    const ckptPath = join(artifactDir, "checkpoint.pt");
    const sidecarPath = join(artifactDir, "checkpoint.pt.sha256");

    writeFileSync(ckptPath, payload);
    writeFileSync(sidecarPath, digest, "utf-8");
    writeFileSync(
      join(tempRoot, "registry.json"),
      JSON.stringify({
        schema: "zyrquen.model-registry.v1",
        versions: {
          [version]: {
            version,
            checkpoint: {
              step: 500,
              sha256: digest,
              path: `artifacts/${version}/checkpoint.pt`,
              sha256_path: `artifacts/${version}/checkpoint.pt.sha256`,
            },
          },
        },
      }),
      "utf-8",
    );

    process.env.ZYRQUEN_MODEL_REGISTRY_ROOT = tempRoot;

    const okRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: `v1/models/registry/${version}/verify`,
      authorizationHeader: `Bearer ${token}`,
    });
    expect(okRes.status).toBe(200);
    const okBody = okRes.body as CheckpointIntegrityResult;
    expect(okBody.status).toBe("Verified");
    expect(okBody.verified).toBe(true);
    expect(okBody.expected_sha256).toBe(digest);
    expect(okBody.actual_sha256).toBe(digest);

    // Tamper checkpoint bytes
    writeFileSync(ckptPath, Buffer.from("tampered-checkpoint-bytes"));
    const tamperedRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: `v1/models/registry/${version}/verify`,
      authorizationHeader: `Bearer ${token}`,
    });
    expect(tamperedRes.status).toBe(200);
    const tamperedBody = tamperedRes.body as CheckpointIntegrityResult;
    expect(tamperedBody.status).toBe("Corrupted");
    expect(tamperedBody.verified).toBe(false);

    // Restore bytes and delete sidecar
    writeFileSync(ckptPath, payload);
    unlinkSync(sidecarPath);
    const missingRes = await handleInMemoryBackendRequest({
      method: "POST",
      path: `v1/models/registry/${version}/verify`,
      authorizationHeader: `Bearer ${token}`,
    });
    expect(missingRes.status).toBe(200);
    const missingBody = missingRes.body as CheckpointIntegrityResult;
    expect(missingBody.status).toBe("Corrupted");
    expect(missingBody.verified).toBe(false);
    expect(missingBody.sidecar_present).toBe(false);
  });
});
