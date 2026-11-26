# ZYRQUEN V10 — PyTorch CPU-Only Installation Plan (Pre-Approval Review)

- **Document ID:** `V10-PYTORCH-CPU-INSTALL-PLAN`
- **Status:** `READY FOR HUMAN REVIEW — NOT EXECUTED`
- **Gate Prerequisite:** `READY_FOR_PYTORCH_CPU_PREPARATION` (`READY`)
- **Current Runtime State:** `TORCH_RUNTIME_STATUS = NOT INSTALLED`
- **Scope Boundary:** PyTorch CPU-only runtime installation & minimal tensor/thread-cap verification **only**. Strictly **NO** training, **NO** inference, **NO** benchmarking, **NO** dataset/checkpoint generation, and **NO** GPU/CUDA dependencies.

---

## 1. Verified Python & OS Architecture Compatibility

Measured directly on the current host (read-only inspection, no mutations):

| Property | Measured Value | ZYRQUEN Platform Requirement | Compatibility Status |
|---|---|---|---|
| **Python Version** | `3.11.2` (`CPython`, GCC `12.2.0`) | Python `3.11` (`>=3.9, <=3.12`) | **COMPATIBLE** |
| **Executable** | `/usr/bin/python3` | Standard Python 3 runtime | **COMPATIBLE** |
| **Extension ABI Tag** | `.cpython-311-x86_64-linux-gnu.so` | `cp311` Linux `x86_64` wheels | **COMPATIBLE** |
| **Operating System** | `Linux` (`4.19.0-gvisor`, `Linux-4.19.0-gvisor-x86_64-with-glibc2.36`) | Linux | **COMPATIBLE** |
| **CPU Architecture** | `x86_64` (`64bit`) | `x86_64` CPU | **COMPATIBLE** |
| **C Library** | `glibc 2.36` | `manylinux_2_17` / `manylinux_2_28` (`>= 2.17`) | **COMPATIBLE** |
| **CPU SIMD Extensions** | `sse4_2`, `avx`, `fma`, `avx2`, `avx512f`, `avx512_vnni` | Standard CPU tensor ops | **COMPATIBLE** |
| **CPU Cores** | `4` (`os.cpu_count() == 4`) | `>= 2` cores (clamped to `<= 2` threads during training/eval) | **PASS** |
| **RAM** | `12.0 GiB` total / `10.583 GiB` available (`0.0 GiB` swap) | `>= 3.5 GiB` hard limit (`3.0 GiB` soft limit) | **PASS** |
| **Disk Free** | `282.144 GiB` free | `>= 2.0 GiB` reserve + `<= 1.0 GiB` artifact budget | **PASS** |
| **GPU / CUDA** | `nvidia-smi`: `None` (`cuda_available: False`) | CPU-only (no GPU / no CUDA) | **PASS** |
| **Packaging Tooling** | `venv: True`, `ssl: True`, `curl: /usr/bin/curl`, `pip: False`, `ensurepip: False` | `pip` required to install CPU wheel | **BOOTSTRAP REQUIRED** |

---

## 2. Policy Compliance Controls (Native-Only & CPU-Only)

Every step in this plan must satisfy ZYRQUEN Ω∞ mandatory governance rules:

1. **CPU-Only Wheel Source Isolation**
   - Install **exclusively** from PyTorch's official CPU wheel index: `https://download.pytorch.org/whl/cpu`.
   - Never install `cuda`, `nvidia-*`, `triton`, or GPU PyTorch builds.
   - Verify `torch.cuda.is_available() is False` and `"cuda"` / `"nvidia"` packages are absent after installation.
2. **Native-Only Zero-External-AI Compliance**
   - Install **only** `torch` (and its minimal pure-runtime CPU dependencies such as `filelock`, `typing-extensions`, `sympy`, `networkx`, `jinja2`, `fsspec`, `mpmath`).
   - Strictly **prohibited**: `transformers`, `huggingface_hub`, `accelerate`, `peft`, `bitsandbytes`, `openai`, `anthropic`, `google-genai`, `langchain`, `litellm`, `ollama`, or any pretrained weights/checkpoints.
   - Re-verify the External AI dependency scan (`0 matches`) after installation.
3. **Resource Guard & Thread Cap Enforcement**
   - Immediately validate `apps.core.workflow.resource_guard.enforce_cpu_thread_cap(2)` against live `torch` (`OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `TORCH_NUM_THREADS=2`, `torch.get_num_threads() <= 2`).
   - Confirm `apps.core.workflow.resource_guard.check_disk_reserve(".", reserve_gb=2.0)` stays `ok: True`.
4. **Hard Stop Before Runtime Execution**
   - Installation approval **does not** authorize `tools/gen_nagi_v10.py`, `tools/train_nagi_v10.py` execution, `train()`, `train_sft()`, `EvaluationEngine.evaluate_native_model()`, dataset creation (`data/`), or checkpoint creation (`checkpoints/`).
   - `V10-D` remains `NOT RUN` (waiting on Tier-2 HMAC approval and experiment execution) and `V11–V20` remain `LOCKED` until V10-D passes cleanly.

---

## 3. Proposed PyTorch CPU-Only Installation Steps (Reference — Pending Approval)

> **NOTE:** Commands below are **NOT EXECUTED**. Execute only after explicit human approval of PyTorch CPU Preparation.

### Step 1 — Re-Verify Clean Pre-Install State (Read-Only)
Confirm no `torch` installation and no runtime artifact directories (`data/`, `checkpoints/`, `eval/`) exist:

```bash
python3 -c 'import importlib.util; from pathlib import Path; print("torch:", importlib.util.find_spec("torch"), "dirs:", {d: Path(d).exists() for d in ("data", "checkpoints", "eval")})'
```

### Step 2 — Bootstrap `pip` Without GPU Tooling
Because `/usr/bin/python3` currently lacks both `pip` and `ensurepip`, provision `pip` cleanly via OS package manager or `get-pip.py` (optionally inside a dedicated project `.venv` if isolation is preferred over system site-packages):

- **Option A (System Python via apt, if root/apt available):**
  ```bash
  apt-get update && apt-get install -y --no-install-recommends python3-pip
  ```
- **Option B (Isolated Virtualenv without `ensurepip`, user-space safe):**
  ```bash
  python3 -m venv --without-pip .venv
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  .venv/bin/python /tmp/get-pip.py
  rm -f /tmp/get-pip.py
  ```

### Step 3 — Install PyTorch CPU-Only Wheel
Using the target Python interpreter (`python3` or `.venv/bin/python`), install **strictly** the CPU-only `torch` build with `--no-cache-dir` to minimize disk footprint:

```bash
python3 -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
```

*(Pinning a specific verified CPU release such as `torch==2.5.1+cpu` or `torch==2.6.0+cpu` is supported if required by release governance.)*

### Step 4 — Verify CPU-Only Runtime, Thread Cap & Tensor Allocation (No Training)
Run a minimal read-only tensor & Resource Guard check without creating datasets, checkpoints, or evaluation files:

```bash
python3 - <<'PY'
from apps.core.workflow.resource_guard import (
    check_disk_reserve,
    check_torch_cpu_runtime,
    enforce_cpu_thread_cap,
)
import torch

probe = check_torch_cpu_runtime()
assert probe["available"] is True, probe
assert probe["cuda_available"] is False, "CUDA must remain unavailable in CPU-only mode"

caps = enforce_cpu_thread_cap(2)
assert caps["torch_threads"] <= 2, caps

x = torch.randn(2, 4, device="cpu", dtype=torch.float32)
y = torch.matmul(x, x.transpose(0, 1))
assert y.shape == (2, 2) and bool(torch.isfinite(y).all())

disk_ok, disk_info = check_disk_reserve(".", reserve_gb=2.0)
assert disk_ok is True, disk_info

print("PYTORCH_CPU_PREP_OK:", {"torch_version": probe["version"], "cuda": probe["cuda_available"], "threads": caps["torch_threads"], "disk_free_gb": disk_info["free_gb"]})
PY
```

### Step 5 — Post-Install Native-Only & Hygiene Audit
Verify no external AI packages, no CUDA/NVIDIA packages, and no runtime artifact directories were created:

```bash
python3 -m pip list
grep -rnE "openai|anthropic|from_pretrained|huggingface_hub|litellm|groq|together|cohere|replicate|google\.generativeai|google\.genai" \
  apps/core/native apps/core/training apps/core/workflow
```

Confirm:
- Zero `nvidia-*` / `cuda` packages installed.
- Zero external AI SDK / pretrained weight dependencies.
- `data/`, `checkpoints/`, and `eval/` still do **not** exist.
- Stop immediately after verification; do **not** initiate training, inference, or benchmarking without separate explicit authorization.

---

## 4. Approval Boundary

Approval of this document authorizes **Steps 1–5 only** (`PyTorch CPU Preparation`).  
Actual V10 dataset generation, controlled CPU training (`<= 500` steps), native inference evaluation, and V10-D closure require separate explicit authorization and single-use Tier-2 HMAC approval tokens.
