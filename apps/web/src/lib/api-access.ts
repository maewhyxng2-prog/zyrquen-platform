import { apiRequest } from "./api";
import type { ApiKeyMetadata, ApiKeyUsage, CreatedApiKey } from "./types";

export const AUTO_ROTATE_PRESETS = [7, 30, 60, 90] as const;
export const MIN_AUTO_ROTATE_DAYS = 1;
export const MAX_AUTO_ROTATE_DAYS = 365;

type ApiKeyResponse = {
  id: string;
  name: string;
  key_prefix: string;
  scope: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  auto_rotate_enabled?: boolean;
  auto_rotate_interval_days?: number | null;
  last_rotated_at?: string | null;
  next_rotation_at?: string | null;
  rotation_count?: number;
};

function mapApiKey(key: ApiKeyResponse): ApiKeyMetadata {
  return {
    id: key.id,
    name: key.name,
    keyPrefix: key.key_prefix,
    scope: key.scope,
    createdAt: key.created_at,
    expiresAt: key.expires_at,
    revokedAt: key.revoked_at,
    autoRotateEnabled: Boolean(key.auto_rotate_enabled),
    autoRotateIntervalDays: key.auto_rotate_interval_days ?? null,
    lastRotatedAt: key.last_rotated_at ?? null,
    nextRotationAt: key.next_rotation_at ?? null,
    rotationCount: key.rotation_count ?? 0,
  };
}

function identityHeaders(userId: string): HeadersInit {
  return { "X-Zyrquen-Expected-User-ID": userId };
}

export function validateAutoRotateInterval(
  enabled: boolean,
  intervalDays: number | null,
): string | null {
  if (!enabled) return null;
  if (
    typeof intervalDays !== "number" ||
    !Number.isInteger(intervalDays) ||
    intervalDays < MIN_AUTO_ROTATE_DAYS ||
    intervalDays > MAX_AUTO_ROTATE_DAYS
  ) {
    return `รอบเวลา Auto-rotate ต้องเป็นจำนวนเต็มระหว่าง ${MIN_AUTO_ROTATE_DAYS} ถึง ${MAX_AUTO_ROTATE_DAYS} วัน`;
  }
  return null;
}

export async function listApiKeys(userId: string): Promise<ApiKeyMetadata[]> {
  const keys = await apiRequest<ApiKeyResponse[]>("users/me/api-keys", {
    headers: identityHeaders(userId),
  });
  return keys.map(mapApiKey);
}

export async function createApiKey(
  userId: string,
  name: string,
  expiresAt: string,
  autoRotate?: { enabled: boolean; intervalDays: number | null },
): Promise<CreatedApiKey> {
  const payload: Record<string, unknown> = {
    name,
    expires_at: expiresAt,
  };
  if (autoRotate) {
    payload.auto_rotate_enabled = autoRotate.enabled;
    payload.auto_rotate_interval_days = autoRotate.enabled
      ? autoRotate.intervalDays
      : null;
  }
  const key = await apiRequest<ApiKeyResponse & { key: string }>(
    "users/me/api-keys",
    {
      method: "POST",
      headers: identityHeaders(userId),
      body: JSON.stringify(payload),
    },
  );
  return { ...mapApiKey(key), key: key.key };
}

export async function updateApiKeyAutoRotate(
  userId: string,
  keyId: string,
  enabled: boolean,
  intervalDays: number | null,
): Promise<ApiKeyMetadata> {
  const key = await apiRequest<ApiKeyResponse>(
    `users/me/api-keys/${keyId}/auto-rotate`,
    {
      method: "PATCH",
      headers: identityHeaders(userId),
      body: JSON.stringify({
        auto_rotate_enabled: enabled,
        auto_rotate_interval_days: enabled ? intervalDays : null,
      }),
    },
  );
  return mapApiKey(key);
}

export async function rotateApiKey(
  userId: string,
  keyId: string,
): Promise<CreatedApiKey> {
  const key = await apiRequest<ApiKeyResponse & { key: string }>(
    `users/me/api-keys/${keyId}/rotate`,
    {
      method: "POST",
      headers: identityHeaders(userId),
    },
  );
  return { ...mapApiKey(key), key: key.key };
}

export async function revokeApiKey(
  userId: string,
  keyId: string,
): Promise<void> {
  await apiRequest<{ id: string; revoked: boolean }>(
    `users/me/api-keys/${keyId}`,
    {
      method: "DELETE",
      headers: identityHeaders(userId),
    },
  );
}

export async function getApiKeyUsage(
  userId: string,
  keyId: string,
): Promise<ApiKeyUsage> {
  const usage = await apiRequest<{
    key_id: string;
    successful_requests: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    updated_at: string | null;
  }>(`users/me/api-keys/${keyId}/usage`, {
    headers: identityHeaders(userId),
  });
  return {
    keyId: usage.key_id,
    successfulRequests: usage.successful_requests,
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    totalTokens: usage.total_tokens,
    updatedAt: usage.updated_at,
  };
}
