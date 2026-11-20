# ZYRQUEN Ω∞

Independent online AI platform and native intelligence infrastructure.

## What is in this repository

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

The API uses the configured local ZYRQUEN model artifact. Model weights are
not included in this repository. Without a loadable artifact, the API can start
in degraded mode, but native inference is unavailable. Inference also fails
closed when the account has no active quota policy.

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

## Checks

Web tests and static checks:

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
