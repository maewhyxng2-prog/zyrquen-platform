# ZYRQUEN Ω∞ — V11 Reasoning Benchmark Specification

- **Document ID:** `V11-DOC-11`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Target Dimensions:** Abstract Reasoning, Relational Generalization, OOD Transfer, Multi-Step Planning (พร้อม Principle Probes ต่อยอดจาก V9/V10)

---

## 1. Benchmark Design Philosophy (Anti-Shortcut Engineering)

ข้อบกพร่องในอดีต (`v8` / `nagi_500_v3`) แสดงให้เห็นว่าโมเดลสามารถ "จำตำแหน่งคำหรือความถี่คำตอบ" โดยไม่เข้าใจเหตุผล V11 Reasoning Benchmark จึงบังคับใช้หลักการ 5 ข้อ:

1. **Shuffled Premise Ordering:** ข้อเท็จจริงใน Context ถูกสลับลำดับแบบสุ่ม ไม่เรียงเป็นโซ่ซ้ายไปขวา (เช่น `C -> D; A -> B; B -> C`) เพื่อบังคับ Multi-hop Graph Traversal
2. **Distractor Branches:** เพิ่มโหนด/เส้นเชื่อมหลอก `2–5` เส้นที่เชื่อมกับตัวแปรหลักแต่ไม่นำไปสู่คำตอบที่ถูกต้อง
3. **Unique-Path Exhaustive Verification:** กราฟต้องมีคำตอบเดียวเท่านั้นตาม Exhaustive Solver (ห้ามมีทางคู่ขนานที่ให้ผลลัพธ์สองค่า)
4. **Negative / Boundary Cases:** ทุกหมวดต้องมีกรณีปฏิเสธคำตอบ (`unknown`, `impossible`, `conflict`) เพื่อวัดว่าโมเดลไม่ได้เดาจาก Prior Frequency
5. **Strict Split Disjointness:** Entity, Phrasing (`TL-01`), และ OOD Graph Topology (`SL-01`) แยกขาดระหว่าง `train`, `validation`, `unseen`, และ `ood`

---

## 2. Benchmark Suite Breakdown Across Core Reasoning Domains

### 2.1 Abstract Reasoning (`abstract_reasoning`)
- **Structure:** Acyclic partial order / equivalence graphs (`greater_than`, `equal_to` หากเปิดใช้)
- **Probes:**
  - Direct vs 2–4 hop Transitive Comparison (`A > B`)
  - Inverse Query (`B ? A` จาก `A > B` ต้องตอบ `<`)
  - Disconnected Components Query (ต้องตอบ `"unknown"`)
- **OOD Shift:** เพิ่มจำนวนโหนดและ Distractor chains ใน `ood` split โดยใช้ Entity Pool `OO_*`

### 2.2 Relational Generalization (`relational_generalization`)
- **Structure:** Directed relation chains with distractor forks & dead-end branches
- **Probes:** Exact 3-hop path resolution โดยไม่มี shortcut `1–2` hops ที่ปลายทางเดียวกัน
- **Metric Focus:** `unseen_entity_copy_acc` บน `unseen` split + Distractor Rejection Rate

### 2.3 OOD Transfer (`ood_transfer`)
- **Explicit Structural Separation (`SL-01`):**
  - `train`: 2–3 hops via `connects_to`
  - `validation`: 3 hops via `bridges_to` (disjoint entities & phrasing)
  - `unseen`: 3 hops via `relates_to` (unseen entities & phrasing)
  - `ood`: **4–6 hops** via `transfers_to` / `channels_to` (unseen depth + unseen relation + unseen structural pattern)
- **Purpose:** พิสูจน์ Compositional Length & Relation Generalization ไม่ใช่การจำ hop count ตายตัว

### 2.4 Multi-Step Planning (`multi_step_planning`)
- **Structure:** Dependency DAGs + Cycle / Missing-Precondition Traps
- **Probes:**
  - Unique topological plan (`goal: Z | deps: ...`) พร้อม irrelevant parallel tasks ที่ต้องตัดออกไม่รวมในแผน
  - Cycle trap (`X requires Y, Y requires X`) -> `"impossible"`
  - Missing prerequisite trap (`Z requires M`, โดยไม่มี rule สร้าง `M`) -> `"impossible"`
- **Metric Focus:** Exact sequence match (Free-Generation), `TF - FG` gap, และ Cycle/Impossible precision

---

## 3. Principle Probes (Behavioral Diagnostics, Not Counted as Model Accuracy Alone)

นอกจาก Exact Match หลัก ยังคำนวณ Behavioral Diagnostics:
1. **Slot Permutation Invariance Probe:** ทดสอบ Prompt เดียวกันโดยสลับหมายเลข `<slot_k>` ระหว่าง 2 รัน (คำตอบหลัง restore ต้องคงเดิม 100%)
2. **Premise Order Invariance Probe:** ทดสอบกราฟเดียวกันหลังสลับลำดับข้อเท็จจริงใน Input
3. **Abstention Calibration Probe:** วัด False-Positive Guessing Rate บนกรณี `unknown`/`impossible`

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- รูปแบบ Prompt ของ 4–6 hops + distractor edges ใน `ood` ยังสามารถจัดวางให้อยู่ในงบ `<= 250` structural tokens (`max_seq_len = 256`) ได้
- `EvaluationEngine` สามารถบันทึก per-split และ per-difficulty-level breakdown ลงใน evaluation report JSON ได้

### OPEN DECISIONS
- **OD-RB-01:** กำหนดจำนวน hop สูงสุดใน `ood` split (`5 hops` vs `6 hops`) ตามผลตรวจสอบ Token Length Distribution จริงของ Tokenizer V11
- **OD-RB-02:** จะรวม Slot Permutation Invariance Score เป็น Hard Release Criterion ใน Stage 6 หรือใช้เป็น Diagnostic Metric

### NOT VERIFIED
- อัตราที่ `ZyrquenModel` 4-layer vs 6-layer (`<= 5M` params) สามารถทำ Length Generalization จาก 2–3 hops ไปยัง 5–6 hops หลังฝึก 10,000 Steps ยัง **NOT VERIFIED**
- Latency ของ Exhaustive Generator/Solver สำหรับกราฟ 6 hops + distractors ยัง **NOT VERIFIED**
