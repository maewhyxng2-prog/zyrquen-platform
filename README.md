# ZYRQUEN Ω∞

Software for an AI platform under development. The repository includes a web
client, API, native-model infrastructure, and contract-level intelligence
components; it does not include trained model weights or prove production
readiness.

<picture>
  <source media="(forced-colors: active)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <img src="apps/web/public/zyrquen-logo.svg" width="640" height="128" alt="ZYRQUEN animated geometric logo">
</picture>

The logo is native vector SVG with CSS motion and a `prefers-reduced-motion`
fallback. See the [brand assets](#brand-assets) for icon and monochrome variants.

## Status by evidence

| Category | Current status |
| --- | --- |
| **Implemented** | Next.js web application; FastAPI routes for account access, inference, conversations, usage, training/evaluation, and administration; native tokenizer/model/training source; Phase 9 intelligence contracts. |
| **Validated** | Phase 9 contract tests and SVG safety/accessibility checks are run separately. The complete repository suite still has known failures; see [verification](#verification). |
| **Blocked** | Native inference requires a local compatible model artifact, which is not included. Production database concurrency/migrations and public deployment require separately provisioned, approved infrastructure. |
| **Not implemented** | A trained ZYRQUEN model, model-backed reasoning or learning, real tool execution, generated-code execution, application file creation/build, and public cloud deployment. |

Implemented source code does not by itself mean a feature is operational or
validated. The [Phase 9 status](docs/PHASE_9_STATUS.md) distinguishes contract
validation from model capability. The [known limitations](docs/operations/KNOWN_LIMITATIONS.md)
document tracks production blockers.

## Architecture at a glance

| Layer | Repository location | Current boundary |
| --- | --- | --- |
| Web client | `apps/web/` | Next.js dashboard, login, workspace, settings, and status views. |
| API | `apps/api/` | FastAPI routes, authentication, authorization, quotas, and database access. |
| Native runtime | `apps/core/` | Local model loader/runtime, tokenizer, dataset and training code. Inference is unavailable without a compatible local artifact. |
| Intelligence contracts | `apps/core/intelligence/` | Knowledge lookup, structural reasoning/planning, feedback, permission, coding/application contracts, evaluation evidence, and contract-level integration. Not model-backed. |
| Infrastructure | `docker-compose.yml`, `apps/api/Dockerfile` | Local/single-host container configuration; not proof of a cloud deployment. |

Browser requests go through an allowlisted same-origin Next.js proxy before
reaching the FastAPI service. Phase 9's `IntelligenceRuntime` is a software
contract layer; it is not connected as a native model reasoning engine.

## Roadmap

- **Current:** stabilize and verify the existing web/API and native-core code;
  close the production blockers listed in
  [known limitations](docs/operations/KNOWN_LIMITATIONS.md).
- **Native model:** prepare data and training infrastructure, then train and
  evaluate an actual model artifact before claiming native intelligence.
- **Intelligence:** evolve Phase 9 contracts only after trusted evidence,
  permissions, and safe execution backends exist.
- **Production:** validate PostgreSQL migrations/concurrency, then provision and
  test a real deployment; none is currently claimed.

See the [development roadmap](docs/roadmap/01_ZYRQUEN_Roadmap.md) and
[next-steps snapshot](docs/NEXT_STEPS_STATUS.md) for additional context.

## Brand assets

All assets are transparent, hand-authored vector SVGs with no embedded bitmap,
script, or external resource:

| Asset | Color | Monochrome |
| --- | --- | --- |
| Animated lockup | [zyrquen-logo.svg](apps/web/public/zyrquen-logo.svg) | [zyrquen-logo-mono.svg](apps/web/public/zyrquen-logo-mono.svg) |
| Animated symbol | [zyrquen-icon.svg](apps/web/public/zyrquen-icon.svg) | [zyrquen-icon-mono.svg](apps/web/public/zyrquen-icon-mono.svg) |
| Wordmark | [zyrquen-wordmark.svg](apps/web/public/zyrquen-wordmark.svg) | [zyrquen-wordmark-mono.svg](apps/web/public/zyrquen-wordmark-mono.svg) |

The icon is used in the dashboard, login header, and browser tab. Motion is
disabled by each animated SVG when the operating system requests reduced motion.
Monochrome assets use the system text color for dark mode and forced-colors mode.

## Repository contents

- `apps/web/`: Next.js App Router frontend for login, the AI workspace, account
  settings, training/evaluation views, and administration.
- `apps/api/`: FastAPI service for authentication, native inference and
  streaming, conversations, usage and quota enforcement, API keys, training,
  evaluation, and admin operations.
- `apps/core/`: Native model runtime, inference, evaluation, tokenizer,
  dataset, training, and resource-management code.
- `apps/api/migrations/`: Alembic schema changes. Migrations are guarded and
  require an explicitly identified Test database; they are not run on API
  startup.
- `docker-compose.yml`: local Web, API, and PostgreSQL services.

The API uses a configured local ZYRQUEN model artifact. Model weights are not
included in this repository. Without a loadable artifact, the API can start in
degraded mode, but native inference is unavailable. Inference also fails closed
when the account has no active quota policy.

## Local development

### Web application

From the repository root:

```bash
npm install
cp apps/web/.env.example apps/web/.env.local
npm run dev
```

The web server defaults to `http://localhost:8000` as its API origin in
development. Set `ZYRQUEN_API_BASE_URL` in `apps/web/.env.local` if the API is
running elsewhere. Browser requests use the same-origin Next.js proxy.

### API

Install the API dependencies, then configure the environment for an approved
database target before starting the service:

```bash
python -m pip install -r apps/api/requirements.txt
export PYTHONPATH="$PWD:$PWD/apps/api"
export ZYRQUEN_ENV=development
export DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<database>
export ZYRQUEN_DEVELOPMENT_DATABASE_HOST=<host>
export ZYRQUEN_DEVELOPMENT_DATABASE_PORT=<port>
export ZYRQUEN_DEVELOPMENT_DATABASE_NAME=<database>
export JWT_SECRET_KEY=<server-secret>
uvicorn apps.api.main:app --reload
```

The API validates that the PostgreSQL URL matches the declared environment
host, port, and database name. It rejects SQLite outside `unit_test` and
rejects unapproved database targets. The service exposes `/health` and the
interactive API schema at `/docs`.

The API does not automatically create database tables or apply migrations.
Its Alembic environment permits migrations only against a Test database whose
identity is explicitly verified. Do not point migration commands at production.

### Local Compose stack

Configure the required values in a local, untracked `.env` file, then run:

```bash
docker compose up --build
```

The stack exposes the web application on port `3000` and API on port `8000`.
Compose does not install model weights or apply database migrations.

## Trusted admin bootstrap

Newly registered users receive the `user` role. Admin authorization uses the
role loaded from the database, never a client-supplied role or JWT claim.
Bootstrap an existing account using a comma-separated list of trusted user
UUIDs supplied only to the backend:

```bash
export ZYRQUEN_ADMIN_USER_IDS=<user-uuid>[,<user-uuid>...]
python -m apps.api.admin_bootstrap
```

The command fails if the setting is empty, malformed, or references a user
that does not exist. Keep this setting out of browser configuration and source
control.

## Login proxy configuration

By default, login throttling uses the direct peer IP and ignores
`X-Forwarded-For`. Configure `ZYRQUEN_TRUSTED_PROXY_IPS` with the exact trusted
proxy IPs/CIDRs before forwarded addresses are considered. The proxy must
append or replace forwarded client addresses correctly; never allow clients
to connect as a trusted proxy or pass through an unsanitized forwarded header.

Login failures are limited per account identifier and globally per derived
client IP. Failed-login responses do not disclose whether an account exists.

## Verification

The Phase 9 contract suite and SVG asset checks:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:$PWD/apps/api" pytest -q tests
```

Web tests and static checks (dependencies are managed by the root npm workspace):

```bash
npm run test
npm run typecheck
npm run lint
npm run build
```

API and native Python tests from the repository root:

```bash
PYTHONPATH="$PWD:$PWD/apps/api" \
PYTHON_DOTENV_DISABLED=1 \
DATABASE_URL=sqlite:///./test.db \
ZYRQUEN_ENV=unit_test \
JWT_SECRET_KEY=test-secret \
python -m pytest -v apps/api apps/core/test_*.py apps/core/native \
  apps/core/training_infrastructure apps/core/training
```

SQLite is used only for unit tests. PostgreSQL-specific migration and
row-locking behavior must be validated against an explicitly identified
non-production Test database. Native PyTorch-dependent tests may be skipped
when PyTorch is not installed.

The full repository suite is not currently all-green: the known failures are
`apps/api/test_auth_gate.py::test_multi_user_isolation_and_backend_authorization`
(the test passes an unsupported `user_id` to `EvaluationRun`) and four tests in
`apps/core/native/test_evaluation.py` (the tests pass unsupported
`max_val_loss`/`max_perplexity` constructor arguments). These are outside the
Phase 9 and branding changes.

## Phase 7 production operations

The repository now contains production-oriented health, structured logging,
container, CI, security, and recovery documentation. For operators, use:

- `docs/operations/PRODUCTION_OPERATIONS.md`
- `docs/operations/DEPLOYMENT_READINESS.md`
- `docs/operations/HEALTH_READINESS.md`
- `docs/operations/LOGGING_MONITORING.md`
- `docs/operations/BACKUP_RECOVERY_RUNBOOK.md`
- `docs/operations/INCIDENT_RESPONSE_RUNBOOK.md`
- `docs/operations/CONFIGURATION_REFERENCE.md`
- `docs/operations/SECURITY_OPERATIONS_CHECKLIST.md`
- `docs/operations/KNOWN_LIMITATIONS.md`

Operational endpoints:

- `GET /livez` — process liveness only; does not probe dependencies.
- `GET /readyz` — real database and native-runtime readiness probe.
- `GET /health` — backward-compatible aggregate dependency health.

`/readyz` is intended for orchestration readiness. A not-loaded native model
is reported as `not_configured` or `degraded`; it is never fabricated as
healthy. Database readiness executes a real local connection check and is not
an inferred configuration check.

Phase 7 implementation does not establish that the platform is deployed or
production-ready. PostgreSQL concurrency, safe Test PostgreSQL migrations,
and production-like HTTP/multi-user testing remain separate blockers.
