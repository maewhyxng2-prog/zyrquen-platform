# ZYRQUEN Ω∞ — V12 Self-Verification Specification

- **Document ID:** `V12-DOC-13`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Primary Training Window:** Stage 6 (`Self-Verification & Capability Integration`: steps `41,001–50,000`)
- **Governance Anchor:** Phase 16 Epistemic Verification Discipline & `V12_EVALUATION_PLAN.md`

---

## 1. Anti-Self-Deception Principle

ตามข้อบังคับหลักของ ZYRQUEN Ω∞:
> **ห้ามให้โมเดลประเมินตัวเองแล้วประกาศว่า "ผ่าน" โดยไม่มีหลักฐานที่ตรวจสอบได้อิสระ**

ดังนั้น **Self-Verification** ใน V12 มีความหมาย 2 ชั้นที่แยกขาดจากกัน:
1. **Model-Level Epistemic Self-Verification (ความสามารถภายในโมเดล — Stage 6):** โมเดลสามารถตรวจสอบข้อความอ้างอิง แผนงาน หรือคำตอบร่างเทียบกับ Premises เพื่อแยก `true` / `false` / `unknown`, แยก `fact` / `assumption` / `unverified`, และตรวจจับแผน `invalid_*` ก่อนส่งคำตอบ
2. **External Deterministic Gate Verification (กลไกตัดสินจากภายนอก — Workflow & Engine):** `EvaluationEngine` และ Deterministic Solvers ภายนอกโมเดลเป็นผู้ตัดสิน `PASS / FAIL` เสมอ — โมเดลไม่มีสิทธิ์ออก Score หรืออนุมัติตัวเอง

---

## 2. Four Core Verification Tasks in Stage 6 (`steps 41,001–50,000`)

| Task Code | Input Framing | Allowed Output Labels | Purpose |
|---|---|---|---|
| **SV-01: Claim Entailment** | Premise Set + Candidate Claim | `true`, `false`, `unknown` | ป้องกันการยืนยันคำกล่าวที่ไม่รองรับด้วย Premises |
| **SV-02: Epistemic Tagging** (Phase 16) | Reasoning Step / Statement + Grounded Context | `fact`, `assumption`, `unverified` | บังคับให้แยกข้อเท็จจริงที่มีหลักฐานออกจากสมมติฐานและสิ่งที่ไม่รู้ |
| **SV-03: Plan Trace Critique** | Goal + Preconditions + Proposed Action Sequence | `valid`, `invalid_precondition`, `invalid_cycle`, `invalid_goal` | จับข้อผิดพลาดในแผน Multi-step ก่อนตอบจริง |
| **SV-04: Abstention Calibration** | Underspecified / Missing-Premise Query | `unknown` / `insufficient_evidence` | ลด Confident Hallucination เมื่อข้อมูลไม่พอ |

---

## 3. Anti-False-Abstention & Safety Balance Metrics

โมเดลที่ขี้ขลาดเกินไปอาจตอบ `unknown` ทุกข้อเพื่อหลีกเลี่ยงความผิดพลาด Stage 6 จึงบังคับวัด 3 ตัวชี้วัดควบคู่กัน:
1. **`abstention_precision`:** ในบรรดาข้อที่โมเดลตอบ `unknown` มีกี่ % ที่โจทย์ขาดหลักฐานจริง (ป้องกันการขี้เกียจตอบในข้อที่แก้ได้)
2. **`unsupported_false_accept_rate`:** ในบรรดาข้อที่หลักฐานไม่พอหรือผิด โมเดลเผลอตอบ `true` / `valid` กี่ % (ต้องลดลงเมื่อเทียบกับ Stage 1–4)
3. **`core_reasoning_retention`:** การเพิ่ม SV-01..04 ใน Stage 6 **ต้องไม่ทำให้** `CAP-01..CAP-04` (Reasoning & Planning Accuracy) ตกลงเกิน Tolerance Gate

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Labels สำหรับ **SV-01..SV-04** ทั้งหมดถูกสร้างจาก Deterministic Entailment/Planning Verifiers ในชุดข้อมูล Stage 6 เท่านั้น (ปราศจาก External LLM Annotation)

### OPEN DECISIONS
- **OD-V12-SV-01:** เกณฑ์ตัวเลขขั้นต่ำของ `abstention_precision` และเพดานสูงสุดของ `unsupported_false_accept_rate` สำหรับ Stage 6 Final Gate (กำหนดหลังเห็น V11 Stage 5 Verification Baseline)

### NOT VERIFIED
- สมดุลระหว่าง Abstention Discipline กับ Reasoning Accuracy บน `ZyrquenModel` ที่ฝึกถึง `50,000` Steps ยัง **NOT VERIFIED / NOT RUN**
