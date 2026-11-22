# ZYRQUEN Ω∞ — V10–V20 Master Preparation Plan

- **Document ID:** `ZYRQUEN-V10-V20-MASTER-PLAN`
- **Scope:** ZYRQUEN V10 through V20 Complete Preparation & Cross-Version Integration
- **Mode:** `CONTROLLED PREPARATION & INTEGRATION`
- **Active Execution Status:**
  - **V10 Runtime Closure:** `BLOCKED` (`READY_FOR_PYTORCH_CPU_PREPARATION`; Blockers 02–06 remediated at unit level; Blocker 01 = `TORCH_RUNTIME_STATUS = NOT INSTALLED` pending separate approval)
  - **V11 (10,000 Steps / 6 Stages):** `BLUEPRINT ONLY — LOCKED UNTIL V10 RUNTIME CLOSURE PASS`
  - **V12 (50,000 Cumulative Steps / 6 Stages / >=100 Experiments):** `BLUEPRINT ONLY — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
  - **V13–V20 (Long-Term Progression):** `LONG-TERM BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION`
- **Strict Prohibitions Active:**
  - `training_started = false` | `inference_executed = false` | `torch_installed = false` | `datasets_or_checkpoints_created = false` | `paid_gpu_provisioned = false` | `git_pushed_or_deployed = false`
  - V7–V9 (`tools/`) and Phases 11–20 (`phases/phase11.py..phase20.py`, `docs/PHASE_11_SPEC.md..PHASE_20_SPEC.md`) remain immutable.
  - Zero Phase 21, zero V12 Stage 7, zero external AI dependencies, zero hidden external model weights.

---

## 1. Strategic Identity & Non-Negotiable Core Rules

**ZYRQUEN Ω∞** is an independent **Native General Intelligence (NGI)** and **Native Software Engineering (NSE)** research and engineering program.

1. **Native-Only Strategy (`ZyrquenModel` / Random Initialization):**
   Every model generation initializes weights natively from documented random initialization (or explicitly audited, approved native ZYRQUEN checkpoint lineage when version continuation rules are satisfied).
2. **Zero External AI Dependencies:**
   External LLM APIs, third-party model endpoints, pretrained weights (`from_pretrained`, `.safetensors`/`.gguf` from external foundation models), or external LLM distillation are strictly banned inside `apps/core/native/`, `apps/core/training/`, `apps/core/workflow/`, and datasets.
3. **Truthfulness & Anti-False-PASS:**
   Status claims are strictly classified as `VERIFIED` (Static / Unit), `RUNTIME PASS`, `BLOCKED`, `PENDING`, `NOT RUN`, or `BLUEPRINT ONLY`. Preparation completion **never** implies training readiness or completed capability across V10–V20.
4. **Separation Between Product Roadmap (`Phases 11–20`) and Model Versions (`V10–V20`):**
   - `phases/phase11.py..phase20.py` are deterministic platform/guardrail/engineering contracts (epistemic verification, tenant memory isolation, security policy, reasoning/planning enforcement).
   - `V10–V20` are native neural model generations interacting with those platform layers through versioned adapters and `CentralWorkflowOrchestrator`.

---

## 2. Central Native Workflow Engine Integration (8 Unified Groups)

ZYRQUEN enforces a **single Central Workflow Engine** (`apps/core/workflow/orchestrator.py` — `CentralWorkflowOrchestrator`). All 8 operational groups register under one scheduler/queue (`WorkflowStepQueue`), one resource guard (`WorkflowResourceGuard`), one Tier-2 HMAC-SHA256 governance gate (`WorkflowGovernance`), and one append-only SQLite audit log (`workflow_audit_logs` protected by `trg_wf_audit_no_update` and `trg_wf_audit_no_delete`):

| Group # | Canonical Workflow Group | Handler Module / Anchor | Primary Responsibilities Across V10–V20 | Approval Tier |
|---|---|---|---|---|
| **1** | **System Operations Workflow** | `apps/core/workflow/handlers/` + `apps/api/operations.py` | API/Runtime health, SQLite DB & storage checks, CPU/RAM/Disk telemetry, `torch` presence verification, daily readiness reports | Tier-1 (`Read-Only`) |
| **2** | **Data Workflow** | `apps/core/training/orchestrator.py` + `tools/gen_nagi_v10.py` + `tools/audit_leakage_v10.py` | Dataset generation/intake, schema validation, deduplication (`DL-01`), leakage gates (`EL-01..06`, `TL-01`, `SL-01`), deterministic `train`/`validation`/`unseen`/`ood` splitting, SHA-256 `manifest.json` | Tier-1 / Tier-2 on intake mutation |
| **3** | **Native Training Workflow** | `apps/core/workflow/handlers/groups.py::handle_training_execute` + `apps/core/native/train.py` + `apps/core/workflow/resource_guard.py` (`TrainingRuntimeGuard`) | CPU thread cap (`<=2`), budget caps (`params<=5M`, `seq<=256`, `batch<=4`, `steps<=500`), monotonic `experiment<=1200s` & `loop<=3600s` timeouts, `RamMonitor` (`3.0/3.5 GB`), `Disk >=2.0 GB` reserve + `<=1.0 GB` new disk, isolated run dir, `VersionedCheckpointManager` handoff | **Tier-2 Single-Use HMAC** (`training.execute`) |
| **4** | **Evaluation Workflow** | `apps/core/native/evaluation/engine.py` + `tools/eval_nagi_v10.py` + `handle_evaluation_gate` | Real-weight inference against `version_manifest.json` or `ModelRegistry`, strict `zyrquen.v10.evaluation_report.v1` contract, prompt length check (`< max_seq_len`), multi-split reporting, baseline delta & `zero_regression` check | Tier-1 eval + **Tier-2** (`model.stage` / `model.promote`) |
| **5** | **Knowledge & Memory Workflow** | `phases/phase17.py` + `docs/v11/V11_MEMORY_AND_KNOWLEDGE.md` + `docs/v12/V12_MEMORY_AND_KNOWLEDGE.md` | Tenant-isolated `MemoryStore`, provenance linking, contradiction detection, temporal belief revision (expanding natively in V15) | Tier-1 read / Governed write |
| **6** | **Autonomous Improvement Workflow** | `apps/core/workflow/autonomous_training_loop.py` | Analyzes verified deficits (`diagnose_nagi_v10.py` / `compare_nagi_v10.py`), proposes bounded Tier-2-gated experiments; **strictly forbidden** from auto-unlocking stages, skipping approvals, or auto-promoting weights | **Tier-2** per proposed run |
| **7** | **Security & Governance Workflow** | `apps/core/workflow/governance.py` + `store.py` + `apps/api/security.py` | Auth/RBAC checks, HMAC token validation (`run_id`/`step_key`/`scope`), paid GPU bypass prevention (`compute.paid_gpu`), symlink/path-traversal checks, append-only audit trail | **Tier-2 / Tier-3 Hard Block** |
| **8** | **Project & Development Workflow** | `.github/workflows/*.yml` + `apps/core/native/closure_audit.py` + `/v1/v10/closure-audit` | CI/test status (`compileall`, `unittest`, Vitest), repo-vs-runtime audit, immutable baseline guard (`v7..v9`, `phases/phase11..20`), V10–V20 gate tracking | Tier-1 audit / **Tier-3** on commit/push/deploy |

---

## 3. All 20 Preparation Areas Unified Across V10–V20

Every item in the 20-part master checklist is anchored across three clear horizons:
- **Horizon A — V10 Active Preparation (`code + remediated unit contracts`, awaiting Blocker 01 PyTorch CPU approval)**
- **Horizon B — V11 (`10,000` steps, 6 stages) & V12 (`50,000` cumulative steps, 6 stages, `>=100` experiments) (`docs/v11/` & `docs/v12/`, LOCKED)**
- **Horizon C — V13–V20 Long-Term Progression (`docs/long_term/`, BLUEPRINT ONLY)**

| # | Preparation Domain | V10 Implemented Anchor | V11 / V12 Locked Specification | V13–V20 Long-Term Blueprint Scope |
|---|---|---|---|---|
| **1** | **Native Model Architecture** | `ZyrquenConfig` / `ZyrquenModel` (`zyrquen-decoder`, Pre-RMSNorm, RoPE, Causal SDPA, SwiGLU; default `3,737,856` params, 4096-vocab `4,262,144`) | `V11-Tier0` / `V12-Tier0` (`<=5M` active baseline; `Tier1 12.19M` & `Tier2 27.80M` locked behind RSS/throughput proof) | `docs/long_term/V13..V20_BLUEPRINT.md` — modular extensions only after V12 saturation proof; zero fabricated parameter numbers |
| **2** | **Environment & Dependency Management** | Host `Python 3.11.2`, `Linux x86_64`, `12 GB` RAM, `282 GB` disk; `torch` **NOT INSTALLED** (separate approval required); `requirements.txt` free of external AI SDKs | Dedicated CPU-only or separately approved compute runtime; strict separation between ordinary libs & banned external AI engines | Compute upgrades gated per version by empirical throughput telemetry & separate budget signoff |
| **3** | **Dataset Engineering** | `tools/gen_nagi_v10.py`, `zyrquen.dataset-manifest.v1`, SHA-256 integrity, 6 NGI capabilities, 3 splits (`train`/`validation`/`test`), unique-answer solver | V11 expands to 4 canonical splits (`train`/`validation`/`unseen`/`ood`); V12 adds NSE executable tasks across 8 app domains | V13–V20 deterministic generators for multi-branch logic, planning sims, math proofs, multimodal pairs (zero LLM distillation) |
| **4** | **Tokenizer & Native Representation** | `ZyrquenTokenizer` (`zyrquen.tokenizer.v2`), byte-level BPE, 32 `<slot_0>..<slot_31>` atomic tokens, train-only merges, `EL-05` leak check, `_V10_ENTITY_RE` | Post-V10 `UN`/`OO` slot regex expansion gated in `sft.py`; pinned `tokenizer_sha256` across multi-stage resumes | V18 multimodal native tokenizers (code AST, diagrams, UI layout, audio/sensor streams) preserving SHA-256 lineage |
| **5** | **Training Pipeline** | `train_sft()` (`zyrquen.sft.v1`, `IGNORE_INDEX=-100`, finite loss check, step checkpointing) + `handle_training_execute` | V11: `10,000` steps across 6 stages (`20` x 500-step segments or approved cap); V12: `50,000` steps (`5K+8K+10K+10K+8K+9K`, `>=100` exps) | Sequential stage/curriculum continuation only under approved experiment plans; V19 gated self-curriculum proposals |
| **6** | **Resource Management** | `TrainingRuntimeGuard` + `WorkflowResourceGuard` + `RamMonitor` (`cpu<=2`, RAM `3.0/3.5 GB`, Disk reserve `>=2.0 GB`, new disk `<=1.0 GB`, timeouts `1200s/3600s`, paid GPU blocked) | Multi-run disk hygiene (`max_checkpoints=3` retention, artifact pruning audit), RSS telemetry before Tier1/Tier2 unlock | Dynamic budget profiles per version (`V13..V20`) bound inside HMAC token payloads; zero unapproved paid compute |
| **7** | **Checkpoint & Recovery** | `CheckpointManager` (SHA-256) + `VersionedCheckpointManager` (`version_manifest.json`, `weights_only=True`, no duplicate overwrite, `run_<run_id>` isolation) | Cumulative parent SHA-256 lineage across all 6 stages (`V11` and `V12 EXP-001..100`), atomic resume recovery | Multi-generation immutable lineage (`V10 -> V11 -> V12 -> ... -> V20`) with strict `v7..v9` & release write protection |
| **8** | **Native Inference** | `EvaluationEngine` + `_resolve_version_artifacts` (`checkpoint_dir` & `registry_root`), `enforce_cpu_thread_cap`, rejects prompt length `>= max_seq_len` | Standalone native decoding metrics (`exact_match`, `eos_hit_rate`, invalid termination audit) reported separately from tool scaffolding | Verifier-guided native inference (planning tree search V14, retrieval-grounded V15, code repair V16, proof check V17) |
| **9** | **Evaluation & Capability Measurement** | 6 NGI capabilities, independent `audit_leakage_v10.py` (`EL-01..06`, `TL-01`, `SL-01`, `DL-01`), `compare_nagi_v10.py`, `diagnose_nagi_v10.py` | 4 splits + baseline delta vs V10 (for V11) & V10+V11 (for V12); V12 adds NSE sandbox (`Compile`/`Unit`/`Int`/`Hidden`/`Security`) | Cumulative regression matrices (`V10..V(N-1)`) + deterministic verifiers + abstention/calibration checks (`unknown`/`conflict`) |
| **10** | **Reasoning & Planning** | Capabilities `abstract_reasoning`, `relational_generalization`, `ood_transfer` (`hops 2->4->5`), `multi_step_planning`; Phases 11–13 contracts | V11 10K stages build multi-hop & topological DAG reliability; V12 Stages 3–4 push 6–10+ OOD hops | V13 (counterfactuals, deep induction, ambiguity rejection) + V14 (hierarchical DAG decomposition & replanning) |
| **11** | **Memory & Knowledge Integration** | Capability `knowledge_integration` + `phases/phase17.py` (`MemoryStore` tenant isolation) | `V11_MEMORY_AND_KNOWLEDGE.md` & `V12_MEMORY_AND_KNOWLEDGE.md` (provenance, conflict flagging, belief revision) | V15 (`V15_BLUEPRINT.md`) episodic/semantic consolidation & temporal consistency across long project horizons |
| **12** | **Adaptive Learning** | `AutonomousTrainingLoop` bounded experiment runner (`WAITING_RESOURCE`, `BLOCKED`, never auto-promotes) | Evaluation-driven curriculum weight balancing across 6 stages without mutating frozen eval splits | V19 (`V19_BLUEPRINT.md`) controlled failure-to-experiment loop under Tier-2 human approval & zero-drift checks |
| **13** | **Native Software Engineering** | Platform engineering specs (`phases/phase11..20`, `apps/api`, `apps/web`, CI workflows) | `docs/v12/V12_CAPABILITY_SPECIFICATION.md`: Cross-Stage `CAP-SE-01..10` across 8 application domains verified by deterministic build/test | V16 (`V16_BLUEPRINT.md`) full-lifecycle multi-file app architecture, code, DB/API/UI, test repair & security audit |
| **14** | **Autonomous Capability** | Orchestrated multi-step workflow execution gated by `Approval Gate` & `Verification` | Governed stage-by-stage progression through V11 (6 stages) & V12 (`EXP-001..100`) | End-to-end governed engineering + scientific/multimodal workflows in V16–V20 with zero bypass of Tier-2/Tier-3 controls |
| **15** | **Security & Governance** | `WorkflowGovernance` (HMAC-SHA256 `run_id`+`step_key`+`model:<version>` binding), append-only audit DB triggers, paid-GPU payload bypass removed | `V11_SECURITY_AND_GOVERNANCE.md` & `V12_SECURITY_AND_GOVERNANCE.md`: RBAC, path containment, secret scanning | Adversarial prompt/sandbox containment, hidden evaluation test isolation, formal release signoff chain |
| **16** | **Cross-Version Integration** | `ModelRegistry`, `VersionedCheckpointManager`, `EvaluationEngine`, `/v1/v10/closure-audit`, `<ClosureAudit />` | `V11_INTEGRATION_CONTRACT.md` & `V12_INTEGRATION_CONTRACT.md` — single codebase extension via adapters without parallel schedulers | Unified contract version matrix documented in `ZYRQUEN_V10_V20_VERSION_COMPATIBILITY_MATRIX.md` |
| **17** | **Terminal Training Commands** | `tools/*_nagi_v10.py` deterministic CLI suite with preflight/dry-run/read-only safety | Canonical multi-stage segmented CLI workflows & Tier-2 minting hooks | Documented end-to-end in `ZYRQUEN_V10_V20_TERMINAL_MASTER_GUIDE.md` (marked `NOT EXECUTED — REFERENCE ONLY`) |
| **18** | **Version Promotion & Compatibility** | `stage_model_with_approval`, `promote_model_with_approval`, `rollback_model_with_approval` (`zero_regression=True`, `model:<version>` scope) | Baseline lineage `v10 -> v11 -> v12` preserved immutably; prior releases never overwritten | Strict sequential gate: `V10 Closure -> V11 Gate -> V12 Gate -> V13 -> ... -> V20` |
| **19** | **Long-Term Native Intelligence** | Scientific split discipline, unique-answer verification, honest `BLOCKED`/`NOT RUN` accounting | Incremental dual-mission proof (`NGI + NSE`) across 10K & 50K cumulative optimizer steps | V17 (Math/Science), V18 (Multimodal), V19 (Adaptive), V20 (Integrated NGI) under `docs/long_term/` |
| **20** | **Final Preparation Manifest** | `docs/v10/` (3 docs), tests (`52` unittest + `20` module pass / `12` skipped no-torch) | `docs/v11/` (23 docs), `docs/v12/` (23 docs), `docs/long_term/` (9 docs) | Cataloged in `ZYRQUEN_V10_V20_PREPARATION_MANIFEST.md` & verified in `FINAL_READINESS_REPORT.md` |

---

## 4. Mandatory Sequential Gate Map (`V7 → V20`)

```
[V7, V8, V9 FROZEN BASELINES (tools/, eval/)]
        │ (Immutable Reference Only)
        ▼
[V10: Controlled CPU Baseline (<=5M params, <=500 steps)]
  ├─ V10-A Contracts:      VERIFIED (Static/Unit)
  ├─ V10-B Governance:     VERIFIED (Static/Unit)
  ├─ V10-C Hooks & UI:     VERIFIED (Static/Unit; Remediation Complete)
  └─ V10-D PyTorch Run:    BLOCKED (Blocker 01: torch NOT INSTALLED — Needs Separate Approval)
        │
        ▼ (Unlocks ONLY when V10 Final Closure = RUNTIME PASS + Registry Baseline Promoted)
[V11: 10,000-Step Multi-Stage NGI (6 Stages, 4 Splits, docs/v11/)] ── LOCKED
        │
        ▼ (Unlocks ONLY when V11 Release Gate = RUNTIME PASS + Zero Regression vs V10)
[V12: 50,000-Step Cumulative Dual Mission NGI+NSE (6 Stages, >=100 Exps, docs/v12/)] ── LOCKED
        │
        ▼ (Sequential Gate Chain — Each Requires Prior Gate PASS + Separate Approval)
[V13 Reasoning] ─► [V14 Planning] ─► [V15 Memory] ─► [V16 Auto-SE] ─► [V17 Sci/Math] ─► [V18 Multimodal] ─► [V19 Adaptive] ─► [V20 Integrated]
```

---

## 5. Mandatory Truthfulness Declarations

### ASSUMPTIONS
- Separating preparation from execution prevents schema drift, duplicate orchestrators, and unsafe budget bypasses when live PyTorch environments are provisioned.
- Existing frozen V7–V9 artifacts and `phases/phase11.py..phase20.py` remain stable anchors across all subsequent model generations.

### OPEN DECISIONS
- **OD-MASTER-01:** Separate explicit approval to install CPU-only `torch` in the target runtime environment so **V10-D** can transition from `BLOCKED` to live verification.
- **OD-MASTER-02:** Exact runtime host selection (`CPU-only container` vs `HONOR X6b` vs separately approved compute tier) for post-V10 multi-stage 10,000-step (V11) and 50,000-step (V12) benchmarks.
- **OD-MASTER-03:** Timing and approval to enable post-V10 `UN`/`OO` slot regex expansion in `apps/core/native/sft.py` once V10 Runtime Closure is signed off.

### NOT VERIFIED
- Live `import torch`, tensor allocation, real CPU Peak RSS, real `sec/step` throughput, and real convergence/accuracy metrics remain **`NOT RUN / NOT VERIFIED`** across V10–V20 (`TORCH_RUNTIME_STATUS = NOT INSTALLED`).
- V11 (10K), V12 (50K), and V13–V20 exist strictly as **blueprints and preparation contracts**—zero runtime training, zero model weights, and zero capability benchmarks have been executed or claimed.
