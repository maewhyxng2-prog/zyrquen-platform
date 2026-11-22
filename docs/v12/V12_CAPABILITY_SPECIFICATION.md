# ZYRQUEN Ω∞ — V12 Capability Specification

- **Document ID:** `V12-DOC-04`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Core Capabilities:** 6 Verifiable Native Intelligence Domains
- **Verification Principle:** ทุกความสามารถต้องมี Deterministic Ground Truth หรือ Formal Verification Rule — ห้ามใช้ Subjective Scoring หรือ LLM-as-a-Judge

---

## 1. Six Core Capability Domains & Stage Mapping

| ID | Capability | Primary Training Stages | Quantitative Scope in V12 (50K) | Primary Code / Eval Key |
|---|---|---|---|---|
| **CAP-01** | `abstract_reasoning` | Stage 1, 3, 6 | Deduction & Induction เชิงสัญลักษณ์ 2–5 hops, Negation, Conditional Rules, Distractor Filtering | `cap_abstract_reasoning_accuracy` |
| **CAP-02** | `relational_generalization` | Stage 1, 3, 6 | Multi-hop Family/Graph/Ordering Relations (Transitive, Symmetric, Inverse) บน Unseen Entities | `cap_relational_generalization_accuracy` |
| **CAP-03** | `ood_transfer` | Stage 4, 6 | Depth Extrapolation (6–10+ hops เมื่อ Train <= 4 hops), New Templates & Novel Relation Compositions | `cap_ood_transfer_accuracy` |
| **CAP-04** | `multi_step_planning` | Stage 4, 6 | Dependency DAG Action Ordering, Precondition Verification, Explicit `impossible` / Cycle Detection | `cap_multi_step_planning_accuracy` |
| **CAP-05** | `knowledge_integration` | Stage 2, 5, 6 | Grounded Acquisition จาก Provenance `[source=...]`, Conflict Detection & Latest-Valid Belief Revision | `cap_knowledge_integration_accuracy` |
| **CAP-06** | `self_verification` | Stage 5, 6 | Claim Audit (`true`/`false`/`unknown`), `fact`/`assumption`/`unverified` Separation (Phase 16), Plan Check | `cap_self_verification_accuracy` |

---

## 2. Canonical I/O Contract (Across All 6 Capabilities)

- **Prompt Framing:** ใช้ `SFT_FORMAT_VERSION = "zyrquen.sft.v1"` และตัวคั่น `SFT_SEP = "\n### Response:\n"` เสมอ
- **Entity Representation:** ใช้ Atomic Slots `<slot_0>..<slot_31>` แทนชื่อ Entity ดิบ เพื่อขจัด Tokenizer Subword Leakage (EL-05)
- **Strict Output Discipline:**
  - ไม่มีข้อความฟุ่มเฟือย, ไม่มี Preamble ของแชทบอท
  - ปิดท้ายคำตอบด้วย `<eos>` เสมอ (`eos_hit_rate` ต้องวัดทุก Evaluation)
  - ห้ามเดาคำตอบเมื่อหลักฐานไม่พอ: ต้องคืน `unknown` หรือ `conflict` หรือ `impossible` ตาม Canonical Label

---

## 3. Capability-Specific Acceptance Criteria (Blueprint Targets)

| Capability | Stage Exit Focus | Zero-Shortcut Validation Rule |
|---|---|---|
| **CAP-01 Abstract Reasoning** | Stage 3 (`Step 23,000`) | เปลี่ยน Variable Binding (`<slot_i>`) ต้องยังตอบถูก; สลับตำแหน่ง Premise + ใส่ Distractor >= 3 ข้อ ต้องไม่ตกหลุม Keyword Match |
| **CAP-02 Relational Generalization** | Stage 3 (`Step 23,000`) | ใช้ Entity Set ที่ไม่เคยอยู่ด้วยกันใน Train (`unseen`) และห้ามจำคู่ `(entity_a, entity_b)` |
| **CAP-03 OOD Transfer** | Stage 4 (`Step 33,000`) | ต้องทดสอบกับ Graph/Reasoning Depth ที่ลึกกว่า Distribution ใน Train (`>= 6 hops`) และ Phrasing ใหม่ที่ไม่เคยฝึก |
| **CAP-04 Multi-step Planning** | Stage 4 (`Step 33,000`) | ตรวจ Topological Validity + Precondition Satisfaction ผ่าน Exact Simulator และตรวจจับกรณี `impossible` ที่ทำไม่ได้จริง |
| **CAP-05 Knowledge Integration** | Stage 5 (`Step 41,000`) | แยกให้ออกระหว่าง **Update/Override** (Timestamp/Authority ชัดเจน) กับ **Irreconcilable Conflict** (`conflict`) และอ้างอิง `[source=...]` ถูกต้อง |
| **CAP-06 Self-Verification** | Stage 6 (`Step 50,000`) | False Claim Acceptance Rate ต้องลดลงเทียบกับ Stage 1–4 และต้องไม่เปลี่ยนคำตอบถูกเป็นผิด (Calibration Retention) |

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เกณฑ์ Exact-Match ขั้นต่ำเชิงตัวเลข (เช่น `>= 0.75` หรือ `>= 0.85` บน `unseen`/`ood`) จะถูกล็อกเป็นตัวเลขทางการหลังได้รับ **V10 Runtime Baseline** และ **V11 10K Final Baseline** แล้ว เพื่อไม่ให้ตั้งตัวเลขลอยๆ โดยขาดฐานอ้างอิง

### OPEN DECISIONS
- **OD-V12-CAP-01:** การกำหนด Threshold เชิงตัวเลขของแต่ละ Capability (`min_unseen_accuracy`, `min_ood_accuracy`) หลังเห็น V11 Stage 6 Actual Metrics
- **OD-V12-CAP-02:** รูปแบบ Exact Partial-Credit Metric สำหรับ `multi_step_planning` (ควบคู่กับ Strict Exact Sequence Match) เมื่อแผนถูกต้องได้หลาย Topological Orders

### NOT VERIFIED
- ความสามารถจริงของ `ZyrquenModel` ในทุก CAP-01..CAP-06 บน `50,000` Steps ยัง **NOT VERIFIED / NOT RUN**
- อัตราความสำเร็จบน OOD Depth `6–10+ hops` สำหรับโมเดลขนาด `<= 5M` ยัง **NOT VERIFIED**
