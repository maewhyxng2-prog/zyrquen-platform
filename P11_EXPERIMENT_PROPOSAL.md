# ZYRQUEN Ω∞ — P11 Controlled Training Experiment Proposal (`P11_EXPERIMENT_PROPOSAL.md`)

- **Proposal ID:** `P11-EXP-01-PILOT`
- **Status:** `EXPERIMENT_PROPOSAL_PENDING_APPROVAL`
- **Execution Policy:** **DO NOT EXECUTE.** Submitted strictly for human review and explicit Tier-2 training authorization after Readiness Blockers (`P11_BLOCKERS_AND_REMEDIATION.md`) are cleared.
- **Native-Only Compliance:**
  1. Uses **ONLY** a freshly constructed native `ZyrquenModel` (`zyrquen-decoder`) with **randomly initialized weights** (`Normal(0, 0.02)`, residual projections `0.02 / sqrt(2 * n_layers)`, `RMSNorm = 1.0`).
  2. Imports **ZERO** external pretrained weights, HuggingFace checkpoints, weight merging, transfer learning, or distillation.
  3. Uses **ZERO** external AI APIs (OpenAI, Anthropic, Gemini, Llama, Qwen, etc.) for training, data synthesis, reasoning, or evaluation.

---

## 1. Experiment Objective & Strict Scope Separation

**Objective:** Validate the end-to-end ZYRQUEN P11 native training, checkpointing, dynamic slot-binding, and 4-split evaluation mechanics on a single controlled, small-scale Tier-0 CPU segment (`500` steps) BEFORE committing to a full 20-segment (`10,000`-step) curriculum.

### Mandatory Separation: Pipeline Validation vs. Model Capability Results
This proposal enforces two non-interchangeable reporting tracks in the final experiment report:
1. **Track A — Pipeline Validation Results (Infrastructure & Math Mechanics ONLY):**
   - Measures whether PyTorch CPU training runs cleanly, `parameter_changed == True`, training/validation cross-entropy loss is finite and decreases from random baseline (`ln(2048) ≈ 7.6246`), gradients remain finite under `grad_clip=1.0`, `CheckpointManager` reloads with `weights_only=True` and matching SHA-256, `Peak RSS < 3.0 GiB`, and `eval_nagi_v11.py` runs end-to-end greedy decoding without truncation or fake metrics.
   - **Rule:** Passing Track A **NEVER** certifies intelligence or NGI capability!
2. **Track B — Actual Model Capability Results (`validation`, `unseen`, `ood` Greedy + Teacher-Forced Inference):**
   - Measures real native generalization across all 6 P11 capabilities (`knowledge_integration`, `multi_step_planning`, `relational_generalization`, `ood_transfer`, `abstract_reasoning`, `self_verification`) against unseen entities (`UN_E*`) and OOD depths (`OO_E*`, `Depth 4–6`).
   - **Rule:** Expected to remain `FAIL` / pre-competent after only `500` pilot steps (`Stage 1` focus); MUST be reported honestly as raw observed percentages with zero exaggeration, and isolated under `artifacts/experiments/P11-EXP-01-PILOT/` — **NEVER** deployed or promoted to production.

---

## 2. Small-Scale Controlled Experiment Specification

### A. Model Configuration (`V11-Tier0-Default`, Random Init Only)
- **Class:** `ZyrquenConfig` -> `ZyrquenModel` (`apps/core/native/model.py`, `model_type="zyrquen-decoder"`)
- **Hyperparameters:**
  - `vocab_size = 2048` (native `zyrquen.tokenizer.v2` trained strictly on pilot `train.jsonl` slot-masked text)
  - `max_seq_len = 256`
  - `n_layers = 4`, `n_heads = 4` (`head_dim = 64`), `d_model = 256`, `d_ff = 704`
  - `dropout = 0.0`, `rope_theta = 10000.0`, `norm_eps = 1e-5`, `tie_embeddings = True`
- **Exact Parameter Count:** `3,737,856` parameters (`fits <= 5,000,000` `MAX_V10_PARAMETERS` budget)
- **Initialization:** Fresh random init with `seed = 1337` (`parent_checkpoint = None`)

### B. Pilot Dataset Specification (`nagi_v11_pilot`, 4-Split Algorithmic Synthetic)
- **Origin & Provenance:** `100%` in-house deterministic Python symbolic/graph/plan solvers (`tools/gen_nagi_v11.py`, `origin="native-deterministic-solver-v11"`, `license="synthetic-native-zyrquen-v11"`). Zero external LLM outputs.
- **Pilot Split Sizes (`1,560` total rows):**
  - `train.jsonl`: `1,200` rows (`200` per capability; `stage_1_grounding` prioritized + balanced anchor slice; entities `TR_E*`, Template Family `A`, Depth `1–3`)
  - `validation.jsonl`: `120` rows (`20` per capability; disjoint `VL_E*`, Template Family `A`)
  - `unseen.jsonl`: `120` rows (`20` per capability; disjoint `UN_E*`, Template Family `B`)
  - `ood.jsonl`: `120` rows (`20` per capability; disjoint `OO_E*`, Template Family `C`, Depth `4–6` / Plans `5–6`)
- **Pre-Run Leakage Gates (`MUST PASS 100%`):** `EL-01..05` (entity + tokenizer vocab purity), `TL-01` (template skeleton disjointness), `SL-01` (structural depth disjointness), `DL-01` (dedup), and `100%` rows `<= 256` BPE tokens (no silent truncation).

### C. Optimizer, Schedule, Batching & Steps
- **Device & Precision:** CPU-only `float32`, `max_cpu_threads = 2`
- **Optimizer:** `AdamW(lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.1 on dim>=2 / 0.0 on dim<2)`
- **Loss:** Token-level Cross-Entropy with `ignore_index=-100` (prompt tokens masked `-100`; target tokens + `<eos>` supervised)
- **Scheduler:** Linear warmup `100` steps (`0 -> 3e-4`), cosine decay toward `min_lr=3e-5` (pilot `lr_total_steps = 500` OR continuous `10,000` per `OD-TP-01` sign-off — must be frozen explicitly in run config)
- **Batching:** `batch_size = 4`, `grad_accum_steps = 1`, `block_size = 256` (`1,024` tokens/step; dynamic per-step deterministic `<slot_0>..<slot_31>` permutation enabled)
- **Training Steps:** `max_steps = 500` (`512,000` token-slots total; `grad_clip = 1.0`; `log_interval = 10`; `eval_interval = 250`; `checkpoint_interval = 250`; `keep_last = 2`)

### D. Evaluation Metrics (Untrained Step `0` vs Step `500`)
Evaluated using `tools/eval_nagi_v11.py` (`temperature=0.0`, greedy, `max_new_tokens=64`) on all `360` held-out rows (`120 val + 120 unseen + 120 ood`) + `120` diagnostic `train` slice:
- **Track A Metrics:** Initial/final `train_loss`, `val_loss`, gradient norms, `parameter_changed`, `Peak RSS (MiB)`, `sec/step`, `weights_only=True` checkpoint reload integrity, `eos_hit_rate`.
- **Track B Metrics:** `per_split_exact_match` (`train_diag`, `val`, `unseen`, `ood`), `teacher_forced_exact`, `exposure_gap`, `unseen_entity_copy_acc`, `abstention_precision/recall`, `plan_step_validity_rate`, `hop2_3_acc` vs `hop4_6_acc`, `ar_inverse_query_acc`, `near_miss_rejection_rate`, `overfit_gap`, and `ood_transfer_gap`.

---

## 3. Compute, Memory, Storage & Time Estimate

*(Host verified: `4` vCPU, `12.0 GiB` RAM / `~9.83 GiB` avail, `0` swap, `281.45 GiB` disk free, no GPU, `torch` currently absent — runtime telemetry marked `NOT VERIFIED`.)*

| Resource Dimension | Exact Known Static / Budget Value | Estimated Runtime Total (Explicit Assumptions) | Verification Status |
|---|---|---|---|
| Model + AdamW Static State | `14.26 MiB` FP32 weights + `57.04 MiB` AdamW FP32 | Same | `PASS` (Math Exact) |
| Runtime Peak RAM (`Peak RSS`) | Budget Cap: `3.0 GiB` soft / `3.5 GiB` hard (`RamMonitor`) | `~0.50 – 0.90 GiB` (assumes `0.35 GiB` PyTorch base + activations `B=4, L=256`) | `NOT VERIFIED` |
| Disk Storage (`P11-EXP-01-PILOT`) | Budget Cap: `<= 1.0 GiB` new disk, `>= 2.0 GiB` free | `~125 MiB` total (`~2 MiB` data + `2 x 58 MiB` ckpts + logs/eval) | `NOT VERIFIED` |
| Training Execution Time (`500` steps) | Segment Cap: `1200s` soft / `3600s` hard | `~3.2 – 13.5 min` (assumes `0.35 – 1.50 s/step` on `2` CPU threads + `2 x 20`-batch val) | `NOT VERIFIED` |
| Post-Run Evaluation Time (`480` rows, greedy `64` tok) | Uncached `generate()` (`no KV-cache`) | `~2.5 – 8.0 min` (assumes `0.3 – 1.0 s/example`) | `NOT VERIFIED` |
| Cloud / GPU Monetary Spend | `$0.00` | `$0.00` (Local CPU host only) | `PASS` |

---

## 4. Checkpoint Provenance, Isolation & Reproducibility Requirements

1. **Isolation:** All artifacts stored strictly under an isolated sandbox path (`artifacts/experiments/P11-EXP-01-PILOT/`), registered ONLY as experimental/sandbox snapshot (`lifecycle_status = "registered"` or `"quarantined"` if capability gate fails). **Zero overwrite** of production registry, `v7`/`v8`/`v9`, or `V10 CLOSED_FAIL`.
2. **Cryptographic Lineage:** Every checkpoint (`ckpt_00000250.pt`, `ckpt_00000500.pt`) MUST embed and verify SHA-256 digests of:
   - `dataset_version = "nagi_v11_pilot-1.0.0"` + `dataset_content_sha256`
   - `tokenizer_sha256` (`tokenizer.fingerprint()`) + `tokenizer_file_sha256`
   - `model_config` (`ZyrquenConfig.to_dict()`), `train_config`, `experiment_id = "P11-EXP-01-PILOT"`, `seed = 1337`, `git_commit` (if available)
3. **Deterministic Reproducibility:** Exact CLI command, Python/PyTorch versions, `torch.manual_seed(1337)`, `random.Random(1337)`, JSONL step metrics, and `weights_only=True` verification log MUST be archived alongside the run.

---

## 5. Clear Stop Conditions & Failure Criteria

Training or experiment execution MUST **ABORT IMMEDIATELY** and mark `EXPERIMENT_STATUS = FAILED / STOPPED` if ANY of the following triggers:
1. **Numerical Instability:** Any `NaN` or `Inf` loss or gradient norm (`math.isfinite` fails).
2. **Loss Divergence:** Rolling 50-step training loss exceeds `1.5x` initial random loss (`> 11.4` for `V=2048`) or `val_loss` worsens `> 20%` across consecutive evals without recovery.
3. **Zero Learning Signal:** `parameter_changed == False` at step `250`, or `train_loss` drops `< 1%` across all `500` steps.
4. **Mode / EOS Collapse:** `eos_hit_rate < 0.20` at step `500` or model emits single repeated token across `> 80%` of prompts.
5. **Resource Guard Breach:** `Peak RSS >= 3.5 GiB`, step timeout (`> 1200s` soft / `3600s` hard), or free disk `< 2.0 GiB`.
6. **Integrity / Policy Violation:** Any SHA-256 mismatch, leakage rule (`EL-01..05`/`TL-01`/`SL-01`) breach, unauthorized external import, or silent truncation.

**Required Pre-Execution Gate:** Cannot start until all Blockers `B-01..B-12` (`P11_BLOCKERS_AND_REMEDIATION.md`) are remediated, untrained baseline evaluation (`Step 0`) confirms `< 5%` accuracy, and explicit human Tier-2 approval is granted.

---

**Final Proposal Status:** `"EXPERIMENT_PROPOSAL_PENDING_APPROVAL"`
