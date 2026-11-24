# V10-D Live API/Runner Governance Verification

## Purpose

This is a read-only verification of the live FastAPI process and the Colab/runner process before any V10-D workflow run is created. It does not create a workflow, issue approval, invoke a handler, train, write checkpoints, or modify the registry.

## Required API process environment

Configure these values in the API service environment before restarting the API:

- `ZYRQUEN_V10D_APPROVAL_ENABLED=1`
- `ZYRQUEN_WORKFLOW_DB_PATH`: the persistent SQLite path shared with the runner
- `ZYRQUEN_APPROVAL_SECRET`: the same high-entropy secret configured in the runner

The API diagnostics endpoint is admin-only:

`GET /v1/workflows/governance/diagnostics`

It returns the canonical DB-path fingerprint and a SHA-256 secret fingerprint, never the secret itself. It also checks that the live API engine uses the configured DB, that the required workflow tables exist, that the V10-D workflow definition and handlers are registered, and that the workflow engine has started.

## Required runner environment

In the Colab/runner process, configure the same:

- `ZYRQUEN_WORKFLOW_DB_PATH`
- `ZYRQUEN_APPROVAL_SECRET`
- `ZYRQUEN_API_BASE_URL`: reachable API origin, for example `https://api.example.invalid`
- `ZYRQUEN_ADMIN_BEARER_TOKEN`: a short-lived admin access token, supplied through Colab Secrets/environment; never paste it into source or chat

Do not print or share the bearer token or approval secret.

## Run

From the repository root:

```bash
python -m compileall -q apps/core/workflow/governance_diagnostics.py apps/api/routers/workflows.py tools/verify_v10d_governance.py tests/test_v10d_governance_diagnostics.py
python -m unittest discover -s tests -p "test_v10d_governance_diagnostics.py" -v
python tools/verify_v10d_governance.py
```

Expected success is `overall_status: PASS` and all checks true. A 401/403 means the API token is missing, expired, or not an admin token. A DB-path or secret fingerprint mismatch means the API and runner are not configured with matching governance inputs. A missing API endpoint means the API has not yet deployed this revision and restarted.

## Security and execution boundary

- The endpoint requires authenticated Admin access.
- The secret itself is never returned.
- SQLite inspection uses `mode=ro` and `PRAGMA query_only=ON`.
- The verifier only issues an HTTP GET.
- No approval is created or consumed.
- No workflow run is created.
- No training or optimizer step can be invoked by this verifier.
- A PASS establishes configuration consistency and workflow registration only. It does not establish training readiness, issue Tier-2 approval, or prove trained model capability.

After this verification passes, a separate review must confirm the exact training payload and model configuration. Only an authenticated Admin decision through the API can issue Tier-2 approval.
