# ZYRQUEN Ω∞ — V11 Evaluation Plan (4 Splits & Anti-False-PASS)

- **Document ID:** `V11-DOC-10`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Core Engine:** `apps/core/native/evaluation/engine.py::EvaluationEngine` + `apps/core/workflow/handlers/groups.py::handle_evaluation_gate`

---

## 1. Non-Negotiable Truth & Anti-False-PASS Rules

1. **Zero Fabricated Metrics:** ห้ามสร้างตัวเลขจากการสุ่ม Mock, Dummy metrics, หรือ Formula แทนที่การทำ Inference จริง (`EvaluationEngine.evaluate_native_model` ใช้ `ZyrquenModel` Greedy Decoding จริงเท่านั้น)
2. **Strict Status Isolation:** `NOT RUN`, `BLOCKED`, `FAIL`, `PENDING`, `UNKNOWN` ห้ามถูกตีความว่าเป็น `PASS` หรือ `0.0` (คงมาตรฐานเดียวกับ `ModelRegistry._DISALLOWED_EVAL_STATUSES` และ `handle_evaluation_gate`)
3. **Mandatory Provenance Binding:** ทุก Evaluation Report ต้องฝัง `model_version`, `checkpoint_sha256`, `tokenizer_sha256`, `dataset_content_hash`, `report_sha256`, และ `inference_executed = True` จึงจะถูกแนบเป็น `evaluation_evidence` ได้
4. **Zero-Regression Enforcement:** รายงานเปรียบเทียบ (`regression_comparison`) ต้องมีรายการจริง (ห้ามผ่านเพราะ `[]` หรือ missing) และไม่มี Metric ใดลดลงเกิน `0.01` (`val_loss` เพิ่มเกิน `0.01` ถือว่า Regressed ตาม `ModelRegistry.compare_versions`)

---

## 2. Four-Split Evaluation Protocol

ทุก Checkpoint Checkpoint-Gate ประเมินแยกขาดทั้ง **4 Splits** (`permute_slots=False`, greedy decoding `temperature=0`, `max_new_tokens=32` หรือตาม schema ยาวสุดของแผน):

| Split | Isolation Guarantee | Role in Evaluation | Counts toward Release Gate? |
|---|---|---|---|
| **`train` (diagnostic slice)** | Train pool | วัด Optimization Progress, Overfitting Gap (`train_exact - validation_exact`), และ `TF - FG` Exposure Gap | Diagnostic only (ห้ามใช้รับรอง PASS) |
| **`validation`** | Disjoint `VA_*` entities + templates | Stage Gate Decision, Learning Rate / Early Stop Check, Per-Capability Calibration | **Yes (Stage Gate)** |
| **`unseen`** | Disjoint `UN_*` entities + unseen phrasings | วัด Entity Generalization และ Template Invariance (in-distribution structural depth) | **Yes (Mandatory)** |
| **`ood`** | Disjoint `OO_*` entities + unseen templates + unseen structural depth/relations | วัด Compositional Length Transfer (4–6 hops), Unseen Operators และ Anti-Shortcut Resistance | **Yes (Mandatory)** |

---

## 3. Per-Stage Evaluation Gates (Stages 1–6)

| Stage (Step) | Mandatory Checks | Target Gate (Provisional Blueprint Thresholds) |
|---|---|---|
| **Stage 1 (1,000)** | Finite `val_loss`, `eos_hit_rate`, SFT format compliance | `val_loss` finite & lower than init; `eos_hit_rate >= 0.90`; `validation_exact > random_guess` |
| **Stage 2 (3,000)** | Stage 1 checks + `abstract_reasoning` + `relational_generalization` on `validation` & `unseen` | Exact match improves monotonically vs Stage 1; `unseen_entity_copy_acc` measurable (never `N/A`) |
| **Stage 3 (5,000)** | Stage 2 retention + `multi_step_planning` exact match + `impossible` recall | Planning exact match meets stage floor; Stage 2 caps zero-regression |
| **Stage 4 (7,000)** | Stage 3 retention + `knowledge_integration` override/conflict accuracy + Grounded provenance checks | Conflict & Override discrimination >= stage floor; zero PII/cross-tenant leak |
| **Stage 5 (8,500)** | Stage 4 retention + `self_verification` (`claim` & `plan` classification) + `TF - FG` gap audit | Verification gate pass; `TF - FG` exposure gap controlled |
| **Stage 6 (10,000)** | **Full Final Suite:** 6 Capabilities × 4 Splits + V10 Baseline Comparison + Phase 20 End-to-End & SLO Check | Zero-Regression vs V10 & all prior stages; All 6 Capabilities PASS on `validation`, `unseen`, `ood` |

---

## 4. Measured Metrics Set per Evaluation Run

- `exact_match` (overall & per split: `train_exact_match`, `validation_exact_match`, `unseen_exact_match`, `ood_exact_match`)
- `cap_<capability>_accuracy` (สำหรับทั้ง 6 capabilities แยกตาม split)
- `eos_hit_rate` (อัตราที่โมเดลหยุดด้วย `<|eos|>` ก่อนเต็ม `max_new_tokens`)
- `unseen_entity_copy_acc` (ความแม่นยำการคืน Entity ผ่าน `<slot_k>` restoration บน `unseen` & `ood`)
- `teacher_forced_exact` & `exposure_gap` (`TF exact - FG exact`)
- `abstention_precision_recall` (ความแม่นยำในการตอบ `"unknown"`, `"conflict"`, `"impossible"` เมื่อไม่มีคำตอบ)
- `val_loss` & `perplexity` (`apps/core/native/evaluation/metrics.py`)

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `EvaluationEngine.evaluate_native_model` สามารถขยายพารามิเตอร์ `splits` จาก `("validation", "test")` เป็น `("validation", "unseen", "ood")` ได้โดยยังคง backward compatibility กับ V10
- โมเดล V11 เมื่อผ่านการฝึก `10,000` Steps สามารถประเมิน 4 Splits รวม ~1,500 ตัวอย่างบน CPU ได้ภายใน timeout budget ที่ยอมรับได้

### OPEN DECISIONS
- **OD-EP-01:** การกำหนดตัวเลข Threshold ขั้นต่ำเชิงปริมาณสำหรับ `validation`, `unseen`, และ `ood` ใน Stage 6 (เช่น `unseen >= 0.70` / `ood >= 0.55` vs ค่าเปรียบเทียบเหนือ V10 Baseline จริง) — **ต้องตั้งเป็นตัวเลขสุดท้ายหลังได้ผล Baseline จริงจาก V10 เพื่อไม่ให้ตั้งเกณฑ์ลอยตัว**
- **OD-EP-02:** `max_new_tokens` ใน Evaluation (แนะนำ `48` หรือ `64` แทน `32` สำหรับ `multi_step_planning` ที่มีแผน 5–6 ขั้นตอน)

### NOT VERIFIED
- ความเร็ว Inference ต่อตัวอย่าง (`ms/sample`) บน CPU และ HONOR X6b สำหรับ 4-split evaluation ยัง **NOT VERIFIED**
- คะแนน Baseline ของ V10 ที่จะใช้เป็นฐานเปรียบเทียบ `regression_comparison` ยัง **NOT VERIFIED / NOT RUN**
