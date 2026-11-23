# ZYRQUEN Ω∞ — V12 Preliminary Roadmap

- **Document ID:** V12-PLAN-PRELIM-01
- **Status:** PRELIMINARY PLANNING ONLY — NOT APPROVED FOR IMPLEMENTATION OR EXECUTION
- **Planning Basis:** V11 readiness remediation plan and the Native-Only project strategy
- **Branch:** docs/v12-preliminary-roadmap

## 1. Purpose

Prepare a forward-looking V12 direction without interrupting V11 remediation or assuming that V11 will pass. V12 is intended to continue the long-term development of ZYRQUEN as a native general-intelligence research system, not to narrow the project into a chatbot or translation-only system.

This document is a planning placeholder. It does not establish that V11 capabilities have been achieved, does not select a final V12 architecture, and does not authorize code changes, dataset generation, training, evaluation campaigns, deployment, or paid compute.

## 2. Non-Negotiable Project Constraints

1. **Native-Only origin:** V12 model weights must be initialized from scratch. No pretrained external model or external model weights may be used as the initialization base.
2. **No external AI reasoning dependency:** Core reasoning and inference must be performed by ZYRQUEN's native system, not delegated to external AI APIs.
3. **Evidence before claims:** Distinguish source inspection, unit tests, runtime checks, model inference, capability evaluation, and release-gate results. A passing software test is not proof of general reasoning capability.
4. **Immutable lineage:** Preserve V10 and V11 datasets, checkpoints, reports, manifests, and registry records as read-only baselines once formally closed.
5. **Independent versioning:** V12 must use its own dataset, checkpoint, evaluation, and registry namespaces. No V10/V11 artifact may be silently overwritten or reused as V12 initialization.
6. **Fail-closed governance:** Training, inference campaigns, promotion, activation, deployment, and cost-incurring compute require their own explicit authorization and applicable approval gates.

## 3. V12 Entry Gate — Conditions Before Implementation

V12 implementation must not begin until all of the following are reviewed and explicitly approved:

- V11 has a formally recorded terminal outcome (CLOSED_PASS, CLOSED_FAIL, or CLOSED_BLOCKED) with report integrity and provenance documented.
- V11 source, dataset, runtime, and evaluation evidence are separated; unresolved blockers and limitations are listed.
- A capability-by-capability gap analysis compares V11 results against its predeclared thresholds and independent evaluation evidence.
- V12 objectives are justified by measured V11 limitations rather than assumed capability gains.
- Resource feasibility is benchmarked on the intended target environment; parameter count and sequence length are not increased solely to satisfy a scale target.
- V12 data, evaluation splits, leakage controls, and independent validators are specified before any model run.
- A separate V12 implementation proposal and governance decision are reviewed and explicitly approved.

If V11 is CLOSED_FAIL or CLOSED_BLOCKED, V12 may only begin with a documented research plan that addresses the demonstrated failure or blocker. It must not treat an unresolved V11 gate as a pass.

## 4. Preliminary Research Tracks

These are candidate workstreams, not approved implementation tasks.

### Track A — Generalization and Compositional Reasoning
- Measure transfer to genuinely unseen entities, relations, task compositions, and structural depths.
- Separate memorization, lexical/template shortcuts, and compositional generalization.
- Use independent solvers and adversarial near-miss examples to validate task correctness.

### Track B — Persistent and Grounded Memory
- Define memory representation, provenance, confidence, contradiction handling, update/retraction semantics, and isolation boundaries.
- Test retrieval and belief revision under conflicting, incomplete, and stale evidence.
- Prevent unsupported memory claims and cross-context leakage.

### Track C — Planning, Learning, and Self-Verification
- Evaluate multi-step plans with explicit preconditions, dependencies, failure states, and recovery.
- Separate deterministic validators from learned model behavior.
- Require calibrated unknown/abstention behavior and evidence-linked self-checking.

### Track D — Native Architecture and Scaling Research
- Compare architecture alternatives only after V11 profiling identifies a measured bottleneck.
- Benchmark throughput, memory, stability, context length, and capability impact on representative workloads.
- Treat the long-term 1B+ parameter ambition as a research target subject to resource feasibility and demonstrated benefit, not as an immediate V12 requirement.

### Track E — Evaluation Science and Robustness
- Pre-register metrics, denominators, thresholds, confidence intervals, and stop criteria before final evaluation.
- Keep validation, unseen, and OOD evidence distinct; training-set performance is diagnostic only.
- Include reproducibility, contamination/leakage audits, robustness, calibration, and regression comparisons.

## 5. Proposed V12 Gate Structure

| Gate | Purpose | Minimum evidence | Current status |
|---|---|---|---|
| V12-G0 | V11 closure and evidence review | Signed-off V11 terminal record, hashes, provenance, limitations | NOT STARTED |
| V12-G1 | Requirements and capability gap analysis | Measured V11 results mapped to prioritized V12 objectives | NOT STARTED |
| V12-G2 | Architecture and resource feasibility | Reproducible benchmarks and justified design decision | NOT STARTED |
| V12-G3 | Data and evaluation readiness | Versioned schemas, four-way isolation where applicable, independent validators, leakage report | NOT STARTED |
| V12-G4 | Implementation readiness review | Source audit, tests, resource envelope, safety and recovery design | NOT STARTED |
| V12-G5 | Separate execution authorization | Explicit approval for a bounded run with cost/resource limits | NOT AUTHORIZED |

Passing a gate requires its own evidence. No gate is passed by virtue of this roadmap being committed.

## 6. Version Isolation and Artifact Namespaces

Proposed namespace conventions, subject to later review:

- Dataset: data/zyrquen_v12/
- Checkpoints: checkpoints/zyrquen_v12/
- Evaluation: eval/zyrquen_v12/
- Reports/manifests: versioned V12 schemas with content hashes and generator/evaluator provenance
- Registry: a distinct V12 native version lineage with V11 retained as an immutable comparison baseline

These paths are proposals only; do not create directories or artifacts as part of this planning document.

## 7. Explicit Non-Authorization

This roadmap does not authorize:

- V11 or V12 training, inference campaigns, or evaluation runs;
- model initialization, checkpoint creation, promotion, activation, rollback, or deployment;
- changes to V10/V11 source, datasets, checkpoints, reports, or registry records;
- paid cloud resources or other cost-incurring actions;
- changes to the default branch or merging this branch.

V11 readiness remediation remains the active workstream. V12 planning must not delay, bypass, or weaken any V11 gate.

## 8. Open Decisions for a Future V12 Proposal

- Which V11 capability gaps are sufficiently evidenced to justify V12 work?
- Which capabilities should be expanded, and which new capabilities are measurable and testable?
- What memory and learning mechanisms can be validated without relying on external AI services?
- Which architecture changes provide measurable benefit under a verified resource envelope?
- What dataset scale and task diversity are justified by measured tokenization and compute benchmarks?
- What exact release thresholds and uncertainty bounds should be pre-registered?

No answers are assumed in this preliminary roadmap.

## 9. Truthfulness Record

### KNOWN
- V11 readiness remediation has been planned, but its work packages have not yet been executed.
- The V11 planning branch contains a governance transition record and a readiness remediation plan.
- The V10 evaluation outcome recorded in project context is FAIL; this roadmap does not alter it.

### NOT ESTABLISHED
- V11 training readiness, V11 model capability, or V11 release status.
- Any V12 architecture, parameter count, dataset size, performance target, or execution budget.
- Any claim that ZYRQUEN has achieved AGI/NGI.

### NEXT AUTHORIZED PLANNING STEP
After V11 reaches a documented terminal outcome, prepare a V12 requirements and capability-gap proposal using the verified V11 evidence. Obtain a separate explicit decision before implementation.
