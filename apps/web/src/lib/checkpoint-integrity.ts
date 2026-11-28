import { apiRequest } from "./api";
import type {
  CheckpointIntegrityResult,
  NativeModelRegistryResponse,
  NativeModelVariant,
} from "./types";

function parseCreatedAtMs(value?: string | null): number {
  if (!value) return Number.NaN;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/**
 * Select the latest registered checkpoint version from a Model Registry payload.
 * Prefers the newest valid `created_at` timestamp (tie-broken by `checkpoint.step`,
 * then latest order in `versions`), falling back to `active_version`.
 */
export function selectLatestRegistryVersion(
  registry: NativeModelRegistryResponse | null | undefined,
): NativeModelVariant | null {
  if (!registry || !Array.isArray(registry.versions) || registry.versions.length === 0) {
    return null;
  }

  let best: NativeModelVariant = registry.versions[registry.versions.length - 1];
  let bestTime = parseCreatedAtMs(best.created_at);
  let bestStep = typeof best.checkpoint?.step === "number" ? best.checkpoint.step : -1;

  for (let i = 0; i < registry.versions.length; i += 1) {
    const candidate = registry.versions[i];
    if (!candidate || typeof candidate.version !== "string" || !candidate.version.trim()) {
      continue;
    }
    const candTime = parseCreatedAtMs(candidate.created_at);
    const candStep =
      typeof candidate.checkpoint?.step === "number" ? candidate.checkpoint.step : -1;

    if (Number.isFinite(candTime) && !Number.isFinite(bestTime)) {
      best = candidate;
      bestTime = candTime;
      bestStep = candStep;
      continue;
    }

    if (Number.isFinite(candTime) && Number.isFinite(bestTime)) {
      if (candTime > bestTime || (candTime === bestTime && candStep >= bestStep)) {
        best = candidate;
        bestTime = candTime;
        bestStep = candStep;
      }
      continue;
    }

    if (!Number.isFinite(candTime) && !Number.isFinite(bestTime)) {
      if (candStep >= bestStep) {
        best = candidate;
        bestStep = candStep;
      }
    }
  }

  if (best && typeof best.version === "string" && best.version.trim()) {
    return best;
  }

  const active = registry.active_version?.trim();
  if (active) {
    return (
      registry.versions.find((item) => item.version === active) ?? {
        version: active,
      }
    );
  }
  return null;
}

export async function verifyRegistryVersionIntegrity(
  version: string,
): Promise<CheckpointIntegrityResult> {
  const trimmed = version.trim();
  if (!trimmed) {
    throw new Error("Model version is required for integrity verification.");
  }
  return apiRequest<CheckpointIntegrityResult>(
    `v1/models/registry/${encodeURIComponent(trimmed)}/verify`,
    { method: "POST" },
  );
}

export type LatestCheckpointVerificationSnapshot = {
  configured: boolean;
  registryDetail?: string;
  latestVersion: NativeModelVariant | null;
  verification: CheckpointIntegrityResult | null;
};

export async function fetchAndVerifyLatestCheckpoint(): Promise<LatestCheckpointVerificationSnapshot> {
  const registry = await apiRequest<NativeModelRegistryResponse>("v1/models/registry");
  if (!registry.configured) {
    return {
      configured: false,
      registryDetail:
        registry.detail ?? "Model Registry is not configured on the backend.",
      latestVersion: null,
      verification: null,
    };
  }

  const latest = selectLatestRegistryVersion(registry);
  if (!latest) {
    return {
      configured: true,
      registryDetail: "No registered checkpoints found in Model Registry.",
      latestVersion: null,
      verification: null,
    };
  }

  const verification = await verifyRegistryVersionIntegrity(latest.version);
  return {
    configured: true,
    latestVersion: latest,
    verification,
  };
}

export function shortSha256(value?: string | null): string {
  if (!value) return "—";
  if (value.length <= 16) return value;
  return `${value.slice(0, 12)}…${value.slice(-6)}`;
}
