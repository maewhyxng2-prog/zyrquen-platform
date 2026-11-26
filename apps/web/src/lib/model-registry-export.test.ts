import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildModelRegistryMetadataFilename,
  downloadBackendFile,
} from "./api";

describe("model registry metadata export helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("formats a clear, filesystem-safe metadata filename for a registry version", () => {
    const fixedDate = new Date("2026-11-26T03:00:00Z");
    expect(buildModelRegistryMetadataFilename("ZYRQUEN-Native-0.1.0", fixedDate)).toBe(
      "zyrquen-model-registry-ZYRQUEN-Native-0.1.0-metadata-2026-11-26.json",
    );
    expect(buildModelRegistryMetadataFilename("  v2/rc 1  ", fixedDate)).toBe(
      "zyrquen-model-registry-v2-rc-1-metadata-2026-11-26.json",
    );
    expect(buildModelRegistryMetadataFilename("   ", fixedDate)).toBe(
      "zyrquen-model-registry-unknown-version-metadata-2026-11-26.json",
    );
  });

  it("overrides server Content-Disposition filename only when overrideFilename is enabled", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ schema: "zyrquen.model-artifact-manifest.v1", version: "v2" }),
        {
          status: 200,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "content-disposition": 'attachment; filename="v2-manifest.json"',
          },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const createdLinks: Array<{ href: string; download: string; click: () => void; remove: () => void }> = [];
    vi.stubGlobal("document", {
      createElement: () => {
        const el = { href: "", download: "", click: vi.fn(), remove: vi.fn() };
        createdLinks.push(el);
        return el;
      },
      body: { appendChild: vi.fn() },
    });

    const manifestName = await downloadBackendFile(
      "v1/models/registry/v2/artifacts/manifest",
      "fallback.json",
    );
    expect(manifestName).toBe("v2-manifest.json");
    expect(createdLinks[0].download).toBe("v2-manifest.json");
    expect(createdLinks[0].click).toHaveBeenCalledTimes(1);

    const metadataName = await downloadBackendFile(
      "v1/models/registry/v2/artifacts/manifest",
      "zyrquen-model-registry-v2-metadata-2026-11-26.json",
      { overrideFilename: true },
    );
    expect(metadataName).toBe("zyrquen-model-registry-v2-metadata-2026-11-26.json");
    expect(createdLinks[1].download).toBe("zyrquen-model-registry-v2-metadata-2026-11-26.json");
    expect(createdLinks[1].click).toHaveBeenCalledTimes(1);
  });
});
