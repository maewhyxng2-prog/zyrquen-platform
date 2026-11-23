# ZYRQUEN Ω∞ — P11 Training Plan (`P11_TRAINING_PLAN.md`)

- **Mission:** Native Training Plan for ZYRQUEN P11 (`ZYRQUEN-Native-11.x.x`)
- **Mode:** `READINESS AUDIT + PREPARATION` (`TRAINING AUTHORIZATION: NOT GRANTED`)
- **Target Architecture:** `ZyrquenModel` (`zyrquen-decoder`, random initialization ONLY — zero pretrained weights, zero external APIs)
- **Prerequisite Reference Spec:** `/docs/v11/V11_TRAINING_PLAN.md`, `/apps/core/native/train.py`, `/apps/core/workflow/handlers/groups.py`

> Every training configuration, pipeline mechanism, and identified implementation gap below cites exact source paths and explicitly marks unverified runtime assumptions as `NOT VERIFIED` or `BLOCKED`.

---

## 1. Training Pipeline Readiness Matrix

| Component | File / Config Ref | Actual Evidence | Status | Required Remediation | Verification Method |
|---|---|---|---|---|---|
| Tier-0 V11 Config Preset | `/apps/core/native/train.py:78-114` | `TrainConfig.tier0_v11()` exists: `block_size=256, batch_size=4, grad_accum_steps=1, max_steps=500, segment_max_steps=500, lr_total_steps=10_000, lr=3e-4, min_lr=3e-5, warmup_steps=100, weight_decay=0.1, grad_clip=1.0, eval_interval=250, eval_batches=20, checkpoint_interval=250, log_interval=10, seed=1337, strict_limits=True`. | `PASS` (Code Preset) | Freeze open decisions (`OD-TP-01`, `OD-TP-02`) before S1 start. | `tests/test_v11_stage1_readiness.py` |
| Optimizer & Weight Decay Grouping | `/apps/core/native/train.py` (`train`, `train_sft`) | AdamW `betas=(0.9, 0.95)`; `dim >= 2` tensors receive `weight_decay=0.1`; norms/1D weights receive `0.0`. Gradient norm clipped via `clip_grad_norm_(..., grad_clip=1.0)`. | `NOT VERIFIED` (No `torch`) | Execute 20-step PyTorch CPU test validating weight decay groups, finite grad norm clipping, and weight deltas. | `pytest apps/core/native/test_train_torch.py` |
| LR Scheduler (`lr_at`) | `/apps/core/native/train.py:160-200` | Linear warmup (`0 -> lr` over `warmup_steps`) followed by cosine decay (`lr -> min_lr`) over `lr_total_steps` (`10_000`) or `max_steps` (`500`). | `PASS` (Math), `NOT VERIFIED` (Stage Boundary Policy) | Resolve `OD-TP-01`: keep continuous `lr_total_steps=10_000` across 20 segments vs stage-local cosine decay. | Unit test verifying `lr_at(step)` across segment boundaries `step=499 -> 500 -> 501`. |
| SFT Loss Function & Masking | `/apps/core/native/sft.py`, `/apps/core/native/train.py` | CrossEntropyLoss with `ignore_index=-100`; prompt tokens masked `-100`, target + `<eos>` supervised. Truncation guards raise error instead of silently dropping targets. | `PASS` (Static), `NOT VERIFIED` (Runtime) | Validate end-to-end on real V11 tokenized SFT samples with `torch`. | `pytest apps/core/native/test_train_torch.py` |
| Batching & Ephemeral Slot Binding | `/apps/core/workflow/handlers/groups.py:553`, `/apps/core/native/train.py:463` | `groups.py:553` binds `<slot_0>..<slot_31>` **once** before `train_sft()`; `sample_sft_batch()` draws random indices with replacement (`rng.randrange`). | `FAIL` | Move `bind_ephemeral_slots()` into dynamic per-step collation seeded deterministically by `(seed, step, idx)`. | Unit test checking slot permutations vary across steps for the same prompt ID while staying reproducible. |
| Stage Curriculum Filtering (`stage_tags`) | `/apps/core/native/train.py:450-520`, `/apps/core/workflow/handlers/groups.py:551` | `handle_training_execute` loads ALL of `train.jsonl` regardless of `stage_tag`; `TrainConfig.tier0_v11()` lacks `stage_id` / replay ratios. | `FAIL` | Implement `stage_id` + deterministic `stage_replay_weights` curriculum sampler in `train_sft` & `groups.py`. | Unit test asserting Stage 1 samples strictly `stage_1_*` rows and Stage 2 mixes replay ratios deterministically. |
| Checkpoint Save / Resume & `weights_only=True` | `/apps/core/training_infrastructure/recovery/checkpoint_recovery.py:16-184`, `/apps/core/native/train.py:293-331,555-590` | Atomic write + SHA-256 `manifest.json`, `keep_last` rotation, `allow_unsafe_pickle=False` (`weights_only=True`). Saves `"rng": rng.getstate()` tuples. Multi-segment `groups.py` requires `resume_existing=True` and lacks dataset/config SHA verification on resume. | `FAIL` / `NOT VERIFIED` | Test `weights_only=True` load on PyTorch CPU (convert RNG state to `list[int]` if blocked); assert `dataset_content_sha256`, `tokenizer_sha256`, and `model_config` equality on resume. | `tests/native/test_checkpoint_resume.py` with real `torch.save` / `torch.load`. |
| NaN / Divergence / Resource Failure Handling | `/apps/core/native/train.py`, `/apps/core/workflow/resource_guard.py:1-519` | Checks `math.isfinite(total_loss)` before `optimizer.step()`; `CostController` step/time caps; `RamMonitor` (`3.0 / 3.5 GiB`); disk guard (`2.0 GiB` reserve / `1.0 GiB` max new). | `PASS` (Design), `NOT VERIFIED` (Runtime) | Verify `RamMonitor` actually trips cleanly during CPU stress & OOM simulation once `torch` is present. | Fault-injection test forcing NaN loss & synthetic low disk/RAM thresholds. |
| API Orchestrator & Control Endpoints | `/apps/api/routers/training.py`, `/apps/api/training_jobs.py`, `/apps/api/training_schemas.py`, `/apps/core/training/orchestrator.py:38,137-305` | `POST /v1/training/runs` enforces `training.execute` approval if paths configured, uses `ThreadPoolExecutor(max_workers=1)`, defaults `block_size=128, max_steps=100`, lacks `RamMonitor`, cannot resume prior checkpoints, enforces `MAX_CPU_TRAINING_STEPS=1000`, and has **zero pause/cancel/resume endpoints**. | `FAIL` | Align `TrainingOrchestrator` & schemas with `TrainConfig.tier0_v11()`, wire `RamMonitor`, support parent checkpoint resume, and add `POST /v1/training/runs/{id}/cancel`. | API integration tests for cancel propagation, orchestrator resume, and Tier-0 limits. |

---

## 2. Hyperparameters & Approved Model Tiers (P11 Baseline = `Tier-0`)

Training MUST start from **random initialization only** (`ZyrquenModel(cfg)`, `Normal(0, 0.02)` and `0.02 / sqrt(2 * n_layers)` residual projections). No external weights permitted.

| Parameter | Primary Pilot / Tier-0 Baseline | Deep Alternative (Ablation Candidate) | Enforcement Code Location |
|---|---|---|---|
| Architecture Config | `V11-Tier0-Default`: `4L`, `n_heads=4`, `d_model=256`, `d_ff=704`, `vocab_size=2048`, `max_seq_len=256` (`3,737,856` params) | `V11-Tier0-Deep6L`: `6L`, `n_heads=4`, `d_model=256`, `d_ff=576`, `vocab_size=2048`, `max_seq_len=256` (`4,754,688` params) | `ZyrquenConfig.validate_parameter_budget(5_000_000)` |
| Precision / Device | `float32`, CPU (`<= 2` PyTorch threads) | Same | `groups.py:809`, `orchestrator.py:269` |
| Optimizer | `AdamW(lr=3e-4, betas=(0.9, 0.95), weight_decay=0.1)` (0.0 on 1D/norms) | Same | `apps/core/native/train.py` |
| LR Schedule | Linear warmup `100` steps -> Cosine decay to `min_lr=3e-5` across `lr_total_steps=10_000` | Pending `OD-TP-01` resolution | `apps/core/native/train.py::lr_at` |
| Micro-Batch / Accum | `batch_size=4`, `grad_accum_steps=1` (eff. batch `4`) | Candidate: `batch_size=4`, `grad_accum_steps=2` (eff. `8`, after throughput benchmark) | `TrainConfig.tier0_v11()` |
| Segment Budgeting | `segment_max_steps = 500` per Tier-2 approval token (`20` segments = `10,000` total steps) | Same | `TrainConfig.tier0_v11()`, `resource_guard.py` |
| Grad Clip | `1.0` | Same | `TrainConfig.tier0_v11()` |
| Eval & Checkpoint Cadence | `eval_interval=250`, `checkpoint_interval=250`, `log_interval=10`, `keep_last=3` | Same (`eval_batches` needs increase from `20` to full val pass if feasible) | `TrainConfig.tier0_v11()` |
| Seed Policy | Deterministic root `seed=1337` + segment/step sub-seeds (`seed + step`) | Same | `TrainConfig.tier0_v11()` |

---

## 3. Staged 10,000-Step Curriculum (Post-Readiness Execution Blueprint)

> **CRITICAL:** None of Stages 1–6 may start until all blockers in `P11_BLOCKERS_AND_REMEDIATION.md` are resolved AND explicit human Tier-2 approval is granted.

| Stage | Target Capability Focus | Total Steps | Segment Range (`500`/seg) | Target Replay Mix | Gate Between Stages |
|---|---|---:|---|---|---|
| **Stage 0** | Infrastructure Smoke + Untrained Eval Baseline | `0` (eval) + `20` (smoke) | Pre-curriculum | Pipeline check only (NOT registered as capability) | Pipeline smoke PASS (`parameter_changed=True`, finite loss, schema PASS) |
| **Stage 1** | Atomic Knowledge Grounding & Unknown Abstention | `1,500` | Seg 1–3 (`0 -> 1,500`) | 100% Stage-1 data | Val loss down vs random; `stage_1` copy & abstention sanity |
| **Stage 2** | Relational Generalization & 2–3 Hop Inference | `2,000` | Seg 4–7 (`1,500 -> 3,500`) | 75% Stage-2 / 25% Stage-1 replay | Multi-hop val check + zero Stage-1 forgetting |
| **Stage 3** | Multi-Step Planning & Dependency Chains | `2,000` | Seg 8–11 (`3,500 -> 5,500`) | 70% Stage-3 / 30% S1–S2 replay | Action sequence format + dependency validity |
| **Stage 4** | Abstract Reasoning (Symmetry, Inversion, Equivalence) | `1,500` | Seg 12–14 (`5,500 -> 7,000`) | 70% Stage-4 / 30% S1–S3 replay | Inverse query & equivalence consistency |
| **Stage 5** | Self-Verification & Contradiction / Failure Rejection | `1,500` | Seg 15–17 (`7,000 -> 8,500`) | 70% Stage-5 / 30% S1–S4 replay | Near-miss rejection precision vs false positives |
| **Stage 6** | Joint Integration & Generalization Stabilization | `1,500` | Seg 18–20 (`8,500 -> 10,000`) | Balanced multi-capability + OOD-style structural mix | Full 6-capability `zyrquen.v11.evaluation_report.v1` Gate |

---

## 4. Checkpoint Provenance, Continuation & Failure Stops

1. **Lineage Enforcement (`ModelRegistry`):**
   - Segment 1 (`0 -> 500`): randomly initialized `ZyrquenModel` -> registered as `ZYRQUEN-Native-11.0.0` (`parent: null` or explicit V11 lineage root).
   - Segment `k` (`500*(k-1) -> 500*k`): MUST verify `parent_checkpoint_sha256`, `tokenizer_sha256`, `dataset_content_sha256`, `model_config`, and `global_step == expected_start_step` before executing step `500*(k-1) + 1`, then register immutably as `ZYRQUEN-Native-11.0.<k-1>` (`parent = 11.0.<k-2>`).
   - Never overwrite existing `artifacts/ZYRQUEN-Native-11.*` or frozen `v7`/`v8`/`v9`/`v10` records.
2. **Hard Abort / Failure Criteria (`STOP IMMEDIATELY`):**
   - Any `NaN` / `Inf` loss or gradient norm (`math.isfinite` check trips).
   - Loss spike `> 3.0x` rolling baseline persisting `>= 50` steps or plateau collapse (`< 0.5%` delta across 1,000 steps with trivial EOS collapse).
   - `RamMonitor` crossing `3.5 GiB` hard ceiling or disk free space dropping below `2.0 GiB` reserve.
   - Zero weight movement (`parameter_changed == False`).
   - Leakage audit or SHA-256 mismatch detected at segment start.

---

## 5. Proposed Code Changes (For Human Review — NOT Applied)

Because execution is currently in **Readiness Audit + Preparation** mode only, the following required code changes are specified for separate human review:
1. **`/apps/core/native/train.py` & `/apps/core/workflow/handlers/groups.py`:** Add `stage_id` + `stage_replay_weights` curriculum filtering; bind ephemeral slots dynamically inside each training batch (`(seed, step, idx)`); assert `dataset_content_sha256` & `tokenizer_sha256` before resuming checkpoints; convert RNG state tuples to JSON/tensor-safe lists if `weights_only=True` rejects them.
2. **`/apps/core/training/orchestrator.py` & `/apps/api/routers/training.py` + `training_schemas.py`:** Align defaults with `TrainConfig.tier0_v11()`, pass `RamMonitor`, support `parent_version`/`resume_checkpoint`, and implement cooperative `POST /v1/training/runs/{id}/cancel`.
3. **`/apps/core/native/dataset_status.py` (`inspect_training_preflight_readiness`):** Read V11 target config (`block_size=256, max_steps=500`) rather than hardcoded `128 / 100`.

### Open Decisions Requiring Human Freeze Prior to Training
- **`OD-TP-01`:** Continuous `lr_total_steps=10_000` across segments vs per-stage warm-restart schedule.
- **`OD-TP-02`:** Whether `batch_size=4, grad_accum_steps=1` (eff. `4`) or `grad_accum_steps=2` (eff. `8`) gives better Stage-2/3 convergence within CPU time budgets.
- **`OD-MS-01` / `OD-MS-02`:** Select `V11-Tier0-Default (3.74M)` vs `V11-Tier0-Deep6L (4.75M)` and `dropout` (`0.0` vs `0.05` vs `0.1`).
