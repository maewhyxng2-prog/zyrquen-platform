# ZYRQUEN Ω∞ — P11-C Evaluation Thresholds (`P11_C_EVALUATION_THRESHOLDS.md`)

- **Purpose:** Measurable Thresholds, Stop Conditions & Anti-Fake Certification Rules for `P11-EXP-01-PILOT` and Subsequent V11 Stages
- **Policy:** Pipeline Validation (`Track A`) MUST NEVER be conflated with Native General Intelligence Capability (`Track B`). Historical `v7`, `v8`, `v9`, and `V10 (CLOSED_FAIL)` remain permanently immutable.

---

## 1. Track A vs. Track B Gate Thresholds (Before Running Next Experiment)

### Phase 1 — Step 0 Random-Init Baseline Gate (Mandatory Before Any Training Step)
- **Inference Method:** Real greedy decoding (`temperature=0.0`, `do_sample=False`, `max_new_tokens=64`) on `validation`, `unseen`, and `ood`.
- **PASS Gate Criteria (Anti-Leakage / Anti-Shortcut Proof):**
  - Schema & provenance valid (`zyrquen.v11.evaluation_report.v1`, `inference_executed = true`).
  - `unseen` & `ood` `exact_match < 0.05` (confirming random weights have near-zero capability and zero hidden lookup/leakage).
  - Model capability status MUST report **`FAIL`** (expected for untrained baseline).

### Phase 2 — `P11-EXP-01-PILOT` (`500` Steps) Exit Criteria

| Track | Metric / Check | Threshold to PASS | Failure / Stop Trigger |
|---|---|---|---|
| **Track A (Pipeline)** | Weight Movement (`parameter_changed`) | `true` (exact L2 diff > 0) | `false` -> `FAIL` |
| **Track A (Pipeline)** | Numerical Stability | `0` NaN/Inf events; finite grad norms | Any `NaN`/`Inf` -> `ABORT` |
| **Track A (Pipeline)** | Convergence Signal | `final_val_loss < step_0_val_loss` (`>= 5%` drop) | `< 1%` drop or `> 1.5x` spike -> `FAIL` |
| **Track A (Pipeline)** | `weights_only=True` Reload | `100%` SHA-256 + state reload pass | Reload error -> `FAIL` |
| **Track A (Pipeline)** | Resource Compliance | `Peak RSS < 3.0 GiB`; `torch_threads <= 2`; disk `< 1.0 GiB` delta | `Peak RSS >= 3.5 GiB` or timeout -> `ABORT` |
| **Track A (Pipeline)** | Greedy Termination (`eos_hit_rate`) | `>= 0.70` on `validation` at Step `500` | `< 0.20` -> mode/EOS collapse (`FAIL`) |
| **Track B (Capability)** | `validation` / `unseen` / `ood` Exact Match + `exposure_gap` | Reported raw across all 6 capabilities (`Stage-1` copy expected `> step_0` baseline; full NGI certification NOT expected at `500` steps) | Fabricated/hidden scores or skipping `unseen`/`ood` -> `FAIL` |

### Phase 3 — Full `10,000`-Step V11 Certification Candidates (`OD-EP-01` — Frozen Prior to Full Curriculum)
- `eos_hit_rate >= 0.95` across all splits
- `knowledge_integration (unseen) >= 0.75`, `abstention_recall >= 0.80`
- `relational_generalization (unseen) >= 0.70`
- `multi_step_planning (unseen) >= 0.65`
- `abstract_reasoning (unseen) >= 0.65`, `ar_inverse_query_acc >= 0.60`
- `self_verification (unseen)`: `near_miss_rejection_rate >= 0.75` AND `valid_acceptance_rate >= 0.75`
- `ood_transfer (ood) >= 0.45` (`ood_exact_match > 0`)
- `overfit_gap (train_diag - unseen) <= 0.15`
- `zero_regression: true` relative to previous registered V11 checkpoints (never modifying frozen V10 `CLOSED_FAIL`).

---

## 2. Explicit Stop Conditions & Rollback Triggers

Training MUST halt immediately (`stop_criteria_triggered` non-empty) and rollback active sandbox head to last verified checkpoint if:
1. Any `NaN`/`Inf` occurs in forward loss or clipped gradients.
2. Validation loss rises `> 20%` across two consecutive `eval_interval=250` evaluations.
3. Single-token repetition collapse exceeds `80%` of greedy generations or `eos_hit_rate < 0.20`.
4. Overfit divergence (`train_exact - unseen_exact > 0.35`) occurs alongside stagnating `unseen` progress across `>= 2` consecutive stages.
5. Any leakage audit (`EL-01..05`, `TL-01`, `SL-01`, `DL-01`), SHA-256 mismatch, or resource limit breach (`RAM >= 3.5 GiB`, `disk_free < 2.0 GiB`) is detected.
