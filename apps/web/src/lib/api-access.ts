import { apiRequest } from "./api";
import type { ApiKeyMetadata, ApiKeyUsage, CreatedApiKey } from "./types";

type ApiKeyResponse = {
  id: string;
  name: string;
  key_prefix: string;
  scope: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
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
  };
}

function identityHeaders(userId: string): HeadersInit {
  return { "X-Zyrquen-Expected-User-ID": userId };
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
): Promise<CreatedApiKey> {
  const key = await apiRequest<ApiKeyResponse & { key: string }>(
    "users/me/api-keys",
    {
      method: "POST",
      headers: identityHeaders(userId),
      body: JSON.stringify({ name, expires_at: expiresAt }),
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
