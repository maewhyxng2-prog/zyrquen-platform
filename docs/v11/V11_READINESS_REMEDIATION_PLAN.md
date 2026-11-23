# ZYRQUEN V11 — Readiness Remediation Plan

- **Document ID:** `V11-ENG-REMED-01`
- **Status:** `APPROVED FOR READINESS PLANNING — IMPLEMENTATION TASKS NOT YET EXECUTED`
- **Governance basis:** `V11-GOV-DEC-01` (implementation-readiness only)
- **Baseline branch:** `docs/v11-gate-transition-v10-closed-fail`
- **Scope:** Readiness remediation only. No training, inference campaign, evaluation run, model promotion, registry activation, deployment, paid cloud use, or merge to `main`.

## 1. Executive decision

V11 is approved to enter implementation-readiness work, but it is **not technically ready for training**. The source inspection found concrete contract mismatches between the V11 blueprint and the existing native pipeline. Work must proceed in dependency order, with each gate independently evidenced. A documentation change or passing unit test alone does not establish model capability or authorize training.

V10 remains `FAIL`. No V10 report, source, checkpoint, dataset, or evidence may be altered to obtain a passing status. V11 must use independent versioned artifacts and Native-Only random initialization.

## 2. Verified source findings at planning time

The following findings were observed in the inspected branch source:

1. `apps/core/native/dataset.py` defines the existing split set as `train`, `validation`, and `test`; its preparation path writes files for that split set.
2. The same preparation path emits text records with a `text` field, while `load_sft_split()` expects `input` and `target` fields.
3. `apps/core/native/train.py::TrainConfig` defaults include `batch_size=16`, `block_size=128`, and `max_steps=1000`.
4. The inspected `train_sft()` loop uses `cfg.max_steps` as its loop bound and supports checkpoint resume. A caller-level segment contract and global-step accounting still need explicit design and tests.
5. V11 documentation specifies four evaluation/data partitions: `train`, `validation`, `unseen`, and `ood`, with V10 `test` compatibility/archive requirements.
6. V11 documentation describes a Tier-0 batch-size ceiling of 4 and a 256-token sequence target; these do not match the existing training defaults.

These are source-level observations, not runtime test results. No training or evaluation was run for this audit.

## 3. Work packages and acceptance criteria

### WP-0 — Governance and document consistency

**Objective:** Make the V11 documentation accurately reflect the approved transition without silently changing technical gates.

Tasks:
- Update V11 document status text that says V11 is locked until V10 Gate PASS, replacing it only where necessary with the approved condition: V10 may be formally closed as `CLOSED_FAIL` with verified evidence, and V11 may proceed to readiness work only.
- Preserve any independent V10 runtime requirements that remain necessary for V10 closure; do not rewrite them as passed.
- Add a consistent scope statement to the V11 Master Plan, Training Plan, Dataset Specification, and Evaluation Plan.
- Keep all documents explicit that readiness approval is not training authorization.

Acceptance:
- No contradictory “V10 must PASS before any V11 readiness work” language remains where it conflicts with the approved decision.
- No document implies V10 passed, V11 is training-ready, or training is authorized.
- Proposal and decision records remain unchanged and auditable.
- A documentation diff review shows only intended V11 documentation changes.

### WP-1 — Dataset contract and split adapter

**Objective:** Support V11's four isolated splits without silently breaking existing V10 consumers.

Tasks:
- Define a versioned V11 dataset contract and adapter boundary; do not globally replace V10's canonical split contract.
- Define exact semantics for `train`, `validation`, `unseen`, and `ood`; define whether `test` is retained as an archive/compatibility artifact and how it is excluded from V11 scoring.
- Make the manifest enumerate all files, counts, per-file SHA-256, content hash, schema/version, generator provenance, and declared source/license metadata.
- Define record schemas explicitly for both text-pretraining and SFT data. Do not make one loader ambiguously accept both.
- Validate split identity, path containment, symlink rejection, schema, duplicate IDs, empty splits, cross-split duplicate/content leakage, entity/template disjointness, and deterministic generation.
- Ensure evaluation loaders cannot accidentally score `train` as a release split.
- Add compatibility tests proving existing V10 `train`/`validation`/`test` consumers retain their expected behavior.

Acceptance:
- V11 adapter reads exactly the declared four splits and validates their hashes before use.
- Train/validation/unseen/ood split membership and isolation checks are deterministic and reproducible.
- SFT and text record schemas are separately validated with clear failures on mismatch.
- V10 compatibility tests pass without changing V10 evaluation meaning.
- Negative tests reject missing files, tampered hashes, symlinks, traversal paths, duplicate IDs, and cross-split leakage.
- No V11 dataset is declared ready until real generated artifacts and manifest checks have been inspected.

### WP-2 — Configuration and resource envelope

**Objective:** Align configuration with the approved Tier-0 envelope and prevent configuration drift from bypassing runtime limits.

Tasks:
- Define a dedicated V11 Tier-0 configuration profile rather than changing shared defaults in a way that could alter V10.
- Reconcile the documented 256-token target with model `max_seq_len`, training `block_size`, tokenizer BOS/EOS overhead, and SFT collation.
- Set batch size no greater than 4 for Tier-0; establish explicit gradient accumulation semantics.
- Enforce at most 500 optimizer steps per segment and 10,000 planned global steps across the approved curriculum; reject inconsistent combinations.
- Validate CPU thread cap, RAM hard limit, disk reserve, checkpoint retention, wall-clock budget, and stop conditions before any future execution.
- Keep all cost-incurring cloud paths disabled unless separately authorized.

Acceptance:
- Invalid or over-budget configs fail before model allocation or optimizer creation.
- Effective runtime config is serialized into each future run manifest.
- Unit tests cover max batch, sequence length, per-segment steps, global-step accounting, CPU threads, RAM, disk reserve, and checkpoint retention.
- A dry configuration audit reports resource bounds without starting training or allocating a model.

### WP-3 — Segmented training, resume, and observability contracts

**Objective:** Prove the mechanics of segmented execution without launching a training campaign.

Tasks:
- Specify distinct `segment_step` and `global_step` counters and unambiguous checkpoint naming.
- Define resume behavior for model, optimizer, scheduler/LR state, RNG states, data sampler state, dataset/tokenizer fingerprints, config fingerprint, and completed segment identity.
- Ensure resuming cannot reset or exceed the global budget, repeat a completed segment silently, or skip a required segment.
- Define parameter-delta evidence using exact before/after tensor comparisons and per-tensor summaries; retain hard failure when no parameters change.
- Record finite-loss, gradient, optimizer-step, checkpoint integrity, stop reason, and resource telemetry.
- Ensure an interrupted/blocked run is not mislabeled complete or passed.

Acceptance:
- Deterministic tests simulate checkpoint save/load and resume across multiple segments using tiny synthetic fixtures only.
- Tests prove monotonic global steps, no duplicate/omitted step ranges, preserved RNG/sampler state, and hard budget enforcement.
- Parameter-change checks detect both changed and unchanged tensors and cannot be bypassed by loss reduction or an optimizer call.
- Recovery tests cover corrupted/missing checkpoints and interrupted writes.
- These tests are mechanics tests, not evidence of capability or permission to run the real V11 training plan.

### WP-4 — Capability curriculum and data-quality controls

**Objective:** Turn the six-capability blueprint into a reproducible, solver-validated dataset specification.

Tasks:
- Define task schemas, answer spaces, difficulty progression, and capability-specific invariants for all six capabilities.
- Use deterministic generators and independent exhaustive/reference solvers where applicable.
- Validate unique-answer guarantees, balanced labels, distractor construction, relation/depth constraints, and anti-shortcut controls.
- Prove entity/template disjointness across four splits and verify no answer leakage in IDs, metadata, or prompt formatting.
- Specify dataset size and token budgets against measured tokenizer output, not character-count assumptions.
- Version all generator seeds, code fingerprints, solver versions, and manifests.

Acceptance:
- Each generated example is checked by an independent validator/solver, not only by the generator's own labeling function.
- Dataset quality reports include counts, label balance, difficulty distributions, duplicate checks, leakage checks, and token-length distributions.
- Deterministic regeneration produces identical content hashes for identical inputs and versions.
- All six capabilities have explicit positive, negative, ambiguous, and edge-case tests as appropriate.
- No capability is considered demonstrated by synthetic-data correctness alone.

### WP-5 — Evaluation and release-gate implementation

**Objective:** Ensure the evaluation pipeline measures actual native model behavior and cannot produce false PASS.

Tasks:
- Specify per-capability metrics, denominators, minimum sample counts, confidence/uncertainty reporting, and thresholds before examining final V11 results.
- Evaluate `validation`, `unseen`, and `ood` separately; `train` remains diagnostic and cannot satisfy release criteria.
- Pin model/checkpoint, tokenizer, dataset, generator, evaluator, and report hashes.
- Require actual native inference for every scored prediction; record inference execution evidence.
- Preserve separate statuses for `NOT_RUN`, `BLOCKED`, `FAIL`, `ERROR`, and `PASS`; missing evidence must never become zero or PASS.
- Require independent review of report integrity and regression comparisons before any release decision.

Acceptance:
- Tests reject empty evaluation sets, missing splits, stale/mismatched hashes, missing inference evidence, absent regression comparisons, and disallowed statuses.
- Metric denominators and per-capability/per-split counts reconcile exactly.
- Thresholds are frozen and versioned before the final evaluation.
- No evaluation is run as part of this readiness plan.
- Release/promotion remains a separate decision requiring explicit authorization.

## 4. Dependency order

`WP-0 → WP-1 → WP-2 → WP-3 → WP-4 → WP-5`

Parallel work is allowed only where contracts are stable. Dataset contract decisions must precede generator integration; resource and step contracts must precede any training orchestration work; evaluation schema and thresholds must be frozen before any final model evaluation.

## 5. Required evidence bundle per work package

Each completed work package must provide:
- exact commit and changed-file list;
- source-level rationale and compatibility impact;
- tests added and exact test commands/results;
- negative-test results for relevant failure paths;
- machine-readable audit report where appropriate;
- explicit statement of what was not executed.

A work package is `PASS` only when all its acceptance criteria are evidenced. Otherwise use `PARTIAL`, `BLOCKED`, or `FAIL` with the missing evidence listed.

## 6. Non-authorized actions

This plan does not authorize:
- any real training or inference campaign;
- V10 or V11 evaluation runs;
- approval of existing `WAITING_APPROVAL` workflow rows;
- model registry promotion or activation;
- deployment or production traffic;
- paid cloud compute or other cost-incurring actions;
- modifying or merging to `main`.

Separate explicit authorization is required for any of these actions.

## 7. Immediate execution order

1. Implement WP-0 documentation consistency on this branch and review the diff.
2. Design WP-1 adapter interfaces and tests; keep V10 behavior unchanged.
3. Implement WP-2 isolated V11 config validation and resource checks.
4. Implement WP-3 mechanics tests with tiny synthetic fixtures only.
5. Complete WP-4 generator/solver/data-quality validation.
6. Complete WP-5 evaluation-contract tests and independent audit.

**Current disposition:** `READINESS PLAN RECORDED — TECHNICAL GATES NOT PASSED — TRAINING NOT AUTHORIZED`.
