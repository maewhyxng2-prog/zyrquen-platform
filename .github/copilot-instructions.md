# ZYRQUEN platform repository guide

## Repository layout and runtime boundaries

- `apps/api/` is the FastAPI application. `main.py` owns app startup and route registration; `routers/` owns HTTP operations; `database.py`, `models.py`, and `schemas.py` own SQLAlchemy/Pydantic data types.
- `apps/core/` is the native AI runtime and training infrastructure. `runtime.py` is the process-wide loader/health facade; `inference.py` performs timed, serialized generation; `model_loader.py` loads a local Hugging Face-compatible artifact.
- `apps/core/native/` is the independent model implementation: byte-level tokenizer, Transformer model, dataset preparation, and training loop.
- `apps/core/training_infrastructure/` contains cost control, GPU/resource handling, distributed configuration, monitoring, checkpoint recovery, and model validation.
- `docker-compose.yml` is the local API plus PostgreSQL stack. The Docker build context is the repository root because the image copies both `apps/api` and `apps/core`.
- `ARCHITECTURE.md` is the authority for platform boundaries and implementation discipline. Treat it as an architecture specification, not proof that every described subsystem exists.

## Environment and Python import paths

The API requires environment variables at import/runtime:

- `DATABASE_URL` is required by `apps/api/database.py`.
- `JWT_SECRET_KEY` is required to create or validate bearer tokens.
- `ZYRQUEN_MODEL_PATH` selects the local model directory. It defaults to `models/zyrquen-native-v1` for non-Docker runs.

Run Python commands from the repository root with both import roots:

```bash
export PYTHONPATH="$PWD:$PWD/apps/api"
export DATABASE_URL="sqlite:///./test.db"
export JWT_SECRET_KEY="test-secret"
```

The split import layout is intentional: API modules use top-level imports such as `from database import Base`, `from routers.auth import router`, and `from models import User`, while core modules use package imports such as `from apps.core.runtime import runtime`. Keep these forms consistent when adding modules.

The `.env.example` template is the source of Compose variable names:

```bash
cp .env.example .env
docker compose up --build
```

## Build and test commands

Install API test dependencies with:

```bash
python -m pip install --upgrade pip
python -m pip install -r apps/api/requirements.txt
```

API tests require `DATABASE_URL` and `PYTHONPATH` as above:

```bash
PYTHONPATH="$PWD:$PWD/apps/api" DATABASE_URL="sqlite:///./test.db" JWT_SECRET_KEY="test-secret" \
  pytest -v apps/api/test_main.py
```

Run the API test directory:

```bash
cd apps/api
PYTHONPATH="$PWD/../..:$PWD" DATABASE_URL="sqlite:///./test.db" JWT_SECRET_KEY="test-secret" pytest -v
```

Run the whole repository suite from the root:

```bash
PYTHONPATH="$PWD:$PWD/apps/api" DATABASE_URL="sqlite:///./test.db" JWT_SECRET_KEY="test-secret" pytest -v
```

PyTorch tests use `pytest.importorskip("torch")`, so missing PyTorch makes them skip rather than fail collection. Run a native test file directly, for example:

```bash
pytest -v apps/core/native/test_tokenizer.py
pytest -v apps/core/native/test_dataset.py
pytest -v apps/core/training_infrastructure/test_training_infrastructure.py
```

Run one test function with node selection:

```bash
pytest -v apps/core/native/test_tokenizer.py::test_roundtrip
pytest -v apps/core/native/test_train_torch.py::test_resume_continues_from_checkpoint
pytest -v apps/api/test_main.py::test_health
```

The GitHub Actions test job uses Python 3.12, installs `apps/api/requirements.txt`, runs `pytest -v` from `apps/api`, and separately runs `pytest -v apps/core/native/test_tokenizer.py` from the root.

Build and run the container stack with:

```bash
docker compose up --build
```

Build only the API image from the repository root:

```bash
docker build -f apps/api/Dockerfile -t zyrquen-api:test .
```

There is currently no configured formatter or linter command in the repository.

## Architecture and implementation patterns

- API startup calls `runtime.initialize()` asynchronously and starts in degraded mode if no native model artifact is available. `/health` reports API health plus native runtime health; `/v1/native-ai/infer` returns 503 until the runtime is ready.
- Authentication creates a 30-minute HS256 bearer token containing the SQLAlchemy user UUID. Protected routes depend on `get_current_user`; passwords use passlib bcrypt and emails are normalized to lowercase.
- Native inference constructs `InferenceContext`, enforces API/request bounds, and uses `NativeInferenceEngine` to serialize generation, run it off the event loop, and enforce a 30-second timeout.
- `NativeModelLoader` uses `local_files_only=True` and `trust_remote_code=False`. It reports CPU or CUDA availability but intentionally does not fall back to external providers.
- The tokenizer is the `ZyrquenTokenizer` byte-level BPE implementation in `apps/core/native/tokenizer.py`; it normalizes text with NFC, persists a schema/fingerprint, and has no dependency outside the Python standard library.
- Dataset preparation is deterministic and manifests integrity. `prepare_dataset()` validates declared source licences, cleans/redacts PII, filters and deduplicates documents, assigns stable train/validation/test splits, and writes SHA-256 metadata; `load_split()` verifies files before reading them.
- Training inputs use IDs with next-token targets. The training loop supports learning-rate warmup/cosine decay, gradient accumulation/clipping, loss monitoring, checkpoint resume, cost limits, and checkpoint pruning.
- Training and model artifact outputs (`checkpoints/`, `runs/`, `artifacts/`, model weights) are local/cloud-volume state and must not be committed.

## Codebase conventions

- Keep provider-specific or external model integrations behind replaceable loader/backend interfaces; `NativeRuntime` and `NativeInferenceEngine` are the in-process boundary.
- Add Pydantic request bounds in `apps/api/routers/` and preserve matching runtime bounds in `InferenceContext`; do not rely on database or model code for HTTP validation.
- Keep SQLAlchemy models thin and database setup centralized in `apps/api/database.py`. Alembic is listed as a dependency, but no migration setup or initial schema is currently implemented.
- Preserve the two import modes documented above. Do not change API modules to use `apps.api.*` internally unless the Docker and pytest import paths are updated together.
- Native data and model code should be independently testable without network access. Torch-dependent tests belong in files and must use `pytest.importorskip("torch")` when they are optional in this environment.
- Dataset source entries require a non-empty licence declaration. PII redaction is pattern-based and must not be described as a privacy guarantee.
- Use deterministic IDs/random seeds and persisted manifests/fingerprints for corpus, tokenizer, and checkpoint behavior. Preserve the existing checkpoint and RNG restoration interfaces.
- Never add real secrets or model weights to source control. Use `.env.example` as the configuration template and keep `.env`, databases, caches, checkpoints, and weights ignored as defined in `.gitignore`.
