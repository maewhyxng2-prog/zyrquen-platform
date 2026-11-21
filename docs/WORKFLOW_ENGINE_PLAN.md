# ZYRQUEN Ω∞ — Central Native Workflow Engine Implementation Plan

- **Document Status:** `PROPOSAL FOR OWNER REVIEW & APPROVAL — NO WORKFLOW ENGINE CODE IMPLEMENTED YET`
- **Repository:** `maewhyxng2-prog/zyrquen-platform`
- **Core Architectural Mandate:** **One Central Native Workflow Engine** (`apps/core/workflow/`) serving all 8 workflow groups (`system_ops`, `data`, `training`, `evaluation`, `knowledge_memory`, `improvement_proposal`, `security_governance`, `project_dev`). No duplicate per-module schedulers or ad-hoc orchestration loops.
- **Native Intelligence Boundary:** The Workflow Engine is **supporting automation and governance infrastructure**. It must **never** substitute for ZYRQUEN's native model, never call or hide external LLMs as ZYRQUEN's intelligence, and never mark `NOT RUN`, `BLOCKED`, or unverified operations as `PASS`.

---

## 1. System Architecture

### 1.1 Reuse Audit of Existing Modules (Zero Duplication)
| Existing Module | Verified Capabilities Already in Repo | Integration Role in Central Workflow Engine |
|---|---|---|
| `apps/api/operations.py` | `database_readiness`, `aggregate_readiness`, `validate_security_configuration`, `JsonFormatter`, `redact_sensitive_text` | Wrapped by **System Operations**, **Security Audit**, and **Audit Redaction** |
| `apps/core/runtime.py` | `NativeRuntime.get_health_status` (reads real `ModelRegistry` and `ZYRQUEN_EVAL_REPORT_PATH` evidence) | Live runtime health probe & capability telemetry source |
| `apps/core/resource.py` | `ResourceManager` (`snapshot`, `check_request` for RAM, VRAM, tokens, elapsed seconds) | Extended with CPU load & disk checks inside **Resource Manager** |
| `apps/core/training/orchestrator.py` | `TrainingOrchestrator` (`prepare`, `run`), CPU bounds (`5M` params, `256` seq, `4` batch, `1000` steps) | Invoked as the **Native Training** step executor |
| `apps/core/training/cost_limits.py` | `cost_controller_from_env`, `CostController`, `CostLimits` | Enforced pre-flight and per-step by Resource Manager |
| `apps/api/training_jobs.py` | `TrainingJobService` (`ThreadPoolExecutor(max_workers=1)`, `TrainingRun` DB persistence, `ModelRegistry` registration) | Routed through the `compute_heavy` worker lane |
| `apps/api/routers/training.py` | `require_training_admin`, `TrainingRunRequest`, `CheckpointManager`, `TrainingMonitor` | Preserved and unified under workflow run tracking & approvals |
| `apps/api/evaluation_service.py` & `routers/evaluation.py` | `EvaluationRun` DB records & `EvaluationEngine` | Triggered automatically by `training.completed` events |
| `apps/core/native/dataset.py` | `prepare_dataset`, `load_split`, `SCHEMA = "zyrquen.dataset-manifest.v1"` | Wrapped by **Data Workflow** validation, PII masking & hashing |
| `apps/core/native/train.py` | Deterministic token streams, warmup/cosine schedule, checkpoint hooks | Legacy native trainer utilities shared cleanly |
| `apps/core/native/registry.py` | `ModelRegistry` (`fcntl.flock`, atomic O_EXCL reservation, SHA-256 verify, immutable `artifacts/<version>/`, `promote`, `rollback`) | Core store extended for **Model Lifecycle & Promotion Gate** |
| `tools/audit_leakage_v9.py` | 4-layer zero-tolerance leakage gate (`EL-01..EL-08`, `TL-01`, `SL-01`, `DL-01`, `SEQ_BUDGET`) | Mandatory pre-training **Data Leakage Gate** |
| `tools/train_nagi_v9.py` & `eval_nagi_v9.py` | Controlled 4-Arm v9 training + TF/FG evaluation + 6 Principle Probes + regression comparison | Pluggable v9 experiment training/evaluation handlers |
| `phases/phase11.py` – `phase20.py` | Pure-logic contracts (`CapabilityRegistry`, `validate_dag`, `ExecutionSafetyPolicy`, `MemoryStore`, `AdaptiveLearning`, `SafetyGovernance`, `SystemMaturity`) | Kept untouched; pure contracts adapted into persistent workflow services |

### 1.2 Target Module Layout
```text
apps/
├── core/
│   └── workflow/                       # [PROPOSED — Single Central Workflow Engine]
│       ├── __init__.py
│       ├── models.py                   # WorkflowDefinition, WorkflowStep, RunState, StepEvidence
│       ├── registry.py                 # Versioned WorkflowRegistry across the 8 groups
│       ├── dag.py                      # Kahn/DFS topological validation & cycle rejection
│       ├── triggers.py                 # EventBus + single CentralScheduler (DB lease lock)
│       ├── queue.py                    # Dual-lane Task Queue (compute_heavy vs control_ops)
│       ├── recovery.py                 # Per-step checkpointing, bounded retry, startup reconcile
│       ├── resource_guard.py           # CPU / RAM / GPU / Disk + CostLimits gate
│       ├── governance.py               # 2-Tier Permission policy + single-use HMAC Approval Gate
│       ├── audit.py                    # Append-only redacted audit trail writer
│       ├── orchestrator.py             # CentralWorkflowOrchestrator state machine
│       └── handlers/                   # 8 thin adapters to existing ZYRQUEN modules
│           ├── system_ops.py
│           ├── data_pipeline.py
│           ├── native_training.py
│           ├── evaluation.py
│           ├── knowledge_memory.py
│           ├── autonomous_improvement.py
│           ├── security_governance.py
│           └── project_dev.py
├── api/
│   ├── workflow_models.py              # [PROPOSED] 5 SQLAlchemy tables
│   ├── workflow_schemas.py             # [PROPOSED] Pydantic request/response schemas
│   ├── workflow_service.py             # [PROPOSED] Transactional queries & approval issuance
│   ├── migrations/versions/
│   │   └── 20261121_08_workflow_engine.py  # [PROPOSED] Alembic down_revision="20261120_07"
│   └── routers/
│       └── workflows.py                # [PROPOSED] RBAC-protected /v1/workflows/* endpoints
```

---

## 2. Workflow Schema & Persistence

Alembic migration `20261121_08_workflow_engine.py` (`down_revision = "20261120_07"`, following `apps/api/migrations/versions/20261120_07_login_rate_limits.py`) introduces 5 tables:

1. **`workflow_definitions`**
   - Columns: `id` (UUID PK), `workflow_key` (`String(64)`), `version` (`String(32)`), `group_name` (`String(32)`), `dag_spec` (`JSON`), `default_tier` (`String(16)`), `is_active` (`Boolean`), `created_at` (`DateTime(tz)`).
   - Constraint: `UniqueConstraint("workflow_key", "version")` — guarantees **Workflow Versioning** and reproducible execution of historical runs.
2. **`workflow_runs`**
   - Columns: `id` (UUID PK), `workflow_key` (`String(64)`), `workflow_version` (`String(32)`), `trigger_type` (`event | schedule | condition | manual`), `trigger_dedup_key` (`String(128)` nullable unique), `trigger_payload` (`JSON`), `status` (`String(24)` indexed), `priority` (`Integer`), `requested_by_user_id` (`UUID FK -> users.id` nullable for scheduler/system triggers), `checkpoint_cursor` (`JSON` nullable), `resource_snapshot` (`JSON` nullable), `error_message` (`Text` nullable), `created_at`, `started_at`, `finished_at`.
3. **`workflow_step_runs`**
   - Columns: `id` (UUID PK), `run_id` (`UUID FK -> workflow_runs.id ON DELETE CASCADE`), `step_key` (`String(64)`), `depends_on` (`JSON`), `lane` (`control_ops | compute_heavy`), `status` (`String(24)`), `attempt` (`Integer`), `max_attempts` (`Integer`), `next_retry_at` (`DateTime(tz)` nullable), `evidence` (`JSON` nullable), `output` (`JSON` nullable), `error_code` (`String(64)` nullable), `started_at`, `finished_at`.
   - Constraint: `UniqueConstraint("run_id", "step_key")`.
4. **`workflow_approvals`**
   - Columns: `id` (UUID PK), `run_id` (`UUID FK -> workflow_runs.id`), `step_key` (`String(64)`), `action_type` (`String(64)`), `scope` (`String(255)`), `requested_by_user_id` (`UUID FK -> users.id` nullable), `approved_by_user_id` (`UUID FK -> users.id` nullable), `status` (`pending | approved | rejected | expired | consumed`), `signature_hmac` (`String(128)` nullable), `expires_at` (`DateTime(tz)`), `consumed_at` (`DateTime(tz)` nullable), `reason` (`Text`), `created_at`.
5. **`workflow_audit_logs`**
   - Columns: `id` (UUID PK), `run_id` (`UUID` nullable indexed), `step_key` (`String(64)` nullable), `actor_id` (`String(64)`), `event_type` (`String(64)`), `resource` (`String(255)`), `decision` (`String(32)`), `details` (`JSON`), `created_at` (`DateTime(tz)` indexed).
   - Append-only table; all free-text fields pass `apps/api/operations.py::redact_sensitive_text` before commit.

---

## 3. Central Orchestrator

`CentralWorkflowOrchestrator` (`apps/core/workflow/orchestrator.py`) manages the single canonical state machine for every run across all 8 groups:

```text
Trigger (Event / Schedule / Condition / Manual)
   │
   ▼
WorkflowRegistry Lookup (workflow_key + semantic version)
   │
   ▼
DAG & Schema Validation ──[invalid]──▶ FAILED + Audit
   │ [valid]
   ▼
Resource Guard (CPU / RAM / GPU / Disk / CostLimits) ──[insufficient]──▶ WAITING_RESOURCE
   │ [ok]
   ▼
Permission & Approval Gate
   ├── Tier 1 (Auto-Allowed) ───────────────────────────────────────────────┐
   └── Tier 2 (Human Gate) ──▶ WAITING_APPROVAL (pending HMAC approval) ────┤
   ┌────────────────────────────────────────────────────────────────────────┘
   ▼
Dispatch Step to Lane (compute_heavy | control_ops)
   │
   ▼
Verify Evidence (PASS / FAIL / BLOCKED / NOT RUN — never infer PASS on missing proof)
   ├── [PASS] ────────▶ Persist checkpoint_cursor -> Advance DAG -> Emit next Event
   ├── [TRANSIENT] ───▶ Schedule Retry (bounded backoff)
   └── [FATAL / GATE] ▶ Transition FAILED or BLOCKED + Audit Alert + Safe Halt
```

- **Canonical Run Statuses:** `PENDING`, `WAITING_RESOURCE`, `WAITING_APPROVAL`, `RUNNING`, `VERIFYING`, `COMPLETED`, `FAILED`, `BLOCKED`, `CANCELLED`.
- **Canonical Verification Verdicts:** `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`.

---

## 4. Event Trigger & Scheduler

1. **Unified `EventBus` (`apps/core/workflow/triggers.py`):**
   - Translates domain events (`api.startup`, `dataset.ingested`, `data.ready`, `training.completed`, `evaluation.completed`, `health.degraded`, `auth.anomaly`, `file.modified`) into idempotent `workflow_runs` using `trigger_dedup_key` to prevent duplicate trigger storms.
2. **Single `CentralScheduler`:**
   - One background loop inside the API/worker process protected by a DB/file lease (`scheduler_lock`) so multi-worker deployments do not fire duplicate cron runs.
   - Manages periodic workflows (`system_ops.daily_health`, `security.integrity_audit`, `project_dev.drift_check`).
   - Condition triggers (e.g., disk free `< 10%` or elevated 5xx/auth-fail rate) evaluate inside `system_ops` / `security_governance` checks and emit events onto the same `EventBus`.

---

## 5. Dependency Graph & Task Queue

1. **DAG Validation (`apps/core/workflow/dag.py`):**
   - Validates `dag_spec` at registration and pre-execution using Kahn's topological sort + cycle detection (aligned with `phases/phase16.py::validate_dag`). Cyclic or dangling dependencies are rejected fail-closed.
   - Supports conditional branching edges (e.g., `eval_gate == PASS -> promote_staging`, `eval_gate == FAIL -> quarantine_version`).
2. **Dual-Lane Task Queue (`apps/core/workflow/queue.py`):**
   - **`compute_heavy` lane (`max_workers=1` on CPU):** Serializes `TrainingOrchestrator`, `train_nagi_v9`, and full `EvaluationEngine` / `eval_nagi_v9` runs, replacing standalone worker logic in `TrainingJobService` while preserving concurrency safety.
   - **`control_ops` lane (`max_workers=2`):** Executes lightweight diagnostics, leakage audits, security checks, and repo drift audits immediately without blocking behind long training jobs.

---

## 6. Retry / Recovery / Checkpoint

1. **Per-Step Checkpointing (`apps/core/workflow/recovery.py`):**
   - After every step succeeds and passes verification, `workflow_step_runs` commits `status="COMPLETED"`, `output`, and `evidence` hash, and updates `workflow_runs.checkpoint_cursor`.
2. **Startup Reconciliation:**
   - On process restart, `recovery.py` scans any `workflow_runs` left in `RUNNING` or `VERIFYING` without an active worker (replacing ad-hoc `_reconcile_run` in `apps/api/routers/training.py` across all workflow types).
   - Resumable workflows pick up from the next incomplete DAG step; training steps pass `--resume` pointing to the latest SHA-256 verified checkpoint (`CheckpointManager` or `last.pt`).
3. **Retry Policy & Non-Retryable Failures:**
   - Transient I/O / DB lock contention errors retry with exponential backoff up to `max_attempts` (default `3`).
   - `OutOfMemoryError`, `NaNInfLossError`, `LeakageGateFailed`, `ChecksumMismatchError`, and `ApprovalViolationError` are strictly **non-retryable** and immediately halt into `FAILED` or `BLOCKED`.

---

## 7. CPU / GPU / RAM Resource Manager

Extends `apps/core/resource.py::ResourceManager` and `apps/core/training/cost_limits.py::CostController`:

1. **Pre-Flight Telemetry Snapshot:** Captures `cpu_percent`, `free_ram_mb`, `process_rss_mb`, `free_disk_gb`, `cuda_available`, and `gpu_vram_free_mb`.
2. **Hard CPU Training & Eval Caps:** Enforces `MAX_CPU_MODEL_PARAMETERS <= 5_000_000`, `MAX_CPU_SEQUENCE_LENGTH <= 256`, `MAX_CPU_BATCH_SIZE <= 4`, and `MAX_CPU_TRAINING_STEPS <= 1_000` whenever CUDA/approved compute is absent.
3. **Backpressure & Paid Compute Lock:**
   - If disk `< min_free_disk_gb` or RAM headroom is insufficient, runs pause in `WAITING_RESOURCE` instead of crashing the API host.
   - Any workflow requesting paid cloud GPU or exceeding `CostLimits` (`max_gpu_hours_per_run`, `max_budget_usd`) is **BLOCKED by default** until a verified Tier-2 Approval token explicitly authorizes the compute budget.

---

## 8. Permission & Approval Gate

Two-tier default-deny governance (`apps/core/workflow/governance.py`, upgrading `phases/phase19.py::SafetyGovernance` to DB-backed persistence):

- **Tier 1 (Auto-Allowed Autonomous Operations):**
  - System health & DB readiness checks (`operations.py`, `NativeRuntime`).
  - Data validation, dedup, PII filtering, leakage auditing (`audit_leakage_v9.py`), and `manifest.json` verification.
  - Read-only evaluation & 6 Principle Probes on already-approved checkpoints.
  - Security audits, checksum verification, repo drift reports, and drafting (never executing) autonomous improvement proposals.
- **Tier 2 (Mandatory Human Approval Gate — Blocked Without Token):**
  - Starting real model training runs or provisioning paid GPU compute.
  - Modifying model architecture, database schema, or core workflow definitions.
  - Promoting a model version to `staging` or `production`, or executing a rollback.
  - Deleting datasets, checkpoints, models, or knowledge records.
  - Running `git commit`, `git push`, `merge`, or production deployment.
- **Cryptographic Enforcement:**
  - Approval tokens in `workflow_approvals` carry an HMAC-SHA256 signature computed with `os.getenv("ZYRQUEN_APPROVAL_SECRET")` (validated at startup by `validate_security_configuration`), bound to `(run_id, step_key, action_type, scope, expires_at)`.
  - Approver must be an authenticated RBAC `admin` (and in `training_admin_emails()` for training/model actions). Tokens are single-use (`consumed_at` set atomically in the DB transaction prior to execution).

---

## 9. Audit Log & Workflow History

1. Every trigger, state transition, resource block, approval request/decision/consumption, retry, failure, and model registry transition appends an immutable row to `workflow_audit_logs`.
2. Sensitive credentials, tokens, paths, or bearer headers are scrubbed via `apps/api/operations.py::redact_sensitive_text`.
3. `workflow_definitions` keeps semantic versions (`v1`, `v2`, ...), and `workflow_runs` always records `workflow_version`, input `trigger_payload`, `resource_snapshot`, and step-level `evidence` hashes for full post-mortem reproducibility.

---

## 10. Training Workflow Integration

Registered workflow `native_training.v1` DAG:
1. **`verify_data_gate`** (`control_ops`, Tier 1): Verifies dataset `manifest.json` SHA-256 and runs `audit_leakage_v9.py` (`EL-01..08`, `TL-01`, `SL-01`, `DL-01`, `SEQ_BUDGET`). Blocks immediately on any failure.
2. **`check_resources_and_caps`** (`control_ops`, Tier 1): Validates CPU/RAM/Disk/VRAM and `CostLimits` against model params/seq/batch/steps.
3. **`await_training_approval`** (`control_ops`, Tier 2): Suspends run in `WAITING_APPROVAL` until signed admin token is approved.
4. **`execute_training`** (`compute_heavy`, Tier 2 consumed): Dispatches `TrainingOrchestrator` or `train_nagi_v9.py --mode train` with deterministic seed, atomic `best.pt`/`last.pt` writes, NaN/Inf gradient/loss abort, OOM guard, and best validation weight restoration.
5. **`register_candidate_version`** (`control_ops`, Tier 1): Registers immutable checkpoint artifacts + provenance + SHA-256 into `ModelRegistry` (`lifecycle_status = "registered"`), then emits `training.completed`.

---

## 11. Evaluation Workflow Integration

Registered workflow `evaluation_pipeline.v1` DAG (auto-triggered by `training.completed` or `manual`):
1. **`verify_artifact_integrity`** (`control_ops`, Tier 1): Calls `ModelRegistry.verify(version)` and confirms `EL-05 == 0` on checkpoint vocabulary + dataset manifest SHA-256.
2. **`run_evaluation_and_probes`** (`compute_heavy`, Tier 1): Runs `EvaluationEngine` / `eval_nagi_v9.py` (Teacher-Forced + Free-Generation + OOD Novel Structure + all 6 Principle Diagnostic Probes).
3. **`compare_regression_gate`** (`control_ops`, Tier 1): Compares per-capability & overall metrics against parent baseline and current `production` model (`build_regression_comparison` / `regression_gate`).
4. **`update_registry_and_report`** (`control_ops`, Tier 1): Persists `EvaluationRun` + JSON/Markdown report hashes; transitions registry status to `verified` if Acceptance Gate + Regression Gate pass with real evidence, otherwise `quarantined` (never self-certifies PASS without evidence). Emits `evaluation.completed`.

---

## 12. Native Model Registry Integration

Extends `apps/core/native/registry.py::ModelRegistry` without replacing its `fcntl.flock` locking, atomic `O_EXCL` directory reservation, or immutable `artifacts/<version>/` layout:

1. **Additive Metadata Fields in `registry.json`:**
   - `lifecycle_status`: `development | registered | evaluated | verified | staging | production | quarantined | archived`.
   - `lineage`: `{ parent_version, dataset_manifest_sha256, checkpoint_sha256, tokenizer_sha256, config_sha256, seed }`.
   - `evaluation_evidence`: `{ eval_run_id, report_path, report_sha256, tf_exact, fg_exact, unseen_copy_acc, probe_pass_count, zero_regression_vs_prod }`.
   - `workflow_lineage`: `{ training_workflow_run_id, eval_workflow_run_id, approval_id, approved_by }`.
2. **Evidence-Linked Health:** `apps/core/runtime.py::NativeRuntime` continues reading verified metrics directly from the active `production` registry entry and evaluation report without any hardcoded fallbacks.

---

## 13. Model Lifecycle & Promotion Gate

```text
DEVELOPMENT ──▶ REGISTERED ──▶ EVALUATED
                                  ├── [Gate FAIL / Missing Evidence] ──▶ QUARANTINED / BLOCKED
                                  └── [Acceptance + Regression PASS] ──▶ VERIFIED
                                                                            │ (Tier-2 Approval)
                                                                            ▼
                                                                         STAGING ──(Tier-2 Approval)──▶ PRODUCTION
                                                                                                            │ (incident/regression)
                                                                                                            ▼
                                                                                                         ARCHIVED / ROLLED_BACK
```

- **Hard Gate in `ModelRegistry.promote(version, ...)`:**
  - Refuses promotion if `ModelRegistry.verify(version)` fails (SHA-256 or required artifact mismatch).
  - Refuses promotion if `lifecycle_status` is `quarantined`, `blocked`, or lacks an attached verified `evaluation_evidence` report.
  - Requires an unconsumed Tier-2 `workflow_approvals` ID (`action_type="model.promote"`) before updating `active_version` (same gate for `model.rollback`).

---

## 14. Failure Handling & Recovery

| Failure Scenario | Immediate Engine Reaction | Persistence & Recovery Behavior |
|---|---|---|
| **Loss / Gradient NaN or Inf** | Abort training loop immediately (`abort_nan_inf_*`), discard bad step | Keep last verified `best.pt`, mark step `FAILED` (non-retryable), preserve weights untouched, emit alert |
| **OOM (CPU RAM or CUDA VRAM)** | Abort step cleanly (`abort_oom`), clear CUDA cache | Mark `FAILED` (non-retryable under current config); recommend reducing batch/seq in improvement log |
| **Data Leakage Gate FAIL** | Fail-closed before model allocation (`BLOCKED`) | Refuse training/registration; block downstream DAG nodes; record gate IDs in `workflow_audit_logs` |
| **Checksum / Provenance Mismatch** | Halt inference/evaluation/promotion (`BLOCKED`) | Mark model version `quarantined`; require admin investigation |
| **API / Worker Crash Mid-Run** | Startup reconciler inspects DB `RUNNING` rows without active worker | Non-training control steps resume from `checkpoint_cursor`; training steps resume cleanly from verified `last.pt` SHA-256 |
| **Post-Promotion Production Anomaly** | `system_ops` / `security_governance` raises `health.degraded` | Proposes rollback workflow waiting at Tier-2 Approval Gate for instant revert to previous verified parent |

---

## 15. Security & Operational Boundaries

1. **RBAC & Least Privilege:** Tier-1 status queries require authenticated user/operator; workflow mutations & Tier-2 approvals require `admin` + `training_admin_emails()` match where applicable.
2. **Secret Hygiene:** `ZYRQUEN_APPROVAL_SECRET` lives strictly in environment variables, validated by `validate_security_configuration()`, never logged or returned by API responses.
3. **Immutable Evidence:** Evaluation reports, dataset manifests, checkpoints, and `workflow_audit_logs` are immutable/append-only and hashed via SHA-256.
4. **Workspace Isolation:** `knowledge_memory` workflows enforce strict `(owner_id, workspace_id)` isolation and PII pattern redaction (`phase17.py` + `dataset.py`).
5. **No External Model Substitution:** Workflows cannot register external LLM endpoints (OpenAI, Gemini, Claude, Llama APIs) as ZYRQUEN's native model inference or training generator.

---

## 16. API & UI Integration

### 16.1 Proposed REST Endpoints (`/v1/workflows`)
- `GET /v1/workflows/definitions` — list registered workflow definitions & versions across the 8 groups.
- `GET /v1/workflows/runs` / `GET /v1/workflows/runs/{run_id}` — filter runs by group/status, inspect DAG step statuses, `resource_snapshot`, and `evidence`.
- `POST /v1/workflows/runs` — trigger a manual workflow run (`Tier 1` runs immediately; `Tier 2` pauses at `WAITING_APPROVAL`).
- `POST /v1/workflows/runs/{run_id}/cancel` — safely cancel pending/running workflow.
- `GET /v1/workflows/approvals` / `POST /v1/workflows/approvals/{approval_id}/decision` — approve or reject Tier-2 requests with HMAC signature issuance & audit logging.
- `GET /v1/models/registry` / `POST /v1/models/registry/{version}/promote` / `rollback` — expose `ModelRegistry` lifecycle states, comparisons, and Tier-2 gated promotions.

### 16.2 Frontend Integration (`/training` Workspace — `apps/web/src/app/training/page.tsx`)
Currently, `apps/web/src/app/training/page.tsx` accurately renders static capability cards (`CapabilityRadarChart` + unavailable status banners for Datasets, Training Runs, Resources, Checkpoints, Model Versions, and Evaluation) because no workflow/registry Web API exists yet. Once approved and built:
- Keep zero mock metrics rule: every panel reads real `/v1/workflows/*` and `/v1/models/registry` responses and shows explicit `NOT RUN` / `Unavailable` states when absent.
- Add tabs/panels inside `/training` for:
  1. **Workflow Runs & DAG Inspector** (8 groups filter, live step states, failure reasons).
  2. **Approval Queue** (admin-only Approve/Reject modal with scope & cost limits preview).
  3. **Model Registry & Version Comparison** (Lifecycle badges `Registered -> Verified -> Staging -> Production / Quarantined`, Arm/Version delta table, and gated Promote/Rollback buttons).

---

## 17. Testing Strategy

1. **Unit Tests (`pytest`):**
   - `test_workflow_dag.py`: Cycle detection, dangling `depends_on`, topological ordering, conditional edges.
   - `test_workflow_governance.py`: Tier-1 vs Tier-2 defaults, HMAC tamper rejection, expired token rejection, single-use replay rejection, RBAC non-admin 403.
   - `test_workflow_resource_guard.py`: CPU cap enforcement (`5M/256/4/1000`), disk/RAM backpressure (`WAITING_RESOURCE`), paid GPU default block.
   - `test_workflow_recovery.py`: Startup reconciliation of orphaned `RUNNING` runs, bounded transient retries vs immediate halt on `OutOfMemoryError`/`NaNInfLossError`/`LeakageGateFailed`.
   - `test_registry_lifecycle.py`: `quarantined` promotion rejection, missing evaluation report rejection, SHA-256 verification gate, atomic `promote` & `rollback`.
2. **Migration & API Integration Tests (`pytest`):**
   - Alembic upgrade/downgrade `20261120_07 -> 20261121_08`.
   - End-to-end API flow: `POST /v1/workflows/runs` -> `WAITING_APPROVAL` -> `POST /approvals/{id}/decision` -> `compute_heavy` execution -> `ModelRegistry` update -> `workflow_audit_logs` check.
3. **Frontend Verification (`vitest`, `npm run typecheck`, `npm run build`):**
   - Verify empty/blocked/pending approval UI states render honestly with zero fabricated data.

---

## 18. Mapping with Roadmap 11–20 (`phases/phase11..20.py` Preserved Untouched)

| Roadmap Phase | Existing Module Contract | Central Workflow Engine Mapping |
|---|---|---|
| **Phase 11** (`Workspace Intelligence`) | `suggest_followups`, `ConversationContext` | Workflow API suggests follow-up actions cleanly without auto-running Tier-2 tasks |
| **Phase 12** (`Native Foundation`) | `CapabilityRegistry` (`available / blocked`) | **System Ops** & `NativeRuntime` derive capability readiness from verified `ModelRegistry` entries |
| **Phase 13** (`Knowledge & Data`) | `ingest_record`, `check_governance`, `validate_record` | **Data Workflow** executes schema, provenance, PII, dedup, and `audit_leakage_v9` checks |
| **Phase 14** (`Evaluation`) | `evaluate_case`, `compare_benchmark`, `regression_gate` | **Evaluation Workflow** enforces TF/FG/OOD + 6 Probes + `zero_regression` gate before `verified` |
| **Phase 15** (`Model Readiness`) | `check_compatibility`, `ModelRegistry` lifecycle | Pre-flight config/checkpoint compatibility guard prior to evaluation or production promotion |
| **Phase 16** (`Reasoning & Planning`) | `validate_dag`, `ExecutionSafetyPolicy`, `verify_step` | Direct foundation for `workflow/dag.py` and default-deny step verification |
| **Phase 17** (`Memory & Knowledge`) | `MemoryStore` (tenant isolation, groundedness, PII scrub) | **Knowledge & Memory Workflow** adds conflict detection, indexing, and verification |
| **Phase 18** (`Adaptive Learning`) | `AdaptiveLearning` (offline replay, zero unsafe mutation) | **Autonomous Improvement Workflow** drafts offline experiment proposals and pauses at Approval Gate |
| **Phase 19** (`Safety Governance`) | `SafetyGovernance` (allowlist, HMAC approval, audit trail) | Production DB-backed `workflow_approvals` + `ZYRQUEN_APPROVAL_SECRET` + `workflow_audit_logs` |
| **Phase 20** (`System Maturity`) | `SystemMaturity` (SLO thresholds, readiness checklist) | **System Ops** & **Project & Dev Workflows** generate daily health & Roadmap 11–20 status reports |

---

## 19. Implementation Milestones

| Milestone | Scope | Verification Gate Before Next Milestone |
|---|---|---|
| **M1 — Core Engine & Migration** | `apps/core/workflow/` core (`models`, `dag`, `registry`, `resource_guard`, `governance`, `recovery`, `triggers`, `queue`, `audit`, `orchestrator`) + `workflow_models.py` + Alembic `20261121_08` | Unit tests for DAG, HMAC approvals, recovery, resource caps, and migration pass cleanly |
| **M2 — 8 Domain Handlers & Registry Lifecycle** | Implement the 8 handlers reusing `operations.py`, `TrainingOrchestrator`/`train_nagi_v9`, `EvaluationEngine`/`eval_nagi_v9`, `dataset.py`, `audit_leakage_v9`, and extend `ModelRegistry` lifecycle states | Integration tests verify Training -> Eval -> Verified/Quarantined -> Gated Promote without fake data |
| **M3 — FastAPI Router & `/training` UI** | Expose `/v1/workflows/*` & `/v1/models/registry/*` routers; upgrade `apps/web/src/app/training/page.tsx` with Workflow Runs, Approval Queue, and Model Lifecycle views | API pytest suite + `vitest` + `npm run typecheck` + `npm run build` pass |
| **M4 — Staging Soak & Acceptance Sign-Off** | Run daily `system_ops`, `security_governance`, and `project_dev` workflows in staging; verify crash recovery & audit completeness | All Section 20 Acceptance Criteria verified `RUNTIME_PASS` |

---

## 20. Acceptance Criteria

Implementation of the Central Native Workflow Engine is accepted **only when all criteria below pass real verification**:
1. **Single Orchestrator Invariant:** Exactly one `CentralScheduler` and one `CentralWorkflowOrchestrator` execute all 8 workflow groups; zero duplicate schedulers exist.
2. **Fail-Closed Safety Gates:** Leakage Gate failure, checkpoint SHA-256 mismatch, NaN/OOM abort, missing evaluation report, or missing Tier-2 HMAC approval **always** blocks execution/promotion (`BLOCKED` / `FAILED`).
3. **Crash & Restart Recovery:** Killing the worker mid-workflow leaves zero stuck `RUNNING` zombies after restart; resumable workflows continue from persisted `checkpoint_cursor` with `workflow_audit_logs` intact.
4. **Zero-Regression Promotion Enforcement:** `ModelRegistry.promote()` rejects `quarantined` or unverified versions and requires an unconsumed Tier-2 approval token.
5. **Honest Reporting & Security:** Zero hardcoded metrics, zero external AI model calls disguised as ZYRQUEN NGI, zero leaked secrets in logs/API responses, and full RBAC test pass.
