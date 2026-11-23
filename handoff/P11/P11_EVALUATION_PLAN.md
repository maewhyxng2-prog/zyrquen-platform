# ZYRQUEN Ω∞ — P11 Evaluation Plan (`P11_EVALUATION_PLAN.md`)

- **Mission:** Native Evaluation Framework Audit & P11 Evaluation Design
- **Mode:** `READINESS AUDIT + PREPARATION` (`EXECUTION AUTHORITY: NOT GRANTED`)
- **Primary References:** `/docs/v11/V11_EVALUATION_PLAN.md`, `/docs/v11/V11_GATE_TRANSITION_DECISION.md`, `/apps/core/native/evaluation/engine.py`, `/apps/core/workflow/handlers/groups.py:1258-1467`, `/apps/api/routers/evaluation.py`

---

## 1. Historical Baseline & Governance Preservation (Non-Negotiable)

| Baseline / Phase | File / Config Ref | Actual Evidence | Current Status | Policy Rule | Verification Method |
|---|---|---|---|---|---|
| **V7, V8, V9 Baselines** | `/apps/core/native/registry.py:70-72,632-633,899-900` | `FROZEN_BASELINE_NAMES = {"v7", "v8", "v9", "ZYRQUEN-v7", "ZYRQUEN-v8", "ZYRQUEN-v9"}` raises `RegistryError` on mutation or overwrite. | `PASS` (Code Enforced) | Never alter, delete, or re-evaluate V7–V9 historical verdicts. | `tests/test_evaluation_gate_safety.py` |
| **V10 Historical Outcome** | `/docs/v11/V11_GATE_TRANSITION_DECISION.md`, `/apps/core/native/closure_audit.py` | Governance decision `V10-GOV-DEC-01` preserves V10 capability as `CLOSED_FAIL`. Live probe `build_v10_closure_audit()` locally returned `overall_status: "BLOCKED"`, `v11_gate: {"unlocked": False, "status": "LOCKED"}` (6 missing V10/runtime artifacts on disk). | `PASS` (Verdict Preserved); `BLOCKED` (Local V11 Gate) | Preserve V10 `CLOSED_FAIL` unchanged in all docs & DB; never mark V10 `PASS`. P11 readiness preparation proceeds strictly without granting training/promotion authority. | `python3 -m unittest tests/test_v10_closure_audit.py` |

---

## 2. Evaluation Pipeline Audit Findings

### Finding `EV-01` — Output Schema Mismatch Between `evaluate_native_model()` and `handle_evaluation_gate()`
- **File / Config Ref:** `/apps/core/native/evaluation/engine.py:1-675`, `/apps/core/workflow/handlers/groups.py:1258-1467`, `/tools/`
- **Actual Evidence:** `evaluate_native_model()` already detects 4-split `nagi_v11`, runs greedy generation across `("validation", "unseen", "ood")`, forbids silent prompt truncation, restores `<slot_k>` via `_V11_ENTITY_RE`, and emits `schema: "zyrquen.native_inference_evaluation.v1"`. However, `handle_evaluation_gate()` (`groups.py:1258-1467`) requires `"report_schema": "zyrquen.v11.evaluation_report.v1"` containing `"overall_status"`, `"dataset_integrity"`, `"leakage_audit_status"`, `"inference_executed": true`, `"inference_status": "PASS"`, all 6 capability scores (`PASS`), `"regression_comparison"` (`zero_regression: true`), `"stop_criteria_triggered": []`, and `"acceptance_assessment.criteria"`. No `tools/eval_nagi_v11.py` exists to transform raw inference outputs + integrity checks into `zyrquen.v11.evaluation_report.v1`.
- **Current Status:** `FAIL`
- **Required Remediation:** Implement `tools/eval_nagi_v11.py` (strictly non-fabricated; real model forward/generate execution only) outputting `zyrquen.v11.evaluation_report.v1` verified against `handle_evaluation_gate()`.
- **Verification Method:** Run `tools/eval_nagi_v11.py` on untrained random-init `ZyrquenModel` -> assert schema validation passes in `handle_evaluation_gate()` while capability verdict reports `FAIL`.

### Finding `EV-02` — Missing V11 Metric Computations & Truncated `max_new_tokens` Default
- **File / Config Ref:** `/apps/core/native/evaluation/engine.py`, `/docs/v11/V11_EVALUATION_PLAN.md`
- **Actual Evidence:** `evaluate_native_model()` computes `exact_match`, `eos_hit_rate`, `per_capability`, `unseen_entity_copy_acc`, `overfit_gap`, and `ood_transfer_gap`, defaulting `max_new_tokens = 32`. It does NOT compute `teacher_forced_exact` / `exposure_gap` (comparing teacher-forced accuracy vs greedy decoding), `abstention_precision` / `abstention_recall`, `ar_inverse_query_acc`, `ar_unknown_f1`, `ood_transfer_hop4/5/6_acc`, `ood_transfer_lexical_gap`, `ood_transfer_structural_gap`, or `near_miss_rejection_rate`. Moreover, `32` tokens truncates 5–6-step plan targets.
- **Current Status:** `FAIL`
- **Required Remediation:** Extend `apps/core/native/evaluation/metrics.py` + `engine.py` with teacher-forced + greedy dual evaluation, V11 diagnostic metrics, and default `max_new_tokens=64` for V11 `multi_step_planning` / `self_verification` splits.
- **Verification Method:** Deterministic unit tests verifying metric formulas against synthetic reference predictions and zero silent target truncation.

### Finding `EV-03` — Open / Unfrozen Numeric PASS Thresholds (`OD-EP-01` & `OD-RG-01`)
- **File / Config Ref:** `/docs/v11/V11_EVALUATION_PLAN.md` (`OD-EP-01`), `/docs/v11/V11_RELEASE_GATE.md` (`OD-RG-01`)
- **Actual Evidence:** Exact numeric PASS floors (`exact_match`, `abstention_f1`, `unseen_copy`, `max_overfit_gap`, `ood_transfer_ratio`) remain `[TBD / OPEN]` in V11 specs; meanwhile `handle_evaluation_gate()` passes any report whose upstream JSON marks `"overall_status": "PASS"` and finite non-negative capability scores without enforcing the frozen V11 numeric thresholds inside the gate itself.
- **Current Status:** `FAIL` (Anti-Self-Certification Risk)
- **Required Remediation:** Freeze explicit quantitative V11 thresholds in `P11` governance config AND enforce them inside `handle_evaluation_gate()` / `tools/eval_nagi_v11.py` independently of any model or report summary claims.
- **Verification Method:** Gate rejection test submitting inflated summary `"overall_status": "PASS"` paired with sub-threshold capability metrics -> must fail gate!

### Finding `EV-04` — Broken `/v1/evaluation/runs` Router & Legacy Mock Module Risk
- **File / Config Ref:** `/apps/api/routers/evaluation.py:1-182`, `/apps/api/evaluation_service.py:1-112`, `/apps/core/evaluation/engine.py:1-47`
- **Actual Evidence:** `POST /v1/evaluation/runs` invokes `engine.run_evaluation(..., run_inference=False)` with empty `metrics` and never calls `evaluation_service.create_evaluation_run()` -> always returns HTTP `503` and persists nothing to DB. Meanwhile legacy `/apps/core/evaluation/engine.py` (unwired) still returns hardcoded `15.5` / `0.85`.
- **Current Status:** `FAIL`
- **Required Remediation:** Quarantine/remove `/apps/core/evaluation/engine.py` (with human approval) and wire `/v1/evaluation/runs` to real `evaluate_native_model(..., run_inference=True)` + DB `EvaluationRun` persistence with SHA-256 report hashes.
- **Verification Method:** `pytest apps/api/test_evaluation.py` + `tests/test_evaluation_gate_safety.py`.

---

## 3. P11 6-Capability Evaluation Suite & Required Metrics

Every model evaluation MUST run **actual greedy inference (`temperature=0.0`, `do_sample=False`, `max_new_tokens=64`)** across `validation`, `unseen`, and `ood` splits (plus optional diagnostic `train` subset strictly labeled as `diagnostic_only` to compute `overfit_gap = train_exact - unseen_exact`), PLUS teacher-forced exact check to expose `exposure_gap = teacher_forced_exact - greedy_exact`.

| # | P11 Capability | What Is Tested (`validation` + `unseen` + `ood`) | Required Metrics | Anti-Fake / Cheat Proof |
|---|---|---|---|---|
| **1** | `knowledge_integration` | Bind multi-fact atomic records (`TR`/`VL`/`UN`/`OO`), multi-attribute synthesis, missing/contradictory premise detection | `exact_match`, `unseen_exact`, `unseen_entity_copy_acc`, `abstention_precision`, `abstention_recall` | Must answer `"UNKNOWN"` on missing entities rather than guessing; `<slot_k>` restored cleanly |
| **2** | `multi_step_planning` | Ordered action plans (`1–4` steps in train/val; `5–6` steps in OOD) respecting preconditions & state transitions | `exact_match`, `plan_step_validity_rate`, `goal_state_accuracy`, `eos_hit_rate`, `ood_plan5_6_acc` | Exact state-machine replay check; invalid intermediate actions fail full sample |
| **3** | `relational_generalization` | Graph/chain traversal (`2–3` hops in train/val; `4–6` hops & unseen relation triples in `unseen`/`ood`) | `exact_match`, `hop2_3_acc`, `hop4_6_acc`, `unseen_copy_acc`, `exposure_gap` | Disjoint entity prefixes (`UN_E*`, `OO_E*`); zero entity memorization |
| **4** | `ood_transfer` | Combined lexical paraphrase (`Family B/C`) + deeper compositional structure (`Depth 4–6`, unseen combinations) | `ood_exact_match`, `ood_lexical_gap = val - unseen`, `ood_structural_gap = unseen - ood` | Zero overlap with `train`/`val` templates (`TL-01`) and depths (`SL-01`) |
| **5** | `abstract_reasoning` | Rule symmetry, inverse queries (`B -> A` from `A -> B`), transitivity, symbolic equivalence classes | `exact_match`, `ar_inverse_query_acc`, `ar_unknown_f1`, `symmetry_consistency` | Pairwise bidirectional test (`forward` AND `inverse` both required) |
| **6** | `self_verification` | Verify candidate claims/plans against context: accept valid derivations vs detect **near-miss corruptions** (1 wrong hop / missing precondition) | `exact_match`, `near_miss_rejection_rate`, `valid_acceptance_rate`, `false_accept_rate` | Balanced 50/50 valid vs adversarial 1-token near-miss perturbations; trivial "always accept/reject" scores `FAIL` |

---

## 4. Proposed Frozen Thresholds for Human Approval (`OD-EP-01` Resolution Candidate)

*(Not active until ratified by human engineering sign-off before Stage-1 training starts):*
- **Untrained Random-Init Baseline Check (Pre-Training):** Must report `exact_match < 0.05` across `unseen` and `ood` (`status = FAIL` on intelligence, confirming zero leakage and zero hardcoded shortcuts).
- **Stage-1 Pilot Thresholds (`500`-step controlled pilot):** No capability promotion expected (`capability = NOT_YET_TRAINED_FULL`); evaluates whether `val_loss < init_val_loss`, `eos_hit_rate > 0.70`, and `knowledge_integration` copy improves strictly above random baseline.
- **Full `10,000`-Step V11 Release Certification Candidates (`OD-EP-01`):**
  - `eos_hit_rate >= 0.95` across all splits
  - `knowledge_integration` (`unseen`): `>= 0.75`, `abstention_recall >= 0.80`
  - `relational_generalization` (`unseen`): `>= 0.70`
  - `multi_step_planning` (`unseen`): `>= 0.65`
  - `abstract_reasoning` (`unseen`): `>= 0.65`, `ar_inverse_query_acc >= 0.60`
  - `self_verification` (`unseen`): `near_miss_rejection_rate >= 0.75` and `valid_acceptance_rate >= 0.75`
  - `ood_transfer` (`ood`): `>= 0.45` (`ood_exact_match > 0` and clearly above guessing floor, with no catastrophic collapse vs `unseen`)
  - `overfit_gap (train - unseen) <= 0.15`
  - `zero_regression: true` relative to prior registered V11 checkpoints (never regressing `V10` baseline, which remains archived as `CLOSED_FAIL`).
