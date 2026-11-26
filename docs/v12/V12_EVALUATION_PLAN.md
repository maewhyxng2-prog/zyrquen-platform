# ZYRQUEN Ω∞ — V12 Evaluation Plan (50,000-Step Multi-Stage)

- **Document ID:** `V12-DOC-10`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Engine Anchor:** `apps/core/native/evaluation/engine.py::EvaluationEngine`
- **Strict Mandate:** Zero False-PASS, Zero Self-Grading Without Evidence, Mandatory 4-Split Evaluation & Baseline Regression Check

---

## 1. Evaluation Philosophy Across 50,000 Steps

ในโครงการ 50,000 Steps ความผิดพลาดที่อันตรายที่สุดคือ **Goodhart's Law / Evaluation Collapse** (Loss ลดลงสวยหรูบน Train แต่ความสามารถจริงบน Unseen/OOD หายไป หรือ Stage หลังทำลาย Stage แรก) ดังนั้นทุก Stage Exit และทุก Experiment Boundary ใน V12 ต้องวัดผลผ่าน `EvaluationEngine` แบบ **Free Autoregressive Generation (`do_sample=False`, Greedy Deterministic Decoding)** บน 4 Splits แยกกันอย่างชัดเจน:

1. **`train` (Diagnostic Audit Subset):** ตรวจ Optimization Health & Teacher-Forcing vs Free-Gen Gap (`tf_fg_gap`) — **ห้ามใช้เป็น Gate ผ่าน**
2. **`validation` (In-Distribution Holdout):** ตรวจ Convergence, Calibration, และ Per-Experiment Progress
3. **`unseen` (Unseen Entities & Combinations):** ตรวจ Generalization ข้าม Entity Pool ใหม่ทั้งหมด (`UN_*`)
4. **`ood` (Out-of-Distribution Structure & Depth):** ตรวจ Real Reasoning Transfer ข้าม Depth (`6–10+ hops`), Novel Templates, และ Unseen Relations (`OO_*`)

---

## 2. Evaluation Cadence (3-Tiered Verification Schedule)

| Evaluation Level | Frequency | Splits Covered | Required Output | Blocking Power |
|---|---|---|---|---|
| **Level A: Micro-Check** | ทุก `500` steps (จบทุก 1 Experiment `EXP-001..100`) | `validation` (subset) + Anti-Regression Probe | Loss finite check, `eos_hit_rate`, NaN/Collapse check, Mini-Eval Accuracy | Block Next Experiment ถ้าพัง/Collapse |
| **Level B: Stage Exit Gate** | จบทุก Stage (`Step 5K, 13K, 23K, 33K, 41K, 50K`) | **Full 4 Splits** (`train_diag`, `validation`, `unseen`, `ood`) | Full Per-Capability Metrics + `regression_comparison` vs Stage ก่อนหน้า & V11/V10 | **Hard Block** ห้ามขึ้น Stage ถัดไป |
| **Level C: Final V12 Gate** | Step `50,000` (จบ Stage 6) | **Full 4 Splits + Standalone & System E2E + Seed Stress** | Full Reproducible Audit Bundle + Registry Promotion Evidence | **Hard Block** ห้ามประกาศ V12 COMPLETE |

---

## 3. Mandatory Metrics Matrix (Reported Per Split)

ทุก Report JSON จาก `EvaluationEngine` ต้องมีครบทุก Field (ห้ามเว้นว่างหรือ Fake Placeholder):
- **`exact_match`:** Greedy Free-Generation String Match หลัง Canonical Normalization
- **`eos_hit_rate`:** สัดส่วนที่โมเดลสร้าง `<eos>` ภายใน `max_new_tokens` (บังคับ `>= 0.95` ใน V12)
- **`tf_fg_gap`:** `teacher_forced_token_acc - free_gen_exact_match` (ตรวจจับ Exposure Bias)
- **`calibration_ece` / `abstention_accuracy`:** วัดการตอบ `unknown` / `conflict` / `impossible` เมื่อหลักฐานไม่ครบ แทนการเดามั่ว
- **6 Capability Metrics:** `cap_abstract_reasoning_accuracy`, `cap_relational_generalization_accuracy`, `cap_ood_transfer_accuracy`, `cap_multi_step_planning_accuracy`, `cap_knowledge_integration_accuracy`, `cap_self_verification_accuracy`
- **`regression_comparison`:** Delta เทียบกับ **V10 Baseline**, **V11 10K Final Baseline**, และ **Prior V12 Stage Checkpoint** โดย `zero_regression = True` (หรือมี Negative Delta ใน Tolerance Gate ที่อนุมัติล่วงหน้าเท่านั้น)

### 3b. Native Software Engineering Execution Metrics (`CAP-SE-01..10`)

การประเมินแอปพลิเคชันที่ ZYRQUEN สร้างขึ้นห้ามใช้การให้คะแนนด้วยตาหรือ LLM ภายนอก ต้องวัดผ่าน **Deterministic Execution Harness** ตามเกณฑ์จริง:
- **`se_compile_pass_rate`:** สัดส่วนแอป/โมดูลที่ Build / Typecheck / Syntax Compile ผ่านจริง
- **`se_unit_test_pass_rate`:** อัตราการผ่านของ Unit Tests ที่ตรวจสอบตรรกะโมดูลย่อย
- **`se_integration_test_pass_rate`:** อัตราการผ่านของ API + Database Schema/Migration Integration Tests
- **`se_hidden_eval_pass_rate`:** อัตราการผ่านของ **Hidden Acceptance Tests** ที่โมเดลไม่เคยเห็นใน Prompt/Train
- **`se_security_check_pass_rate`:** อัตราการผ่านการตรวจ Static Scan + RBAC + Injection + Path Traversal Guards
- **`se_debug_repair_rate`:** อัตราที่โมเดลแก้ Bug จาก Real Compiler/Test Error Trace สำเร็จใน Sandbox โดยไม่ทำให้ Test เดิมพัง

---

## 4. Anti-False-PASS Rules (Zero Exceptions)

1. ถ้าขาดไฟล์ Split ใดใน 4 Splits (`validation`, `unseen`, `ood`), หรือ `regression_comparison` ว่าง (`{}`), หรือ `torch` Runtime ไม่มีจริง -> สถานะต้องเป็น `BLOCKED` หรือ `FAIL` เสมอ (ห้ามปัดเป็น `PASS`)
2. ห้ามใช้ Heuristic Solver ภายนอกแก้คำตอบแทน `ZyrquenModel` แล้วนำมาลงคะแนนเป็น Model Accuracy
3. ต้องรายงาน **Standalone Model Score** แยกจาก **Workflow/Memory-Assisted System Score** เสมอใน Stage 5–6

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เกณฑ์ตัวเลข Delta ขั้นต่ำเทียบกับ V11 (`V12_score >= V11_score + delta_target`) จะกำหนดอย่างเป็นทางการหลังได้ผล V11 Stage 6 จริง

### OPEN DECISIONS
- **OD-V12-EVL-01:** Tolerance Window ของ Anti-Regression Check ราย Stage (เช่น Allow jitter ไม่เกิน `-0.5%` บน Sub-capability หรือ Strict `>= 0.0%` ที่ Stage Boundaries)
- **OD-V12-EVL-02:** ขนาด Sample ต่อ Split สำหรับ Level B Stage Exit Gate เพื่อให้รัน Evaluation บน CPU จบภายใน Budget เวลาที่กำหนด

### NOT VERIFIED
- ระยะเวลารัน Full 4-Split Evaluation ของ `EvaluationEngine` บน CPU สำหรับโมเดล V12 ยัง **NOT VERIFIED / NOT RUN**
- ค่า `exact_match`, `eos_hit_rate`, และ `tf_fg_gap` จริงของ V10/V11/V12 ยัง **NOT VERIFIED**
