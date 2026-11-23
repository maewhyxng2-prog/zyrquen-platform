# ZYRQUEN P11 Training Plan

**Document ID:** ZYRQUEN-P11-TP-001  
**Version:** 1.0  
**Status:** Proposed — Not Training Authorization  
**Applies to:** Native-only ZYRQUEN P11 development  
**Baseline prerequisite:** Random-initialization baseline artifact must be completed, inspected, and hash-recorded before P11 code remediation or any training gate review.

---

## 1. Purpose and scope

This plan defines an auditable path from pre-training readiness through native pre-training, supervised fine-tuning (SFT), and evaluation for the P11 workstream. It specifies conditional hardware allocation, hyperparameter optimization (HPO) targets, validation gates, experiment controls, and required evidence.

This document is a planning artifact only. It does **not** authorize a training run, CPU benchmark, GPU allocation, cloud reservation, paid compute, pilot, curriculum run, checkpoint promotion, registry activation, inference service, or deployment. Each execution phase requires its own explicit human approval after its entry gate is reviewed. A passing preflight is not training authorization.

## 2. Mandatory engineering and governance constraints

1. **Native-only initialization:** initialize all model parameters from the ZYRQUEN implementation's approved random initialization. Do not load, adapt, merge, distill, or transfer external pretrained weights.
2. **No external model runtime:** no external AI model/API may perform ZYRQUEN reasoning, inference, planning, training decisions, or evaluation scoring.
3. **Data provenance:** every dataset, tokenizer, configuration, source revision, and checkpoint must have a recorded SHA-256 digest and provenance record.
4. **Immutable history:** V7–V10 artifacts and reports remain unchanged. P11 outputs use versioned, experiment-specific paths.
5. **Fail closed:** missing evidence, checksum mismatch, leakage failure, resource breach, or configuration ambiguity blocks the phase. Never convert FAIL to PASS by weakening thresholds.
6. **Human-controlled transitions:** no import-time training, automatic job launch, automatic checkpoint promotion, or implicit gate transition.
7. **Reproducibility:** record source commit, environment, dependency lock, seed, deterministic settings, hardware inventory, and exact command for every run.
8. **Cost and access control:** no GPU/cloud resource is allocated until an authorized account owner approves the provider, region, quota, budget, and time window.

## 3. Phase and gate model

| Phase | Objective | Required evidence | Exit decision |
|---|---|---|---|
| G0 — Baseline | Establish random-initialization floor | Baseline JSON, evaluator version, dataset/tokenizer hashes, output SHA-256 | Accept or block |
| G1 — Remediation | Complete B-05/B-06/B-07 and pipeline controls | Unit tests, static audit, four-split checks, resume parity tests, code review | Remediation PASS/FAIL |
| G2 — Preflight | Verify local dataset, tokenizer, environment and leakage | Preflight JSON, manifest and tokenizer hashes, leakage report | Ready or BLOCKED |
| G3 — Resource benchmark | Measure actual resource envelope | Approved microbenchmark report, RSS, seconds/step, checkpoint round-trip | Resource PASS/FAIL |
| G4 — Native pre-training pilot | Validate the approved training path on a bounded run | Step logs, loss curves, checkpoint manifest, evaluation report | Pilot PASS/FAIL |
| G5 — SFT | Adapt native model on approved supervised examples | SFT lineage, data audit, training telemetry, held-out evaluation | SFT PASS/FAIL |
| G6 — Capability validation | Test generalization and safety of claims | Split-wise results, baseline comparison, error analysis, signed report | Capability decision |
| G7 — Promotion review | Consider a candidate checkpoint for a later stage | Complete provenance bundle and independent review | Separate approval required |

No phase inherits authorization from a prior phase.

## 4. Hardware allocation strategy

### 4.1 Current P11-B baseline envelope

The initial P11-B plan is resource-constrained and must be treated as **CPU-first**. The reported AI Studio host had no GPU, 4 logical CPUs, and approximately 12 GiB RAM; the reported environment lacked the required Python training/test packages and did not execute training. Those measurements are historical environment observations, not a validated production capacity profile.

The first executable benchmark, if separately approved, must use the local/controlled CPU environment and enforce:
- CPU threads: maximum 2;
- soft RSS target: below 3.0 GiB;
- hard RSS stop: 3.5 GiB;
- minimum free-disk reserve: 2.0 GiB;
- bounded 10–20-step measurement before any pilot;
- actual weights_only=True checkpoint save/reload verification;
- no registry writes and no checkpoint promotion.

The benchmark must report measured values. Estimates must be labelled estimates and cannot satisfy a measured gate.

### 4.2 Conditional GPU-cluster tiers

GPU clusters are a future capacity option, not a current allocation or a prerequisite for the CPU-first P11 gate. The following tiers are planning envelopes only; exact GPU type, count, memory, interconnect, provider, region, and cost must be selected and approved after measured workload profiling.

| Tier | Intended use | Allocation policy | Required controls |
|---|---|---|---|
| CPU validation | Dataset checks, unit tests, small smoke tests, initial benchmark | Local or approved CPU runner; 2-thread cap for P11-B constrained runs | RSS/disk guard, deterministic seed, no background training |
| Single-GPU development | Optional later profiling and bounded native experiments | One isolated GPU; no reservation before approval | Record GPU model/VRAM/driver, power and utilization telemetry, pinned software environment |
| Multi-GPU cluster | Only if measured single-device throughput or memory proves inadequate | Smallest viable node count; scale only after single-GPU profiling | Explicit distributed strategy, rank-level logs, synchronized checkpoint protocol, communication metrics |
| Multi-node cluster | Not in initial P11-B scope | Requires a separate architecture and cost review | Network topology, failure recovery, rendezvous security, per-node provenance, aggregate resource budget |

**Allocation sequence**
1. Measure the actual model and batch memory footprint on the approved CPU/single-device environment.
2. Prefer the smallest single device that satisfies the measured memory and throughput requirement.
3. Consider data parallelism only after a correct single-device training path and checkpoint recovery are demonstrated.
4. Consider multi-node execution only when a documented bottleneck justifies it and distributed determinism/recovery tests pass.
5. Set a hard runtime and cost ceiling before any cloud job is submitted. Stop automatically on the approved ceiling; require human review to extend it.

No GPU cluster, cloud compute, or paid reservation is authorized by this document.

### 4.3 Capacity accounting

Each experiment must include CPU model, physical/logical core count, thread cap and RAM; GPU model/count, VRAM, driver/runtime versions, interconnect and utilization if applicable; storage type and free space before/after; checkpoint size and I/O duration; peak RSS and GPU memory peak; wall-clock duration, seconds/step, samples/second and tokens/second; estimated and actual cost with currency and billing interval if applicable; and exact stop reason.

## 5. Model and data configuration

The initial P11 target is the native ZYRQUEN architecture and local tokenizer. The configuration must be read from the checked-out source and the experiment manifest; do not copy a parameter count or architecture from an earlier planning document without reconciling it against the actual instantiated model.

The current proposed Tier-0 configuration is a candidate, not a frozen training configuration:

| Parameter | Proposed candidate | Status |
|---|---:|---|
| Layers | 4 | Pending config audit |
| Attention heads | 4 | Pending config audit |
| Model width | 256 | Pending config audit |
| Feed-forward width | 704 | Pending config audit |
| Maximum sequence length | 256 | Pending tokenizer/data audit |
| Vocabulary | 1,272 | Must match tokenizer file |
| Embeddings | Tied | Pending implementation check |
| Dropout | 0.0 or 0.05 | Open decision; do not guess |
| Initialization | Native random initialization, seed recorded | Mandatory |
| Precision | CPU float32 for initial constrained validation | Proposed |
| Parameter count | Compute from actual instantiated model | Must be recorded; resolve documentation discrepancy |

The dataset contract includes the four named splits: train, validation, unseen, and ood. The manifest must declare all splits and their file hashes. The tokenizer must be local, schema-compatible, and validated for the required atomic slot tokens. External tokenizer downloads are prohibited.

## 6. Hyperparameter optimization targets

HPO is a controlled experiment, not an unconstrained search. Do not start HPO until G0–G3 pass and a separate HPO authorization is recorded.

### 6.1 Initial candidate values

| Hyperparameter | Candidate | Search/decision policy |
|---|---:|---|
| Optimizer | AdamW | Fixed for initial pilot unless evidence requires review |
| Learning rate | 3e-4 | Small bounded sweep only after pilot path is valid |
| Betas | (0.9, 0.95) | Fixed initial candidate |
| Weight decay | 0.1 for matrix weights; 0.0 for 1-D/norm parameters | Verify parameter grouping in tests |
| Gradient clipping | 1.0 | Record pre/post clipping norm |
| Warmup | 100 steps | Reconcile with total-step schedule |
| Minimum LR | 3e-5 | Candidate; validate schedule endpoint |
| Batch size | 4 | Candidate |
| Gradient accumulation | 1 or 2 | Open decision; compare effective batch and memory |
| Sequence/block length | 256 | Must not exceed tokenizer/data contract |
| Seed | 1337 | Record all RNG states |
| Pilot length | Up to 500 steps | Separate explicit approval required |
| Evaluation/checkpoint interval | 250 steps | Candidate for bounded pilot |

### 6.2 Open decisions

Resolve and record these before freezing the experiment config: total-step schedule (the previous 10,000-step schedule is not automatically appropriate for a 500-step pilot); gradient accumulation (effective batch 4 versus 8); dropout (0.0 versus 0.05); actual parameter count and optimizer-state footprint; stage sampling weights and curriculum boundaries; and stopping thresholds and baseline comparison semantics.

### 6.3 HPO method and objective

Use a staged, budget-limited procedure:
1. Establish a reproducible baseline and a fixed validation protocol.
2. Change one high-impact dimension at a time for initial screening.
3. Use a small, predeclared search space and fixed trial budget; do not expand it after seeing results without a documented amendment.
4. Compare trials on the same validation examples, tokenization, evaluation code, and compute budget.
5. Select by validation loss subject to capability, generalization, stability, and resource constraints—not training loss alone.
6. Keep unseen and OOD sets out of HPO selection. Use them only for locked evaluation after configuration selection.

Primary optimization targets are finite/stable loss and gradients; validation-loss improvement against the random-initialization baseline; no degradation in unseen/OOD generalization; reliable EOS behavior and valid output formatting; deterministic replay and checkpoint-resume parity; and resource use within the approved envelope.

Any proposed numeric threshold must be versioned in the experiment protocol before a run. Do not retrofit thresholds after observing results.

## 7. Validation workflow: pre-training through fine-tuning

### 7.1 Pre-training readiness

Required checks:
- verify required environment variables and local paths;
- verify dataset manifest schema, four split declarations, file existence, and SHA-256 integrity;
- verify tokenizer file SHA-256, schema, vocabulary, and atomic slot support;
- run strict leakage audit, including split disjointness, entity/template/structural checks, and PII scan;
- verify model config and parameter count from the instantiated native model;
- verify Native-Only dependency and artifact policy;
- verify the baseline JSON and its evaluator provenance;
- confirm no pre-existing job, checkpoint, or registry state will be overwritten.

Output: immutable preflight report with PASS or BLOCKED, hashes, timestamp, source commit, and exact command. Preflight must not initialize training, update weights, create checkpoints, or mutate the registry.

### 7.2 Native pre-training

Pre-training may begin only after explicit approval for the exact experiment ID, code commit, dataset/tokenizer hashes, config hash, resource envelope, step budget, and output directory.

During execution:
- initialize weights from scratch using the approved native initializer;
- log seed and all relevant RNG states;
- record per-step loss, learning rate, gradient norm, throughput, RSS and device memory;
- abort before optimizer update on NaN/Inf loss or gradient norm;
- stop on hard RAM, disk, runtime, or cost limits;
- checkpoint atomically with SHA-256 and a provenance manifest;
- verify checkpoint loading with safe weights_only=True behavior;
- never fall back to unsafe pickle loading.

Pilot validation should separately report pipeline correctness and capability outcomes. A successful training loop is not evidence of general intelligence or capability readiness.

### 7.3 Supervised fine-tuning (SFT)

SFT is a later, separately approved phase. It must use only the approved native checkpoint produced by the P11 lineage and an independently audited, versioned SFT dataset.

Before SFT:
- verify parent checkpoint SHA-256 and provenance;
- verify dataset, tokenizer, and model-config hashes;
- verify no external/pretrained weights entered the lineage;
- audit target construction, slot binding, stage tags, deduplication, and train/validation separation;
- lock validation examples and evaluation thresholds.

During SFT:
- preserve the parent checkpoint unchanged;
- write child checkpoints to a new experiment directory;
- record optimizer/scheduler state and Python/NumPy/PyTorch RNG states as applicable;
- use stage-aware sampling only after its implementation and statistical tests pass;
- log stage-wise sampling frequencies and loss metrics;
- apply the same resource and non-finite-value stop conditions as pre-training.

After SFT, compare the child checkpoint against both its parent and the random baseline using the same locked evaluation protocol. SFT may not overwrite or silently promote the parent artifact.

### 7.4 Evaluation and generalization

Report metrics separately for train diagnostic (diagnostic only; never a promotion metric), validation (for model selection under the locked protocol), unseen (generalization), and OOD (distribution-shift robustness).

Include exact-match and task-appropriate capability metrics, per-category sample counts, confidence intervals where meaningful, privacy-safe error analysis, and a comparison against the random-initialization baseline. Empty, skipped, or unexecuted evaluation categories must be labelled NOT_RUN, not zero and not PASS.

## 8. B-05/B-06/B-07 remediation acceptance

| Work item | Required acceptance evidence |
|---|---|
| B-05 — dataset/orchestrator | All four splits validated; manifest/content hashes checked; leakage audit required before training; missing or inconsistent split blocks preparation |
| B-06 — dynamic slots and stage sampler | Prompt/target slot mapping is consistent and reversible; ephemeral mapping is seed-reproducible; capacity overflow rejected; stage weights validated; sampler distribution tested statistically and deterministically |
| B-07 — checkpoint resume parity | Resume rejects dataset-content, tokenizer, or model-config mismatch; safe checkpoint loading only; RNG/sampler state restored; interrupted/resumed behavior tested against uninterrupted control |

Tests must be independently runnable and must not start a training job. A regression test that asserts a not-yet-implemented API exists may remain an expected failure during remediation, but it must be clearly reported and must not be counted as a passing gate.

## 9. Checkpoint, artifact, and audit requirements

Use a unique immutable experiment directory, for example:

artifacts/experiments/P11-EXP-<ID>/

Never reuse an experiment ID or overwrite prior evidence. Each run must preserve the experiment plan and approval record; source commit SHA and changed-file list; environment/dependency inventory; dataset manifest, split-file hashes, tokenizer hash; model-config hash and actual parameter count; seed and RNG-state metadata; exact command, start/end timestamps, exit code and stop reason; raw metrics/logs and summarized evaluation; resource telemetry; checkpoint SHA-256 manifest and safe-load audit; leakage report and test/static-audit outputs; and reviewer decision with unresolved deviations.

Use append-only or immutable storage where available. Hash the final evidence bundle and verify it before review. A manifest hash proves integrity of the listed files, not correctness of the experiment or trustworthiness of model provenance.

## 10. Stop conditions and incident handling

Immediately block or abort the current phase on missing/invalid manifest, tokenizer, environment variable, or split; dataset, tokenizer, model-config, or checkpoint hash mismatch; leakage, PII, or Native-Only policy failure; NaN/Inf loss or gradient norm; hard RSS/disk/runtime/cost limit reached; checkpoint safe-load or resume-parity failure; unexpected external model dependency, external weight, or remote inference call; or unapproved code/config/data change during a run.

Preserve logs and the last verified checkpoint. Record the stop reason and hashes. Do not automatically resume, alter thresholds, or promote an alternate checkpoint; require human review.

## 11. Current authorization matrix

| Activity | Current status |
|---|---|
| Documentation and read-only audits | Permitted within existing scope |
| B-05/B-06/B-07 code remediation | Blocked until the required baseline artifact is verified, per current project sequence |
| Preflight execution | Read-only; does not authorize training |
| CPU microbenchmark | Not authorized until separately approved |
| GPU cluster allocation / cloud compute | Not authorized |
| P11 native pre-training pilot (500 steps) | Not authorized |
| SFT | Not authorized |
| 10,000-step curriculum | Not authorized |
| Checkpoint promotion / production activation / deployment | Not authorized |

## 12. Required review checklist

- [ ] Baseline JSON exists, parses, and meets the evaluator-defined baseline contract.
- [ ] Baseline SHA-256 and evaluator/source provenance are recorded.
- [ ] B-05/B-06/B-07 tests and audits have explicit results.
- [ ] Dataset, tokenizer, model config, and source commit hashes match the approval record.
- [ ] Native-only initialization and artifact lineage are demonstrated.
- [ ] Validation splits and thresholds are locked before execution.
- [ ] Hardware, runtime, storage, and cost ceilings are explicit.
- [ ] Checkpoint safe-load, integrity, and resume-parity tests pass.
- [ ] Stop conditions and rollback procedure are tested/documented.
- [ ] The exact phase has a separate human approval.

**Final rule:** P11 is not Training-Gate PASS until all required evidence is verified. This plan itself is not evidence of execution and does not grant permission to train.
