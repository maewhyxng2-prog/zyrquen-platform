import { describe, expect, it } from "vitest";
import { resolveApiBaseUrl, validateOutboundResearchUrl } from "./api-config";
import {
  getInMemoryNativeHealth,
  shouldUseInMemoryBackend,
} from "./in-memory-backend";

describe("P0/P2 Strict Native-Only & Online-First Web Policy", () => {
  it("never falls back silently to in-memory backend in production", async () => {
    expect(await shouldUseInMemoryBackend(null, false, "production")).toBe(false);
    expect(await shouldUseInMemoryBackend(null, true, "production")).toBe(false);
    expect(
      await shouldUseInMemoryBackend("https://api.example.com", true, "production"),
    ).toBe(false);
  });

  it("reports BLOCKED native health when no PyTorch weights are loaded", () => {
    const health = getInMemoryNativeHealth();
    expect(health.runtime_status).toBe("blocked");
    expect(health.native_model_loaded).toBe(false);
    expect(health.inference_available).toBe(false);
    expect(health.is_trained).toBe(false);
    expect(health.progress_metrics).toBeNull();
  });

  it("blocks SSRF metadata, private IPs, and credentials in API or research URLs", () => {
    expect(
      resolveApiBaseUrl("http://169.254.169.254/latest/meta-data", "production"),
    ).toBeNull();
    expect(
      resolveApiBaseUrl("https://user:secret@api.example.com", "production"),
    ).toBeNull();
    expect(
      resolveApiBaseUrl("http://metadata.google.internal", "development"),
    ).toBeNull();

    expect(validateOutboundResearchUrl("http://169.254.169.254/").valid).toBe(
      false,
    );
    expect(validateOutboundResearchUrl("http://10.0.0.5/internal").valid).toBe(
      false,
    );
    expect(validateOutboundResearchUrl("http://192.168.1.1/admin").valid).toBe(
      false,
    );
    expect(validateOutboundResearchUrl("http://172.16.0.10/").valid).toBe(false);
    expect(
      validateOutboundResearchUrl("https://docs.python.org/3/library/").valid,
    ).toBe(true);
  });
});
