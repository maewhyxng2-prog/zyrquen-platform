# ZYRQUEN Ω∞ — Central Native Workflow Engine Implementation Plan

- **Document Status:** `APPROVED PLANNING SPECIFICATION — AWAITING IMPLEMENTATION APPROVAL`
- **Architectural Principle:** **One Central Native Workflow Engine** (`apps/core/workflow/`) serving all 8 operational and research domains as registered workflows. No duplicate schedulers or per-subsystem orchestrators.
- **NGI Boundary:** The Workflow Engine is **supporting orchestration and governance infrastructure** for ZYRQUEN Ω∞. It is **never** a substitute for the native intelligence model, never embeds external LLMs as ZYRQUEN's reasoning engine, and never fabricates PASS/metrics.
- **Governance Rule:** Still **no code edits** to `apps/`, `phases/phase11..20.py`, `tools/*v7*`, `tools/*v8*`, or database migrations until this specification is reviewed and approved.

---

## 1. Repository Audit & Reuse Strategy (Zero Duplication)

Before introducing any new workflow module, existing repository components map cleanly into the central engine:

| Existing Module | Verified Capabilities Already in Repo | Role Inside Central Workflow Engine |
|---|---|---|
| `apps/api/operations.py` | `database_readiness`, `aggregate_readiness`, `validate_security_configuration`, `JsonFormatter`, `redact_sensitive_text` | Wrapped by **System Operations** & **Audit Redaction** |
| `apps/core/runtime.py` | `NativeRuntime.get_health_status` (reads real `ModelRegistry` or `ZYRQUEN_EVAL_REPORT_PATH` evidence) | Runtime health probe & capability readiness feed |
| `apps/core/resource.py` | `ResourceManager` (`snapshot`, `check_request` for RAM, VRAM, tokens, elapsed seconds) | Extended with CPU load & disk check for **Resource Guard** |
| `apps/core/training/orchestrator.py` | `TrainingOrchestrator` (`prepare`, `run`), CPU caps (`5M` params, `256` seq, `4` batch, `1000` steps) | Invoked as the **Native Training** step executor |
| `apps/core/training/cost_limits.py` | `cost_controller_from_env` (`CostController`, `CostLimits`) | Enforced by Resource Manager for runtime & GPU-hour ceilings |
| `apps/api/training_jobs.py` | `TrainingJobService` (`ThreadPoolExecutor(max_workers=1)`, `TrainingRun` DB persistence, `ModelRegistry` commit) | Migrated behind `compute_heavy_lane` worker dispatch |
| `apps/core/native/dataset.py` | `prepare_dataset`, `load_split`, `SCHEMA = "zyrquen.dataset-manifest.v1"` | Wrapped by **Data Workflow** ingestion & manifest verification |
| `tools/audit_leakage_v9.py` | 4-layer zero-tolerance leakage audit (`EL-01..EL-08`, `TL-01`, `SL-01`, `DL-01`, `SEQ_BUDGET`) | Mandatory pre-training **Data Leakage Gate** |
| `apps/core/native/registry.py` | `ModelRegistry` (file lock `fcntl.flock`, atomic reservations, SHA-256 verification, immutable artifacts, `promote`, `rollback`) | Core backend for **Model Registry & Lifecycle Gate** |
| `apps/api/evaluation_service.py` & `apps/api/routers/evaluation.py` | `EvaluationRun` DB records & `EvaluationEngine` | Wrapped by **Evaluation Workflow** (auto-triggered post-training) |
| `phases/phase11.py` – `phase20.py` | Pure-logic contracts (`CapabilityRegistry`, `validate_dag`, `ExecutionSafetyPolicy`, `MemoryStore`, `AdaptiveLearning`, `SafetyGovernance`, `SystemMaturity`) | **Preserved untouched**; their logic & invariants are adapted into persistent `apps/core/workflow/` services |

---

## 2. Target Architecture & Module Layout

```text
apps/
├── core/
│   └── workflow/                    # [NEW — Single Central Engine Core]
│       ├── __init__.py
│       ├── models.py                # Dataclasses: WorkflowDefinition, WorkflowStep, StepResult, RunState
│       ├── registry.py              # WorkflowRegistry (versioned definitions for the 8 groups)
│       ├── dag.py                   # Topological validation, cycle detection, dependency resolution
│       ├── triggers.py              # EventBus + single CentralScheduler (cron/interval)
│       ├── queue.py                 # Dual-lane persistent task dispatcher (compute_heavy vs control_ops)
│       ├── recovery.py              # Step checkpointing, transient retry policy, startup reconciliation
│       ├── resource_guard.py        # Unified CPU / RAM / GPU / Disk & CostLimits pre-flight guard
│       ├── governance.py            # 2-Tier Permission policy + HMAC-signed Tier-2 Approval Gate
│       ├── audit.py                 # Append-only redacted audit trail writer
│       ├── orchestrator.py          # CentralWorkflowOrchestrator (state machine + execution loop)
│       └── handlers/                # Adapters connecting the 8 workflow groups to existing modules
│           ├── system_ops.py
│           ├── data_pipeline.py
│           ├── native_training.py
│           ├── evaluation.py
│           ├── knowledge_memory.py
│           ├── autonomous_improvement.py
│           ├── security_governance.py
│           └── project_dev.py
├── api/
│   ├── workflow_models.py           # [NEW] SQLAlchemy models (5 tables)
│   ├── workflow_schemas.py          # [NEW] Pydantic request/response schemas
│   ├── workflow_service.py          # [NEW] DB transaction & approval query service
│   ├── migrations/versions/
│   │   └── 20261121_08_workflow_engine.py  # [NEW] Alembic down_revision="20261120_07"
│   └── routers/
│       └── workflows.py             # [NEW] /v1/workflows/* RBAC-protected REST endpoints
```

---

## 3. Execution Flow & State Machine

Every registered workflow executes through one uniform lifecycle:

```text
Trigger (Event / Schedule / Condition / Manual)
   │
   ▼
WorkflowRegistry Lookup (workflow_key + semantic version)
   │
   ▼
DAG & Pre-Flight Validation (cycle check, dependencies, input schema)
   │
   ▼
Resource Guard (CPU / RAM / GPU / Disk / CostLimits) ──[insufficient]──▶ WAITING_RESOURCE
   │ [ok]
   ▼
Permission & Approval Gate
   ├── Tier 1 (Auto-Allowed: read-only / bounded checks) ──────────────────┐
   └── Tier 2 (Gated: training GPU, promotion, delete, arch edit, push)    │
         └──▶ WAITING_APPROVAL (human RBAC admin + single-use HMAC token) ─┤
   ┌───────────────────────────────────────────────────────────────────────┘
   ▼
Execute Step (checkpointed per DAG node in isolated lane)
   │
   ▼
Verification & Monitoring (check real evidence, NaN/OOM/leakage/regression)
   │  ├── [PASS] ──▶ Next DAG Step / Emit Follow-up Event / Audit Log / Report
   │  ├── [TRANSIENT ERR] ──▶ Exponential Backoff Retry (up to max_attempts)
   │  └── [FATAL / VIOLATION] ──▶ Immediate Abort (FAILED or BLOCKED) + Audit Alert
```

### Canonical Status Rules (Phase 14 & Phase 20 Aligned)
- Valid run states: `PENDING`, `WAITING_RESOURCE`, `WAITING_APPROVAL`, `RUNNING`, `VERIFYING`, `COMPLETED`, `FAILED`, `BLOCKED`, `CANCELLED`.
- Valid verification outcomes: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`.
- **Hard Rule:** `NOT RUN` and `BLOCKED` **never** coerce to `PASS`.

---

## 4. Database Schema Specification (Alembic `20261121_08`, `down_revision = "20261120_07"`)

1. **`workflow_definitions`**
   - `id` (UUID PK), `workflow_key` (`String(64)`), `version` (`String(32)`), `group_name` (`String(32)`), `dag_spec` (`JSON`), `default_tier` (`String(16)`), `is_active` (`Boolean`), `created_at` (`DateTime(tz)`)
   - Unique constraint on `(workflow_key, version)` for **Workflow Versioning**.
2. **`workflow_runs`**
   - `id` (UUID PK), `workflow_key` (`String(64)`), `workflow_version` (`String(32)`), `trigger_type` (`event | schedule | condition | manual`), `trigger_payload` (`JSON`), `status` (`String(24)` indexed), `priority` (`Integer`), `requested_by_user_id` (`UUID FK -> users.id`), `checkpoint_cursor` (`JSON` nullable), `resource_snapshot` (`JSON` nullable), `error_message` (`Text`), `created_at`, `started_at`, `finished_at`.
3. **`workflow_step_runs`**
   - `id` (UUID PK), `run_id` (`UUID FK -> workflow_runs.id ON DELETE CASCADE`), `step_key` (`String(64)`), `depends_on` (`JSON`), `lane` (`control_ops | compute_heavy`), `status` (`String(24)`), `attempt` (`Integer`), `max_attempts` (`Integer`), `next_retry_at` (`DateTime(tz)` nullable), `evidence` (`JSON` nullable), `output` (`JSON` nullable), `started_at`, `finished_at`.
   - Unique constraint on `(run_id, step_key)`.
4. **`workflow_approvals`**
   - `id` (UUID PK), `run_id` (`UUID FK -> workflow_runs.id`), `step_key` (`String(64)`), `action_type` (`String(64)`), `scope` (`String(255)`), `requested_by_user_id` (`UUID FK -> users.id`), `approved_by_user_id` (`UUID FK -> users.id` nullable), `status` (`pending | approved | rejected | expired | consumed`), `signature_hmac` (`String(128)` nullable), `expires_at` (`DateTime(tz)`), `consumed_at` (`DateTime(tz)` nullable), `reason` (`Text`), `created_at`.
5. **`workflow_audit_logs`**
   - `id` (UUID PK), `run_id` (`UUID` nullable indexed), `step_key` (`String(64)` nullable), `actor_id` (`String(64)`), `event_type` (`String(64)`), `resource` (`String(255)`), `decision` (`String(32)`), `details` (`JSON`), `created_at` (`DateTime(tz)` indexed).
   - Append-only; all text payloads pass `apps/api/operations.py::redact_sensitive_text`.

---

## 5. The 8 Registered Workflow Groups

| # | Workflow Group | Triggers | Core Steps & Reused Modules | Approval Tier |
|---|---|---|---|---|
| **1** | **System Operations** (`system_ops`) | `schedule` (hourly/daily), `api.startup`, `health.degraded` | Check API/DB (`operations.py`), `NativeRuntime.get_health_status`, CPU/RAM/VRAM/Disk (`ResourceManager` + `disk_usage`), emit daily status report | **Tier 1** (Read-only diagnostic) |
| **2** | **Data Workflow** (`data`) | `dataset.ingested`, `manual` | Provenance & license check (`phase13` rules), PII/dedup (`dataset.py`), 4-layer Leakage Gate (`audit_leakage_v9.py`), Train/Val/Test split, SHA-256 `manifest.json` | **Tier 1** (Ingestion/Audit); **Tier 2** (Overwrite/Delete dataset) |
| **3** | **Native Training** (`training`) | `manual`, `data.ready` | Pre-flight readiness check, Resource Guard + CPU Cap (`<=5M/256/4/1000`), **Approval Gate**, execute `TrainingOrchestrator` / v9 trainer, atomic checkpointing, NaN/OOM/Loss-collapse abort | **Tier 2** (Real training run / Paid GPU) |
| **4** | **Evaluation** (`evaluation`) | `training.completed`, `manual` | Verify dataset/checkpoint SHA-256, run `EvaluationEngine` / `eval_nagi_v9` (TF + FG + 6 Probes), compare baseline (`regression_gate`), store `EvaluationRun` + report, never self-certify without evidence | **Tier 1** (Read-only eval on verified artifact) |
| **5** | **Knowledge & Memory** (`knowledge_memory`) | `knowledge.submitted`, `evaluation.completed` | Multi-tenant isolation (`owner_id` + `workspace_id`), grounded source check, contradiction/conflict check, index & verify stored knowledge (extending `phase17.py`) | **Tier 1** (Verified read/store); **Tier 2** (Cross-workspace/purge) |
| **6** | **Autonomous Improvement** (`improvement_proposal`) | `evaluation.completed` | Analyze weak capabilities & error cases, generate hypothesis + experiment plan draft, check zero-regression constraints (`phase18.py`). **Stops at Approval Gate** — never auto-mutates weights or architecture | **Tier 1** (Analysis & draft plan); **Tier 2** (Execute experiment) |
| **7** | **Security & Governance** (`security_governance`) | `schedule`, `auth.anomaly`, `file.modified` | Audit Auth/RBAC config (`validate_security_configuration`), rate-limit anomaly check, critical file checksum integrity (`apps/core/`, `apps/api/`), verify approval token audit log | **Tier 1** (Audit); **Tier 2** (Revoke/lockdown actions) |
| **8** | **Project & Development** (`project_dev`) | `schedule`, `manual` | Check repo-vs-runtime drift, CI/pytest/vitest summary, completed vs pending Roadmap 11–20 checklist (`phase20.py`). **Blocks** unauthorized `git push` or production deploy | **Tier 1** (Status & test audit); **Tier 2** (Commit/Push/Deploy) |

---

## 6. Subsystems Detail

### 6.1 Event Trigger & Single Central Scheduler
- **EventBus (`triggers.py`):** Synchronous/queued in-process dispatcher that translates internal events (`training.completed`, `evaluation.completed`, `dataset.ingested`, `health.degraded`) into DB-backed `workflow_runs` with idempotency keys (`trigger_dedup_key`) to prevent duplicate storms.
- **CentralScheduler:** A single background asyncio/thread loop inside the API/worker runtime with a DB lease (`scheduler_lock`) checking registered cron/interval definitions (`system_ops.daily`, `security.integrity_audit`). No separate `schedule`/`cron` runners in individual modules.

### 6.2 Dependency Graph & Dual-Lane Task Queue
- **DAG Validation (`dag.py`):** Validates every `workflow_definitions.dag_spec` at registration time using Kahn's topological sort + DFS cycle detection (matching `phases/phase16.py::validate_dag`). Invalid DAGs are rejected before persistence.
- **Task Queue (`queue.py`):**
  - `compute_heavy_lane` (`max_workers=1` on CPU): serializes Training & Full Evaluation so memory never spikes beyond hardware limits.
  - `control_ops_lane` (`max_workers=2`): runs lightweight diagnostics, leakage audits, and repo checks concurrently without waiting behind a training job.

### 6.3 Retry, Recovery & Step Checkpointing
- Every completed DAG step atomically updates `workflow_step_runs` (`status="COMPLETED"`, `output`, `evidence`) and advances `workflow_runs.checkpoint_cursor`.
- On process restart, `recovery.py` reconciles any `workflow_runs` left in `RUNNING`:
  - Resumable workflows resume strictly from the next uncompleted DAG node using persisted `checkpoint_cursor` (and for training steps, pass `--resume` to the latest SHA-256 verified checkpoint via `CheckpointManager`).
- **Fail-Closed Non-Retryable Errors:** `OutOfMemoryError`, `NaNInfLossError`, `LeakageGateFailed`, `ChecksumMismatchError`, and `ApprovalViolationError` skip retries and transition immediately to `FAILED` or `BLOCKED`.

### 6.4 Resource Manager (`CPU / RAM / GPU / Disk`)
- Extends `apps/core/resource.py::ResourceManager` and `apps/core/training/cost_limits.py::CostController`:
  - Checks: `free_ram_mb`, `process_rss_mb`, `free_disk_gb`, `cuda_available` / `vram_mb`, and `CPU Caps` (`MAX_CPU_MODEL_PARAMETERS = 5_000_000`, `MAX_CPU_SEQUENCE_LENGTH = 256`, `MAX_CPU_BATCH_SIZE = 4`, `MAX_CPU_TRAINING_STEPS = 1_000`).
  - **Paid Compute Lock:** Any step requesting paid cloud GPU or exceeding `CostLimits` is **blocked by default** unless a valid Tier-2 Approval record explicitly authorizes `budget_usd` and `max_gpu_hours`.

### 6.5 Permission & 2-Tier Approval Gate
- **Tier 1 (Auto-Allowed):** Read-only checks, health probes, static audits, leakage gates, evaluation report generation on already-approved checkpoints, and proposal drafting.
- **Tier 2 (Human-in-the-Loop Gate):**
  - Requires authenticated `admin` (and `training_admin_emails()` match for training/model promotion).
  - Generates a single-use HMAC-SHA256 approval record in `workflow_approvals` signed with `os.getenv("ZYRQUEN_APPROVAL_SECRET")` (startup rejects weak/missing secret in production via `validate_security_configuration`), bound to `(run_id, step_key, action_type, scope, expires_at)`.
  - Consumed atomically (`consumed_at` set in DB transaction) before executing gated actions (Paid GPU, Model Promote/Rollback, Architecture/Schema change, Deletion, Git Push/Deploy).

---

## 7. Integration with Native Training, Evaluation & Model Registry

### 7.1 Training → Evaluation → Registry Lifecycle Pipeline
```text
[1. Data Gate PASS]
   │  (audit_leakage_v9 / dataset manifest SHA-256)
   ▼
[2. Tier-2 Training Approval]
   │
   ▼
[3. Native Training Run] ──(TrainingOrchestrator / train_nagi_v9)
   │  (saves immutable checkpoint + provenance + SHA-256)
   ▼
[4. Model Registry: Register] ──(Status: REGISTERED)
   │  (links version, parent, checkpoint SHA-256, tokenizer SHA-256, dataset manifest)
   ▼
[5. Auto-Triggered Evaluation] ──(EvaluationEngine / eval_nagi_v9 + 6 Probes)
   │  (Status: EVALUATED -> checks Acceptance Gate + Regression Gate vs active version)
   ├── [Gate FAIL / Incomplete] ──▶ QUARANTINED / BLOCKED (cannot promote)
   └── [Gate PASS] ───────────────▶ VERIFIED / STAGING
                                       │
                                       ▼ (Tier-2 Human Approval Required)
                                    PRODUCTION (ModelRegistry.promote)
                                       │ (on regression/incident)
                                       ▼
                                    ROLLED_BACK (ModelRegistry.rollback)
```

### 7.2 Extending `apps/core/native/registry.py` (Without Breaking Existing Immutability)
- Preserve `ModelRegistry`'s `fcntl.flock` + O_EXCL reservation + immutable `artifacts/<version>/` design.
- Add structured metadata fields to `registry.json` records (additive/backwards-compatible):
  - `lifecycle_status`: `development | registered | evaluated | verified | staging | production | quarantined | archived`
  - `evaluation_summary`: `{ eval_run_id, report_sha256, fg_exact_match, unseen_copy_acc, probe_pass_count, regression_vs_parent }`
  - `workflow_lineage`: `{ training_workflow_run_id, eval_workflow_run_id, approval_id, approved_by }`
- Enforce inside `ModelRegistry.promote(...)`: refuse promotion unless `verify(version)` passes AND `lifecycle_status in ("verified", "staging")` AND a valid unconsumed Tier-2 `approval_id` is recorded.

---

## 8. Mapping to Roadmap Phase 11–20 (`phases/phase11..20.py` Preserved Untouched)

| Phase | Existing Pure-Logic Contract | Production Integration via Workflow Engine |
|---|---|---|
| **Phase 11** (`Workspace Intelligence`) | `suggest_followups`, `ConversationContext` | Workflow UI/API surfaces follow-up workflow recommendations without auto-executing gated tasks |
| **Phase 12** (`Native Foundation`) | `CapabilityRegistry` (`available / blocked`) | `system_ops` & `NativeRuntime` sync verified model capabilities dynamically from `ModelRegistry` |
| **Phase 13** (`Knowledge & Data`) | `ingest_record`, `check_governance`, `validate_record` | Enforced in **Data Workflow** Stage 1 before dataset splitting & manifest hashing |
| **Phase 14** (`Evaluation`) | `evaluate_case`, `compare_benchmark`, `regression_gate`, `reliability_score` | Enforced in **Evaluation Workflow** before transitioning a model version to `VERIFIED` |
| **Phase 15** (`Model Readiness`) | `check_compatibility`, `ModelRegistry` lifecycle | Pre-flight check ensuring model config matches checkpoint metadata prior to inference load |
| **Phase 16** (`Reasoning & Planning`) | `validate_dag`, `ExecutionSafetyPolicy`, `verify_step` | Direct foundation for `apps/core/workflow/dag.py` and default-deny Tier-2 gate |
| **Phase 17** (`Memory & Knowledge`) | `MemoryStore` (multi-tenant, source-grounded, PII filter) | Wrapped by **Knowledge & Memory Workflow** with DB persistence and conflict detection |
| **Phase 18** (`Adaptive Learning`) | `AdaptiveLearning` (replay, zero online weight mutation) | Wrapped by **Autonomous Improvement Workflow**; drafts offline experiment plans for approval |
| **Phase 19** (`Safety Governance`) | `SafetyGovernance` (tool allowlist, signed token, audit log) | Upgraded from pure-logic demo secret to `ZYRQUEN_APPROVAL_SECRET` + DB `workflow_approvals` & `workflow_audit_logs` |
| **Phase 20** (`System Maturity`) | `SystemMaturity` (SLO, readiness checklist, maintenance gate) | Drives **System Operations** & **Project/Dev Workflow** readiness reports |

---

## 9. Phased Rollout & Verification Plan (Requires Approval Before Coding)

1. **Stage A — Core Engine & DB Migration:** Implement `apps/core/workflow/` (`dag`, `registry`, `resource_guard`, `governance`, `recovery`, `orchestrator`), `apps/api/workflow_models.py`, and Alembic `20261121_08_workflow_engine.py`. Verify with pytest unit/migration/DAG/approval-gate tests.
2. **Stage B — Handlers & Registry Lifecycle Bridge:** Connect the 8 workflow handlers to `operations.py`, `TrainingOrchestrator`, `EvaluationEngine`, and `ModelRegistry` lifecycle states (`verified`/`quarantined`/gated `promote`). Verify end-to-end integration tests with zero fake metrics.
3. **Stage C — API Router & `/training` Workspace UI:** Add `/v1/workflows/*` RBAC endpoints and surface Workflow Runs, Approval Queue, and Model Registry Lifecycle inside `/training`. Verify `pytest`, `npm run typecheck`, `vitest`, and `compile_applet`.
