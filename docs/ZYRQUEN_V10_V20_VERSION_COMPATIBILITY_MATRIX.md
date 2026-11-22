# ZYRQUEN Ω∞ — V10–V20 Version Compatibility & Contract Matrix

- **Document ID:** `ZYRQUEN-V10-V20-COMPAT-MATRIX`
- **Status:** `PREPARATION CONTRACT — AUTHORITATIVE CROSS-VERSION SPECIFICATION`
- **Scope:** Preserves compatibility from frozen **V7–V9** baselines through **V10 (Blocked on Torch)**, **V11 (Locked)**, **V12 (Locked)**, and **V13–V20 (Long-Term Blueprints)**.

---

## 1. Version Status & Parameter/Step Contract Matrix

| Version | Status | Architecture Core | Parameter Ceiling | Context (`max_seq_len`) | Optimizer Step Horizon | Evaluation Splits | Target Focus |
|---|---|---|---|---|---|---|---|
| **V7–V9** | `FROZEN BASELINE` | Legacy native scripts (`tools/`) | Legacy CPU baselines | Legacy V7–V9 caps | Legacy fixed (`<=500` etc.) | Legacy V7–V9 eval files | Historical immutable regression references (`FROZEN_BASELINE_NAMES`) |
| **V10** | `BLOCKED (Blocker 01: No Torch)` | `ZyrquenConfig` / `ZyrquenModel` (`zyrquen-decoder`: Pre-RMSNorm, RoPE, Causal SDPA, SwiGLU) | **`<= 5,000,000`** (`3,737,856` default / `4,262,144` v4096) | **`<= 256`** (`<=250` payload + `<bos>`/`<eos>`) | **`<= 500`** per experiment (`batch <= 4`, `cpu <= 2`) | 3 splits (`train`, `validation`, `test`) | Runtime baseline + 6 symbolic NGI capabilities (`EL-01..06`, `TL-01`, `SL-01`, `DL-01`) |
| **V11** | `BLUEPRINT ONLY — LOCKED` | `zyrquen-decoder` (`V11-Tier0` CPU baseline; `Tier1 12.19M` / `Tier2 27.80M` LOCKED) | **`<= 5,000,000`** (`Tier0` initial) | `256` (scaling gated) | **`10,000` total steps** across **6 Stages** (`docs/v11/`) | **4 splits** (`train`, `validation`, `unseen`, `ood`) + `test` adapter | Multi-stage 10K NGI consolidation, slot generalization, memory & self-verification |
| **V12** | `BLUEPRINT ONLY — LOCKED` | `zyrquen-decoder` (`V12-Tier0` CPU entry; higher tiers gated on V11 RSS/saturation proof) | **`<= 5,000,000`** (`Tier0` initial; `Tier1/Tier2` LOCKED) | `256..512` (gated) | **`50,000` cumulative steps** across **6 Stages** (`5K+8K+10K+10K+8K+9K`), `>=100` exps | **4 splits** + NSE Sandbox (`Compile`, `Unit`, `Int`, `Hidden`, `Security`) | Dual Mission: NGI (6–10+ OOD hops) + Cross-Stage Native Software Engineering (`CAP-SE-01..10`) |
| **V13** | `LONG-TERM BLUEPRINT ONLY` | `zyrquen-decoder` + deductive verification hooks (`docs/long_term/V13_BLUEPRINT.md`) | *Unassigned (No fabricated numbers; benchmark-gated)* | *Benchmark-gated* | *Benchmark-gated* | Cumulative V10–V12 + counterfactual/deep suites | Advanced Reasoning (multi-branch deduction, counterfactuals, ambiguity rejection) |
| **V14** | `LONG-TERM BLUEPRINT ONLY` | Modular planning & DAG simulator verifier interface (`V14_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + dynamic replanning simulators | Autonomous Planning (hierarchical task decomposition, precondition repair) |
| **V15** | `LONG-TERM BLUEPRINT ONLY` | Retrieval-grounded temporal memory integration (`MemoryStore` + belief revision, `V15_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + temporal contradiction suites | Advanced Memory (episodic/semantic consolidation, strict tenant isolation) |
| **V16** | `LONG-TERM BLUEPRINT ONLY` | Multi-file workspace AST/compiler/test sandbox loop (`V16_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + full multi-file SE sandbox suites | Autonomous Software Engineering (`CAP-SE-01..10` at full project scale) |
| **V17** | `LONG-TERM BLUEPRINT ONLY` | Symbolic CAS & formal proof-checker verifier coupling (`V17_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + formal proof & scientific verification | Scientific & Mathematical Intelligence |
| **V18** | `LONG-TERM BLUEPRINT ONLY` | Native multimodal encoders/decoders (`UI`, `diagrams`, `AST`, `audio/sensor`, `V18_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + cross-modal OOD grounding | Multimodal Native Intelligence |
| **V19** | `LONG-TERM BLUEPRINT ONLY` | Tier-2-gated deficit analyzer & curriculum proposer (`V19_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Cumulative + zero-drift stability suites | Adaptive Learning (non-destructive, human-approved self-improvement) |
| **V20** | `LONG-TERM BLUEPRINT ONLY` | Unified integrated native core across V10–V19 subsystems (`V20_BLUEPRINT.md`) | *Benchmark-gated* | *Benchmark-gated* | *Benchmark-gated* | Full V10–V19 regression + adversarial audit | Integrated Native Intelligence |

---

## 2. Schema & Wire Contracts Across Generations

### A. Tokenizer & Slot-Binding Compatibility
| Contract Key | Schema / Constant | V10 Behavior | V11–V12 Forward Contract | V13–V20 Extension Boundary |
|---|---|---|---|---|
| **Tokenizer Schema** | `zyrquen.tokenizer.v2` (`apps/core/native/tokenizer.py`) | Byte-level BPE + 4 control tokens (`0..3`) + 32 `<slot_0>..<slot_31>` atomic tokens (`4..35`); merges learned strictly on `train` split (`EL-05`) | Preserved verbatim; `tokenizer_sha256` pinned into every `version_manifest.json` and `ModelRegistry` record | Additive versioned schemas (e.g. V18 multimodal tokens) must preserve text/slot token compatibility or declare explicit adapter bridges |
| **SFT Sample Schema** | `zyrquen.sft.v1` (`apps/core/native/sft.py`) | Separator `SFT_SEP = "\n### Response:\n"`, prompt masked with `IGNORE_INDEX = -100` | Preserved across all 10K (V11) & 50K (V12) SFT stages | Future objectives (verification/RL/search) remain isolated behind explicit schema IDs |
| **Ephemeral Entity Regex** | `_V10_ENTITY_RE` (`apps/core/native/sft.py`) | Matches `TR`/`VA`/`TE` entity prefixes (`EL-01..06` isolation) | **`UN`/`OO` prefix expansion (`unseen`/`ood` splits) STRICTLY LOCKED until V10 Runtime Closure PASS** | Extensible per split namespace via split isolation validators (`audit_leakage`) |

### B. Dataset Manifest & Split Compatibility
| Field / Rule | V10 Contract (`zyrquen.dataset-manifest.v1`) | V11–V12 Contract | Backward Compatibility Adapter |
|---|---|---|---|
| **Required Splits** | `("train", "validation", "test")` | `("train", "validation", "unseen", "ood")` | `V11_V10_COMPATIBILITY.md`: `test` artifacts map cleanly to `unseen` or retain dual compatibility in `dataset.py`/`registry.py` during V11 rollout |
| **Integrity Hashing** | Per-file `sha256` + aggregate `content_sha256` (`tools/gen_nagi_v10.py`) | Mandatory per-stage manifest SHA-256 + parent lineage metadata | Symlinks, absolute paths, and `..` traversal strictly rejected |
| **Leakage Audit** | `EL-01..06`, `TL-01`, `SL-01`, `DL-01`, `SEQ_BUDGET <= 250` (`tools/audit_leakage_v10.py`) | Extends entity/template/structural checks across 4 splits + SE code clone/AST leakage checks (V12) | Every eval run records `dataset_content_sha256` to reject cross-dataset comparisons |

### C. Checkpoint, Registry & Evaluation Contracts
| Contract Layer | Code Anchor | Cross-Version Guarantee |
|---|---|---|
| **Raw Step Checkpoint** | `apps/core/native/checkpoint.py::CheckpointManager` | Safe `torch.load(..., weights_only=True)`, atomic write, SHA-256 sidecar integrity, refuses overwrite of completed run unless explicitly resuming |
| **Versioned Checkpoint** | `apps/core/native/checkpoint.py::VersionedCheckpointManager` | Atomic `version_manifest.json` binding `model_version`, `checkpoint_sha256`, `tokenizer_sha256`, `parent_version`, `lineage`; `register_existing_checkpoint()` prevents `.pt` duplication |
| **Model Registry** | `apps/core/native/registry.py::ModelRegistry` | `FROZEN_BASELINE_NAMES = ("v7", "v8", "v9")` immutable; `staging -> promoted -> rolled_back` lifecycle requires Tier-2 HMAC token bound to exact `scope = f"model:{version}"` |
| **Native Evaluation Engine** | `apps/core/native/evaluation/engine.py::EvaluationEngine` | Resolves **both** `VersionedCheckpointManager(checkpoint_dir)` and `ModelRegistry(registry_root)`; rejects prompts `>= cfg.max_seq_len` (zero silent truncation); clamps CPU inference threads `<= 2` |
| **Evaluation Gate** | `apps/core/workflow/handlers/groups.py::handle_evaluation_gate` | Accepts only `zyrquen.v10.evaluation_report.v1` (or successor schema), requires `overall_status == "PASS"`, `inference_status == "PASS"`, non-empty `capabilities` dict, and `zero_regression == True` |

---

## 3. Product Roadmap (`Phases 11–20`) vs Model Versions (`V10–V20`) Boundary

| Platform Module (`phases/`) | Responsibility (Immutable Infrastructure) | Model Versions Consuming Interface |
|---|---|---|
| `phases/phase11.py` | Core execution/reasoning scaffold contracts | V10–V20 via adapters |
| `phases/phase12.py..phase15.py` | Language registry, planning enforcement, tool/feedback verification | V10–V20 (especially V13–V16 planning & SE verifiers) |
| `phases/phase16.py` | Epistemic honesty (`Fact` / `Assumption` / `Unverified` separation) | All versions (enforces `ABSTAIN`/`unverified` over hallucination) |
| `phases/phase17.py` | Multi-tenant isolated `MemoryStore` | V11–V12 baseline memory; V15 advanced memory |
| `phases/phase18.py..phase20.py` | Application contracts, security execution boundaries, global system integration | V12 Dual Mission & V16–V20 integrated workspace orchestration |

> **Hard Invariant:** Never alter `phases/phase11.py..phase20.py` or create `phase21.py` to represent neural model versions. Model generations evolve solely inside documented `docs/v10..v12/`, `docs/long_term/`, and version-isolated `apps/core/native/` implementations once gated and approved.

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Backward schema compatibility across `zyrquen.dataset-manifest.v1`, `zyrquen.tokenizer.v2`, and `zyrquen.sft.v1` avoids re-architecting core evaluation/registry infrastructure at each version increment.

### OPEN DECISIONS
- **OD-COMPAT-01:** Formal schema identifier bumping (`zyrquen.v11.evaluation_report.v1` vs backward-compatible extension of `v1` schema) to be finalized only when V11 unlocks.

### NOT VERIFIED
- Cross-version weight-transfer or continual learning compatibility across trained V10→V11→V12 checkpoints has **NOT BEEN TESTED AT RUNTIME** because `torch` is not installed and zero trained checkpoints exist yet.
