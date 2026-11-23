# ZYRQUEN Ω∞ — P11-C Compute Plan (`P11_C_COMPUTE_PLAN.md`)

- **Host Environment Verified (AI Studio Container):** `4` vCPU (`Python 3.11.2`), `12.00 GiB` total RAM (`9.894 GiB` available, `0` swap), `281.448 GiB` free disk, no GPU (`nvidia_smi: None`).
- **Missing Dependency Block:** `torch` is NOT installed in AI Studio -> **ALL runtime memory (`Peak RSS`) and duration (`sec/step`) numbers remain `NOT VERIFIED` assumptions until measured in the user's terminal.**
- **Cloud / Paid Compute Budget:** `$0.00` (Local CPU-only execution; paid GPUs strictly prohibited).

---

## 1. Memory Budget (`V11-Tier0-Default`, `3,737,856` params, `float32`)

| Component | Exact / Estimated Footprint | Basis / Verification |
|---|---|---|
| Model Parameters (`FP32`) | `14.26 MiB` (`3,737,856 x 4 B`) | Exact math (`ZyrquenConfig`) |
| AdamW Static State (`w + grad + m + v`) | `57.04 MiB` (`3,737,856 x 16 B`) | Exact math |
| PyTorch Base Runtime RSS | `~250 – 450 MiB` (Assumed) | `NOT VERIFIED` (`torch` absent) |
| Forward/Backward Activations (`B=4, L=256`) | `~150 – 400 MiB` (Assumed) | `NOT VERIFIED` (`torch` absent) |
| Dataset & Tokenizer RAM Cache | `~20 – 50 MiB` (Assumed) | `NOT VERIFIED` |
| **Estimated Peak RSS** | **`~0.50 – 0.95 GiB`** | **Well below `3.0 GiB` soft / `3.5 GiB` hard `RamMonitor` limit (`NOT VERIFIED`)** |

## 2. Storage Plan (`_TrainingRuntimeGuard` Compliant)

- **Pilot Dataset (`nagi_v11_pilot`, `1,560` rows + manifest + leakage report):** `~1.5 – 2.5 MiB`
- **Tokenizer (`zyrquen.tokenizer.v2`, `V=2048`):** `< 0.5 MiB`
- **Checkpoints (`ckpt_00000250.pt`, `ckpt_00000500.pt`, `keep_last=2`, `~58 MiB` each):** `~116 MiB`
- **Eval Outputs + Logs (`eval/`, JSONL):** `~5 – 10 MiB`
- **Total New Disk Usage (`P11-EXP-01-PILOT-R1`):** **`~130 MiB` (`~0.13 GiB`)** — well inside `max_new_disk_gb = 1.0 GiB` and leaving `> 281 GiB` free (`reserve >= 2.0 GiB`).

## 3. Runtime Estimates Across CPU Latency Regimes (`NOT VERIFIED`)

*(Assuming `batch_size=4, block_size=256, max_cpu_threads=2`; must be calibrated via 10-step CPU micro-benchmark before launching `500` steps.)*

| Metric | Optimistic (`0.35 s/step`) | Nominal (`0.85 s/step`) | Conservative (`1.50 s/step`) | Status |
|---|---:|---:|---:|---|
| `10`-step Micro-Benchmark | `~3.5 s` | `~8.5 s` | `~15 s` | Gate prerequisite before `500`-step run |
| `500`-step Training (`+2` val evals) | `~3.2 min` (`~190 s`) | `~7.7 min` (`~460 s`) | `~13.5 min` (`~810 s`) | Fits `1200s` soft / `3600s` hard timeout |
| `480`-row Greedy Eval (`max_new_tokens=64`, uncached) | `~2.5 min` | `~5.0 min` | `~8.0 min` | Separate post-run command; monitor timeout |
| **Total Wall-Clock Window** | **`~6 min`** | **`~13 min`** | **`~22 min`** | **`NOT VERIFIED` until terminal PyTorch probe** |
