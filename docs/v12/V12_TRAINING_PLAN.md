# ZYRQUEN Ω∞ — V12 Training Plan (50,000 Cumulative Steps)

- **Document ID:** `V12-DOC-05`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Target Cumulative Horizon:** `50,000` Optimizer Steps (`6` Stages, `>= 100` Sequential Verified Experiments)
- **Step Accounting Rule:** ทุก Step ที่นับรวมต้องมาจาก Verified Checkpoints และไม่มี Step ที่ถูก Rollback รวมอยู่

---

## 1. Global Steps vs. Experiment Steps Contract

ตามข้อจำกัด `apps/core/workflow/autonomous_training_loop.py::MAX_STEPS = 500` ต่อ 1 Training Run:
- **Experiment Steps (`exp_steps`):** จำนวน Optimizer Steps ใน 1 Run ที่ได้รับ Tier-2 Approval (`1 <= exp_steps <= 500` ภายใต้ Policy ปัจจุบัน; หากอนุมัติขยาย Cap ต้องอัปเดตเอกสารและ Tier-2 Policy ก่อน)
- **Global Cumulative Steps (`global_step`):** ตัวนับสะสมข้าม Runs (`0 -> 50,000`) ที่บันทึกใน Checkpoint Manifest และ Model Registry Lineage
- **Strict Accounting Formula:**
  $$\text{global\_step}_{\text{after}} = \text{global\_step}_{\text{parent}} + \text{verified\_steps}_{\text{run}}$$
  หาก Run ใดล้มเหลว (NaN, OOM, Evaluation Gate FAIL) **ห้าม** บวก Steps ของ Run นั้นเข้า `global_step` และต้อง Resume จาก `last_verified_checkpoint` เท่านั้น

---

## 2. Detailed 6-Stage Training Schedule (`50,000` Steps)

| Stage | Stage Name | Global Step Range | Stage Steps | Min Experiments (`<= 500`/exp) | Curriculum Mix (Primary -> Maintenance) | LR Schedule Policy | Mandatory Exit Gate |
|---|---|---|---:|---:|---|---|---|
| **Stage 1** | **Native Representation** | `1 – 5,000` | `5,000` | `10` (`EXP-001..010`) | 70% Format/Slot/EOS Alignment, 30% Simple 1–2 Hop Primitives | Linear Warmup (`500` steps) -> Cosine Peak `3e-4` | Finite Loss, `eos_hit_rate >= 0.95`, Slot Integrity 100% |
| **Stage 2** | **Knowledge Acquisition** | `5,001 – 13,000` | `8,000` | `16` (`EXP-011..026`) | 60% Provenance Facts & Domain Schemas, 40% Stage 1 Replay | Cosine `2.5e-4 -> 1.5e-4` | `knowledge_integration` gain > V11; Stage 1 retention >= 98% |
| **Stage 3** | **Abstract & Relational Reasoning** | `13,001 – 23,000` | `10,000` | `20` (`EXP-027..046`) | 65% Abstract + Relational (2–5 hops + distractors), 35% Stage 1–2 Replay | Cosine `2e-4 -> 1e-4` | `abstract_reasoning` & `relational` PASS on `unseen`; zero regression |
| **Stage 4** | **Multi-step Planning & OOD Transfer** | `23,001 – 33,000` | `10,000` | `20` (`EXP-047..066`) | 60% Planning DAG + Long-Horizon OOD, 40% Stage 1–3 Replay | Cosine `1.5e-4 -> 8e-5` | `multi_step_planning` & `ood_transfer` PASS on `ood`; zero regression |
| **Stage 5** | **Memory & Knowledge Integration** | `33,001 – 41,000` | `8,000` | `16` (`EXP-067..082`) | 60% Grounded Memory Recall / Override / Conflict, 40% Stage 1–4 Replay | Cosine `1e-4 -> 5e-5` | Override vs Conflict & Tenant/PII Guard PASS; zero regression |
| **Stage 6** | **Self-Verification & Capability Integration** | `41,001 – 50,000` | `9,000` | `18` (`EXP-083..100`) | 50% Self-Verification (`true`/`false`/`unknown`, `fact`/`assumption`), 50% Balanced Joint Replay (All 6 Caps) | Cosine Decay `8e-5 -> 1e-5` | Full 4-Split Eval PASS (`V12 vs V11 & V10`); **V12 Final Gate PASS** |
| **Total** | — | **`1 – 50,000`** | **`50,000`** | **`100`** | — | — | **Complete V12 Milestone** |

### Cross-Stage Curriculum Rule: Native Software Engineering (Inside Existing 6 Stages)

- **ห้ามเพิ่ม Stage 7 และห้ามขยายยอดรวมเกิน `50,000` Cumulative Steps:** ความสามารถด้าน Software Engineering (`CAP-SE-01..10`) กระจายตัวเป็น Cross-Stage Modules ตั้งแต่ Stage 1–6:
  - **Stage 1–2:** Requirement Decomposition, Structured Schema/Code Formatting, Pattern Acquisition ครอบคลุม 8 App Domains
  - **Stage 3–4:** Architecture DAG Design, Database Schema & API Contract Reasoning, Modular Full-Stack Code & UI Component Generation (รวม Transfer ข้าม App Domains ใน `ood`)
  - **Stage 5–6:** Multi-File Memory Coherence (`MemoryStore`), Automated Test Synthesis, Compiler/Runtime Error Debugging, และ Security Patch Verification
- **No Unverified Sub-Allocation:** สัดส่วน % ต่อ Stage ของ Software Engineering Tasks จะกำหนดเป็นตัวเลขทางการต่อเมื่อมี Verified SE Dataset Manifest และ CPU Token Throughput Benchmark แล้วเท่านั้น

---

## 3. Anti-Forgetting Replay & Stability Rules

1. **Replay Ratio Floor:** ทุก Stage ตั้งแต่ Stage 2–6 ต้องคง Replay Mixture จาก Stage ก่อนหน้าไม่น้อยกว่า `35% – 50%` เพื่อป้องกัน Catastrophic Forgetting ตลอด 50,000 Steps
2. **Boundary Micro-Check:** ทุก `500` Steps (`1` experiment) ต้องรัน Validation Mini-Eval + Regression Check ก่อนอนุญาตให้ออก Checkpoint ถัดไป
3. **Inter-Stage Gate:** ห้ามข้ามขึ้น Stage ถัดไป (เช่น Stage 2 -> Stage 3) หาก Stage ปัจจุบันยังไม่ผ่าน `EvaluationEngine` + Gate Criterion ของ Stage นั้น

---

## 4. Immediate Automatic Stop Conditions

หยุด Training Loop และตีสถานะเป็น `FAILED` / `STOPPED_FOR_REVIEW` ทันทีหากพบข้อใดข้อหนึ่ง:
- `NaN` หรือ `Inf` ใน Loss หรือ Gradient Norm ติดต่อกัน
- `grad_norm > 10.0` ติดต่อกัน `3` logging windows
- Memory RSS แตะ `RAM_HARD_GB` (`3.5 GB`) หรือ Disk เหลือน้อยกว่า `DISK_RESERVE_GB` (`2.0 GB`)
- `eos_hit_rate < 0.85` หลัง Step `1,000` (บ่งชี้ Exposure Bias / Termination Collapse)
- Loss Collapse (Loss ลดลงใกล้ `0` พร้อม `unseen`/`ood` Accuracy ร่วงลง -> Overfit/Memorization Alert)
- Data Corruption หรือ Hash Mismatch ของ Dataset / Tokenizer / Parent Checkpoint

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Learning Rate (`3e-4` ลงสู่ `1e-5`) และ Replay Ratio (`35–50%`) เป็นค่าตั้งต้นเชิงวิศวกรรมที่จะปรับจูนตาม **V11 10K Actual Convergence Curve** ก่อนเริ่ม Stage 1 ของ V12
- `Optimizer` ที่ใช้คือ `AdamW` (`weight_decay=0.01..0.05`, `betas=(0.9, 0.95)`)

### OPEN DECISIONS
- **OD-V12-TRN-01:** ปรับใช้ Continuous Cosine Decay ยาว `50,000` steps หรือ Stage-wise Cosine Warm-Restarts (อิงผล Stability จาก V11 Stage 1–6)
- **OD-V12-TRN-02:** Batch Size / Gradient Accumulation Configuration บน CPU เพื่อรักษา Effective Batch Size คงที่โดยไม่เกิน `RAM_SOFT_GB = 3.0 GB`

### NOT VERIFIED
- ความเร็ว Training (`sec/step`) รวมของ `50,000` Steps บน Hardware จริงยัง **NOT VERIFIED**
- ประสิทธิผลของการป้องกัน Catastrophic Forgetting ด้วย `35–50%` Replay บนโมเดล `<= 5M` parameters ตลอด 50,000 Steps ยัง **NOT VERIFIED**
