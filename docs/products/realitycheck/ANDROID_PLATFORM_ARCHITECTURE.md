# RealityCheck Android Platform Architecture

- Status: implementation plan / first Android client slice
- Product: RealityCheck
- Module: RestoreProof
- Android package: `com.zyrquen.realitycheck`
- Backend: existing authenticated FastAPI service
- AI provider: existing ZYRQUEN Native AI only

## Product boundary

RealityCheck is a deterministic backup-verification product. The Android app is a native control client; it is not the restore engine. Backup inspection, isolated database restore, post-restore validation, evidence sealing, and cleanup must run on a separately provisioned backend worker.

The Android client must never:
- connect directly to production databases;
- execute shell commands or restore archives locally;
- declare PASS based on UI state, AI text, file presence, or checksum alone;
- invent metrics, run history, worker health, or evidence;
- silently retry or repeat a side-effecting operation.

## Existing repository capabilities to reuse

- FastAPI authentication: `/auth/login`, `/auth/me`, `/auth/logout`.
- Native model inference: `POST /v1/native-ai/infer`; provider is the repository's native runtime, and it may return unavailable when the model is not ready.
- Workflow engine: authenticated `/v1/workflows/runs`, run detail, cancellation, and approval endpoints.
- Existing workflow approval/audit infrastructure and `control_ops` queue.
- Existing SHA-256-only local verifier: `scripts/verify_backup_integrity.py`. It proves digest agreement only; it does not prove restore recoverability.

Do not duplicate authentication, workflow storage, approval gates, or tool audit infrastructure.

## Android application

Native Kotlin + Jetpack Compose APK. First client slice:
- configure an HTTPS API base URL;
- authenticate using the existing account endpoint;
- persist the bearer token using Android Keystore-backed encrypted preferences;
- read API health and authenticated workflow runs;
- send prompts to the existing ZYRQUEN Native AI inference endpoint;
- display backend/model unavailability honestly;
- never treat AI text as execution evidence.

Later RestoreProof screens must bind to dedicated backend resources and server-issued run IDs. A button must remain disabled unless the server advertises the required capability and target readiness.

## RestoreProof backend contract (next implementation gate)

Proposed versioned resources:
- `GET /v1/realitycheck/capabilities`
- `GET /v1/realitycheck/targets`
- `POST /v1/realitycheck/targets`
- `POST /v1/realitycheck/runs`
- `GET /v1/realitycheck/runs`
- `GET /v1/realitycheck/runs/{run_id}`
- `POST /v1/realitycheck/runs/{run_id}/cancel`
- `GET /v1/realitycheck/runs/{run_id}/evidence`
- `GET /v1/realitycheck/runs/{run_id}/evidence/export`

Required states: `QUEUED`, `RUNNING`, `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN`, `CANCELLED`.

Only the worker may issue a terminal verdict. Missing evidence, worker loss, timeout, unsupported format, digest mismatch, production-target detection, or cleanup failure must never become PASS. The API must return `BLOCKED` or `FAIL` with a machine-readable reason.

## AI Operations Assistant

The first Android slice uses the existing Native AI inference endpoint for explanations and operational guidance. It is not an autonomous agent and is not connected to a new external model API.

Tool execution is a separate, governed path:
1. AI may propose a structured action and explain why.
2. Backend validates the action against a server-side allowlist and the authenticated user's permissions.
3. Side-effecting operations require the existing approval gate where policy requires it.
4. Worker executes only the validated operation.
5. Evidence and final status come from the worker, never from AI-generated prose.

The model cannot approve its own action, bypass policy, choose arbitrary shell commands, or write PASS.

## Release gates

1. Android Gradle project compiles and produces a debug APK.
2. Login, token handling, health, workflows, and native inference work against a real configured backend.
3. API errors and native model unavailability are visible; no fixture data is shown as live.
4. RestoreProof worker is implemented and passes isolated integration/safety tests before Restore controls are enabled.
5. APK is installed and tested on a physical Android device.
