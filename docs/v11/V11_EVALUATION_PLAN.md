# ZYRQUEN Ω∞ — V11 Evaluation Plan (10,000-Step Objective & 4 Splits)

- **Document ID:** `V11-DOC-10`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 RUNTIME CLOSURE GATE PASS`
- **V10 Closure Program Pre-Check:** V10 Static/Integration/Governance Contracts (`V10-A`..`V10-D`) passed audit; Runtime PyTorch Training & Evaluation remain **BLOCKED / NOT RUN** (`torch` not installed). All V11 execution stays locked until V10 produces verified real-weight checkpoint and `zyrquen.v10.evaluation_report.v1` PASS evidence.
- **Core Engines Reused:** `apps/core/native/evaluation/engine.py::EvaluationEngine` + `apps/core/workflow/handlers/groups.py::handle_evaluation_gate` + `apps/core/native/registry.py::ModelRegistry`
- **Report Schema:** `zyrquen.v11.evaluation_report.v1`

---

## 1. Non-Negotiable Truth & Anti-False-PASS Rules

1. **Zero Fabricated Metrics:** ทุกคะแนนต้องเกิดจาก Real Greedy Native Inference (`temperature=0`, `ZyrquenModel` บน checkpoint ที่ตรวจ SHA-256 แล้ว) ผ่าน `EvaluationEngine.evaluate_native_model` เท่านั้น ห้ามใช้ Mock, Formula แทนการรัน, หรือ Hardcoded Answers
2. **Strict Verdict Separation:** สถานะ `NOT RUN`, `BLOCKED`, `FAIL`, `FAILED`, `ERROR`, `UNKNOWN`, `PENDING` ห้ามถูกตีความว่าเป็น `PASS` หรือ `0.0` (คงมาตรฐานเดียวกับ `ModelRegistry._DISALLOWED_EVAL_STATUSES` และ `handle_evaluation_gate`)
3. **Zero Empty Regression Bypass:** รายงานเปรียบเทียบ (`regression_comparison`) ต้องมีรายการเปรียบเทียบจริง (`non-empty list`) กับ Stage ก่อนหน้าและ V10 Baseline จึงจะถือว่า `zero_regression = True` ได้
4. **Full Provenance Pinning:** รายงานต้องแนบ `model_version`, `checkpoint_sha256`, `tokenizer_sha256`, `dataset_content_hash`, `report_sha256`, และ `inference_executed = True` จึงจะบันทึกลง `ModelRegistry.attach_evaluation_evidence()` ได้

---

## 2. Four-Split Evaluation Taxonomy (`Train`, `Validation`, `Unseen`, `OOD`)

การประเมินในแผน 10,000 Steps แยกบทบาทของทั้ง 4 Splits อย่างเด็ดขาด (ทุก Split รันด้วย `permute_slots=False` เพื่อความสามารถในการทำซ้ำ 100%):

| Split | Sample Scope During Evaluation | Isolation Property | Scientific Purpose | Counts toward Stage / Release PASS? |
|---|---|---|---|---|
| **`train` (Diagnostic Slice)** | Fixed deterministic subset `n=120` (`20` per cap) at segment probes; up to `n=480` at Stage Exit | Same entity/template pool as training (`TR_*`) | ตรวจ Optimization convergence, Loss-vs-Exact alignment, Overfitting gap (`train - validation`), และ `TF - FG` exposure gap | **No** (Diagnostic only — `train` สูงอย่างเดียวห้ามผ่าน Gate) |
| **`validation`** | Full `validation.jsonl` (`480` rows, `80` per cap) | Disjoint `VA_*` entities & `*_VA_*` templates; seen depth/relations | Hyperparameter/LR monitoring, Catastrophic forgetting check, Early-stop trigger | **Yes (Every Segment & Stage Gate)** |
| **`unseen`** | Full `unseen.jsonl` (`480` rows, `80` per cap) | Disjoint `UN_*` entities & `*_UN_*` phrasings; matched complexity | วัด **Entity & Phrasing Generalization** (`unseen_entity_copy_acc` ต้องมีค่าจริง ห้ามเป็น `N/A`) | **Yes (Every Stage Exit Gate & Final Gate)** |
| **`ood`** | Full `ood.jsonl` (`480` rows, `80` per cap) | Disjoint `OO_*` entities + `*_OO_*` templates + **unseen `4–6` hop depth & relations (`SL-01`)** | วัด **Out-of-Distribution Structural & Depth Transfer**, anti-shortcut robustness | **Yes (Mandatory at Stage 2/6 & Final Gate; Tracked every Stage Exit)** |

### 2.1 Four-Split Diagnostic Failure Separation Rules
การใช้ทั้ง 4 Splits พร้อมกันช่วยให้ระบุรากเหง้าของความล้มเหลวได้โดยไม่เดา:

| Observed Pattern Across 4 Splits | Primary Root Diagnosis | Mandatory Corrective Action (Never Mask with Prompt Hacks) |
|---|---|---|
| `train` ต่ำ & `validation` ต่ำ | **Underfitting / Broken Optimization** (LR, warmup, gradient flow หรือ data bug) | ตรวจ `val_loss`, `<|eos|>` hit rate, `-100` label masking (`sft.py`) และความจุโมเดล |
| `train` สูง แต่ `validation` ต่ำ | **Memorization of Training Entities / Overfitting** | เพิ่ม Replay / Regularization (`wd=0.1`), ตรวจ Slot Permutation (`permute_slots=True`) |
| `validation` สูง แต่ `unseen` ต่ำ | **Entity/Lexical Shortcut or Slot Binding Leakage** | ตรวจ `unseen_entity_copy_acc`, `EL-05` BPE leaks, และ regex binding (`sft.py` ครอบคลุม `UN_*`) |
| `unseen` สูง แต่ `ood` ต่ำ | **Depth/Relation Overfitting (`SL-01` Failure)** | ตรวจสอบว่าทำ shortcut `<= 3` hops หรือจำ relation verb; ปรับ curriculum Stage 2/6 + Near-Miss distractors |
| `teacher_forced_exact` สูง แต่ `free_gen_exact` ต่ำ | **Exposure Bias / Autoregressive Drift** | ตรวจข้อผิดพลาดทีละ token บน multi-step plans และความยาว `max_new_tokens` |

---

## 3. Evaluation Schedule Across the 10,000-Step Objective (Stages 1–6)

แผนการประเมินแบ่งเป็น **2 จังหวะ (Dual-Cadence Evaluation)** เพื่อควบคุมเวลา CPU แต่ไม่ปล่อยให้ Regression ซ่อนตัว:
- **In-Stage Segment Checkpoints (ทุก `250` หรือ `500` steps):** วัด `val_loss` + `train_slice (n=120)` + `validation (n=480)` เพื่อจับ NaN, Divergence หรือ Collapse เร็วที่สุด
- **Mandatory Stage Exit Gates (`Step 1000, 3000, 5000, 7000, 9000, 10000`):** วัดครบทั้ง **4 Splits** (`train` slice `n=240`, full `validation n=480`, full `unseen n=480`, full `ood n=480`) + Save Immutable Stage Milestone

| Stage & Exit Step | Capabilities Active in Training | Splits Evaluated at Exit Gate | Required Checks & Provisional Blueprint Gate Targets *(Calibrated via `OD-EP-01` after V10 Baseline)* | Regression Baseline Compared |
|---|---|---|---|---|
| **Stage 1 Exit** (`Step 1,000`) | Format, `<slot_k>`, EOS, simple 1–2 hop `abstract_reasoning` & `relational_generalization` | `train` (slice), `validation`, `unseen`, `ood` (baseline probe) | - `val_loss` finite & lower than Step 0 random-init<br>- `eos_hit_rate >= 0.90` on `validation` & `unseen`<br>- `validation_exact` & `unseen_exact` > chance baseline<br>- Zero invalid slot decoding | Step `0` (Random Init) |
| **Stage 2 Exit** (`Step 3,000`) | `abstract_reasoning` (full 1–3 hop) + `relational_generalization` (2–3 hop + distractors) | `train` (slice), `validation`, `unseen`, `ood` | - `validation` & `unseen` accuracy on `abstract_reasoning` & `relational_generalization` improves monotonically vs Stage 1<br>- `unseen_entity_copy_acc` measured & non-`N/A`<br>- Preliminary `ood` transfer signal recorded honestly (never hidden if low) | Stage 1 Exit (`Step 1,000`) |
| **Stage 3 Exit** (`Step 5,000`) | `multi_step_planning` (unique topological + `impossible`) + Stage 1–2 replay | `train` (slice), `validation`, `unseen`, `ood` | - `multi_step_planning` `validation` & `unseen` exact match meets stage floor<br>- Cycle / missing-prereq `"impossible"` recall verified (no false topological chains)<br>- **Zero Regression** on Stage 2 `abstract_reasoning` & `relational_generalization` (`delta >= -0.02` provisional) | Stage 2 Exit (`Step 3,000`) |
| **Stage 4 Exit** (`Step 7,000`) | `knowledge_integration` (`base`/`update`/`retract`/`conflict` + Memory tags) + Stage 1–3 replay | `train` (slice), `validation`, `unseen`, `ood` | - Override vs `conflict` vs `[verified=false]` discrimination verified<br>- Zero PII / cross-tenant leakage in Phase 17 checks<br>- **Zero Regression** across Stages 2–3 capabilities | Stage 3 Exit (`Step 5,000`) |
| **Stage 5 Exit** (`Step 9,000`) | `self_verification` (`claim_check`, `plan_check`, epistemic tags) + Stage 2–4 replay | `train` (slice), `validation`, `unseen`, `ood` | - `self_verification` accuracy across `valid`/`invalid_order`/`invalid_missing`/`invalid_cycle` meets stage floor<br>- Deterministic `phases/phase16.py::validate_dag` & `verify_step` agreement check passes<br>- `TF_exact - FG_exact` exposure gap measured on `multi_step_planning` | Stage 4 Exit (`Step 7,000`) |
| **Stage 6 Exit (Final)** (`Step 10,000`) | All 6 Capabilities + `ood_transfer` depth/relation consolidation | **FULL 4 SPLITS** (`train` slice `n=480`, `validation n=480`, `unseen n=480`, `ood n=480`) | - **All 6 Capabilities = `PASS`** on `validation`, `unseen`, AND `ood`<br>- `unseen_entity_copy_acc` & `abstention` pass calibration<br>- `zero_regression = True` vs **V10 Baseline** AND Stages 1–5<br>- Phase 20 End-to-End (`architecture -> reasoning -> planning -> memory -> learning -> safety`) + SLO check = `PASS` | Stage 5 Exit (`Step 9,000`) **AND** Closed V10 Baseline |

---

## 4. Mandatory Metrics & Diagnostic Breakdown

ทุก Evaluation Report (`zyrquen.v11.evaluation_report.v1`) ต้องคำนวณและบันทึกเมตริกจริงต่อไปนี้ (ห้ามเป็น `null` เมื่อ `inference_status == "PASS"`):

1. **Split-Level Aggregate Metrics:**
   - `train_diag_exact_match`, `validation_exact_match`, `unseen_exact_match`, `ood_exact_match`
   - `val_loss`, `perplexity` (`apps/core/native/evaluation/metrics.py`)
   - `overfit_gap = train_diag_exact_match - unseen_exact_match`
   - `ood_transfer_gap = unseen_exact_match - ood_exact_match`
2. **Per-Capability × Per-Split Matrix (`6 × 4 = 24` cells):**
   - `cap_<capability>_<split>_accuracy` สำหรับทุก capability ใน `{abstract_reasoning, relational_generalization, ood_transfer, multi_step_planning, self_verification, knowledge_integration}` และทุก split ใน `{train, validation, unseen, ood}`
3. **Behavioral & Calibration Metrics:**
   - `eos_hit_rate` (หยุดที่ `<|eos|>` จริงก่อนเต็ม `max_new_tokens`)
   - `unseen_entity_copy_acc` (ความแม่นยำการ copy & restore `<slot_k>` บน `unseen` และ `ood` แยกกัน)
   - `teacher_forced_exact` และ `exposure_gap = teacher_forced_exact - free_gen_exact`
   - `abstention_precision` / `abstention_recall` (บนเป้าหมาย `"unknown"`, `"conflict"`, `"impossible"`)
   - `principle_probes`: `slot_permutation_invariance`, `premise_order_invariance` (Diagnostic)
4. **Runtime Footprint:**
   - `eval_wall_time_sec`, `ms_per_example`, `peak_ram_gb` (เก็บจาก `RamMonitor`)

### 4.1 Explicit Metric Matrix for `abstract_reasoning` & `ood_transfer` Across 4 Stages (`Train`, `Validation`, `Unseen`, `OOD`)

| Capability | Metric Key | Exact Computation & Meaning | Evaluated Stages (`Train`, `Validation`, `Unseen`, `OOD`) | Role in 10,000-Step Objective |
|---|---|---|---|---|
| **`abstract_reasoning`** | `cap_abstract_reasoning_<split>_accuracy` | Exact match of restored output token against singleton target in `{">", "<", "=", "unknown"}` across split `s` | `train` (diag), `validation`, `unseen`, `ood` | Core score per Stage (Stages 1, 2, 6 + replay retention Stages 3–5) |
| **`abstract_reasoning`** | `ar_<split>_inverse_query_acc` | Accuracy exclusively on reversed-direction queries (`B ? A` when chain gives `A > ... > B`) | `train` (diag), `validation`, `unseen`, `ood` | Detects directional heuristic collapse vs real transitive order graph |
| **`abstract_reasoning`** | `ar_<split>_unknown_f1` | Precision/Recall/F1 on `"unknown"` disconnected/incomparable fork pairs | `validation`, `unseen`, `ood` | Prevents majority-class `{">", "<"}` guessing |
| **`abstract_reasoning`** | `ar_ood_depth_4to6_acc` & `ar_order_invariance` | Accuracy on `4–6` hop shuffled-premise DAGs + consistency under premise permutation | `ood` (with baseline check vs `unseen`) | Proves multi-hop transitive generalization beyond training depth |
| **`ood_transfer`** | `cap_ood_transfer_<split>_accuracy` | Exact match of restored terminal entity (`<slot_k>` -> surface entity) after exact `H`-hop unique traversal | `train` (diag `2–3`h), `validation` (`3`h), `unseen` (`3`h), `ood` (`4–6`h) | Measures both in-dist relation execution & true OOD extrapolation |
| **`ood_transfer`** | `ood_transfer_hop4_acc`, `ood_transfer_hop5_acc`, `ood_transfer_hop6_acc` | Stratified accuracy by hop depth `H = 4`, `5`, `6` on `transfers_to`/`channels_to` | `ood` (tracked Stages 2–6; Final Gate Stage 6) | Quantifies exact length extrapolation slope beyond `train` (`H <= 3`) |
| **`ood_transfer`** | `ood_transfer_lexical_gap` | `cap_ood_transfer_validation_accuracy - cap_ood_transfer_unseen_accuracy` | `validation` vs `unseen` | Isolates unseen relation phrasing + unseen entity copy performance (`routes_to` vs `relates_to`) |
| **`ood_transfer`** | `ood_transfer_structural_gap` | `cap_ood_transfer_unseen_accuracy - cap_ood_transfer_ood_accuracy` | `unseen` vs `ood` | Isolates pure `SL-01` depth & topology shift gap (`3`-hop -> `4–6`-hop + near-miss `H-1`/`H+1` traps) |
| **`ood_transfer`** | `unseen_entity_copy_acc` & `near_miss_rejection_rate` | Exact `<slot_k>` entity copy accuracy + % avoiding `H-1` dead-end distractor terminals | `unseen`, `ood` | Verifies slot equivariance and resistance to shortcut traps |

---

## 5. Evaluation Gate Fail & Stop Rules (`handle_evaluation_gate`)

`handle_evaluation_gate` ต้องคืน **`FAIL`**, **`BLOCKED`**, หรือ **`NOT RUN`** (ห้ามคืน `PASS` เด็ดขาด) หากพบเงื่อนไขใดเงื่อนไขหนึ่ง:
- ขาด Split ใดใน `("validation", "unseen", "ood")` หรือจำนวนตัวอย่างที่รันจริงเท่ากับ `0`
- มี Capability ใดใน 6 ด้านมีสถานะ `FAIL`, `BLOCKED`, `NOT RUN`, หรือ score ไม่ใช่ finite float
- `inference_executed is not True` หรือ `inference_status != "PASS"`
- `leakage_audit_status != "PASS"` หรือ `dataset_integrity != "PASS"`
- `regression_comparison` เป็น `None`, ว่าง (`[]`), หรือมีรายการที่ `zero_regression is False`
- `stop_criteria_triggered` ไม่ว่าง (`loss_diverged`, `ram_hard_stop`, `stage_forgetting_collapse`)
- `ModelRegistry.verify(model_version)` ล้มเหลว หรือ `checkpoint_sha256` / `tokenizer_sha256` ไม่ตรง

### 5.1 Governance & Toolchain Continuity (Closed V10-B/C Pipeline Reuse)
V11 ต้องใช้โครงสร้างที่ผ่าน Closure แล้วจาก V10-B/C โดยตรง ห้ามสร้าง Gate แยกใหม่:
1. **Evaluation Runner → Gate → Registry Chain:** `EvaluationEngine.evaluate_native_model()` → รายงาน JSON (ขยาย schema จาก `eval_nagi_v10.py` + `build_regression_comparison()`) → `handle_evaluation_gate` (ตรวจ finite capability score + non-empty `regression_comparison` + `acceptance_assessment`) → `ModelRegistry.attach_evaluation_evidence()` (`verified` / `quarantined`)
2. **Tier-2 HMAC Lifecycle Chain:** การเปลี่ยนสถานะจาก `verified` → `staging` (`stage_model_with_approval`) → `production` (`promote_model_with_approval`) → `rollback` (`rollback_model_with_approval`) ต้องผ่าน Single-Use HMAC-SHA256 Approval Token และบันทึกใน `WorkflowAuditLogger` ทุกครั้ง
3. **Cross-Run Metric Continuity:** ชื่อคีย์หลักใน `metrics` และ `compare_nagi_v10.py` (`exact_match`, `validation_exact_match`, `eos_hit_rate`, `cap_<capability>_accuracy`) ต้องคงอยู่ครบใน V11 เพื่อให้เปรียบเทียบตรงกับ Baseline V10 ได้โดยไม่พัง schema

---

## 6. Canonical V11 Report Schema (`zyrquen.v11.evaluation_report.v1`)

```json
{
  "schema_version": "2.0",
  "report_schema": "zyrquen.v11.evaluation_report.v1",
  "project": "ZYRQUEN Ω∞",
  "experiment": "Native Model v11",
  "experiment_id": "v11-stage6-exp20-step10000",
  "experiment_index": 20,
  "experiment_steps": 500,
  "global_step_start": 9500,
  "global_step_end": 10000,
  "stage": 6,
  "global_step": 10000,
  "overall_status": "PASS | FAIL | BLOCKED | NOT RUN",
  "inference_status": "PASS | FAIL | BLOCKED | NOT RUN",
  "inference_executed": true,
  "dataset_integrity": "PASS",
  "leakage_audit_status": "PASS",
  "checkpoint": {"model_version": "ZYRQUEN-Native-0.2.0", "checkpoint_sha256": "<64-hex>", "verified": true},
  "splits": {
    "train": {"evaluated": 480, "exact_match": 0.0, "diagnostic_only": true},
    "validation": {"evaluated": 480, "exact_match": 0.0},
    "unseen": {"evaluated": 480, "exact_match": 0.0, "unseen_entity_copy_acc": 0.0},
    "ood": {"evaluated": 480, "exact_match": 0.0, "unseen_entity_copy_acc": 0.0}
  },
  "capability_evaluation": {
    "abstract_reasoning": {"status": "NOT RUN", "splits": {}},
    "relational_generalization": {"status": "NOT RUN", "splits": {}},
    "ood_transfer": {"status": "NOT RUN", "splits": {}},
    "multi_step_planning": {"status": "NOT RUN", "splits": {}},
    "self_verification": {"status": "NOT RUN", "splits": {}},
    "knowledge_integration": {"status": "NOT RUN", "splits": {}}
  },
  "metrics": {},
  "regression_comparison": [],
  "acceptance_assessment": {"criteria": {}, "stop_criteria_triggered": []}
}
```

---

## 7. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `EvaluationEngine.evaluate_native_model` สามารถขยายให้รับ `splits=("train", "validation", "unseen", "ood")` (พร้อม `max_examples_per_split` สำหรับ `train` diagnostic slice) ได้โดยรักษาความเข้ากันได้กับ V10
- Token generation length `max_new_tokens = 48` หรือ `64` เพียงพอสำหรับแผน 5–6 ขั้นตอนใน `multi_step_planning` (ปรับจาก `32` ของ V10)

### OPEN DECISIONS
- **OD-EP-01:** ตัวเลขเกณฑ์ขั้นต่ำราย Capability และราย Split สำหรับ Stage 2–6 (เช่น `unseen_exact_match >= X`, `ood_exact_match >= Y`) — **ตั้งใจเว้นเป็นตัวเลขสุดท้ายจนกว่าจะได้ Baseline จริงของ V10 เพื่อไม่ให้ตั้งเป้าหมายลอยตัว**
- **OD-EP-02:** ค่า `max_new_tokens` มาตรฐานสำหรับการประเมิน V11 (`48` vs `64`) เพื่อให้ Multi-step plan `5–6` ขั้นไม่ถูกตัดกลางคัน
- **OD-EP-03:** ค่า Tolerance ของ Stage-to-Stage Replay Regression (`-0.02` ชั่วคราวระหว่าง Stage 3–5 ก่อนบังคับ `>= 0.0` ใน Stage 6 vs `-0.01` เข้มงวดทุก Stage)

### NOT VERIFIED
- **V10 Runtime Baseline:** แม้ V10-A..D Static/Governance/Hook Closure Audit ผ่านแล้ว แต่คอนเทนเนอร์ปัจจุบันยังไม่มี `torch` — จึงยัง **NOT VERIFIED / NOT RUN** สำหรับคะแนนน้ำหนักจริงของ V10 ที่ต้องใช้เป็น Baseline ใน `regression_comparison`
- เวลาเฉลี่ยในการประเมิน 4 Splits (`480 × 3 + 240 = 1,680` examples) บน CPU 2–4 threads ยัง **NOT VERIFIED** เนื่องจากยังไม่มี `torch` ใน container
- พฤติกรรม `TF - FG` exposure gap ของ `ZyrquenModel` บนแผน 5–6 ขั้นตอน ยัง **NOT VERIFIED**
