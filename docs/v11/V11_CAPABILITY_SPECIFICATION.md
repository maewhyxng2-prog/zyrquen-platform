# ZYRQUEN Ω∞ — V11 Capability Specification

- **Document ID:** `V11-DOC-04`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`
- **Capability Foundation:** 6 Core Reasoning Capabilities (ต่อเนื่องจาก V10) + Memory Grounding + Structured Self-Verification

---

## 1. Capability Taxonomy & Contract

V11 กำหนดให้ทุกตัวอย่างและการประเมินผลผูกกับหนึ่งใน **6 Canonical Capabilities** (ตรงกับ `tools/gen_nagi_v10.py`, `tools/audit_leakage_v10.py`, และ `apps/core/workflow/handlers/groups.py::_V10_EXPECTED_CAPABILITIES`) พร้อมเพิ่มระดับความซับซ้อนเชิงโครงสร้างสำหรับ V11:

| # | Canonical Capability Key | Core Reasoning Task | V11 Elevation Over V10 | Target Output Contract |
|---|---|---|---|---|
| 1 | `abstract_reasoning` | Transitive partial/strict order DAG comparison & equivalence inference | Mixed order operators (`>`, `<`, `=`), distractor disconnected components, multi-branch paths, inverse queries | `{">", "<", "=", "unknown"}` |
| 2 | `relational_generalization` | Exact-hop directed graph traversal with distractor edge pruning | Shuffled premise ordering, higher entity fan-out (`3–5` distractors), exact walk uniqueness verified by solver | Exact single `<slot_k>` / restored Entity Name |
| 3 | `ood_transfer` | Variable-depth & unseen-relation path composition across splits | Explicit depth jump: `train` (2–3 hops), `validation` (3 hops unseen entities/templates), `unseen` (3 hops unseen phrasing), `ood` (4–6 hops + unseen relation names) | Exact single `<slot_k>` / restored Entity Name |
| 4 | `multi_step_planning` | Dependency-driven topological planning with prerequisite closure | Irrelevant goal pruning, cycle / missing-prereq `impossible` detection, multi-subgoal ordering | Canonical unique sequence `E_a -> E_b -> ...` หรือ `"impossible"` |
| 5 | `self_verification` | Claim & plan verification against constraints + Phase 16 step classification | Multi-defect audit (`valid`, `invalid_order`, `invalid_missing`, `invalid_cycle`), epistemic status separation (`fact`/`assumption`/`unverified`) | `{"true", "false", "unknown"}` หรือ `{"valid", "invalid_order", "invalid_missing", "invalid_cycle"}` |
| 6 | `knowledge_integration` | Belief revision (`base` + `update` + `retract`), conflict detection & grounded memory | Integration with Phase 17 `MemoryStore` attributes (`[source=...]`, `verified=true/false`, multi-tenant boundary, retract -> `unknown`) | Resolved Entity/Value หรือ `"conflict"` หรือ `"unknown"` |

---

## 2. Auxiliary Behavioral Requirements (Cross-Cutting)

1. **EOS Discipline:** โมเดลต้องสร้าง `<|eos|>` ทันทีหลังจบคำตอบที่ถูกต้อง ไม่สร้างข้อความส่วนเกิน (`eos_hit_rate` ถูกวัดเป็นเมตริกบังคับ)
2. **Epistemic Honesty (Non-Hallucination):**
   - เมื่อกราฟขาดการเชื่อมโยง ต้องตอบ `"unknown"` แทนการเดา entity
   - เมื่อมีข้อเท็จจริงขัดแย้งกันโดยไม่มี `update:` ต้องตอบ `"conflict"` แทนการเลือกข้าง
   - เมื่อแผนมี Cycle หรือขาดจุดตั้งต้น ต้องตอบ `"impossible"` แทนการเรียงลำดับเท็จ
3. **Ephemeral Slot Generalization:** ความสามารถทั้ง 6 ด้านต้องทำงานได้โดยไม่พึ่งพาตัวอักษรชื่อ Entity ใดๆ ใน Vocabulary (`EL-05 = 0` leakage)

---

## 3. Out-of-Scope Capabilities (Explicit Non-Goals for V11)

- Open-ended creative chatbot roleplay หรือ casual chit-chat generation
- Unrestricted OS/shell execution หรือ autonomous tool invocation ที่ไม่มี Human Approval Token (ต้องถูกบล็อกโดย Phase 16 `ExecutionSafetyPolicy` และ Phase 19 Governance)
- Calling external LLMs/APIs เมื่อโมเดลหลักไม่มั่นใจ

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Unique-Answer Exhaustive Solvers สำหรับทุก Capability สามารถรันตรวจสอบทั้งตอน Generate และตอน Audit ได้ภายใน Pure Python Standard Library
- ความสามารถที่ 6 (`knowledge_integration`) และที่ 5 (`self_verification`) สามารถแทนที่ในรูปแบบ SFT structured text ที่มีความยาวรวมไม่เกิน `250` structural tokens เพื่อรองรับ `max_seq_len = 256`

### OPEN DECISIONS
- **OD-CS-01:** ใน Capability `abstract_reasoning` จะเพิ่มสัญลักษณ์ `"="` และใน `knowledge_integration` จะเพิ่ม `retract:` เข้าชุดข้อมูล V11 ตั้งแต่ Stage 4 หรือเริ่มที่ Stage 2/4 ตามลำดับ
- **OD-CS-02:** ความยาว hop สูงสุดของ Split `ood` (`4–5` hops vs `4–6` hops) ภายใต้ข้อจำกัด `max_seq_len = 256` tokens

### NOT VERIFIED
- ประสิทธิภาพจริง (Exact-Match Score) ของทั้ง 6 Capabilities บน `ZyrquenModel` ขนาด `3.74M – 4.75M` พารามิเตอร์ยัง **NOT VERIFIED**
- การแยก `fact` / `assumption` / `unverified` ของโมเดลในเชิง Generative output ยังไม่มี Dataset ตัวอย่าง V11 ที่ Generate และผ่านการ Audit จริง
