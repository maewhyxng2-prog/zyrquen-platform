# ZYRQUEN Ω∞ — V11 Self-Verification Specification

- **Document ID:** `V11-DOC-13`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Existing Subsystem Anchors:**
  - `phases/phase16.py` (`ReasoningStep`, `ReasoningPipeline`, `validate_dag`, `verify_step`, `ExecutionSafetyPolicy`)
  - `apps/core/intelligence/contract.py` (`validate_result`, `ContractViolation`)

---

## 1. Dual-Layer Self-Verification Architecture

V11 ออกแบบการตรวจสอบตนเองเป็น **2 ชั้นที่ทำงานเสริมกัน (Neural + Deterministic Guard)**:

### Layer 1: Neural Self-Verification Capability (Stage 5 Training)
ฝึกโมเดล `ZyrquenModel` ใน Capability `self_verification` ให้ตรวจความถูกต้องของคำกล่าวอ้างและแผนงานจากข้อมูลในบริบท:
1. **Claim Verification:** ตรวจสอบข้อสรุปกับข้อเท็จจริงและส่งออก `"true"`, `"false"`, หรือ `"unknown"`
2. **Plan Audit:** ตรวจสอบแผนขั้นตอนที่เสนอมาเทียบกับ Dependency DAG และส่งออกหนึ่งใน 4 สถานะเท่านั้น:
   - `"valid"` — ครบถ้วนและลำดับถูกต้องตาม Prerequisites
   - `"invalid_order"` — มีขั้นตอนครบแต่ลำดับผิด Dependency
   - `"invalid_missing"` — ขาดขั้นตอน Prerequisite ที่จำเป็น
   - `"invalid_cycle"` — Dependency มีวงจรปิด
3. **Epistemic Status Tagging (Phase 16 Contract Alignment):** แยกข้อมูลใน Reasoning trace ออกเป็น `fact` (มี `evidence` รองรับ), `assumption` (สมมติฐาน), และ `unverified` (ยังไม่ผ่านการตรวจ) เพื่อไม่ให้สมมติฐานถูกยกระดับเป็นข้อเท็จจริง

### Layer 2: Deterministic Runtime & Contract Guard (Zero Bypass)
ผลลัพธ์จาก Neural Layer **ไม่เคย** ได้รับอนุญาตให้ execute action ใดๆ โดยตรง แต่ต้องผ่านการตรวจแบบ Deterministic ก่อน:
1. **DAG Structural Gate (`phases/phase16.py::validate_dag`):** ปฏิเสธ (`BLOCK`) แผนที่มี duplicate task ID, missing dependency, หรือ cycle ทันที
2. **Reasoning Result Contract (`apps/core/intelligence/contract.py::validate_result`):** ห้ามรายงาน `model_inference=True` โดยไม่มี `native_model_evidence` จริง (`model_id` + non-empty `response`)
3. **Execution Safety Policy (`phases/phase16.py::ExecutionSafetyPolicy`):** Default-Deny สำหรับ `action["type"] == "execution"` — ต้องรันใน `sandbox="isolated"`, มี Human Approval Token, และอยู่ใต้ token hard cap
4. **Verifier Fail-Closed (`phases/phase16.py::verify_step`):** หากไม่มี `checker` หรือ `checker` error ให้คืน `"BLOCKED"` เสมอ ห้าม fallback เป็น `"PASS"`

---

## 2. Anti-Hallucination & Self-Correction Loop Rules

- หาก Neural output ขัดแย้งกับ Deterministic DAG check หรือ Slot integrity (เช่น คืน `<slot_99>` ที่ไม่ได้ bind ไว้) ระบบต้อง Flag สถานะเป็น `FAIL` / `unverified` และ **ห้ามซ่อน Error หรือสร้างคำตอบใหม่โดยใช้ External AI**
- จำนวน Step ใน `ReasoningPipeline` จำกัดด้วย Hard Cap (`max_steps = 20`) เพื่อกัน Infinite Reasoning Loops บน CPU

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Neural classifier (`true`/`false`/`unknown` และ `valid`/`invalid_*`) สามารถเรียนรู้ขอบเขตการขาดข้อมูล (`unknown`) และการสลับลำดับ (`invalid_order`) ได้ใน Stage 5 (`1,500` steps + replay)
- Deterministic Layer ใน `phases/phase16.py` และ `apps/core/intelligence/contract.py` มีเสถียรภาพเพียงพอและไม่จำเป็นต้องแก้ไขไฟล์ `phases/phase16.py`

### OPEN DECISIONS
- **OD-SV-01:** ใน Runtime Pipeline, หาก Neural model ตอบ `plan` แล้วไม่ผ่าน Deterministic `validate_dag`, จะคืน error/unverified ทันที (1-pass strict, recommended for CPU budget) หรืออนุญาต Retry พร้อม Diagnostic feedback (จำกัด `<= 2` attempts ใต้ token cap)
- **OD-SV-02:** รูปแบบ Structured Output ของ `ReasoningStep` เมื่อต้องการให้โมเดลสร้าง Reasoning trace ร่วมกับคำตอบสุดท้ายภายใต้ `256`-token window

### NOT VERIFIED
- ความแม่นยำจริงของ `self_verification` บน `invalid_order` vs `invalid_missing` กับแผน 4–6 ขั้นตอนใน `ood` split ยัง **NOT VERIFIED**
- End-to-end latency ของ Neural generation + `validate_dag` + `verify_step` ใน runtime จริงยัง **NOT VERIFIED**
