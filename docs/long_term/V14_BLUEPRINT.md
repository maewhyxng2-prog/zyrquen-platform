# ZYRQUEN V14 Blueprint — Autonomous Planning & Multi-Step Execution

- **Document ID:** `ZYRQUEN-LT-V14`
- **Status:** **`LONG-TERM BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION`**
- **Predecessor Gate:** **ZYRQUEN V13 Final Gate = `PASS`**
- **Strategy:** Native-Only (`Random Initialization`, Zero Pretrained Weights, Zero External AI APIs, Zero Distillation)

---

## 1. Executive Summary
ZYRQUEN V14 extends V13's deep reasoning capabilities into **autonomous multi-step planning, hierarchical task decomposition, closed-loop plan execution, and deterministic failure recovery**. Planning outputs are verified against state-transition simulators rather than superficial text fluency.

## 2. Strategic Objective
Enable native plan synthesis across dynamic dependencies, resource limits, preconditions, and environmental feedback—while automatically detecting impossible goals and safety boundary violations before execution.

## 3. Capability Specification
- **CAP-V14-01 (`hierarchical_plan_decomposition`):** Breaking complex goals into dependency-valid sub-plans (`subplan_validity_rate`).
- **CAP-V14-02 (`closed_loop_replanning`):** Adapting remaining action sequences when simulated tool/step states diverge or fail (`replan_recovery_rate`).
- **CAP-V14-03 (`resource_and_precondition_awareness`):** Respecting explicit budgets, permissions, and temporal ordering constraints (`constraint_violation_rate`).
- **CAP-V14-04 (`unachievable_goal_rejection`):** Identifying cycles, missing prerequisites, and Tier-3 prohibited actions (`impossible_and_safety_reject_f1`).
- *(Numeric acceptance thresholds remain `TBD` pending V13 verified baselines.)*

## 4. Architecture Proposal
- Built atop V13's verified native decoder core with structured action/state-transition schema framing (`Plan -> Precondition Check -> Action Proposal -> Simulator/Env Observation -> Replan/Verify`).
- Planning execution connects exclusively through `CentralWorkflowOrchestrator` action interfaces, keeping deterministic precondition and safety checks outside learned weights.

## 5. Model Requirements
- **Provisional Scaling Options (NOT Fixed):** Evaluate whether V13's verified parameter tier suffices or requires context/capacity expansion (`TBD` after V13 runtime benchmarks).
- Must support structured action-trace sequences with exact state variable bindings (`<slot_i>` / typed action IDs) without truncation leakage.

## 6. Training Strategy
- Random initialization (or approved V13 lineage) using verifier-validated trajectory data: valid plans, near-miss invalid plans, cycle traps, and dynamic mid-execution failure recovery traces.
- Step budgets and training schedules remain **`TBD`** until V13 hardware throughput benchmarks exist.

## 7. Dataset Requirements
- 4-split architecture (`train`, `validation`, `unseen`, `ood`) featuring deterministic state-machine simulators, DAG planners, and execution error logs.
- `ood` evaluates longer horizon depths, unseen action inventories, and multi-failure recovery cascades.
- Strict anti-leakage (`EL`, `TL`, `SL`, `DL`) ensures unseen goal graphs never overlap training topologies.

## 8. Evaluation and Benchmark Strategy
- Exact simulator verification on every predicted plan: topological validity, precondition satisfaction, final goal state reached, and zero unauthorized steps.
- Measure both open-loop initial plans and closed-loop replanning efficiency separately from workflow scaffolding logic.

## 9. Capability Preservation
- Full regression sweep covering V10–V13 reasoning, constraint satisfaction, and SE baseline checks; `zero_regression = True` mandatory.

## 10. Native Software Integration
- Maps directly into `apps/core/workflow/` orchestrator handlers, `planning` contract/enforcement validators (`Phases 11–20` preserved unmodified), and `ModelRegistry`.

## 11. Resource and Scaling Requirements
- Requires dry-run CPU/memory benchmarking of multi-step rollout latency and simulator overhead before approving any V14 experiment runs.
- Enforces `WorkflowResourceGuard` budgets and zero unapproved paid compute.

## 12. Security and Governance
- Tier-2 approval required for all high-impact plan actions; Tier-3 actions (paid compute, checkpoint deletion, unapproved git/deploy) remain hard-blocked regardless of model output.
- Ordinary deterministic graph/simulator libraries kept distinct from banned external AI engines.

## 13. Integration Contracts
- Preserves tokenizer/SFT contracts, checkpoint SHA-256 pinning, and strict `EvaluationEngine` report schemas (`NOT RUN`/`BLOCKED` honest semantics).

## 14. Test Strategy
- Unit and integration tests for cycle rejection, safety-policy refusal, closed-loop recovery under injected tool failures, and PyTorch CPU runtime parity.

## 15. Release Gate
- Requires V13 Gate `PASS`, deterministic simulator pass rates meeting locked post-V13 thresholds across all 4 splits, `zero_regression=True` vs V10–V13, and Tier-2 admin signoff.

## 16. Dependencies on Previous Versions
- Depends directly on V13 constraint/deductive reasoning and V12 planning & SE foundations. Blocked until V10, V11, V12, and V13 pass sequentially.

## 17. Risks and Mitigations
- *Risk (`R-V14-01`):* Endless replanning loops on unsolvable tasks -> *Mitigation:* Hard step/retry caps and mandatory `impossible` detection training.
- *Risk (`R-V14-02`):* Planner attempting policy-restricted actions -> *Mitigation:* Deterministic workflow permission gate outside model control.

## 18. Assumptions
- Deterministic task simulators can cover multi-step tool/workflow failure modes at manageable CPU cost.

## 19. Open Decisions
- **OD-V14-01:** Maximum closed-loop replanning depth permitted per evaluation episode before failing with timeout/budget exceeded.

## 20. NOT VERIFIED / NOT IMPLEMENTED Declaration
- **Status:** **`NOT IMPLEMENTED / NOT RUN / NOT VERIFIED`**
- No V14 planning weights, simulators, datasets, or execution metrics exist.
