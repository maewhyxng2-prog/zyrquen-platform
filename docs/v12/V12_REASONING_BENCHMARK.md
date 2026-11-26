# ZYRQUEN Ω∞ — V12 Reasoning & OOD Benchmark Suite

- **Document ID:** `V12-DOC-11`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Scope:** Deep Structural Reasoning, Relational Generalization, Multi-step Planning & 6–10+ Hop OOD Transfer
- **Verification Rule:** Deterministic Graph/Logic Exact Verifier Only — No Subjective LLM Judges

---

## 1. Purpose: Measuring True Native Generalization at 50K Steps

ชุดทดสอบ V12 Reasoning Benchmark ถูกออกแบบมาเพื่อแยกให้ขาดระหว่าง **"การจำแพทเทิร์นจาก 50,000 Steps"** กับ **"การเข้าใจโครงสร้างเชิงเหตุผลอย่างแท้จริง"** โดยอัดความท้าทายในมิติ Depth Extrapolation, Distractor Injection, Variable Permutation, และ Unfeasible Detection

---

## 2. Benchmark Suites (`RB-01` .. `RB-06`)

| Suite ID | Domain | Test Structure & Difficulty Scaling | Anti-Shortcut / Perturbation Test |
|---|---|---|---|
| **RB-01** | **Symbolic Abstract Deduction** | Modus Ponens, Modus Tollens, Disjunctive Syllogism, Negation Chains (3–6 steps) | **Distractor Injection:** ใส่กฏหลอก >= 4 ข้อที่มี Keyword ใกล้เคียง; **Permutation:** สลับลำดับ Premises ทั้งหมด |
| **RB-02** | **Relational Graph Composition** | Multi-hop Kinship / Causal / Ordering Graphs (Transitive, Inverse, Symmetric) | **Slot Reshuffle Test:** ประเมินคู่ Prompt เดิมที่สลับ `<slot_i>` Binding ใหม่ 3 Seeds; Consistency Must Hold |
| **RB-03** | **OOD Depth Extrapolation** | Train สูงสุด 4 hops -> ทดสอบ `ood` ที่ **6, 8, และ 10 hops** | ห้ามมีตัวอย่าง `>= 6 hops` ใน Train โดยเด็ดขาด |
| **RB-04** | **OOD Structural & Template Shift** | ถามคำตอบแบบ Backward Query, Double-Negated Framing, Unseen Surface Templates | **TL-01 Verified:** Surface Signature ต่างจาก Train 100% |
| **RB-05** | **Multi-Step DAG Planning** | วางลำดับ Action ตาม Preconditions/Effects (4–8 Actions) + Goal Verification | **Impossible Plan Slice (30%):** ใส่ Cycle หรือ Missing Precondition -> โมเดลต้องตอบ `impossible` ไม่ใช่เดาลำดับมั่ว |
| **RB-06** | **Counterfactual & Perturbed Logic** | เปลี่ยน Fact เพียง 1 จุดใน Context แล้วถามผลกระทบต่อข้อสรุป | วัดว่า Sensitivity ต่อการเปลี่ยนแปลง Logic จริงสูงกว่า Memorized Priors |
| **RB-SE-01** | **Requirement-to-Architecture Decomposition** | แปลงโจทย์แอป (เช่น Store + Inventory + Auth + Reports) เป็น Module Boundaries + Dependency DAG | ตรวจ Cyclic Dependency, Missing Auth Boundary, และ Requirement Coverage |
| **RB-SE-02** | **Relational Schema & API Consistency** | ออกแบบ DB Tables/Foreign Keys + REST/GraphQL Contracts ให้สอดคล้องกันข้าม Entities | ตรวจ Schema Normalization, Orphan Keys, และ Contract Mismatch ผ่าน Verifier |
| **RB-SE-03** | **Fault Localization & Patch Reasoning** | วิเคราะห์ Real Compiler/Test Trace + Multi-file Code Context เพื่อชี้ Root Cause และสร้าง Minimal Patch | ตรวจผ่าน Hidden Regression Tests หลัง Patch (ไม่ใช่แค่เดาบรรทัดผิด) |

---

## 3. Diagnostic Disentanglement Report

เพื่อไม่ให้คะแนนรวมปกปิดจุดอ่อน ทุก Stage Exit Report ใน Stage 3, 4, 6 ต้องแตกผลออกเป็น:
1. **`valid_vs_impossible_confusion`:** แยก Precision/Recall ของกรณีทำได้ vs `impossible`
2. **`hop_decay_curve`:** กราฟ Accuracy แยกตาม Hop Depth (`2, 3, 4, 5, 6, 8, 10 hops`) เพื่อดูว่า V12 Extrapolate ได้ไกลขึ้นกว่า V11 จริงหรือไม่
3. **`slot_permutation_consistency`:** สัดส่วนที่คำตอบยังคงถูกต้องสอดคล้องกันเมื่อสลับ Slot IDs (`<slot_0>..<slot_31>`) บน Logic กราฟเดิม

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Exact Planning Validator สำหรับ **RB-05** สามารถรองรับ Multiple Valid Topological Orderings เมื่อ Graph มี Branch ขนานที่ถูกต้องตาม Preconditions ทุกประการ

### OPEN DECISIONS
- **OD-V12-RB-01:** เพดาน `max_seq_len` สำหรับ **RB-03 (10-hop OOD)** — หาก Token Count ของ 10-hop + Distractors เกิน `256` tokens จะต้องใช้ `max_seq_len=512` (ซึ่งเชื่อมโยงกับ **OD-V12-ARCH-01**)

### NOT VERIFIED
- อัตราความแม่นยำของ `ZyrquenModel` (`3.74M` หรือ `12.19M`) บน `6–10 hop` OOD Extrapolation ยัง **NOT VERIFIED / NOT RUN**
- โค้ด Generator และ Validator สำหรับ **RB-01..RB-06** ยังไม่ได้เขียนใน Repository
