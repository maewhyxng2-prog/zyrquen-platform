# Cloud deployment preparation

This repository contains container build definitions and a local Compose stack.
It is **not deployed** to a cloud provider, and Compose is not a production
managed-services configuration.

## Application topology

- **Web:** build `apps/web/Dockerfile` from `apps/web/`. It serves the existing
  Next.js application and its same-origin backend proxy on port 3000.
- **API:** build `apps/api/Dockerfile` from the repository root:
  `docker build -f apps/api/Dockerfile -t zyrquen-api .`
- **Database:** the API requires `DATABASE_URL`. Production should use a managed
  PostgreSQL service with TLS and backups; the Compose PostgreSQL container is
  for local/single-host development only.
- **Model storage:** mount persistent storage at `/data/models` and set
  `ZYRQUEN_MODEL_PATH=/data/models/zyrquen-native-v1`. The mounted artifact must
  be readable by container UID 10001. No model is downloaded or bundled.
- **GPU/training:** no cloud GPU provider adapter is implemented. The current
  provisioner only detects GPUs on the machine where it runs.

Deploy the web and API images behind a TLS-enabled ingress with separate public
HTTPS hostnames, or route them through one HTTPS domain. Point the web service's
server-side `ZYRQUEN_API_BASE_URL` at the API HTTPS origin (or a private service
URL reachable from the web container). The browser calls the same-origin web
proxy, not the API directly, so this flow does not require permissive CORS.
Keep API ingress restricted to the web service and trusted operators where the
provider supports private networking.

## Runtime configuration and secrets

Configure these values through the cloud provider's secret/environment manager;
do not commit production values:

| Variable | Required configuration |
|---|---|
| `ZYRQUEN_API_BASE_URL` | Server-side API origin reachable by the web container. Use the deployed API's `https://` URL, or a provider-private service URL. Production rejects missing or loopback URLs. |
| `DATABASE_URL` | Managed PostgreSQL SQLAlchemy URL, e.g. `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB?sslmode=require`. URL-encode special characters in credentials. |
| `JWT_SECRET_KEY` | High-entropy secret stored in the provider secret manager. |
| `ZYRQUEN_MODEL_PATH` | Persistent mount path to the native model artifact; default deployment path is `/data/models/zyrquen-native-v1`. |
| `ZYRQUEN_TRAINING_ADMIN_EMAILS` | Comma-separated allowlist of authenticated administrator emails. Empty means training management is disabled. |
| `ZYRQUEN_DATASET_DIR` | Directory containing the prepared dataset manifest and train/validation splits. |
| `ZYRQUEN_TOKENIZER_PATH` | Path to the matching ZYRQUEN tokenizer JSON artifact. |
| `ZYRQUEN_TRAINING_ROOT` | Persistent output directory for per-run telemetry and checkpoints; default `/data/training`. |

`NODE_ENV=production`, `PORT`, and the web bind address are set by the web
container. `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are only for
the local Compose database and should not replace managed PostgreSQL credentials.

The web/API images run as non-root. Configure volume ownership/permissions for
UID 1001 on the web container if persistent web storage is ever added, and UID
10001 for API model, dataset, tokenizer, and training mounts.

## Health checks and readiness

- Web container liveness: `GET /api/session`.
- API container liveness: existing `GET /health`.
- Native runtime readiness: existing `GET /v1/native-ai/health`.

An API health response does not imply the native model is ready. The current
image does not install PyTorch/Transformers and the repository has no production
native-model artifact, so native inference must remain unavailable until those
runtime dependencies and a ZYRQUEN-trained artifact are provisioned and verified.
Do not substitute or download an external model.

Training job endpoints are admin-allowlisted and return 503 until a CUDA-enabled
PyTorch runtime, attached NVIDIA GPU, verified dataset, and tokenizer are
available. Jobs run in a single API process; deploy one API worker/replica for
this initial dispatcher. The native training loop reports steps, not epochs,
and telemetry reports epochs as unavailable rather than deriving them.

Before starting the API, apply the additive training schema migration against a
database that already has the existing `users` table:

```bash
DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DB?sslmode=require' \
  alembic -c apps/api/alembic.ini upgrade head
```

The migration adds `training_runs` and does not alter `users`. This repository
does not yet contain a baseline migration for the existing authentication
schema.

## Production blockers

Before a real deployment can be attempted, an operator must select and provide:

1. A cloud provider, account/project, region, container registry, and deployment
   service for the web and API images.
2. Public DNS domains and TLS ingress/certificates.
3. Managed PostgreSQL service and production `DATABASE_URL`.
4. Persistent model storage, appropriate permissions, and a verified native
   model artifact.
5. Secret-manager values for `JWT_SECRET_KEY` and service configuration.
6. Apply the included `training_runs` migration after provisioning the existing
   `users` table. A baseline migration for the authentication schema is still
   absent.
7. For cloud training, a GPU provider and explicit approval for any paid
   compute. No cloud GPU integration exists yet.

No public URLs, cloud credentials, provider account, managed database, TLS
domain, persistent cloud volume, or GPU service are configured in this
repository. Do not treat local container builds or tests as online deployment
verification.
