# ZYRQUEN Ω∞ — P11 Compute Estimate (`P11_COMPUTE_ESTIMATE.md`)

- **Mission:** Hardware, Memory, Storage & Training Duration Estimate for P11
- **Mode:** `READINESS AUDIT + PREPARATION` (`SPEND / CLOUD PROVISIONING: STRICTLY PROHIBITED`)
- **Host Probe Timestamp:** Verified via live non-destructive Linux host inspection

> **Honesty Rule:** Because `torch` is NOT installed in this container, exact runtime PyTorch base RSS, backward activation spikes, and CPU `sec/step` throughput are explicitly marked **`NOT VERIFIED`**. Duration figures below use explicit, labeled conservative CPU assumptions and MUST NOT be reported as measured benchmarks.

---

## 1. Verified Host Hardware & Software Baseline

| Resource | Measured Value (`run_command` Probe) | Code Enforcement / Budget Cap | Status |
|---|---|---|---|
| CPU Cores | `4` logical vCPUs | `max_cpu_threads = 2` (`resource_guard.py`, `groups.py`) | `PASS` |
| System RAM Total / Available | `12.00 GiB` total / `~9.83 GiB` available (`0 kB` swap) | `RamMonitor`: `3.0 GiB` soft / `3.5 GiB` hard (`groups.py`) | `PASS` (Static capacity) |
| GPU / Accelerator | None (`nvidia_smi: None`) | CPU-only `float32` enforced (`groups.py:809`) | `PASS` (CPU-only compliant for Tier-0) |
| Disk Total / Free | `282.85 GiB` total / `281.45 GiB` free | `min_free_disk_gb = 2.0 GiB`, `max_new_disk_gb = 1.0 GiB` (`_TrainingRuntimeGuard`) | `PASS` |
| Python & PyTorch | Python `3.11.2`; `torch = None`, `fastapi = None`, `pytest = None`, `pip = None` | Hard prerequisite before any runtime step | `BLOCKED` |

---

## 2. Static & Estimated Runtime Memory Per Model Tier (`float32`)

Formulas verified from `apps/core/native/config.py`:
- $\text{FP32 Weights} = P \times 4\text{ bytes}$
- $\text{AdamW Static State (Weights + Grads + m + v)} = P \times 16\text{ bytes}$
- $\text{Estimated Peak RSS} = \text{PyTorch Base RSS } (0.25\text{–}0.45\text{ GiB, NOT VERIFIED}) + \text{AdamW Static} + \text{Batch Activations/Logits } (B=4, L=256 \approx 0.15\text{–}0.40\text{ GiB, NOT VERIFIED}) + \text{Dataset/Tokenizer in RAM } (\approx 0.05\text{ GiB})$

| Tier Configuration | Params (`estimated_num_parameters`) | FP32 Weights | AdamW Static FP32 | Estimated Peak RSS (`B=4, L=256`) | Fits `5M` Cap & `3.0/3.5 GiB` RAM Guard? | Verification Status |
|---|---:|---:|---:|---:|---|---|
| **V11-Tier0-SmokeMini** (`2L, d=128, ff=352, V=640, L=256`) | `483,968` | `1.85 MiB` | `7.38 MiB` | `~0.35–0.60 GiB` (est.) | **YES** (`fits_5M=True`) | `NOT VERIFIED` (`torch` absent) |
| **V11-Tier0-Default** (`4L, d=256, ff=704, V=2048, L=256`) | `3,737,856` | `14.26 MiB` | `57.04 MiB` | `~0.50–0.90 GiB` (est.) | **YES** (`fits_5M=True`) | `NOT VERIFIED` (`torch` absent) |
| **V11-Tier0-Vocab4096** (`4L, d=256, ff=704, V=4096, L=256`) | `4,262,144` | `16.26 MiB` | `65.04 MiB` | `~0.55–0.98 GiB` (est.) | **YES** (`fits_5M=True`) | `NOT VERIFIED` (`torch` absent) |
| **V11-Tier0-Deep6L** (`6L, d=256, ff=576, V=2048, L=256`) | `4,754,688` | `18.14 MiB` | `72.55 MiB` | `~0.55–1.05 GiB` (est.) | **YES** (`fits_5M=True`) | `NOT VERIFIED` (`torch` absent) |
| **V11-Tier1-Candidate** (`6L, d=384, ff=1024, V=4096, L=512`) | `12,194,688` | `46.52 MiB` | `186.08 MiB` | `~1.00–1.85 GiB` (est.) | **BLOCKED** (`>5M` cap) | `BLOCKED` |
| **V11-Tier2-Candidate** (`8L, d=512, ff=1408, V=4096, L=512`) | `27,795,968` | `106.03 MiB` | `424.13 MiB` | `~1.50–2.80 GiB` (est.) | **BLOCKED** (`>5M` cap) | `BLOCKED` |

> **Important Memory Caveat:** Notice `handle_training_execute` copies model initial weights once (`groups.py` / `train.py:454-457`) and keeps `list(train_pairs)` + tokenized inputs in RAM. A real 10-step CPU RSS measurement MUST confirm Peak RSS stays strictly `< 1.5 GiB` (well inside `3.0 GiB` soft / `3.5 GiB` hard caps).

---

## 3. Storage Requirements (`_TrainingRuntimeGuard` Compliant)

Per `_TrainingRuntimeGuard`: must keep `>= 2.0 GiB` disk free and add `<= 1.0 GiB` new artifacts per run.

| Artifact Category | Tier0-Default (`3.74M`) | Tier0-Deep6L (`4.75M`) | Notes |
|---|---:|---:|---|
| Dataset `data/nagi_v11/` (`6,240` JSONL rows + manifest + audit report) | `~2.5 – 5.0 MiB` | `~2.5 – 5.0 MiB` | Deterministic symbolic text prompts |
| Tokenizer `tokenizer.json` (`V=2048`) | `< 0.5 MiB` | `< 0.5 MiB` | JSON vocabulary & merges |
| Single Rolling Checkpoint (`ckpt_*.pt`: weights + AdamW `m, v` + metadata) | `~58 MiB` | `~74 MiB` | `keep_last=3` -> `~174–222 MiB` live working set |
| ModelRegistry Immutable Snapshots (`20` x 500-step segments, `ckpt + tok + manifest`) | `~1.15 GiB` (20 snaps) | `~1.48 GiB` (20 snaps) | **Warning:** `20` full optimizer-state snapshots exceed `1.0 GiB` cumulative if not pruned! |
| Evaluation Reports + JSONL Logs (`eval/` + `TrainingMonitor`) | `~5 – 15 MiB` | `~5 – 15 MiB` | Per-step JSONL + eval output predictions |
| **Single-Segment Peak New Disk Delta (`<= 500` steps)** | **`~240 MiB` (`0.23 GiB`)** | **`~300 MiB` (`0.29 GiB`)** | **Fits cleanly inside `1.0 GiB` max new disk cap** |

---

## 4. Training & Evaluation Duration Estimates (Explicit Unverified Assumptions)

**CRITICAL:** Actual CPU `sec/step` on this 4-vCPU container (`max_cpu_threads = 2`) is **`NOT VERIFIED`** until PyTorch CPU is installed and benchmarked. Calculations below model three explicit latency regimes for `batch_size=4, seq_len=256, grad_accum=1` (`1,024` tokens/step):

| Scenario | Assumed CPU `sec/step` | Periodic Val Eval Overhead (20 batches / 250 steps) | Single `500`-Step Segment Time | Full `10,000`-Step (`20`-Segment) Curriculum | Fits `groups.py` Segment Timeout (`1200s` soft / `3600s` hard)? |
|---|---:|---:|---:|---:|---|
| Optimistic CPU (AVX2 / AVX-512) | `0.35 s/step` | `~15 s` | `~3.2 min` (`~190 s`) | `~1.06 hr` | **YES** (`< 1200s`) |
| Nominal CPU (`2` threads, `Tier0-Default`) | `0.85 s/step` | `~35 s` | `~7.7 min` (`~460 s`) | `~2.56 hr` | **YES** (`< 1200s`) |
| Conservative CPU (`2` threads, `Tier0-Deep6L`) | `1.50 s/step` | `~60 s` | `~13.5 min` (`~810 s`) | `~4.50 hr` | **YES** (within `1200s` soft / `3600s` hard) |
| Degraded / Over-Throttled CPU (`> 2.5 s/step`) | `2.50+ s/step` | `~100 s` | **`>= 22.5 min` (`>= 1350 s`)** | `>= 7.5 hr` | **FAILS `1200s` soft timeout** -> shrink segment to `250` steps or verify CPU threads |

### Greedy Evaluation Runtime Estimate (1,440 examples across `val + unseen + ood`, `max_new_tokens=64`)
- Because `ZyrquenModel.generate()` (`apps/core/native/model.py:123-141`) lacks KV-cache, `64` decode steps require `64` forward passes per example (~`92,160` forward passes total across `1,440` rows if single-example decoded).
- **Assumed Uncached Decode Time (`NOT VERIFIED`):** At `0.3–1.0 s/example`, evaluating all `1,440` rows single-threaded could take **`7 – 24 minutes`** (`420 – 1,440 s`) — exceeding or crowding a `1200s` soft workflow timeout!
- **Remediation Option (No Architecture Change Required Initially):** Benchmark 20-row decode speed first; if slow, support batched padded/left-padded evaluation or smaller stratified diagnostic eval (`180` rows) during intermediate segments while running full `1,440`-row eval ONLY at major stage gates (`S2, S4, S6`).

---

## 5. Small-Scale Validation Options (Zero Cloud Spend)

All initial validation uses local CPU host resources only (**$0 cloud spend**; zero paid GPUs):

1. **Option A — Micro-Benchmark & Runtime Smoke (`20` steps, `Tier0-SmokeMini` `484K`):** Verifies PyTorch CPU install, `weights_only=True` RNG serialization, real Peak RSS, and baseline `ms/step` in `< 30 seconds` (est.). Does NOT verify intelligence.
2. **Option B — Controlled Tier-0 Single-Segment Pilot (`500` steps, `Tier0-Default` `3.74M`):** Tests end-to-end 4-split SFT dataset loading, dynamic slot binding, cosine warmup, checkpoint SHA-256 save/resume, and full `zyrquen.v11.evaluation_report.v1` harness within `1` Tier-2 approval segment (`~5–15 min` est.).
3. **Option C — Architecture Depth Probe (`1,000` steps = `2 x 500` segments comparing `Tier0-Default 4L` vs `Tier0-Deep6L 6L`):** Only after Option B passes pipeline validation cleanly.
