# ZYRQUEN Ω∞ — Native Model v10 Specification & Integration Record

- **Version:** `10.0`
- **Status:** `PREPARATION (INTEGRATION AUDIT READY — STOPPED BEFORE TRAINING)`
- **Training Status:** `NOT STARTED`
- **Evaluation Inference Status:** `NOT RUN`
- **Baseline (Frozen / Immutable):** `v7`, `v8`, `v9`
- **Project:** ZYRQUEN Native General Intelligence (NGI)

---

## 1. Mission & Strategic Scope

v10 advances ZYRQUEN's native symbolic reasoning, relational generalization, out-of-distribution transfer, multi-step planning, self-verification, and knowledge integration under strict anti-leakage, unique-answer, CPU-budget, and Tier-2 HMAC governance controls.

v10 is **not** a chatbot-only project, does **not** use external AI APIs as native intelligence, and does **not** claim general intelligence without verified training and evaluation evidence.

---

## 2. Canonical v10 File Set (7 Files)

| File | Responsibility | Execution Safety |
|---|---|---|
| `tools/v10_summary.md` | Central v10 specification, contracts, and integration status | Documentation only |
| `tools/gen_nagi_v10.py` | Deterministic generator for `data/nagi_v10/` across 6 capabilities and 3 splits | Pure stdlib; never overwrites existing output; verifies unique answers |
| `tools/audit_leakage_v10.py` | Read-only leakage, SHA-256, schema, and unique-answer solver auditor | Strictly read-only; exit `0` only on full PASS |
| `tools/train_nagi_v10.py` | CPU-budgeted training controller wired to Workflow Engine, Resource Guard, HMAC Gate, and ModelRegistry | Training hook locked (`False`); never fabricates approval or metrics |
| `tools/eval_nagi_v10.py` | Evaluation controller validating manifest, SHA-256, leakage audit, and optional read-only Registry state | Inference hook locked (`False`); reports `NOT RUN` honestly |
| `tools/diagnose_nagi_v10.py` | Read-only diagnostic analyzer for evaluation and preflight reports | Never runs inference or modifies artifacts |
| `tools/compare_nagi_v10.py` | Read-only multi-experiment & frozen-baseline comparison | Never treats `NOT RUN` as `0.0` or `PASS`; checks `dataset_content_sha256` |

---

## 3. Unified Dataset & Manifest Contract (`data/nagi_v10/`)

### 3.1 Splits & Default Counts
- **Canonical Splits:** `("train", "validation", "test")`
- **Output Files:** `train.jsonl`, `validation.jsonl`, `test.jsonl`, `manifest.json`
- **Default Counts:** `train = 480` (80 × 6), `validation = 60` (10 × 6), `test = 60` (10 × 6) → `600` total examples (configurable via CLI; cycles cleanly across all 6 capabilities).

### 3.2 Six Capabilities & Unique-Answer Guarantee
Every generated example belongs to one of the 6 canonical capabilities and is checked by an independent exhaustive solver at **both** generation (`gen_nagi_v10.py`) and audit (`audit_leakage_v10.py`) to prevent multi-answer ambiguity:

1. `abstract_reasoning` (`ordered_comparison` / `transitive_order_inference`): Acyclic `greater_than` DAG; unique answer in `{">", "<", "unknown"}`.
2. `relational_generalization` (`relational_chain` / `directed_path_composition`): Exact 3-hop `linked_to` graph; distractor edges are accepted **only** if exact 3-hop reachable endpoint set has cardinality 1, walk count is 1, and no shortcut `< 3` hops reaches the answer.
3. `ood_transfer` (`ood_relational_chain` / `variable_depth_path_composition`): Disjoint hop depth & relation per split (`train`: 2-hop `connects_to`, `validation`: 4-hop `routes_to`, `test`: 5-hop `transfers_to`); same strict unique-path DP verification.
4. `multi_step_planning` (`dependency_planning` / `topological_plan_resolution`): Prerequisite closure must either contain a cycle (`"impossible"`) or admit **exactly one** valid topological execution sequence (`len(ready) == 1` at every Kahn step).
5. `self_verification` (`claim_and_plan_verification` / `consistency_verification`): Unambiguous claim verification (`"true"`, `"false"`, `"unknown"`) and plan verification (`"valid"`, `"invalid_order"`, `"invalid_missing"`, `"invalid_cycle"`).
6. `knowledge_integration` (`multi_source_reconciliation` / `belief_revision_and_conflict`): Deterministic belief revision (`base` + `update` override/retention) and primary conflict detection (`"conflict"`).

### 3.3 Manifest Schema (`zyrquen.dataset-manifest.v1`)
`manifest.json` exposes both `splits` (`train`, `validation`, `test`) and `files` (`train.jsonl`, `validation.jsonl`, `test.jsonl`), `version = "10.0.0"`, `dataset = "nagi_v10"`, `content_sha256` (SHA-256 of concatenated split hashes), and `split_isolation` metadata — ensuring 100% compatibility with `audit_leakage_v10.py`, `eval_nagi_v10.py`, `train_nagi_v10.py`, `ModelRegistry._verify_dataset`, and `apps/core/workflow/handlers/groups.py`.

### 3.4 Audit Gates (`tools/audit_leakage_v10.py`)
- `INTEGRITY_MANIFEST`: Manifest schema, non-symlink path safety, split file SHA-256, record counts, `content_sha256`.
- `SCHEMA_VALIDATION`: Required record fields, split label match, target/answer equality.
- `UNIQUE_ANSWER`: Independent exhaustive solver verification per example (zero multi-answer examples).
- `EL-01..EL-06`: Zero entity overlap across `train` / `validation` / `test`, zero eval entity leakage into static train vocabulary, 100% unseen-entity eval coverage.
- `TL-01`: Zero `template_id` and raw phrasing overlap across splits.
- `SL-01`: Zero `ood_transfer` abstract structural pattern overlap across splits.
- `DL-01`: Zero duplicate IDs, duplicate exact/normalized inputs, or empty targets.
- `SEQ_BUDGET`: `<= 250` structural tokens per example (fits inside `MAX_SEQUENCE_LENGTH = 256` with `<bos>`/`<eos>`).

---

## 4. Locked Resource Budget

Matches `apps/core/workflow/autonomous_training_loop.py` and `apps/core/workflow/resource_guard.py`:

| Resource | Locked Maximum / Limit |
|---|---|
| CPU threads | `<= 2` cores |
| Model parameters | `<= 5,000,000` |
| Sequence length | `<= 256` |
| Batch size | `<= 4` |
| Training steps | `<= 500` per experiment |
| RAM soft limit | `3.0 GB` |
| RAM hard stop | `3.5 GB` |
| New disk usage | `<= 1.0 GB` |
| Minimum free disk reserve | `>= 2.0 GB` |
| Experiment timeout | `20 minutes` (`1200s`) |
| Complete loop timeout | `60 minutes` (`3600s`) |
| Checkpoints | `<= 10` files per run (`checkpoints/nagi_v10/`) |
| Paid GPU | **FORBIDDEN** (`use_paid_gpu = False`) |

---

## 5. Existing Infrastructure Integration (Zero Duplication)

| Existing ZYRQUEN Component | Module | How v10 Connects |
|---|---|---|
| Central Workflow Engine | `apps/core/workflow/orchestrator.py` (`CentralWorkflowOrchestrator`) | `train_nagi_v10.py` registers and runs `training.nagi_v10_controlled_run` |
| Resource Guard | `apps/core/workflow/resource_guard.py` (`WorkflowResourceGuard`) | Validates RAM, disk, CPU bounds, paid-GPU prohibition, and `CostLimits` |
| HMAC Approval Gate | `apps/core/workflow/governance.py` (`WorkflowGovernance`) | Tier-2 `training.execute` pauses at `WAITING_APPROVAL` until admin-signed HMAC token is verified & consumed |
| Budget / Disk / RAM Helpers | `apps/core/workflow/autonomous_training_loop.py` | Reuses `validate_budget`, `check_disk_reserve`, and locked budget constants |
| Workflow Audit Log | `apps/core/workflow/audit.py` (`WorkflowAuditLogger`) | Records trigger, resource, and approval state transitions |
| Model Registry | `apps/core/native/registry.py` (`ModelRegistry`) | Optional read-only inspection/verification in `train_nagi_v10.py` and `eval_nagi_v10.py` |

### Known Integration Boundaries (Outside the 7 v10 Files — Not Modified)
1. `apps/core/workflow/handlers/groups.py::handle_data_verify_and_audit` dispatches `audit_leakage_v9` for v9 splits (`val_unseen`/`test_ood`) and only checks `manifest.json` for non-v9 datasets; automatic dispatch to `tools/audit_leakage_v10.py` inside `groups.py` is pending future core wiring.
2. `apps/core/workflow/handlers/groups.py::handle_training_execute` targets `ZyrquenModel` token-stream LM training rather than a dedicated v10 reasoning architecture/objective (still `pending_review`).
3. `apps/core/native/evaluation/engine.py::get_status()` reports `native_inference_evaluation_wired: False`; `eval_nagi_v10.py` therefore keeps `INFERENCE_HOOK_IMPLEMENTED = False` and reports `NOT RUN`.
4. PyTorch (`torch`) is not installed in the current container (`ModuleNotFoundError`), so real training/inference execution remains `BLOCKED` here.

---

## 6. Baseline Protection & Current Status

- **Immutable Baselines:** `v7`, `v8`, and `v9` files, datasets, and checkpoints are untouched.
- **Evaluation Report Schema:** `zyrquen.v10.evaluation_report.v1`
- **Diagnostic Report Schema:** `zyrquen.v10.diagnostic_report.v1`
- **Comparison Report Schema:** `zyrquen.v10.comparison_report.v1`
- **Preflight Report Schema:** `zyrquen.v10.training_preflight.v1`
- **Current Gate:** Ready for Static Verification & Integration Audit (`Training: NOT STARTED`, `Promotion: NOT AUTHORIZED`).
