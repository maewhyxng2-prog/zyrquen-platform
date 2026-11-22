# API Access

API keys authorize server-to-server requests to the ZYRQUEN Native Inference API. They do not authenticate browser sessions or grant access to profile, conversation, usage, or admin endpoints.

## Create and manage a key

Create keys while logged in with the normal session:

```http
POST /users/me/api-keys
Authorization: Bearer <session-token>
Content-Type: application/json

{
  "name": "worker",
  "expires_at": "2027-01-01T00:00:00Z"
}
```

The response contains the plaintext `key` once. The database stores only its SHA-256 digest. Copy it to a secret manager immediately; it cannot be retrieved later. `GET /users/me/api-keys` returns metadata only and is strictly read-only: listing keys never rotates or invalidates a credential. `GET /users/me/api-keys/{id}/usage` returns completed inference totals attributed to that key. `DELETE /users/me/api-keys/{id}` revokes an owned key; keys belonging to another user are indistinguishable from missing keys.

Keys are restricted to the `native:inference` scope and must have a timezone-aware future expiry. Revocation and expiry are checked on each inference request.

### Rotation behavior

A configured rotation interval records the next target date in key metadata; it does not silently replace a credential in a background request. When rotation is due, an authorized owner must explicitly call `POST /users/me/api-keys/{id}/rotate`. That response returns the replacement plaintext key once. Store it securely and update dependent services immediately; the previous key is invalidated by the rotation. The list endpoint never returns plaintext secrets.

Unattended rotation is intentionally not enabled until a secure one-time secret-delivery workflow is implemented. This avoids invalidating a production key when no safe channel exists to deliver its replacement.

## Native inference

Send the key as a Bearer credential directly to the configured ZYRQUEN API:

```http
POST /v1/native-ai/infer
Authorization: Bearer zyr_<secret>
Content-Type: application/json

{
  "prompt": "ข้อความที่ต้องการให้ Native Model ประมวลผล",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "max_tokens": 128
}
```

`POST /v1/native-ai/infer/stream` accepts the same authentication and requires a `conversation_id`. Inference is performed only by the locally configured ZYRQUEN Native Model. The `request_id` is required for idempotency; reusing it with different input returns `409`.

## Errors and limits

- `401`: missing, expired, revoked, or invalid credential.
- `403`: the authenticated account is inactive or lacks required authorization.
- `409`: request ID reused with different input or an already-used key revocation operation.
- `413`: request body exceeds the BFF's 64 KiB request limit.
- `422`: invalid input or request ID.
- `429`: the account's configured backend quota is exceeded; response details identify the limiting metric and backend-confirmed usage/limit.
- `429` on login: the account identifier exceeded the persistent failed-login threshold; `Retry-After` reports the cooldown.
- `503`: Native Model, database, tokenizer metrics, or quota policy is unavailable. Requests fail closed when no quota policy is active.

API keys share the owning user's quota and usage accounting. There is no separate per-key rate limit; inference is constrained by backend quota reservations. No quota plan or limit is created by issuing a key. The BFF is session-cookie based and does not forward API-key credentials; server clients should call the ZYRQUEN API directly over TLS. Never put keys in browser code, URLs, logs, or source control.
