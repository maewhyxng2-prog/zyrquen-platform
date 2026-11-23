# ZYRQUEN Ω∞ — P11 Dataset Requirements (`P11_DATASET_REQUIREMENTS.md`)

- **Mission:** Native Dataset Pipeline Audit & P11 Specification (`nagi_v11`)
- **Mode:** `READINESS AUDIT + PREPARATION` (`TRAINING AUTHORIZATION: NOT GRANTED`)
- **Primary References:** `/docs/v11/V11_DATASET_SPECIFICATION.md`, `/apps/core/native/dataset.py`, `/apps/core/native/dataset_v11.py`, `/apps/core/native/sft.py`, `/apps/core/native/tokenizer.py`, `/apps/core/native/dataset_status.py`

---

## 1. Dataset Pipeline Readiness Audit

| Check Area | File / Config Ref | Actual Evidence | Status | Required Remediation | Verification Method |
|---|---|---|---|---|---|
| V11 Dataset Artifacts & Generator | `/data/`, `/tools/` | Neither `data/` nor `tools/gen_nagi_v11.py` / `tools/audit_leakage_v11.py` exists. Live `get_datasets_pipeline_status()` returned `configured: False, status: "not_configured"`. | `BLOCKED` | Implement `tools/gen_nagi_v11.py` & `tools/audit_leakage_v11.py` (100% deterministic native algorithmic solvers — zero LLM generation) and generate `data/nagi_v11/*`. | `verify_dataset_manifest()` + `inspect_v11_training_dataset_readiness()["ready"] == True`. |
| 4-Split Recognition (`train`, `validation`, `unseen`, `ood`) | `/apps/core/native/dataset.py:18-20,256-367`, `/apps/core/native/dataset_v11.py:15-191` | `V11_SPLITS = ("train", "validation", "unseen", "ood")`; `verify_dataset_manifest()` checks SHA-256, non-symlink, traversal safety. `DataAdapter` checks 4 splits, split field mismatches, normalized exact text overlap, and `_V11_ENTITY_RE` cross-split entity overlap. | `PASS` (Partial Static Contract) | Extend `prepare_dataset()` (`dataset.py:172-237`) beyond 3-split raw-text `"text"` to support V11 4-split SFT schema. | Unit test creating synthetic 4-split SFT dir & verifying `DataAdapter` + `verify_dataset_manifest()`. |
| Manifest `"files"` vs `"splits"` Contract Conflict | `/apps/core/training/orchestrator.py:137-153`, `/docs/v11/V11_DATASET_SPECIFICATION.md:214` | `TrainingOrchestrator.prepare()` requires `manifest["files"]["train.jsonl"]["documents"]` and `manifest["files"]["validation.jsonl"]["documents"]`; V11 spec doc omitted `"files"`; `orchestrator.prepare()` skips `unseen`/`ood` & `detect_leakage()`. | `FAIL` | Require `"files"` (exact filename -> `{sha256, documents}`) AND `"splits"` in V11 `manifest.json`; update `TrainingOrchestrator.prepare()` to validate via `verify_dataset_manifest()` + `DataAdapter.detect_leakage()`. | Unit test `TrainingOrchestrator.prepare()` on canonical `nagi_v11` manifest + poisoned leakage manifest. |
| Missing Anti-Leakage Gates (`TL-01`, `SL-01`, `DL-01`, Length Cap) | `/apps/core/native/dataset_v11.py`, `/apps/core/native/dataset.py:149`, `/apps/core/workflow/handlers/groups.py:250-315` | Only exact `_dedup_key`, normalized exact text, and `_V11_ENTITY_RE` entity IDs are audited. **Zero checks exist** for `TL-01` (template/surface phrasing overlap), `SL-01` (hop/plan-depth overlap vs OOD), `DL-01` (fuzzy/n-gram dedup inside train), or `len <= 256` token budget. | `FAIL` | Implement `TL-01`, `SL-01`, `DL-01`, and BPE token length verifier inside `tools/audit_leakage_v11.py` & `DataAdapter.detect_leakage()`. | Negative tests injecting shared `ood` template phrasing, shallow depth-3 in `ood`, near-duplicate rows, and 260-token prompts — all must fail. |
| Slot-Safe Tokenizer (`zyrquen.tokenizer.v2`) | `/apps/core/native/tokenizer.py:1-305`, `/apps/core/native/sft.py:24-230` | NFC normalization, byte-level BPE, 32 atomic `<slot_0>..<slot_31>` tokens (`IDs 4..35`), `train_slot_safe_tokenizer()` checks `EL-05` against held-out `_V11_ENTITY_RE` tokens (`UN_E*`, `OO_E*`, `node_un_*`, etc.). | `PASS` (Code), `NOT VERIFIED` (Corpus) | Train tokenizer ONLY on `train.jsonl` slot-masked text (`vocab_size=2048` primary / `4096` candidate); assert `EL-05` pass and `100%` round-trip fidelity on `unseen`/`ood`. | Run `train_slot_safe_tokenizer()` on generated `nagi_v11` corpus + verify zero held-out entity merges. |
| Origin & License Provenance | `/apps/core/native/dataset.py:5-6` | Only self-declared `"source"` / `"license"` strings supported; no verification rule enforces native-only synthetic origin or blocks third-party LLM outputs. | `NOT VERIFIED` | Require `origin="native-deterministic-solver-v11"`, `license="synthetic-native-zyrquen-v11"`, solver version + seed in `manifest.json` verified by `handle_data_verify_and_audit`. | Audit test rejecting missing/external `origin` or `license` tags. |
| Dataset Status / Report APIs | `/apps/api/routers/datasets.py:1-48` | Exposes only `GET /v1/datasets/status` and `GET /v1/datasets/{dataset_version}/status`. No audit-report, split-distribution, or token-length endpoint exists. | `FAIL` | Add read-only `GET /v1/datasets/{version}/audit` and `GET /v1/datasets/{version}/token-stats` routes backed by disk artifacts (no fabricated metrics). | FastAPI router tests (`200` on verified data, `503` unconfigured, `422` corrupted SHA-256). |

---

## 2. Origin, Licensing & Anti-External-Data Policy

1. **100% Algorithmic Synthetic Provenance:** Every record in `nagi_v11` MUST be generated deterministically in-house using ZYRQUEN Python symbolic/graph/planning/verification solvers (`tools/gen_nagi_v11.py`) with recorded generator version and integer seeds (`seed_train`, `seed_val`, `seed_unseen`, `seed_ood`).
2. **Strictly Prohibited Sources:**
   - Zero outputs generated or paraphrased by OpenAI, Anthropic, Gemini, Llama, Qwen, or any external LLM/API.
   - Zero unverified public web scrapes or third-party instruction dumps without explicit license clearance and origin records.
3. **Mandatory Manifest Provenance Fields:**
   - `"dataset_id": "nagi_v11"`, `"version": "11.0.0"`, `"schema": "zyrquen.dataset-manifest.v1"`
   - `"origin": "native-deterministic-solver-v11"`, `"license": "synthetic-native-zyrquen-v11"`
   - `"files"` (required for `TrainingOrchestrator` compatibility) AND `"splits"` (V11 split metadata: counts, entity namespace, seed, SHA-256).

---

## 3. Target Split Architecture & Baseline Sizing (`nagi_v11`)

Per `/docs/v11/V11_DATASET_SPECIFICATION.md`, P11 requires strict 4-split separation (plus optional frozen holdout `test` archive if separated downstream for release certification):

| Split | File | Baseline Rows | Entity Namespace Prefix | Structural / Template Domain | Purpose |
|---|---|---:|---|---|---|
| `train` | `train.jsonl` | `4,800` (`800` x 6 capabilities) | `TR_E*`, `node_tr_*`, `step_tr_*`, `rec_tr_*` | Template Family `A` (Depth `1–3`, Plans `1–4` steps) | Supervised training + tokenizer training ONLY |
| `validation` | `validation.jsonl` | `480` (`80` x 6 capabilities) | Disjoint `VL_E*`, `node_vl_*` | Template Family `A` | Step loss monitoring, checkpoint selection |
| `unseen` | `unseen.jsonl` | `480` (`80` x 6 capabilities) | Disjoint `UN_E*`, `node_un_*` | Template Family `B` (unseen phrasings) | Unseen entity + paraphrase generalization |
| `ood` | `ood.jsonl` | `480` (`80` x 6 capabilities) | Disjoint `OO_E*`, `node_oo_*` | Template Family `C` (Depth `4–6`, Plans `5–6` steps, unseen relations/inverses) | True compositional & structural OOD test |
| **Total** | **4 Splits** | **`6,240`** | **100% Disjoint** | **3 Disjoint Families (`A`, `B`, `C`)** | **Zero Cross-Split Entity / Template / Structural Leakage** |

*(Pilot experiment runs before full `6,240`-row corpus generation may use an explicitly labeled smaller pilot subset — e.g. `1,200` train / `120` val / `120` unseen / `120` ood — provided every disjointness, template, structural, and `EL-05` invariant holds.)*

---

## 4. Schema, Tokenization & Sequence-Length Budget

### Required Record Fields (JSONL)
Every record MUST provide:
- `id`: unique deterministic record ID
- `split`: exact split matching file (`"train" | "validation" | "unseen" | "ood"`)
- `capability`: `"knowledge_integration" | "multi_step_planning" | "relational_generalization" | "ood_transfer" | "abstract_reasoning" | "self_verification"`
- `stage_tag`: `"stage_1_grounding" | ... | "stage_6_joint"`
- `input`: prompt with unique verifiable symbolic context and explicit question/task
- `target`: exact ground-truth output string (including explicit `"UNKNOWN"` / `"REFUSE: ..."` for abstention & verification negatives)
- `entities`, `template_id`, `structure_signature` (`hop_depth`, `plan_len`), `unique_answer_verified: true`

### Tokenization & Length Contracts (`max_seq_len = 256`)
- **Tokenizer:** `zyrquen.tokenizer.v2`, `vocab_size = 2048` (baseline) or `4096` (if >30% prompts exceed 200 tokens — verified during tokenization check), `32` atomic `<slot_0>..<slot_31>`.
- **Prompt + Target Loss Masking (`sft.py::encode_sft_pair`):**
  - Sequence: `prompt_ids + target_ids + [<eos>]`
  - Labels: `[-100] * len(prompt_ids) + target_ids + [<eos>]`
- **Hard Length Cap:** `total_tokens <= 256` for 100% of records (`P99 <= 240`, safety margin `>= 6` tokens before `block_size=256`); zero silent truncation (`encode_sft_pair` raises error if exceeded).
- **Target Decode Budget:** Target response alone MUST fit within `max_new_tokens` (`64` tokens recommended for V11 P5–P6 multi-step plans).

---

## 5. Mandatory Anti-Leakage & Deduplication Gates (Pre-Training Lock)

Before ANY P11 training step is authorized, `tools/audit_leakage_v11.py` MUST verify and produce an immutable JSON audit report (`PASS` across all rules):
1. **`EL-01..EL-04` (Entity Disjointness):** Zero overlap across all pairs of `{train, validation, unseen, ood}` entities extracted by `_V11_ENTITY_RE` and metadata `entities`.
2. **`EL-05` (Tokenizer Vocabulary Purity):** Zero held-out `unseen` / `ood` entity identifiers exist in trained BPE merges (`vocab_size` check).
3. **`TL-01` (Template / Phrasing Disjointness):** Normalized surface skeletons (entities & numbers replaced by placeholders) from `unseen` (`Family B`) and `ood` (`Family C`) have zero overlap with `train`/`validation` (`Family A`).
4. **`SL-01` (Structural Disjointness):** `ood` structural depth / plan length signatures (`hop >= 4` or `plan_len >= 5`) have zero structural isomorphism with `train` (`hop <= 3`, `plan <= 4`).
5. **`DL-01` (Exact & Fuzzy Deduplication):** `100%` exact `normalized(input + "||" + target)` uniqueness across all splits; within-train Jaccard n-gram (`n=5`) near-duplicate rate `<= 1.0%` (excluding shared boilerplate headers).
6. **`SL-02` / Unique-Answer Solver Check:** `100%` of prompts verified by deterministic solver (`unique_answer_verified == True`) — zero ambiguous multi-answer prompts or unsolvable contexts mistakenly labeled with valid answers.
