# ZYRQUEN V10 — v9 Failure Response & Evidence-Gated Preparation Plan

- **Document ID:** `V10-V9-FAILURE-RESPONSE`
- **Date:** 2026-11-24
- **Status:** `PREPARATION ONLY — NO SOURCE CHANGE / NO TRAINING`
- **Parent gates:** `docs/v10/V10_CLOSURE_STATUS.md`, `docs/V9_EXPERIMENT_CLOSURE_REPORT.md`
- **Architecture constraint:** V10 remains the existing Native `ZyrquenModel` / SFT track. The v9 `arm_d` Slot-Transformer + Pointer candidate is a measured comparison baseline, not an approved architecture to copy or merge.

## 1. Current V10 truth

V10-A/B/C are recorded as static, unit, or integration-wiring verified. V10-D remains **BLOCKED** because the required PyTorch CPU runtime, real training, real-weight inference evaluation, runtime resource telemetry, and signed closure evidence have not been produced. V11 remains **LOCKED**. This plan does not change those statuses.

## 2. v9 failure evidence that V10 must address

| Failure domain | v9 observed baseline | V10 evidence requirement |
|---|---:|---|
| OOD generalization | test OOD FG exact match 9.2%; val OOD 2.5% | Evaluate held-out syntax, operators, structural forms, and depth; publish per-slice scores, not only aggregate exact match. Freeze acceptance thresholds before the run. |
| Unseen entity extraction | test copy accuracy 27.7%; test OOD 2.2% | Separate entity binding/copy from reasoning; test multiple unseen entities in one context and verify exact surface restoration without train-vocabulary leakage. |
| Multi-hop reasoning | test unseen 2–3 hop 25.7%; 4–5 hop 7.2%; OOD 2–3 hop 0% | Report each hop-depth band independently, including 4–5+ hops; no extrapolation claim from shallow tasks. |
| Distractor robustness | 100% with zero distractors → 0% with 3–4 distractors | Use matched minimal pairs with 0–4 distractors; report absolute accuracy and percentage-point degradation. |
| Conflict vs override | override 100%; conflict 0% | Use balanced paired cases and report each class, confusion matrix, and both-correct rate. |
| Copy/generation gate | copy mean p_gen 0.6821 (target <=0.45) | If V10 uses a copy/pointer mechanism, evaluate gate calibration on copy and reasoning subsets. If no such mechanism exists, mark N/A with rationale; do not fabricate an equivalent metric. |
| Planning and sequence stability | planning FG repetition 93.3%; premature EOS 12.5%; overall repetition 7.9% | Evaluate EOS position, premature termination, repeated n-grams/tokens, plan validity, and task completion separately. |
| Knowledge acquisition | 0% across all v9 splits | Define a genuine acquisition/update/retention protocol; distinguish learning from prompt-conditioned retrieval and memorization. |

## 3. Benchmark and anti-leakage protocol

Before any V10 training run:
1. Generate the V10 dataset only through the existing V10 generator and run its leakage auditor. Preserve manifest, split counts, hashes, and audit output.
2. Keep train, validation, and test entities disjoint. Hold out syntax/operator families and structural templates for OOD tests. Include controlled distractor counts and explicit hop-depth labels.
3. Add paired minimal examples for override, conflict, retention, and retraction. Balance labels and report class-wise metrics.
4. Keep the test set sealed from tokenizer fitting, vocabulary construction, training, checkpoint selection, and threshold tuning.
5. Freeze benchmark version, metrics, acceptance thresholds, and stop criteria before training. Do not revise thresholds after observing test results.
6. Report teacher-forced and free-generation separately. Free-generation is the primary capability measure; teacher-forced scores are diagnostic only.
7. Publish per-capability and per-slice metrics, sample counts, confidence intervals where appropriate, representative error categories, and exact artifact hashes. No missing metric may be silently treated as zero or PASS.

## 4. V10 acceptance rules

- The existing V10 closure gate remains authoritative: Sections 5–12 of `V10_CLOSURE_STATUS.md` must reach the required verified state using real runtime evidence.
- V10 must be compared against the frozen v9 results on matched task families where the metrics are genuinely comparable. Clearly label non-comparable architecture- or task-specific metrics.
- V10 must show measurable improvement on the targeted failure slices without regressions in other reported capabilities. Acceptance thresholds must be written and frozen before the run; this document intentionally does not invent an OOD exact-match threshold absent from the v9 acceptance specification.
- Any criterion that is unmeasured, blocked, or lacks an artifact is `NOT RUN` / `BLOCKED`, never PASS.
- A successful training process, falling loss, static tests, or zero stop triggers alone cannot close V10.
- V11 remains locked until the V10 final runtime closure gate is genuinely `VERIFIED (RUNTIME PASS)`.

## 5. Execution order and authorization boundaries

| Order | Work item | Current status |
|---|---|---|
| 1 | Record v9 experiment as `CLOSED_FAIL` baseline | Completed in `docs/V9_EXPERIMENT_CLOSURE_REPORT.md` |
| 2 | V10 failure-response and benchmark preparation | This document; preparation only |
| 3 | Confirm CPU-only PyTorch runtime availability and obtain separate approval before installing dependencies | BLOCKED / approval required |
| 4 | Run V10-D preflight, dataset generation, and leakage audit in the approved runtime | NOT RUN |
| 5 | Obtain required Tier-2 approval and run the bounded V10-D real-weight training/evaluation workflow | NOT RUN |
| 6 | Audit actual reports, checkpoint/tokenizer hashes, resource telemetry, regression gates, and closure artifact | NOT RUN |
| 7 | Unlock V11 only after V10 runtime closure PASS and explicit stage authorization | LOCKED |

## 6. Non-actions

This preparation plan does **not** authorize dependency installation, dataset generation, model/source edits, training, checkpoint creation or promotion, registry mutation, paid compute, deployment, or V11/V12 implementation. v7/v8 remain frozen; v9 remains a failed, immutable comparison baseline. Product Phase 11–20 files are outside this model-experiment plan and must not be altered by it.
