# ZYRQUEN Ω∞ — V11 Release Gate Criteria

- **Document ID:** `V11-DOC-19`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Rule:** ห้ามประกาศ `V11 COMPLETE` หรือ Promotion ขึ้น `production` หาก Gate ใด Gate หนึ่งยังเป็น `FAIL`, `BLOCKED`, `NOT RUN`, หรือ `NOT VERIFIED`

---

## 1. Pre-Start Gate (Gate 0: Before Any V11 Code or Training)

- [ ] **V10 Final Closure Gate = `PASS`** (V10-A, V10-B, V10-C, V10-D ครบถ้วนและปิดช่องโหว่ Governance/False-PASS แล้ว)
- [ ] **V11 Blueprint Consistency Audit = `PASS`** (เอกสาร 22 ฉบับ + `README.md` ผ่านการตรวจและผู้ดูแลอนุมัติ)
- [ ] **Open Decisions Resolved:** ประเด็น `OD-*` ที่จำเป็นต่อ Stage 1 ได้รับการตัดสินใจเป็นลายลักษณ์อักษร

---

## 2. Implementation & Data Gate (Gate 1: Before Stage 1 Training)

- [ ] **V11 Dataset & Auditor PASS (`100%`):** `train`, `validation`, `unseen`, `ood` ผ่าน `INTEGRITY_MANIFEST`, `SCHEMA_VALIDATION`, `UNIQUE_ANSWER`, `EL-01..06`, `TL-01`, `SL-01`, `DL-01`, `SEQ_BUDGET`, และ `PII_HYGIENE` (Exit `0`)
- [ ] **Tokenizer Freeze & Leakage Free:** `tokenizer.json` (`zyrquen.tokenizer.v2`) ฝึกจาก `train` split เท่านั้น, `EL-05 == 0`, และ `sha256` ล็อกแล้ว
- [ ] **All Tier 1–3 Automated Tests PASS (0 Failed, 0 Unaccounted Skip)**
- [ ] **PyTorch CPU Benchmark PASS:** ติดตั้ง `torch` และผ่าน Tier 4 Smoke Test + Segmented Resume Test + วัด Real Peak RSS `< 2.5 GB` & CPU sec/step ตรงกับ Budget
- [ ] **Tier-2 Admin HMAC Approval Issued** สำหรับ Stage 1

---

## 3. Execution & Training Gate (Gate 2: 6 Stages / 10,000 Steps)

- [ ] **Stages 1–6 Completed Sequentially:** ครบ `10,000` Steps โดยไม่มี `loss_diverged` (NaN/Inf), ไม่มี `ram_hard_stop`, ไม่มี `disk_reserve_violated`
- [ ] **All Stage Exit Gates Verified:** บันทึก Evaluation Report และ Milestone Snapshot หลังจบทุก Stage (`1000, 3000, 5000, 7000, 8500, 10000`)
- [ ] **Final Checkpoint Registered:** ลงทะเบียนเข้า `ModelRegistry` เป็น `ZYRQUEN-Native-X.Y.Z` พร้อมตรวจ `verify()` และ `check_compatibility()` = `True`

---

## 4. Final Quality, Safety & Zero-Regression Gate (Gate 3: Before Declaring `V11 COMPLETE`)

- [ ] **Real Native Inference Evaluation (`inference_executed = True`) PASS บนทั้ง 4 Splits (`train` diagnostic, `validation`, `unseen`, `ood`):**
  - ครบทั้ง 6 Capabilities (`abstract_reasoning`, `relational_generalization`, `ood_transfer`, `multi_step_planning`, `self_verification`, `knowledge_integration`)
  - ไม่มีค่า `N/A`, `NOT RUN`, `BLOCKED`, หรือ placeholder
  - `eos_hit_rate` ผ่านเกณฑ์ และ Abstention (`unknown`/`conflict`/`impossible`) ไม่ collapse
- [ ] **Zero Regression vs V10 Baseline & Earlier Stages:** `regression_comparison` ไม่ว่าง และ `zero_regression = True`
- [ ] **End-to-End Integration & Safety Verification:**
  - `Phase 16` (`validate_dag`, `verify_step`, `ExecutionSafetyPolicy`), `Phase 17` (`MemoryStore` tenant/PII isolation), `Phase 19` (Tool/HMAC governance), `Phase 20` (`SystemMaturity` End-to-End + SLO + Readiness Checklist) ผ่านครบ
  - Native-Only Audit: ยืนยัน `0` external weights / `0` external AI APIs ใน codebase
- [ ] **Baseline & Roadmap Protection Verified:** `v7`, `v8`, `v9`, `v10` และ `phases/phase11..20` ไม่ถูกลบหรือแก้ไขเสียหาย และไม่มี `Phase 21`
- [ ] **Separate Human Promotion Approval:** หากต้องการ Promote เป็น Active Model ต้องผ่าน `POST /v1/models/registry/{version}/promote` ด้วย Tier-2 HMAC Token จริง (ไม่มี Auto-Promote)

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เกณฑ์เชิงตัวเลข (Exact-Match Floors ต่อ Split/Capability) จะถูกเติมจากผลการวัดจริงของ V10 Baseline และ Stage 1 Calibration ก่อนล็อก Gate 3

### OPEN DECISIONS
- **OD-RG-01:** ค่า Exact-Match ขั้นต่ำของ `unseen` และ `ood` สำหรับ Stage 6 Release Gate (ต้องตกลงหลังเห็น V10 Baseline Real Run)
- **OD-RG-02:** ความหมายของคำว่า "V11 COMPLETE": ปิดระดับ Research/Verified Staging Candidate หรือต้อง Promote ขึ้น `production` ด้วย (แนะนำให้แยก **V11 Research & Gate Complete = `verified`/`staging`** ออกจากการ **Production Deploy** ที่ต้องขออนุมัติแยก)

### NOT VERIFIED
- เกณฑ์ Gate 0–3 ทั้งหมดยัง **NOT PASSED / LOCKED** ในปัจจุบัน
- ค่า Latency/SLO (`latency <= 500ms`, `error_rate <= 0.01`) ของ `ZyrquenModel` บน CPU ขณะทำ 4-split หรือ API inference ยัง **NOT VERIFIED**
