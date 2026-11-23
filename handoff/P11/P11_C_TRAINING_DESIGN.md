# ZYRQUEN Ω∞ — P11-C Training Design (`P11_C_TRAINING_DESIGN.md`)

- **Target Next Authorized Experiment:** Re-run `P11-EXP-01-PILOT` first (ONLY after terminal preflight & code remediations pass) — **NO increase in model size (`3,737,856`) or step cap (`500`)** until pilot Track A telemetry passes.
- **Native-Only Policy:** `MANDATORY` (fresh random initialization only; zero pretrained weights; zero external AI APIs).

---

## 1. Controlled Re-Baseline Configuration (`P11-EXP-01-PILOT-R1`)

No parameter or step escalation is proposed here because zero baseline steps completed in P11-B:

| Setting | Value | Justification / Guard Code |
|---|---|---|
| Model Tier | `V11-Tier0-Default` (`zyrquen-decoder`) | Already fits `MAX_V10_PARAMETERS = 5,000,000` (`config.py:4`) |
| Parameters | `3,737,856` | Verified by `ZyrquenConfig.estimated_num_parameters` |
| Topology | `n_layers=4, n_heads=4, d_model=256, d_ff=704, vocab_size=2048, max_seq_len=256` | Keeps RoPE `head_dim=64` even |
| Weight Init | Random `Normal(0, 0.02)`, scaled `0.02/sqrt(2*n_layers)` on `attn.proj`/`ffn.down`, `RMSNorm=1.0` | `apps/core/native/model.py::_init_weights` |
| Device & Precision | `cpu`, `float32`, `max_cpu_threads=2` | `groups.py:809`, `resource_guard.py` |
| Optimizer & LR | `AdamW(lr=3e-4, betas=(0.9,0.95), weight_decay=0.1 / 0.0)`, `grad_clip=1.0`, linear warmup `100` -> cosine `min_lr=3e-5` | `TrainConfig.tier0_v11()` |
| Batch & Steps | `batch_size=4, grad_accum=1, block_size=256, max_steps=500, seed=1337` | Hard segment budget limit (`<=500` steps) |
| Artifact Isolation | `artifacts/experiments/P11-EXP-01-PILOT/` | Isolated from production registry & V10 |

*(Only after `P11-EXP-01-PILOT-R1` passes Track A & telemetry review would a subsequent justified Tier-0 Stage `1..6` `10,000`-step schedule in `20 x 500` segments be requested via separate approval.)*

---

## 2. Required Pre-Execution Pipeline Patches (For Terminal/PR Review — Not Yet Applied)

1. **Dynamic Per-Step Slot Binding:** Move `bind_ephemeral_slots()` into training collation seeded by `(seed, step, example_idx)` so slot IDs `<slot_0>..<slot_31>` rotate per step instead of freezing statically in `groups.py:553`.
2. **Stage-Tag Curriculum Sampler (`stage_tags`):** Wire `stage_id` and deterministic `stage_replay_weights` filtering inside `train_sft()` / `handle_training_execute()`.
3. **`weights_only=True` RNG Serialization Fix:** Replace raw Python nested `random.Random.getstate()` tuples if PyTorch `>=2.5` `weights_only=True` rejects them, converting state ints cleanly to plain `list[int]`, and enforce `dataset_content_sha256` + `tokenizer_sha256` + `model_config` assertions on checkpoint resume.
4. **Orchestrator & Manifest Unification (`orchestrator.py:137-153`):** Update `TrainingOrchestrator.prepare()` to validate via `verify_dataset_manifest()` (`files` + `splits`) and enforce `DataAdapter.detect_leakage()` across all 4 splits (`train`, `validation`, `unseen`, `ood`), plus add `POST /v1/training/runs/{id}/cancel`.
5. **Deterministic Solver Pilot Corpus (`nagi_v11_pilot`):** Implement `tools/gen_nagi_v11.py` + `tools/audit_leakage_v11.py` (`EL-01..05`, `TL-01`, `SL-01`, `DL-01`, `<= 256` token budget) producing `1,200` `train` (`TR_E*`), `120` `validation` (`VL_E*`), `120` `unseen` (`UN_E*`), `120` `ood` (`OO_E*`).

---

## 3. Rollback & Anti-Mutation Controls

- **Zero In-Place Overwrite:** Checkpoints write atomically to `ckpt_%08d.pt` with `manifest.json` SHA-256 verification (`keep_last=2`); corrupted files fail validation rather than overwriting prior valid snapshots.
- **Frozen Rollback Reference:** Step `0` random-init checkpoint + report hash is preserved untouched alongside `ckpt_00000250.pt` and `ckpt_00000500.pt` so regression diffs (`step_500 - step_0`) and rollback are exact and immediate.
- **Untouched Production / Historical Baselines:** `v7`, `v8`, `v9`, V10 (`CLOSED_FAIL`), and production `registry.json` (`active = null`) MUST remain untouched.
