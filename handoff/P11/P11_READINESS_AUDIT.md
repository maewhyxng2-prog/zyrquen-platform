# ZYRQUEN Ω∞ — P11 Training Readiness Audit (`P11_READINESS_AUDIT.md`)

- **Mission:** Native Training Phase P11 Readiness Audit & Preparation
- **Mode:** `READINESS AUDIT + PREPARATION` (`EXECUTION AUTHORITY: NOT GRANTED` | `TRAINING AUTHORIZATION: NOT GRANTED`)
- **Audit Scope:** Codebase static & runtime-contract inspection across Native Model Architecture, Dataset Pipeline, Training Pipeline, Evaluation Framework, Compute Readiness, Security/Governance, and Unit Test Suites.
- **Native-Only Policy Gate:** `GATE = PASS` (with unused-artifact hygiene caveats `NAT-01` and `NAT-02` requiring quarantine/removal)
- **Overall P11 Readiness Verdict:** `P11_READINESS = BLOCKED`

> **Scope Disambiguation:** `/phases/phase11.py` and `/docs/PHASE_11_SPEC.md` implement an unrelated Workspace Intelligence layer and are NOT part of ZYRQUEN Native General Intelligence (NGI) Model Phase 11 (`V11` / `P11`). This audit covers the `ZYRQUEN-Native-11.x.x` NGI pipeline exclusively.

---

## Executive Verdict

`P11_READINESS = BLOCKED`

While substantial Stage-1 native scaffolding (`V11-Tier0` configs, `ZyrquenModel`, `zyrquen.tokenizer.v2` 32-slot BPE tokenizer, 4-split `V11_SPLITS` dataset verifier, `TrainConfig.tier0_v11()`, SHA-256 `ModelRegistry`, HMAC Tier-2 approval gate, and `zyrquen.v11.evaluation_report.v1` workflow handler) exists in code and passes pure-stdlib contract tests (`101 PASS, 2 SKIP`), P11 cannot legally or technically train today because:
1. `torch`, `fastapi`, `pytest`, and `pip` are not installed in the container (`P11-ENV-01`), leaving all forward/backward passes, AdamW steps, Peak RSS, step throughput, and PyTorch `weights_only=True` checkpoint reloads `NOT VERIFIED`.
2. Zero V11 data generation (`tools/gen_nagi_v11.py`), leakage audit (`tools/audit_leakage_v11.py`), V11 datasets (`data/nagi_v11/*`), trained V11 tokenizers, V11 training runners, or V11 evaluation scripts (`tools/eval_nagi_v11.py`) exist on disk.
3. Critical V11 code wiring is incomplete or inconsistent: `train_sft()` ignores `stage_tags` curriculum filtering, pre-binds slots statically once instead of per epoch/step, `TrainingOrchestrator.prepare()` rejects `"splits"`-only manifests and checks only 2 splits (`train`/`validation`), `/v1/evaluation/runs` always runs with `run_inference=False` (HTTP 503) and drops DB persistence, and V10 governance closure cannot be locally verified (`build_v10_closure_audit()` reports `BLOCKED`, `v11_gate.status = "LOCKED"`).

---

## 0. Mandatory Native-Only Policy Audit

### Finding `NAT-00` — Core Runtime & Model Native-Only Compliance
- **File / Config Ref:** `/apps/core/native/model.py` (`ZyrquenModel`), `/apps/core/model_loader.py:25-29,283-453`, `/apps/core/maintainer/auditor.py:33-45,363`, `/apps/core/maintainer/policy.py:78`
- **Actual Evidence:** Targeted grep across `apps/core`, `apps/api`, `tools`, and `phases` found zero imports of `openai`, `anthropic`, `google.generativeai`, `google.genai`, `groq`, `together`, `mistralai`, or `litellm`/`vllm`/`ollama`. `maintainer.audit.v1` (via `tests/test_maintainer_bot.py`) scanned `498` files (`294` Python files, `0` syntax errors) and reported `native_only_compliance: PASS`. `NativeModelLoader` rejects directories without `artifact_manifest.json` or `registry.json` (`model_loader.py:283-287`) and enforces `weights_only=True` (`model_loader.py:25-29`), `tokenizer.fingerprint()`, `dataset_version`, and `ZyrquenConfig`.
- **Current Status:** `PASS`
- **Required Remediation:** Preserve AST/regex maintainer scans in CI (`/.github/workflows/maintainer-audit.yml`).
- **Verification Method:** Re-run `grep` across `apps/` + `python3 -m unittest tests/test_maintainer_bot.py`.

### Finding `NAT-01` — Unused Pretrained Model Downloader Present in Repo
- **File / Config Ref:** `/apps/core/download_model.py:1-233` (`DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B"`, `huggingface_hub.snapshot_download`)
- **Actual Evidence:** `download_model.py` explicitly imports `huggingface_hub` and defaults to downloading `Qwen/Qwen2.5-0.5B` (`source: "huggingface-open-source-base-model"`). It is not imported by `apps/api`, `apps/core/native`, or `apps/core/workflow`.
- **Current Status:** `FAIL` (Hygiene / Policy Risk — unused file violates P11 zero-external-weights boundary if ever invoked)
- **Required Remediation:** Quarantine or remove `/apps/core/download_model.py` (requires human approval for deletion/cleanup) and add `huggingface_hub` + `transformers` import prohibitions to `apps/core/maintainer/policy.py`.
- **Verification Method:** Verify zero references (`grep -rn "download_model\|huggingface_hub" apps/ tools/`) after human-approved removal.

### Finding `NAT-02` — Legacy Hardcoded Mock Evaluation Module Present
- **File / Config Ref:** `/apps/core/evaluation/engine.py:1-47` (`EvaluationEngine` returning hardcoded `perplexity=15.5`, `token_accuracy=0.85`)
- **Actual Evidence:** While `/apps/api/routers/evaluation.py` imports `apps.core.native.evaluation.EvaluationEngine`, the legacy file `/apps/core/evaluation/engine.py` remains importable and returns fabricated static metrics (`15.5` / `0.85`).
- **Current Status:** `FAIL` (Anti-Fake Policy Risk under Rule #2: No fabricated metrics)
- **Required Remediation:** Remove or disable `/apps/core/evaluation/engine.py` with human approval so no caller can accidentally invoke mock metrics.
- **Verification Method:** Verify `apps/core/evaluation/engine.py` removal/block and re-run `tests/test_evaluation_gate_safety.py`.

---

## Domain A: Native Architecture Audit

### Finding `A-01` — `ZyrquenModel` Pure Native Architecture & Random Weight Initialization
- **File / Config Ref:** `/apps/core/native/model.py:1-142`, `/apps/core/native/config.py:1-66`
- **Actual Evidence:** `ZyrquenModel` (`model_type="zyrquen-decoder"`) implements a standalone PyTorch decoder-only Transformer using Pre-RMSNorm (`RMSNorm`, `norm_eps=1e-5`), Rotary Position Embeddings (`_apply_rope`, non-persistent `rope_cos`/`rope_sin` buffers), causal Scaled Dot-Product Attention (`F.scaled_dot_product_attention(..., is_causal=True)`), SwiGLU FFN (`gate`, `up`, `down`), optional tied LM head (`tie_embeddings=True`), and cross-entropy loss with `ignore_index=-100`. `_init_weights()` initializes all `nn.Linear` and `nn.Embedding` weights strictly from `Normal(0.0, 0.02)` (`0.02 / sqrt(2 * n_layers)` on `attn.proj.weight` and `ffn.down.weight`) and `RMSNorm` scales to `1.0`. No pretrained weight loading exists in `model.py`.
- **Current Status:** `PASS` (Static architectural contract; runtime instantiation `NOT VERIFIED` until `torch` is installed)
- **Required Remediation:** Add conditional/smoke PyTorch verification test executing `ZyrquenModel(cfg)`, checking `num_parameters() == cfg.estimated_num_parameters`, and confirming finite forward/backward gradients.
- **Verification Method:** Execute `pytest apps/core/native/test_train_torch.py` in PyTorch CPU environment.

### Finding `A-02` — Model Parameter Counts & `5,000,000` Parameter Ceiling vs. V11 Tiers
- **File / Config Ref:** `/apps/core/native/config.py:4,43-60`, `/apps/core/workflow/handlers/groups.py:705,745,749`, `/apps/core/workflow/resource_guard.py:22`, `/apps/core/training/orchestrator.py:38`, `/docs/v11/V11_MODEL_SPECIFICATION.md:16-24`
- **Actual Evidence:** Live probe against `ZyrquenConfig.estimated_num_parameters` produced:
  - `V11-Tier0-SmokeMini` (`V=640, L=256, 2L, d=128, ff=352`): `483,968` params (`1.85 MiB` FP32 weights, `7.38 MiB` AdamW static) — `fits_5M=True`
  - `V11-Tier0-Default` (`V=2048, L=256, 4L, d=256, ff=704`): `3,737,856` params (`14.26 MiB` FP32, `57.04 MiB` AdamW static) — `fits_5M=True`
  - `V11-Tier0-Vocab4096` (`V=4096, L=256, 4L, d=256, ff=704`): `4,262,144` params (`16.26 MiB` FP32, `65.04 MiB` AdamW static) — `fits_5M=True`
  - `V11-Tier0-Deep6L` (`V=2048, L=256, 6L, d=256, ff=576`): `4,754,688` params (`18.14 MiB` FP32, `72.55 MiB` AdamW static) — `fits_5M=True`
  - `V11-Tier0-6L704-OVER` (`V=2048, L=256, 6L, d=256, ff=704`): `5,344,512` params — `fits_5M=False` (exceeds `MAX_V10_PARAMETERS = 5_000_000`)
  - `V11-Tier1-Candidate` (`V=4096, L=512, 6L, d=384, ff=1024`): `12,194,688` params (`46.52 MiB` FP32, `186.08 MiB` AdamW) — `fits_5M=False`
  - `V11-Tier2-Candidate` (`V=4096, L=512, 8L, d=512, ff=1408`): `27,795,968` params (`106.03 MiB` FP32, `424.13 MiB` AdamW) — `fits_5M=False`
- **Current Status:** `PASS` for `Tier0` configs (`<= 5M`); `BLOCKED` for `Tier1`/`Tier2` (hardcoded `MAX_V10_PARAMETERS = 5_000_000` enforced in 4 modules).
- **Required Remediation:** Keep initial P11 experiments strictly inside `V11-Tier0` (`3.74M` or `4.75M` Deep6L). Before any future `Tier1`/`Tier2` run, obtain explicit human Tier-2 approval, benchmark real Peak RSS + `sec/step`, and parameterize per-tier limits rather than hardcoding `MAX_V10_PARAMETERS` for V11.
- **Verification Method:** `ZyrquenConfig.validate_parameter_budget()` + `tests/test_v10a_contracts.py` + `tests/test_v11_stage1_readiness.py`.

### Finding `A-03` — Checkpoint Provenance, Loading Restrictions & `weights_only=True` Compatibility
- **File / Config Ref:** `/apps/core/model_loader.py:25-29,375-468`, `/apps/core/native/registry.py:661-737,812-861`, `/apps/core/training_infrastructure/recovery/checkpoint_recovery.py:16-39`, `/apps/core/native/train.py:293-331,458-590`
- **Actual Evidence:** Both `ModelRegistry` and `NativeModelLoader` default to `torch.load(..., map_location="cpu", weights_only=True)` (`allow_unsafe_pickle=False` in `CheckpointManager`), enforce non-symlinked paths, check SHA-256 of checkpoint/tokenizer/dataset manifest, and verify `model_config`, `tokenizer_sha256`, `dataset_version`, and `vocab_size`. However, `train.py` saves `"rng": rng.getstate()` (nested Python tuple of `int`s) and `"batch_rng": batch_rng.getstate()` inside checkpoints (`train.py:303,560`). On modern PyTorch `weights_only=True`, custom or deeply nested non-tensor state objects have NOT been tested in this container because `torch` is absent.
- **Current Status:** `NOT VERIFIED` (Runtime checkpoint save/reload with `weights_only=True` unverified)
- **Required Remediation:** Test `CheckpointManager.save()` + `load_latest(allow_unsafe_pickle=False)` with real `torch` on PyTorch `>=2.5` CPU; if `weights_only=True` rejects `random.Random.getstate()` tuples, serialize RNG state as plain `list[int]` (`list(rng_state[1])`) instead of raw Python tuples.
- **Verification Method:** Run `python3 -m unittest tests/native/test_checkpoint_resume.py` and `pytest apps/core/native/test_train_torch.py` with `torch` installed.

### Finding `A-04` — Missing Runtime Architectural Controls (CPU-Only Hardcoding, No KV-Cache, No Device Selection)
- **File / Config Ref:** `/apps/core/native/model.py:123-141`, `/apps/core/workflow/handlers/groups.py:809`, `/apps/core/training/orchestrator.py:269,305`
- **Actual Evidence:**
  1. `ZyrquenModel.generate()` (`model.py:123-141`) recomputes the entire `(1, <= max_seq_len)` causal forward pass from scratch on every generated token (`O(T^2)` decode cost per sample) with no KV-cache. On `max_seq_len=256`, `max_new_tokens=64`, multi-split evaluation will perform `~64` full passes per prompt.
  2. Training callers force CPU-only execution (`groups.py:809`, `orchestrator.py:269,305`); no `device` flag, gradient checkpointing, or `bfloat16` mixed precision exists.
  3. Unconditional `import torch` at `apps/core/native/model.py:4-6` causes `ImportError` on module import when PyTorch is absent.
- **Current Status:** `NOT VERIFIED` (CPU inference latency & decode throughput unmeasured; CPU-only acceptable for Tier-0 readiness, GPU scaling `BLOCKED`)
- **Required Remediation:** Benchmark CPU `generate()` latency for `64` tokens at `Tier0`; add KV-cache only in a separate, explicitly authorized architecture change if eval runtime exceeds timeout budget. Keep CPU `float32` for P11 Tier-0 baseline.
- **Verification Method:** Timed CPU inference benchmark under `eval` conditions once `torch` is installed.

---

## Domain B: Dataset Pipeline Audit

### Finding `B-01` — Zero V11 Datasets, Generators, or Trained Tokenizers Exist on Disk
- **File / Config Ref:** `/tools/` (contains only `v8`/`v9`/`v10` scripts; zero `*v11*` scripts), `/data/` (directory absent), `/apps/core/native/dataset_status.py:66-152`
- **Actual Evidence:** Workspace listing confirmed `data/`, `checkpoints/`, and `eval/` do not exist. Live probe `get_datasets_pipeline_status()` returned `{"configured": False, "status": "not_configured"}`. No `tools/gen_nagi_v11.py` or `tools/audit_leakage_v11.py` exists.
- **Current Status:** `BLOCKED`
- **Required Remediation:** Implement `tools/gen_nagi_v11.py` and `tools/audit_leakage_v11.py` per `/docs/v11/V11_DATASET_SPECIFICATION.md`, generate `data/nagi_v11/{train,validation,unseen,ood}.jsonl` + `manifest.json`, and train `zyrquen.tokenizer.v2` on train-only corpus.
- **Verification Method:** File presence + `verify_dataset_manifest()` + `inspect_v11_training_dataset_readiness()["ready"] is True`.

### Finding `B-02` — 4-Split Manifest Schema, SHA-256 Verification & `orchestrator.prepare()` Mismatch
- **File / Config Ref:** `/apps/core/native/dataset.py:18-20,256-367`, `/apps/core/training/orchestrator.py:137-153`, `/docs/v11/V11_DATASET_SPECIFICATION.md:214`
- **Actual Evidence:** `dataset.py` defines `V11_SPLITS = ("train", "validation", "unseen", "ood")`, `resolve_dataset_splits()`, and `verify_dataset_manifest()` supporting either `"files"` or `"splits"` keys, SHA-256 checks, symlink rejection, and path traversal guards. However, `TrainingOrchestrator.prepare()` (`orchestrator.py:137-153`) reads ONLY `manifest["files"]["train.jsonl"]["documents"]` and `manifest["files"]["validation.jsonl"]["documents"]` — ignoring `"splits"` and ignoring `unseen`/`ood` splits! Meanwhile, `V11_DATASET_SPECIFICATION.md:214` omits `"files"` in its schema example.
- **Current Status:** `FAIL` (Contract inconsistency between `TrainingOrchestrator` and V11 manifest spec)
- **Required Remediation:** Canonicalize V11 `manifest.json` to emit `"files"` (required by `orchestrator.py` and `dataset.py`) AND update `TrainingOrchestrator.prepare()` (via human-reviewed patch) to use `verify_dataset_manifest()` + `detect_dataset_format()` and enforce `DataAdapter.detect_leakage()` when V11 splits are present.
- **Verification Method:** Unit test `TrainingOrchestrator.prepare()` against canonical V11 4-split SFT manifest + `tests/test_v11_stage1_readiness.py`.

### Finding `B-03` — `prepare_dataset()` Raw-Text-Only Limitation & Incomplete Leakage/Dedup Checks
- **File / Config Ref:** `/apps/core/native/dataset.py:149-237`, `/apps/core/native/dataset_v11.py:15-191`, `/apps/core/native/sft.py:24-27`, `/apps/core/workflow/handlers/groups.py:250-315`
- **Actual Evidence:**
  1. `prepare_dataset()` (`dataset.py:172-237`) builds only 3 raw-text splits (`"text"`) and does NOT handle V11 4-split SFT (`input`/`target`/`capability`/`stage_tag`/`split`).
  2. `DataAdapter.detect_leakage()` (`dataset_v11.py`) and `handle_data_verify_and_audit()` (`groups.py:250-315`) verify declared split consistency, exact normalized text overlap, and `_V11_ENTITY_RE` entity overlap (`UN_E*`, `OO_E*`, `node_un_*`, etc.).
  3. **Missing checks (`NOT IMPLEMENTED`):** `TL-01` template/phrasing skeleton overlap, `SL-01` structural/hop-depth disjointness (`<=3` train vs `4-6` OOD), `DL-01` fuzzy/n-gram deduplication across train rows, and BPE sequence-length overflow verification (`len <= 256`).
- **Current Status:** `FAIL` (Partial implementation — critical V11 anti-leakage checks missing)
- **Required Remediation:** Add `TL-01`, `SL-01`, `DL-01`, and BPE token-length ceiling checks (`<= 250` typical, `<= 256` hard cap) into `tools/audit_leakage_v11.py` and `apps/core/native/dataset_v11.py`.
- **Verification Method:** Positive & negative adversarial leakage tests in `tests/test_v11_stage1_readiness.py` verifying rejection of template/structural/entity leaks and >256-token examples.

### Finding `B-04` — Slot-Safe Tokenizer (`zyrquen.tokenizer.v2`) & License Provenance
- **File / Config Ref:** `/apps/core/native/tokenizer.py:1-305`, `/apps/core/native/sft.py:24-230`, `/apps/core/native/dataset.py:5-6`
- **Actual Evidence:** `ZyrquenTokenizer` preserves `<pad>`, `<bos>`, `<eos>`, `<unk>` (`0..3`) and 32 atomic ephemeral slots `<slot_0>..<slot_31>` (`4..35`, `BASE_VOCAB=292`), normalizes NFC, and uses lossless byte-level BPE. `train_slot_safe_tokenizer()` checks `EL-05` so raw held-out entity identifiers (`UN_E*`, `OO_E*`) are excluded from tokenizer vocabulary merges. Dataset licenses (`dataset.py:5-6`) are metadata strings (`license`) without automated SPDX validation.
- **Current Status:** `PASS` for tokenizer code (`NOT VERIFIED` on actual V11 corpus due to missing data); `NOT VERIFIED` for corpus license metadata until dataset is generated.
- **Required Remediation:** Require explicit `"license": "Apache-2.0"` (or `synthetic-native-zyrquen-v11`) and `"origin": "native-synthetic-solver-v11"` fields in every `manifest.json`, verified in `handle_data_verify_and_audit`.
- **Verification Method:** Assert `EL-05` tokenizer purity check (`unseen` + `ood` entity IDs not merged as whole tokens) and manifest provenance check during `tools/gen_nagi_v11.py`.

### Finding `B-05` — Missing Dataset Ingestion, Validation Report & Token-Stats APIs
- **File / Config Ref:** `/apps/api/routers/datasets.py:1-48`, `/apps/core/native/dataset_status.py:1-452`
- **Actual Evidence:** Only `GET /v1/datasets/status` and `GET /v1/datasets/{dataset_version}/status` exist (`datasets.py:17-48`). Live call confirmed `configured=False`. There are NO endpoints to trigger dataset audit, inspect persisted `leakage_audit` reports (`TL-01`/`SL-01`/`EL-01..05`), or query per-split BPE token length percentiles (`min/p50/p95/max`).
- **Current Status:** `FAIL` (Missing operational visibility APIs)
- **Required Remediation:** Add read-only dataset audit report and token-length distribution endpoints (`GET /v1/datasets/{version}/audit`, `GET /v1/datasets/{version}/token-stats`) backed by real manifest + tokenizer verification (no mock stats).
- **Verification Method:** API integration tests verifying 503 when unconfigured, 200 with verified stats when configured, and 422 on tampered checksums.

---

## Domain C: Training Pipeline Audit

### Finding `C-01` — Optimizer, LR Schedule, Loss & Guard Logic (`train.py`)
- **File / Config Ref:** `/apps/core/native/train.py:78-114,160-200,400-628`
- **Actual Evidence:** `TrainConfig.tier0_v11()` sets `block_size=256`, `batch_size=4`, `grad_accum_steps=1`, `max_steps=500`, `segment_max_steps=500`, `lr_total_steps=10_000`, `lr=3e-4`, `min_lr=3e-5`, `warmup_steps=100`, `weight_decay=0.1`, `grad_clip=1.0`, `eval_interval=250`, `eval_batches=20`, `checkpoint_interval=250`, `log_interval=10`, `seed=1337`, `strict_limits=True`. AdamW (`betas=(0.9, 0.95)`) splits decaying (`dim >= 2`) and non-decaying (`dim < 2`) parameters. Loss uses CE with `ignore_index=-100`, enforces `math.isfinite(total_loss)` before `optimizer.step()`, checks `CostController` + `TrainingRuntimeGuard`, records exact `parameter_changed` delta against cloned initial weights, and emits JSONL via `TrainingMonitor`.
- **Current Status:** `PASS` (Static design), `NOT VERIFIED` (Runtime execution blocked by missing `torch`)
- **Required Remediation:** Install PyTorch CPU (`>=2.5`) in sandbox and run a 20-step instrumented check confirming `lr_at(step)`, loss decrease, gradient norms, and `parameter_changed == True`.
- **Verification Method:** `pytest apps/core/native/test_train.py apps/core/native/test_train_torch.py`.

### Finding `C-02` — Missing Stage Curriculum (`stage_tags`) Filtering & Replay Ratio Wiring
- **File / Config Ref:** `/apps/core/native/train.py:450-520`, `/apps/core/workflow/handlers/groups.py:545-580`, `/docs/v11/V11_TRAINING_PLAN.md`
- **Actual Evidence:** `handle_training_execute()` (`groups.py:551`) loads the entirety of `train.jsonl` blindly into `train_pairs` without filtering by `stage_tag` or enforcing the 6-stage curriculum mixture (`S1..S6` + replay mix). `TrainConfig.tier0_v11()` has no `stage_id` or `stage_replay_weights` field.
- **Current Status:** `FAIL` (Stage curriculum documented in `V11_TRAINING_PLAN.md` is not wired into `train_sft` or `handle_training_execute`)
- **Required Remediation:** Add explicit `stage_id`, `stage_tags`, and `replay_mix` deterministic weighted sampler in `train_sft()` / `handle_training_execute()` (requires code-change review).
- **Verification Method:** Unit test verifying Stage-1 batch draws exclusively from S1 examples while Stage-2 draws exact configured primary/replay ratio.

### Finding `C-03` — Static Pre-Bound Slot Permutations & Replacement Sampling
- **File / Config Ref:** `/apps/core/workflow/handlers/groups.py:553`, `/apps/core/native/train.py:463`
- **Actual Evidence:** In `groups.py:553`, `permute_slots` binds `<slot_0>..<slot_31>` **once** before calling `train_sft()`. Inside `train_sft()`, `sample_sft_batch()` (`train.py:463`) calls `rng.randrange(0, len(pairs))` randomly with replacement. Consequently, slot bindings are frozen to a single static assignment per record across the entire segment instead of rotating slot IDs dynamically per step/epoch, weakening slot-invariance training. Also, evaluation inside `train_sft()` only samples up to `eval_batches * batch_size = 80` sequential rows (`train.py:471-476`).
- **Current Status:** `FAIL` (Weakens V11 slot-binding objective)
- **Required Remediation:** Move `bind_ephemeral_slots(..., rng=step_rng)` inside batch collation so each training step binds fresh randomized `<slot_k>` assignments deterministically from `(seed, step, example_idx)`.
- **Verification Method:** Assert two training batches for the same prompt ID across different steps produce distinct slot indices when `permute_slots=True` while preserving deterministic replay under identical `(seed, step)`.

### Finding `C-04` — Training Orchestrator & API Router Gaps (Pause/Cancel/Resume, Unchecked Limits, No Cross-Segment Resume)
- **File / Config Ref:** `/apps/api/routers/training.py:1-488`, `/apps/api/training_jobs.py:1-287`, `/apps/core/training/orchestrator.py:38,137-305`, `/apps/api/training_schemas.py:1-95`, `/apps/core/native/dataset_status.py:180-240`
- **Actual Evidence:**
  1. `apps/api/training_schemas.py` defaults to `block_size=128, batch_size=1, max_steps=100`, lacks `segment_max_steps`, `lr_total_steps`, `stage_id`, and `permute_slots`.
  2. `inspect_training_preflight_readiness()` (`dataset_status.py`) invokes `TrainingOrchestrator.prepare()` with hardcoded `block_size=128, max_steps=100`, not `tier0_v11()` (`256 / 500`).
  3. `TrainingOrchestrator` (`orchestrator.py`) always constructs a fresh `ZyrquenModel` (cannot resume from an earlier parent checkpoint across 500-step segments), sets `MAX_CPU_TRAINING_STEPS = 1000` (different from `tier0_v11`'s `segment_max_steps=500`), and passes NO `RamMonitor` (`3.0/3.5 GiB`) to `train_sft()`.
  4. `POST /v1/training/runs` uses single-process `ThreadPoolExecutor(max_workers=1)` (`training_jobs.py`), provides **zero `cancel`, `pause`, or `resume` endpoints**, and marks interrupted runs as `"failed"` on restart (`_reconcile_run`).
  5. `groups.py` requires `resume_existing=True` explicitly; otherwise each segment starts in a new `run_<id>` subdir from `step = 0` with no dataset/config SHA-256 assertion on resume.
- **Current Status:** `FAIL`
- **Required Remediation:** Unify API/Orchestrator with `TrainConfig.tier0_v11()`, enforce `RamMonitor` + dataset/tokenizer SHA-256 verification on checkpoint resume, support explicit `parent_checkpoint_version` continuation, and add `POST /v1/training/runs/{id}/cancel` with cooperative stop-flag propagation.
- **Verification Method:** API & orchestrator unit tests verifying segment-to-segment continuity (`step 500 -> 1000`), cooperative cancellation, and 400/422 rejection of mismatched tokenizer/dataset SHA-256 on resume.

---

## Domain D: Evaluation Framework Audit

### Finding `D-01` — Preservation of Historical Baselines & V10 `CLOSED_FAIL`
- **File / Config Ref:** `/apps/core/native/registry.py:70-72,632-633`, `/docs/v11/V11_GATE_TRANSITION_DECISION.md`, `/apps/core/native/closure_audit.py:1-700`
- **Actual Evidence:** `FROZEN_BASELINE_NAMES = {"v7", "v8", "v9", "ZYRQUEN-v7", "ZYRQUEN-v8", "ZYRQUEN-v9"}` are protected against mutation in `ModelRegistry`. `V11_GATE_TRANSITION_DECISION.md` records V10's status as `CLOSED_FAIL` for NGI capability while permitting P11 Readiness Preparation ONLY (`V10-GOV-DEC-01`). Locally, live probe `build_v10_closure_audit()` returned `overall_status: "BLOCKED"`, `static_status: "STATIC PASS" (5/5)`, `runtime_status: "BLOCKED"`, `v11_gate: {"unlocked": False, "status": "LOCKED"}` with 6 missing runtime blockers (`TORCH_NOT_INSTALLED`, `DATASET_DIR_NOT_CONFIGURED`, `TOKENIZER_NOT_CONFIGURED`, `EVAL_REPORT_NOT_CONFIGURED`, `MODEL_REGISTRY_NOT_CONFIGURED`, `TRAINED_V10_MODEL_UNAVAILABLE`).
- **Current Status:** `PASS` (Historical `v7`/`v8`/`v9` protection verified; V10 `CLOSED_FAIL` preserved untouched; local `v11_gate` stays `LOCKED`)
- **Required Remediation:** Never mutate historical V7–V10 verdicts or artifacts. Keep `v11_gate` locked until either V10 closure report SHA-256 is formally archived per `V10-GOV-DEC-01` OR an explicit human V11 governance override unlocks Stage-2 P11 runs after all `WP-0..WP-5` blockers are resolved.
- **Verification Method:** Inspect `build_v10_closure_audit()` and `ModelRegistry.set_lifecycle_status()` rejection tests on frozen baselines.

### Finding `D-02` — Schema & Tooling Gap Between `evaluate_native_model()` and `handle_evaluation_gate()`
- **File / Config Ref:** `/apps/core/native/evaluation/engine.py:1-675`, `/apps/core/workflow/handlers/groups.py:1258-1467`, `/tools/`
- **Actual Evidence:** `evaluate_native_model()` already detects `nagi_v11` / `unseen`+`ood`, runs greedy decoding across `("validation", "unseen", "ood")`, forbids silent prompt truncation, restores `<slot_k>` via `_V11_ENTITY_RE`, and computes `exact_match`, `eos_hit_rate`, `unseen_entity_copy_acc`, `overfit_gap`, and `ood_transfer_gap`. However:
  1. `evaluate_native_model()` outputs `"schema": "zyrquen.native_inference_evaluation.v1"` WITHOUT `"report_schema": "zyrquen.v11.evaluation_report.v1"`, `"overall_status"`, `"dataset_integrity"`, `"leakage_audit_status"`, `"regression_comparison"`, `"acceptance_assessment"`, or `"checkpoint"` block required by `handle_evaluation_gate()` (`groups.py:1258-1467`).
  2. **No `tools/eval_nagi_v11.py` wrapper script exists** to run inference and emit `zyrquen.v11.evaluation_report.v1`.
  3. Default `max_new_tokens = 32` (`engine.py`) is insufficient for 5–6-step `multi_step_planning` and `self_verification` responses (requires `48–64` tokens).
  4. Missing V11 metrics: `teacher_forced_exact`, `exposure_gap`, `abstention_precision`/`recall`, `ar_inverse_query_acc`, `ar_unknown_f1`, `ood_transfer_hop4/5/6_acc`, `ood_transfer_lexical_gap`, `ood_transfer_structural_gap`, `near_miss_rejection_rate`.
  5. Exact V11 PASS thresholds (`OD-EP-01` / `OD-RG-01`) remain `OPEN` (unfrozen) in `/docs/v11/V11_EVALUATION_PLAN.md`.
- **Current Status:** `FAIL`
- **Required Remediation:** Implement `tools/eval_nagi_v11.py` producing `zyrquen.v11.evaluation_report.v1`, extend `apps/core/native/evaluation/engine.py` with the 6-capability V11 metrics + `max_new_tokens >= 64` support + teacher-forced comparison, and freeze exact V11 PASS floors before any P11 experiment.
- **Verification Method:** Run `tools/eval_nagi_v11.py` against a random-init baseline `ZyrquenModel` (expecting near-0% capability `FAIL`, schema `PASS`) and verify `handle_evaluation_gate()` parses it cleanly without schema errors.

### Finding `D-03` — Broken `/v1/evaluation/runs` API Endpoint
- **File / Config Ref:** `/apps/api/routers/evaluation.py:1-182`, `/apps/api/evaluation_service.py:1-112`
- **Actual Evidence:** `POST /v1/evaluation/runs` calls `engine.run_evaluation(..., run_inference=False)` with NO `metrics`, NO `tokenizer_path`, NO `splits`, and NO `zyrquen.v11.evaluation_report.v1` output — guaranteeing an HTTP `503` (`EvaluationNotConfiguredError`) even when artifacts exist! Moreover, `apps/api/evaluation_service.py` (`create_evaluation_run`, etc.) is NOT wired into the `POST /v1/evaluation/runs` handler, so runs are neither queued nor persisted in PostgreSQL/SQLite.
- **Current Status:** `FAIL`
- **Required Remediation:** Wire `POST /v1/evaluation/runs` to `evaluation_service.create_evaluation_run()` and execute `evaluate_native_model(..., run_inference=True, splits=...)` with persisted report artifacts + SHA-256 digests.
- **Verification Method:** `pytest apps/api/test_evaluation.py` verifying DB row creation, report SHA-256 persistence, and real native inference execution.

---

## Domain E: Compute & Runtime Environment Readiness

### Finding `E-01` — Missing Core Runtime Dependencies (`torch`, `fastapi`, `pytest`, `pip`)
- **File / Config Ref:** Host environment (`python3 3.11.2`), `/apps/api/requirements.txt`
- **Actual Evidence:** Live environment probe confirmed:
  - `python3`: `3.11.2` | `cpus`: `4` | `nvidia_smi`: `None` (no GPU)
  - `torch_spec`: `None` | `fastapi_spec`: `None` | `pytest_spec`: `None` | `pip_spec`: `None`
  - `mem_total`: `12,582,912 kB` (`12.0 GiB`) | `mem_avail`: `10,309,360 kB` (`~9.83 GiB`) | `swap`: `0 kB`
  - `disk_gb`: `282.85 GiB` total, `281.45 GiB` free
- **Current Status:** `BLOCKED`
- **Required Remediation:** Install CPU-only PyTorch (`--index-url https://download.pytorch.org/whl/cpu` per `docs/v10/V10_PYTORCH_CPU_INSTALLATION_PLAN.md`), `fastapi`, and `pytest` inside an approved runtime venv — strictly no paid GPU provisioning.
- **Verification Method:** `python3 -c "import torch, fastapi, pytest; print(torch.__version__, torch.cuda.is_available())"`.

### Finding `E-02` — Unverified Peak RSS, Step Throughput (`sec/step`) & `RamMonitor` / `ResourceGuard` Calibration
- **File / Config Ref:** `/apps/core/workflow/resource_guard.py:1-519`, `/apps/core/workflow/handlers/groups.py:520-585`, `/docs/v11/V11_RESOURCE_AND_SCALING.md`
- **Actual Evidence:** `groups.py` enforces `RamMonitor` (`3.0 GiB` soft, `3.5 GiB` hard), disk guard (`2.0 GiB` free reserve, `1.0 GiB` max new disk), `cpu_threads <= 2`, and segment timeouts (`1200s` soft, `3600s` hard). `V11-Tier0-Default` (`57.04 MiB` AdamW static) and `V11-Tier0-Deep6L` (`72.55 MiB` AdamW static) comfortably fit inside `9.83 GiB` host available RAM mathematically, **but** actual PyTorch runtime baseline RSS, backward activations (`B=4, L=256`), and CPU `sec/step` latency have never been measured.
- **Current Status:** `NOT VERIFIED` (Blocked by `E-01`)
- **Required Remediation:** Run an approved 10-step CPU micro-benchmark (`SmokeMini` then `Tier0-Default`) to measure actual Peak RSS (`MiB`) and `ms/step` before sizing any `500`-step segment timeout.
- **Verification Method:** Recorded JSONL `TrainingMonitor` telemetry (`rss_mb`, `step_duration_s`) from non-production micro-benchmark.

---

## Domain F: Verification & Unit Test Truth Table

| Test Scope | Command Executed | Observed Result | Honest Verdict | Notes |
|---|---|---|---|---|
| V11 Stage-1 Readiness Suite | `python3 -m unittest tests/test_v11_stage1_readiness.py` | `6 ran, 6 OK (0.053s)` | `RUNTIME PASS` (Contracts/Docs) | Pure-stdlib contract & doc alignment checks only; no `torch` |
| Pure-Stdlib Core/Workflow Suites (14 modules) | `python3 -m unittest tests/test_v11_stage1_readiness.py tests/test_v10_closure_audit.py tests/test_v10a_contracts.py tests/test_v10c_integration_hook.py tests/test_v10d_closure_runner.py tests/test_dataset_status_api.py tests/test_evaluation_gate_safety.py tests/native/test_checkpoint_resume.py tests/test_workflow_engine.py tests/test_native_train_observability.py tests/test_v10_remediation_suite.py tests/test_v10_findings_abcd_remediation.py tests/test_v9_static_contracts.py tests/test_maintainer_bot.py` | `101 ran, 99 OK, 2 skipped (6.597s)` | `RUNTIME PASS` (Stdlib Subset) | `2 skipped` due to missing `pydantic`; mock `load_fn` used in checkpoint/registry tests |
| Native Core Pytest Suite | `python3 -m unittest discover apps/core/native` | `FAILED (errors=6)` | `BLOCKED` | `ModuleNotFoundError: No module named 'pytest'` (`test_tokenizer.py`, `test_train.py`, `test_train_torch.py`, `test_registry.py`) |
| API / PG Integration Tests | `apps/api/test_*.py` | Not runnable (`fastapi`/`pytest` absent) | `NOT RUN` | Blocked on missing `fastapi` / `pytest` / DB dependencies |
| Real Native Training / Eval (Tier 4) | — | No `torch`, no V11 data | `NOT RUN` | Prohibited under readiness audit mode (`TRAINING AUTHORIZATION: NOT GRANTED`) |

---

## Final Readiness Assessment (`P11_READINESS = BLOCKED`)

1. **What is already implemented:**
   - Pure native `ZyrquenModel` (`zyrquen-decoder`, Pre-RMSNorm + RoPE + SwiGLU + Causal SDPA + random init) and `ZyrquenConfig` (`Tier0` configs `<= 5M`).
   - `ZyrquenTokenizer` (`zyrquen.tokenizer.v2`) with 32 atomic `<slot_0>..<slot_31>` tokens and `train_slot_safe_tokenizer()` (`EL-05`).
   - `dataset.py` (`V11_SPLITS`, `verify_dataset_manifest()`), `dataset_v11.py` (`DataAdapter` exact + `_V11_ENTITY_RE` check), `sft.py` (`bind_ephemeral_slots`, `restore_ephemeral_slots`, `-100` target masking).
   - `TrainConfig.tier0_v11()`, `train_sft()`, `CheckpointManager` (`weights_only=True`, SHA-256 manifest, `keep_last`), `ModelRegistry` (`reserve_next_native_version`, immutable snapshots, evaluation gate), `NativeModelLoader`, `WorkflowOrchestrator`, `ResourceGuard`, HMAC Tier-2 approval gate, `handle_evaluation_gate` V11 branch (`zyrquen.v11.evaluation_report.v1`), and V11 docs (`docs/v11/*`).
2. **What has been verified by actual tests:**
   - `101` stdlib unit tests (`99 OK, 2 skipped`) across V9/V10/V11 stage-1 readiness, dataset status API logic, evaluation gate anti-fake guards, workflow engine handlers, checkpoint manifest recovery contracts (mocked torch), and `maintainer.audit.v1` native-only compliance (`294` Python files, `0` syntax errors).
   - Host hardware probe (`4` CPU, `12.0 GiB` RAM, `~281.45 GiB` disk free, no GPU) and exact `ZyrquenConfig` parameter counts (`3,737,856`, `4,262,144`, `4,754,688`).
3. **What remains incomplete:**
   - Runtime dependencies (`torch` CPU, `fastapi`, `pytest`, `pydantic`).
   - V11 dataset generator (`tools/gen_nagi_v11.py`), enhanced leakage/dedup auditor (`tools/audit_leakage_v11.py` + `TL-01`/`SL-01`/`DL-01`/token-length check), V11 eval runner (`tools/eval_nagi_v11.py`), and generated `data/nagi_v11/*` + trained `tokenizer.json`.
   - `train_sft` / `handle_training_execute` stage-tag curriculum filtering, per-step dynamic slot permutation, cross-segment checkpoint continuation/resume verification, `TrainingOrchestrator.prepare()` 4-split/`splits`-key support, dataset/eval API endpoints (`/v1/datasets/{ver}/audit`, `/v1/evaluation/runs` DB + inference wiring, `/v1/training/runs/{id}/cancel`), and frozen P11 numeric PASS thresholds (`OD-EP-01`).
4. **Exact blockers preventing training:**
   - `B-01`: `torch`, `fastapi`, `pytest` not installed in container.
   - `B-02`: `data/nagi_v11/` and `tokenizer.json` do not exist; `tools/gen_nagi_v11.py` & `tools/audit_leakage_v11.py` missing.
   - `B-03`: V10 Closure Gate locked locally (`build_v10_closure_audit() -> BLOCKED`, `v11_gate: LOCKED`) until V10 archive/override is reconciled.
   - `B-04`: Missing `TL-01` template, `SL-01` structural, `DL-01` fuzzy dedup, and `<=256` token-budget leakage gates.
   - `B-05`: `train_sft` lacks `stage_tags` curriculum filtering & dynamic per-step slot binding; `TrainingOrchestrator.prepare()` breaks on `"splits"`-only manifests and skips `unseen`/`ood`.
   - `B-06`: Missing `tools/eval_nagi_v11.py` (`zyrquen.v11.evaluation_report.v1` assembler) and unfrozen evaluation PASS thresholds (`OD-EP-01`).
   - `B-07`: Unused `/apps/core/download_model.py` (`Qwen/Qwen2.5-0.5B`) & mock `/apps/core/evaluation/engine.py` unquarantined.
   - `B-08`: Broken `/v1/evaluation/runs` (`run_inference=False` -> 503) & missing training/dataset control APIs.
5. **Recommended sequence of remediation:**
   - `Step 0`: Human decision on V10 archival/closure override + clean/quarantine `download_model.py` and mock `apps/core/evaluation/engine.py`.
   - `Step 1`: Provision CPU-only `torch`, `fastapi`, `pytest` inside clean venv; verify `apps/core/native/test_*.py` + `weights_only=True` RNG serialization + run 10-step CPU RAM/throughput benchmark.
   - `Step 2`: Implement `tools/gen_nagi_v11.py` + `tools/audit_leakage_v11.py` (`TL-01`/`SL-01`/`DL-01`/length cap) -> generate V11 corpus + train `zyrquen.tokenizer.v2` (`EL-05` clean).
   - `Step 3`: Patch `train_sft`, `handle_training_execute`, `TrainingOrchestrator.prepare()` (`stage_tags`, dynamic slot permutation, cross-segment resume verification), and freeze `OD-EP-01` / `OD-MS-01` / `OD-MS-02`.
   - `Step 4`: Implement `tools/eval_nagi_v11.py` (`zyrquen.v11.evaluation_report.v1`) and wire `/v1/evaluation/runs` + `/v1/datasets/{ver}/audit` + `/v1/training/runs/{id}/cancel`.
   - `Step 5`: Run Untrained Random-Init Evaluation Baseline (must return `FAIL` on capabilities, `PASS` on schema) -> Present Gate Evidence for explicit human Tier-2 Training Approval.
6. **Evidence required before training authorization:**
   - `pytest` runtime pass on all native tests (`test_train_torch.py`, `test_tokenizer.py`, `test_checkpoint_resume.py`, `test_registry.py`) with `torch` installed.
   - Non-zero measured CPU RAM (`Peak RSS < 3.0 GiB`) and step latency (`sec/step`) from a 10-step CPU micro-benchmark.
   - Deterministic `data/nagi_v11/manifest.json` SHA-256 + `leakage_audit_report.json` (`PASS` on `EL-01..05`, `TL-01`, `SL-01`, `DL-01`, max token length `<= 256`).
   - Verified random-init baseline `zyrquen.v11.evaluation_report.v1` (`overall_status: FAIL` on intelligence, confirming zero leakage / zero fake pass).
   - Valid consumed Tier-2 HMAC `approval_id` signed for the exact dataset SHA-256, `ZyrquenConfig`, and step budget.
