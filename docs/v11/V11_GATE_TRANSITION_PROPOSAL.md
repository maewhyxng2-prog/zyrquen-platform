# ZYRQUEN Ω∞ — V11 Gate Transition Proposal

- **Document ID:** `V11-GOV-PROP-01`
- **Status:** `PROPOSAL — REVIEW REQUIRED — NOT AN ACTIVE POLICY`
- **Target branch:** `docs/v11-gate-transition-v10-closed-fail`
- **Base branch:** `main`
- **Scope:** Governance transition only. No model, dataset, checkpoint, training, evaluation, registry, or runtime mutation.

## 1. Decision Requested

Approve a narrowly scoped exception to the existing V11 entry condition so that V11 planning and implementation-readiness work may proceed after V10 has been formally closed as **FAIL with complete evaluation evidence**, rather than requiring V10 to achieve PASS.

This proposal does **not**:
- change, overwrite, relabel, or delete any V10 source, dataset, checkpoint, report, registry record, or run;
- convert a V10 FAIL into PASS;
- authorize training, inference campaigns, evaluation reruns, model promotion, registry activation, or production deployment;
- waive V11 safety, integrity, leakage, capability, regression, or release gates;
- authorize paid cloud resources or any cost-incurring execution.

Approval of this proposal is not approval to start training.

## 2. Rationale

The existing V11 documentation states that V11 is locked until the V10 Final Gate passes. The reported V10 evaluation artifact
`v10_evaluation_20261123T135435_849648Z.json` has schema
`zyrquen.v10.evaluation_report.v1`, `overall_status=FAIL`,
`inference_status=PASS`, 200 evaluated examples, and
`stop_criteria_triggered=["capability_threshold_failed"]`.

The reported capability results are:
- `knowledge_integration`: 32/32 (1.000)
- `multi_step_planning`: 18/34 (0.529)
- `relational_generalization`: 6/34 (0.176)
- `ood_transfer`: 4/34 (0.117)
- `abstract_reasoning`: 0/34 (0.000)
- `self_verification`: 0/32 (0.000)

These values are recorded here as **user-supplied evaluation evidence**, not as independently re-executed or repository-verified results. The evaluation is considered complete for the purpose of this proposed governance decision only if the report and its provenance are retained and reviewed as specified below. The FAIL verdict must remain unchanged.

## 3. Proposed V10 Closure States

Introduce the following governance states for lifecycle tracking:

| State | Meaning | V11 entry effect |
|---|---|---|
| `OPEN` | Evaluation or required evidence is incomplete | V11 implementation remains blocked |
| `CLOSED_PASS` | Required final evaluation evidence exists and all V10 gates pass | V11 may proceed under existing approved gates |
| `CLOSED_FAIL` | Required final evaluation evidence exists, but one or more capability/release gates fail | V11 may proceed only after explicit Tier-2 approval of this transition |
| `CLOSED_BLOCKED` | Evaluation cannot be trusted or required integrity/provenance evidence is missing | V11 implementation remains blocked |

For the reported V10 result, the proposed target state is `CLOSED_FAIL`, **not** `CLOSED_PASS`.

A report with `inference_status=PASS` does not override `overall_status=FAIL`. Execution success and capability acceptance are separate outcomes.

## 4. Conditions for V10 CLOSED_FAIL

Before recording the closure decision, a reviewer must verify and preserve:

1. The exact report file and its SHA-256 digest.
2. The report schema and required fields, including the overall FAIL verdict and triggered stop criteria.
3. The evaluation runner/version and checkpoint identity used for the run, where available.
4. The six capability result counts and denominators; no denominator or score may be silently changed.
5. The distinction between user-provided evidence and independently verified repository/runtime evidence.
6. A read-only record that no promotion, active-version change, or evidence fabrication occurred.

If any required integrity or provenance item cannot be established, use `CLOSED_BLOCKED` rather than treating missing evidence as a pass. This proposal does not require rerunning the same checkpoint merely to reproduce an already complete report.

## 5. V11 Entry Conditions After Tier-2 Approval

If and only if Tier-2 explicitly approves the V10 `CLOSED_FAIL` transition:

- V11 may enter **implementation-readiness work** on a separate branch.
- V10 remains immutable and available only as a historical comparison record.
- V11 must use a separate namespace for all new artifacts:
  - Dataset: `data/nagi_v11/`
  - Checkpoints: `checkpoints/nagi_v11/`
  - Evaluation reports: `eval/nagi_v11/`
- V11 model weights must start from random initialization in accordance with Native-Only policy; V10 weights are not a training initialization source.
- No V11 training may begin until its own resource, dataset, runtime, safety, and execution approvals are independently satisfied.

## 6. V11 Technical Readiness Gates

The following are readiness requirements, not claims that implementation or tests already pass.

### Gate A — Configuration and resource envelope

- Reconcile the current native training defaults with the approved Tier-0 resource profile.
- The inspected `TrainConfig` currently defaults to `batch_size=16`, `block_size=128`, and `max_steps=1000`; do not assume these match the V11 Tier-0 plan.
- Establish an explicit RAM, CPU-thread, disk-reserve, and checkpoint-retention budget before any run.
- No cloud or paid resource allocation without separate explicit authorization.

### Gate B — Dataset and leakage controls

- Implement and test the V11 split contract: `train`, `validation`, `unseen`, and `ood`.
- The inspected native `dataset.py` currently declares `train`, `validation`, and `test`; V11 split support is therefore not yet demonstrated by that source.
- Verify deterministic split assignment, source provenance/licensing declarations, content hashes, deduplication across splits, and leakage audits.
- Keep test/evaluation targets isolated from training.

### Gate C — Training observability and recovery

- Record per-step finite loss, learning rate, gradient norm, parameter-update evidence, optimizer-step count, and checkpoint provenance.
- Verify parameter deltas across all trainable parameter groups, not only the first parameter tensor.
- Test interrupted/resumed runs and prove monotonic global-step accounting.
- A configured 20-experiment × 500-step plan is a design target, not proof that 10,000 steps have executed.

### Gate D — Capability curriculum

Prioritize the V10 failure areas:
1. `abstract_reasoning`
2. `self_verification`
3. `relational_generalization`
4. `ood_transfer`

Retain `multi_step_planning` and `knowledge_integration` as monitored capabilities to detect regressions. Dataset construction must include counterexamples, compositional variations, unseen entities, and held-out structural patterns. Do not use evaluation examples as training data.

### Gate E — Independent evaluation and release

- Evaluate all six capabilities on the declared splits with fixed, versioned criteria.
- Report raw correct/total counts, scores, confidence intervals where statistically appropriate, and per-split results.
- Treat `NOT RUN`, missing metrics, non-finite values, integrity failures, and leakage failures as non-passing states.
- Preserve regression comparisons where a valid, comparable baseline exists. If V10 lacks a verified comparable checkpoint or metric, mark that comparison `NOT AVAILABLE`; do not fabricate a zero-regression claim.
- No automatic promotion or active-version assignment. Release requires a separate Tier-2 approval and verified registry evidence.

## 7. Acceptance Rules — No Threshold Relaxation

This transition changes only the V11 entry governance rule. It does not lower any capability threshold, modify V10's report, weaken hard-fail behavior, or change the semantics of PASS/FAIL.

V11's final acceptance thresholds must be fixed and versioned before the final evaluation run. They must not be selected after observing final test results. Thresholds not yet justified by a baseline or task specification remain an explicit open decision; do not invent values in this proposal.

## 8. Required Tier-2 Decision

Tier-2 reviewer must explicitly choose one:

- **APPROVE:** Accept V10 closure as `CLOSED_FAIL` for the limited purpose of allowing V11 implementation-readiness work under independent gates.
- **REJECT:** Keep the existing V11 entry lock; no V11 implementation work proceeds.
- **REQUEST CHANGES:** Return this proposal for revision without changing V10 or starting V11 training.

The approval record must identify the reviewer, timestamp, proposal commit, decision, scope, and any conditions. A general approval to “start V11” must not be interpreted as permission to train, spend money, promote a model, or deploy.

## 9. Current Execution Status

At proposal creation:
- V10: no changes made.
- V11 model/training code: no changes made by this proposal.
- Training and inference: not started.
- Evaluation rerun: not started.
- Model Registry / active version: unchanged.
- `main`: unchanged.
- This document: proposal only; no policy becomes active until reviewed and explicitly approved.

## 10. References

- `docs/v11/V11_MASTER_PLAN.md`
- `docs/v11/V11_V10_COMPATIBILITY.md`
- `docs/v11/V11_TRAINING_PLAN.md`
- `docs/v11/V11_EVALUATION_PLAN.md`
- `docs/v11/V11_SELF_VERIFICATION.md`
- `apps/core/native/config.py`
- `apps/core/native/train.py`
- `apps/core/native/dataset.py`
