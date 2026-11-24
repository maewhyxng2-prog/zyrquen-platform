# ZYRQUEN Ω∞ — v9 Experiment Closure Report

- **Document ID:** `ZYRQUEN-V9-EXPERIMENT-CLOSURE`
- **Evaluation date:** 2026-11-24
- **Candidate:** `arm_d` — ZyrquenSlotReasoner (4-layer encoder / 2-layer decoder Slot-Transformer + Pointer)
- **Status:** **`CLOSED_FAIL`** — runtime experiment completed; capability acceptance criteria not met.
- **Decision:** Preserve the observed results as a failed experimental baseline. Do not promote this candidate as a capable or released model. v10 may proceed with controlled preparation, but its runtime gate remains governed by `docs/v10/V10_CLOSURE_STATUS.md`.

> **Evidence provenance:** Runtime output and the detailed Executive Summary were supplied by the project owner from the Colab run. The underlying `report.json`, `report.md`, checkpoint, and dataset are not stored in this repository. Their hashes therefore have not been independently verified from GitHub. This document records the supplied evidence; it does not claim an independent rerun.

## 1. Runtime and dataset evidence

| Item | Observed result | Interpretation |
|---|---:|---|
| Dataset leakage/integrity audit | 13/13 checks PASS | Dataset gates passed; this is not model capability evidence. |
| Readiness run | PASS; 4/4 tiny samples overfit; checkpoint round-trip PASS | Training path and checkpoint serialization worked on the readiness sample only. |
| Candidate parameters | 1,286,785 | Within the 5,000,000 parameter cap. |
| Training | 960-step run completed on CPU; best checkpoint restored from step 480 | Runtime training completed; later validation loss worsened. |
| Best validation loss | 1.9762 at step 480 | Best observed checkpoint in this run. |
| Final validation loss | 2.4754 at step 960 | Worsening after the best step is consistent with overfitting. |
| Evaluator process | Report written; StopTriggers=0 | A completed evaluator process and zero stop triggers do not imply acceptance PASS. |

## 2. Free-generation and capability results

| Split | Free-generation exact match | Unseen entity copy | Unseen entity reasoning | Multi-hop 2–3 | Multi-hop 4+ |
|---|---:|---:|---:|---:|---:|
| val_unseen (n=120) | 30.8% (37/120) | 29.5% | 28.3% | 28.4% | N/A |
| test_unseen (n=120) | 29.2% (35/120) | 27.7% | 28.3% | 25.7% | N/A |
| val_ood (n=120) | 2.5% (3/120) | 0.0% | 5.7% | 0.0% | 4.3% |
| test_ood (n=120) | 9.2% (11/120) | 2.2% | 15.1% | 0.0% | 7.2% |

Overall free-generation exact match was 30.8% on val_unseen, 29.2% on test_unseen, 2.5% on val_ood, and 9.2% on test_ood. The large OOD degradation is a major generalization failure.

## 3. Diagnostic probe results

| Probe / diagnostic | Observed result | Status |
|---|---:|---|
| Alpha-renaming invariance | 0.0 percentage-point maximum difference | PASS |
| Premise permutation invariance | 0.0 percentage-point drop | PASS |
| Exposure-bias gap | 0.0 | PASS |
| Parameter budget | 1,286,785 / 5,000,000 | PASS |
| Depth extrapolation | 25.7% at 2–3 hops; 7.2% at 4–5 hops; 18.43 pp drop | FAIL |
| Distractor sensitivity | 100.0% with 0 distractors; 0.0% with 3–4 distractors | FAIL |
| Override vs conflict | 100.0% override; 0.0% conflict; 0.0% both-correct | FAIL |
| Pointer gate discipline | Copy mean p_gen 0.6821 (target <=0.45); reasoning 0.8351 (target >=0.60) | FAIL |
| Generation stability | Premature EOS 0.125 (target <=0.02); overall repetition 0.079 (target <=0.05); planning FG repetition 0.933 | FAIL |

Additional observed failure modes:
- `knowledge_acquisition`: 0.0% across all four splits.
- `planning_decomposition`: 6.7% on unseen and 0.0% on OOD, with premature EOS and repetition collapse.
- `verdict_majority_collapse_share`: 0.68 on unseen splits; model over-predicts `false`.
- OOD syntax and distractor clauses frequently lead to `unknown` or structural/relation-keyword copying rather than resolving the queried relation.

## 4. Closure decision

**v9 is CLOSED_FAIL, not PASS.** The experiment is complete and its negative findings are retained. Symbolic invariance and compute efficiency are demonstrated on the supplied benchmark, but generalization, unseen-entity extraction, deeper reasoning, distractor robustness, conflict detection, pointer-gate calibration, and planning stability do not meet the stated acceptance targets.

No claim of general intelligence, broad real-world reasoning, or production readiness is supported by this benchmark.

## 5. Evidence-driven v10 priorities

These are evaluation priorities, not authorization to change architecture or start training:

1. **Planning and decoding stability:** inspect target construction, EOS placement, loss alignment, and decoding behavior for premature termination and repetition.
2. **OOD structure and distractor robustness:** test unseen syntax/operators and controlled 0–4 distractor clauses with independent held-out templates.
3. **Pointer/copy and entity binding:** calibrate copy-vs-generation behavior on extraction tasks and verify unseen-entity accuracy separately from reasoning.
4. **Conflict vs override discrimination:** balance paired minimal cases and report both classes independently; prevent majority-verdict collapse.
5. **Depth generalization:** report 2–3, 4–5, and longer-hop results separately; do not merge them into one aggregate score.

Every v10 improvement must be demonstrated against a frozen v9 report and a separately generated, leakage-audited evaluation set. A v10 runtime release still requires the V10-D gate in `docs/v10/V10_CLOSURE_STATUS.md`; v11 remains locked until that gate passes.

## 6. Frozen scope and non-actions

- v7 and v8 remain frozen and untouched.
- This report does not alter model source, training code, dataset generation, checkpoints, registry state, or product Phase 11–20 files.
- No additional v9 training, v10 training, model promotion, deployment, or paid compute is authorized by this report.
- The v9 Colab artifacts remain external to this Git repository unless separately archived through an approved process.
