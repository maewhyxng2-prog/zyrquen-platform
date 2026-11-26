# ZYRQUEN Ω∞ — V10–V20 Terminal Master Guide

- **Document ID:** `ZYRQUEN-V10-V20-TERMINAL-GUIDE`
- **Notice:** **`ALL COMMANDS LISTED IN THIS DOCUMENT ARE REFERENCE SPECIFICATIONS — NOT EXECUTED IN THE CURRENT ENVIRONMENT`**
- **Current Environment Reality:**
  - `TORCH_RUNTIME_STATUS = NOT INSTALLED` (PyTorch installation requires separate explicit user approval)
  - `data/`, `checkpoints/`, and `eval/` directories **do not exist**
  - **V10 Runtime Closure:** `BLOCKED` | **V11–V20:** `LOCKED`
- **Safety Rule:** Every CLI flag below is verified against existing source files in `tools/` and `tests/`. Commands for V11–V20 represent **locked future gate contracts**—never execute them before all predecessor gates pass and separate Tier-2/user approvals are issued.

---

## Section A — Read-Only Inspection & Verification Commands (`SAFE — NO EXECUTION SIDE EFFECTS`)

These commands verify repository structure, syntax compilation, unit/integration contracts, and clean Native-Only hygiene without creating `data/`, `checkpoints/`, or `eval/`, without installing packages, and without running training or inference:

```bash
# A.1 Static bytecode compilation check across all modules
python3 -m compileall -q apps tools tests phases

# A.2 Full V10 Contract, Closure Audit, Gate Safety, Workflow & Remediation Suite (stdlib unittest)
python3 -m unittest \
  tests/test_v10a_contracts.py \
  tests/test_v10c_integration_hook.py \
  tests/test_v10_closure_audit.py \
  tests/test_evaluation_gate_safety.py \
  tests/test_workflow_engine.py \
  tests/test_v10_remediation_suite.py -v

# A.3 Native & Workflow pure-Python module self-checks (skips torch-only cases if torch absent)
python3 -m unittest apps/core/workflow/test_autonomous_training_loop.py
python3 -m unittest apps/core/workflow/test_training_hook.py

# A.4 Check Python/OS/CPU/RAM/Disk/PyTorch environment telemetry (read-only)
python3 - <<'PY'
import importlib.util, os, platform, shutil
print("python:", platform.python_version(), "| os:", platform.platform())
print("cpu_count:", os.cpu_count(), "| torch_spec:", importlib.util.find_spec("torch"))
print("disk_free_gb:", round(shutil.disk_usage(".").free / (1024**3), 3))
PY

# A.5 Verify Native-Only compliance (zero external AI API / pretrained weight imports)
grep -rnE "openai|anthropic|from_pretrained|huggingface_hub|litellm|groq|together|cohere|replicate|google\.generativeai|google\.genai" \
  apps/core/native apps/core/training apps/core/workflow

# A.6 Read-only evaluation report diagnostics & comparison (only AFTER eval reports exist)
# [NOT EXECUTED — REFERENCE ONLY]
python3 tools/diagnose_nagi_v10.py --eval-dir eval/nagi_v10 --no-write-report
python3 tools/compare_nagi_v10.py --eval-dir eval/nagi_v10 --no-write-report
```

---

## Section B — Controlled V10 Runtime Sequence (`LOCKED UNTIL SEPARATE PYTORCH CPU APPROVAL`)

> **Prerequisite Gate:** Requires explicit separate approval to install CPU-only `torch` AND explicit user confirmation to generate V10 datasets/checkpoints and mint single-use Tier-2 HMAC tokens.  
> **Status:** `NOT EXECUTED — REFERENCE ONLY`

```bash
# B.0 [SEPARATE APPROVAL REQUIRED] Install CPU-only PyTorch & verify tensor allocation
# pip install --index-url https://download.pytorch.org/whl/cpu torch
python3 - <<'PY'
import torch
torch.set_num_threads(2)
x = torch.randn(2, 4, device="cpu")
print("torch:", torch.__version__, "cuda:", torch.cuda.is_available(), "sum:", float(x.sum()))
PY

# B.1 Generate deterministic V10 dataset (data/nagi_v10/ must NOT already exist)
python3 tools/gen_nagi_v10.py \
  --output data/nagi_v10 \
  --seed 42 \
  --train-count 480 \
  --validation-count 60 \
  --test-count 60

# B.2 Run independent read-only Leakage & Integrity Auditor (EL-01..06, TL-01, SL-01, DL-01)
python3 tools/audit_leakage_v10.py --dataset-dir data/nagi_v10

# B.3 Run CPU-only Training Preflight Controller (does NOT start training; validates Workflow + Guard + Dataset)
python3 tools/train_nagi_v10.py \
  --dataset-dir data/nagi_v10 \
  --checkpoint-dir checkpoints/nagi_v10 \
  --report-dir eval/nagi_v10 \
  --seed 42 \
  --batch-size 4 \
  --sequence-length 256 \
  --training-steps 500 \
  --cpu-threads 2 \
  --learning-rate 0.0003 \
  --weight-decay 0.01

# B.4 Controlled V10 Workflow Training Execution (via CentralWorkflowOrchestrator + Tier-2 HMAC Token)
# Invokes workflow 'training.nagi_v10_controlled_run' -> TrainingRuntimeGuard -> train_sft() -> VersionedCheckpointManager
# Note: Production runs supply signed HMAC approval tokens via WorkflowGovernance (never auto-approved).

# B.5 Native Evaluation on Real Trained Checkpoint (rejects missing torch / invalid weights / oversized prompts)
python3 tools/eval_nagi_v10.py \
  --dataset-dir data/nagi_v10 \
  --checkpoint-dir checkpoints/nagi_v10 \
  --model-version ZYRQUEN-Native-10.0.0 \
  --output-dir eval/nagi_v10 \
  --experiment-id v10-baseline-s500 \
  --run-inference \
  --max-new-tokens 32

# B.6 Compare multiple V10 runs & inspect diagnosis
python3 tools/diagnose_nagi_v10.py --eval-dir eval/nagi_v10
python3 tools/compare_nagi_v10.py --eval-dir eval/nagi_v10
```

---

## Section C — V11 (`10,000` Steps / 6 Stages) Gated Commands (`LOCKED`)

> **Gate Prerequisite:** `V10 Final Closure Gate == RUNTIME PASS` AND `docs/v11/V11_RELEASE_GATE.md` pre-entry checklist approved AND `V11` implementation explicitly authorized.  
> **Status:** `LOCKED — BLUEPRINT CONTRACT ONLY (V11 CLI scripts must NOT be created until V10 closes)`

- **Execution Model (`V11-Tier0` Baseline `<= 5,000,000` params):**
  - 6 sequential stages totaling **`10,000` optimizer steps** executed via segmented checkpoint-resume (`<= 500` steps/segment under current `MAX_STEPS` cap, or adjusted strictly via benchmarked Tier-2 approval).
  - Canonical 4 evaluation splits: `train`, `validation`, `unseen`, `ood` (`UN`/`OO` slot binding enabled only after post-V10 approval).
  - Planned entry pattern (conceptual CLI structure per `docs/v11/V11_TRAINING_PLAN.md` & `V11_INTEGRATION_CONTRACT.md`):
    1. Stage-scoped dataset audit (`train`, `validation`, `unseen`, `ood`).
    2. Central Orchestrator workflow dispatch (`v11.stage_<1..6>.train`) with `parent_version` lineage and `tokenizer_sha256` pin.
    3. Mandatory Stage Exit Evaluation + zero-regression check vs V10 baseline before unlocking Stage `k+1`.

---

## Section D — V12 (`50,000` Cumulative Steps / 6 Stages / `>=100` Exps) Gated Commands (`LOCKED`)

> **Gate Prerequisite:** `V10 Closure == PASS` AND `V11 10,000-Step Final Release Gate == PASS` AND V12 explicitly authorized.  
> **Status:** `LOCKED — BLUEPRINT CONTRACT ONLY`

- **Canonical Cumulative Step Contract (`docs/v12/V12_TRAINING_PLAN.md`):**
  - **Stage 1** (`Native Representation`): `5,000` steps (cum `5,000`, min `10` exps `EXP-001..010`)
  - **Stage 2** (`Knowledge Acquisition`): `8,000` steps (cum `13,000`, min `16` exps `EXP-011..026`)
  - **Stage 3** (`Abstract & Relational Reasoning`): `10,000` steps (cum `23,000`, min `20` exps `EXP-027..046`)
  - **Stage 4** (`Multi-step Planning & OOD Transfer`): `10,000` steps (cum `33,000`, min `20` exps `EXP-047..066`)
  - **Stage 5** (`Memory & Knowledge Integration`): `8,000` steps (cum `41,000`, min `16` exps `EXP-067..082`)
  - **Stage 6** (`Self-Verification & Capability Integration`): `9,000` steps (cum `50,000`, min `18` exps `EXP-083..100`)
- **Dual-Mission Stage Exit Gate:** Every stage runs both NGI evaluation (`train`/`validation`/`unseen`/`ood`) AND deterministic Software Engineering Sandbox verification (`Compile -> Unit -> Integration -> Hidden -> Security` across `CAP-SE-01..10`) alongside anti-regression comparison against both **V10** and **V11** immutable baselines.

---

## Section E — V13–V20 Sequential Gate Commands (`LONG-TERM BLUEPRINT ONLY`)

> **Gate Prerequisite:** Strict serial promotion `V12 -> V13 -> V14 -> V15 -> V16 -> V17 -> V18 -> V19 -> V20`. Skipping any version gate is prohibited.  
> **Status:** `LONG-TERM BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION`

Each generation executes through `CentralWorkflowOrchestrator` using a shared 5-step terminal lifecycle once unlocked:
1. `[G1] Environment & Dependency Integrity Check` (Native-Only scan + resource headroom proof)
2. `[G2] Deterministic Dataset & Leakage Gate` (Versioned generator + domain anti-contamination check)
3. `[G3] Tier-2-Approved Segmented Training` (Scoped `model:<version>` HMAC token + `TrainingRuntimeGuard`)
4. `[G4] Independent Evaluation + Cumulative Regression` (`V10..V(N-1)` + version-specific deterministic verifiers: DAG planner V14, temporal memory V15, multi-file app sandbox V16, formal CAS/proof checker V17, multimodal AST/UI grounding V18, driftless curriculum V19, unified V20)
5. `[G5] Scoped Registry Stage & Human-Approved Promote` (`stage_model_with_approval` -> `promote_model_with_approval`)

---

## Section F — Global System & Resource Monitoring Commands

```bash
# F.1 Closure audit API payload inspection (without launching training)
python3 - <<'PY'
import json
from pathlib import Path
from apps.core.native.closure_audit import build_v10_closure_audit
print(json.dumps(build_v10_closure_audit(repo_root=Path(".")), indent=2, default=str))
PY

# F.2 Check immutable baseline protection & verify clean workspace (no unintended mutations)
git status --short
```

---

## Section G — Emergency Stop, Abort & Rollback Recovery Procedures

1. **Immediate Runtime Halt (Triggered Automatically by `TrainingRuntimeGuard`):**
   - Triggers when `RSS > 3.5 GB` (`ram_hard_limit`), `disk_free < 2.0 GB` (`disk_reserve_violated`), `new_disk > 1.0 GB` (`disk_budget_violated`), `NaN`/`Inf` loss (`loss_diverged`), `experiment_elapsed > 1200s`, or `loop_elapsed > 3600s`.
   - Action: Aborts before optimizer step / checkpoint save (preventing partial/corrupt `.pt` artifacts), returns workflow status `BLOCKED` or `WAITING_RESOURCE`, and records immutable failure audit event in `workflow_audit_logs`.
2. **Manual Workflow Cancellation:**
   - Cancel active runs via `CentralWorkflowOrchestrator.cancel_run(run_id, actor_id=..., reason=...)` (writes `workflow.cancelled` into append-only audit DB):
     ```python
     from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator

     orch = CentralWorkflowOrchestrator(db_path="/tmp/zyrquen_workflow.db", work_dir=".")
     orch.cancel_run(run_id, actor_id="admin", reason="manual_abort")
     orch.shutdown(wait=True)
     ```
3. **Scoped Model Registry Rollback (`Tier-2 HMAC Required`):**
   - Execute `CentralWorkflowOrchestrator.rollback_model_with_approval(...)` using a fresh single-use HMAC token with exact `scope = f"model:{target_version}"` and `run_id` binding. Historical checkpoints (`v7..v9`, prior promoted baselines) are never deleted during rollback.

---

## Mandatory Truthfulness Sections

### ASSUMPTIONS
- All future V11–V20 CLI tools will reuse `tools/*_nagi_v10.py` strict non-overwrite atomic report patterns and `CentralWorkflowOrchestrator` Tier-2 governance hooks.

### OPEN DECISIONS
- **OD-CLI-01:** Exact CLI entry point paths for V11+ (`tools/v11/...` vs parameterized subcommands) remain deferred until V10 passes Runtime Closure and V11 implementation is authorized.

### NOT VERIFIED
- Section B (`tools/gen_nagi_v10.py`..`eval_nagi_v10.py` live execution), Section C (V11), Section D (V12), and Section E (V13–V20) have **NOT BEEN EXECUTED** in this container.
