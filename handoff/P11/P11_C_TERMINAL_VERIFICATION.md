# ZYRQUEN Ω∞ — P11-C Terminal Verification Guide (`P11_C_TERMINAL_VERIFICATION.md`)

- **Important Truthfulness Notice:** **NONE** of the PyTorch, `pytest`, or pilot commands below have run in the user's terminal yet (`TERMINAL_VERIFICATION = PENDING`). Never mark any item passed until executed directly in the target terminal.

---

## 1. AI Studio Executed vs. Pending Terminal Verification

| Check | AI Studio Result (Actual) | Terminal Verification Status |
|---|---|---|
| Pure-stdlib 14-suite contract tests (`tests/test_*.py`) | **Executed:** `101 ran, 99 OK, 2 skipped` (`6.201s`) | Confirm parity in git checkout terminal |
| Maintainer native-only scan (`maintainer.audit.v1`) | **Executed:** `505` files, `294` Python files, `0` errors, `native_only_compliance: PASS` | Confirm clean after hygiene remediation |
| Native core `pytest` suite (`apps/core/native/test_*.py`) | **Failed (`6` import errors: `No module named 'pytest'`)** | **PENDING** (run after venv setup) |
| PyTorch CPU wheel & thread cap (`<= 2` threads) | **Blocked (`TORCH_NOT_INSTALLED`)** | **PENDING** |
| Real `torch.save` + `torch.load(weights_only=True)` | **NOT RUN** (mocked in AI Studio) | **PENDING** |
| 10-step CPU micro-benchmark (`Peak RSS`, `sec/step`) | **NOT RUN** | **PENDING** |
| Step-0 & Step-500 `P11-EXP-01-PILOT` execution | **NOT EXECUTED (`BLOCKED`, `0/500` steps)** | **PENDING** (requires remediations `BLK-01..10` + approval) |

---

## 2. Exact Commands to Run in User's Local Git Terminal

### Step 1 — Verify Repository Identity & Clean Tree
```bash
git status --short && git rev-parse HEAD
```
- **Expected Result:** Clean working tree (or only reviewed changes) and 40-char commit SHA recorded into handoff.

### Step 2 — Provision CPU-Only Environment (Strict Zero-GPU, Zero-External-AI)
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
python3 -m pip install --no-cache-dir pytest fastapi pydantic sqlalchemy alembic httpx
python3 -m pip list
```
- **Expected Result:** `torch` `+cpu` installed; **zero** `nvidia-*`, `cuda`, `transformers`, `huggingface_hub`, `openai`, `anthropic`, or `google-genai` packages present.

### Step 3 — Verify PyTorch CPU Runtime & Thread Limits
```bash
python3 - <<'PY'
from apps.core.workflow.resource_guard import check_torch_cpu_runtime, enforce_cpu_thread_cap, check_disk_reserve
probe = check_torch_cpu_runtime()
caps = enforce_cpu_thread_cap(2)
ok_disk, disk = check_disk_reserve(".", reserve_gb=2.0)
assert probe["available"] is True and probe["cuda_available"] is False, probe
assert caps["torch_threads"] <= 2, caps
assert ok_disk is True, disk
print("TERMINAL_TORCH_CPU_OK:", probe, caps, disk)
PY
```
- **Expected Result:** Prints `TERMINAL_TORCH_CPU_OK` with `cuda_available: False`, `torch_threads <= 2`, and `ok: True`.

### Step 4 — Execute Full Native & Stdlib Test Suites
```bash
pytest -v apps/core/native/
python3 -m unittest tests/test_v11_stage1_readiness.py tests/test_v10_closure_audit.py tests/test_v10a_contracts.py tests/test_v10c_integration_hook.py tests/test_v10d_closure_runner.py tests/test_dataset_status_api.py tests/test_evaluation_gate_safety.py tests/native/test_checkpoint_resume.py tests/test_workflow_engine.py tests/test_native_train_observability.py tests/test_v10_remediation_suite.py tests/test_v10_findings_abcd_remediation.py tests/test_v9_static_contracts.py tests/test_maintainer_bot.py
```
- **Expected Result:** All pure-stdlib tests (`0` failures; `0` skipped once `pydantic` installed) AND all `apps/core/native/test_*.py` PyTorch tests (`test_model.py`, `test_train_torch.py`, `test_registry.py`, etc.) PASS cleanly.

### Step 5 — Verify Real `weights_only=True` Checkpoint Reload With RNG State
```bash
python3 - <<'PY'
import random, tempfile, torch
from apps.core.native.config import ZyrquenConfig
from apps.core.native.model import ZyrquenModel
from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager

cfg = ZyrquenConfig()
model = ZyrquenModel(cfg)
rng = random.Random(1337)
with tempfile.TemporaryDirectory() as d:
    mgr = CheckpointManager(d)
    mgr.save(step=1, payload={
        "step": 1,
        "model": model.state_dict(),
        "model_config": cfg.to_dict(),
        "rng": rng.getstate(),
    })
    step, state = mgr.load_latest(allow_unsafe_pickle=False)
    assert step == 1 and isinstance(state, dict)
    print("WEIGHTS_ONLY_RELOAD_OK: step=", step)
PY
```
- **Expected Result:** If PyTorch `>=2.5` prints `WEIGHTS_ONLY_RELOAD_OK`, raw RNG tuples are safe; if `UnpicklingError` / `Weights only load failed` is raised, apply the `list[int]` RNG serialization patch from `P11_C_TRAINING_DESIGN.md` **before** running any training.

### Step 6 — Native-Only & Security Rescan
```bash
grep -rnE "openai|anthropic|huggingface|transformers|Qwen|llama|claude|gemini|genai|litellm|vllm|ollama" apps/core apps/api tools phases --exclude-dir=__pycache__
```
- **Expected Result:** Zero unexpected external AI SDK imports anywhere in runtime/training/API modules (with `download_model.py` quarantined/removed once approved).

### Step 7 — Post-Remediation Gate Before `P11-EXP-01-PILOT` Execution
After implementing `tools/gen_nagi_v11.py`, `tools/audit_leakage_v11.py`, and `tools/eval_nagi_v11.py` (`BLK-03..BLK-09`), run dataset generation + leakage audit (`PASS`) + Step-0 random-init baseline eval (`unseen/ood < 5% FAIL` on intelligence, `PASS` on schema) **before** approving any `500`-step run.
