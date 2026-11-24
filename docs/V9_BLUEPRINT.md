# ZYRQUEN Ω∞ — v9 — Generalization & Native Reasoning Blueprint

- **สถานะเอกสาร:** `HISTORICAL BLUEPRINT — v9 EXPERIMENT CLOSED_FAIL`
- **ผลการทดลองจริง:** [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](V9_EXPERIMENT_CLOSURE_REPORT.md) — arm_d runtime training/evaluation completed; capability acceptance failed.
- **หมายเหตุ:** เนื้อหา Blueprint นี้เป็นข้อกำหนดก่อนทดลอง ไม่ใช่สถานะ runtime ปัจจุบัน; ห้ามตีความข้อความเก่า “NO TRAINING YET” ว่ายังไม่มีการฝึก.
- **สถานะ v8 ปัจจุบัน:** **ปิดการทดลองแล้วตามมติเจ้าของโครงการ** และคงสถานะ **`FROZEN`** (ห้ามแก้ไฟล์เดิม; ใช้ข้อมูลอ้างอิงจาก `docs/V8_SUMMARY.md` และคงหมายเหตุ `BLOCKED IN WORKSPACE` ใน `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` สำหรับตัวเลขจาก Codespaces ที่ยังไม่อยู่ใน Snapshot นี้)
- **ตำแหน่งในเส้นทาง NGI:** `v7 Baseline Foundation` → `v8 Attention + Pointer-Copy (ปิดแล้ว)` → **`v9 Generalization (CLOSED_FAIL; measured baseline)`** → `v10 Relational & Multi-step Reasoning` → `v11 Knowledge Integration` → `v12 Adaptive Learning` → `v13 Planning & Decomposition` → `v14 Verification & Self-Correction` → `v15 Autonomous Capability` → `v16+ Integrated Native Intelligence` → **ZYRQUEN Ω∞ — NGI** *(ไม่จำกัดที่ v20 และคง Roadmap Phase 11–20 เดิม)*
- **เป้าหมายหลัก:** วางแผนพัฒนาความสามารถ **Generalization & Native Reasoning** ของโมเดล ZYRQUEN ต่อจาก `v8` โดยมุ่งให้เรียนรู้หลักการจริงและนำไปใช้กับ Entity และรูปแบบโจทย์ที่ไม่เคยเห็น (**ไม่ใช่ Chatbot-only**)
- **เอกสารแผนการทดลองคู่ขนาน:** ดูสเปก Dataset v9, สถาปัตยกรรม `ZyrquenSlotReasoner` (~1.15M–1.35M params ใต้เพดาน CPU 5M) และ 6 Principle Probes เพิ่มเติมใน `docs/V9_EXPERIMENT_PLAN.md`
- **ขอบเขตเอกสารเดิม:** ข้อความนี้อธิบายขอบเขตก่อนเริ่มทดลองเท่านั้น; ผลจริงภายหลังบันทึกไว้ใน Closure Report โดยไม่แก้ไข v7/v8 หรือ Product Roadmap Phase 11–20.

---

## 1. วิเคราะห์ผล v8 และข้อจำกัดที่ต้องแก้ใน v9

### 1.1 สิ่งที่ v8 วางรากฐานไว้ (อ้างอิงสถานะจริงใน Repository)
การทดลอง `v8` (`tools/train_nagi_500_v8.py` และ `tools/eval_nagi_500_v8.py`) ทดลองเปลี่ยนสถาปัตยกรรมจาก `TinyNGI` 2-layer LSTM ใน `v7` (`tools/train_nagi_500_v7.py`) มาเป็น `Seq2Seq` (`BiGRU Encoder + Bahdanau Additive Attention + Pointer-Copy Gate` ที่ `hid_dim=128`) โดยใช้ชุดข้อมูล `data/nagi_500_v3` และตั้งค่าควบคุมให้สอดคล้องกับ `v7` (`batch_size=4`, sequential batch order, `seq=256`, `Adam lr=0.001`, `seed=42`, train-only vocab)

ในพื้นที่ทำงานปัจจุบัน สถานะของการปิดการทดลอง `v8` ยังเป็น **`PARTIAL / BLOCKED IN WORKSPACE`** และ **`FROZEN`** (ดูรายละเอียดเชิงโครงสร้างและรายการหลักฐานครบถ้วนใน `docs/V8_SUMMARY.md` และ `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`) เนื่องจากไฟล์ `checkpoints/nagi_500_v8/*.pt`, `eval/nagi_500_v8/report.json`, `eval/nagi_500_v7_500/report.json`, และ `data/nagi_500_v3/*.jsonl` อยู่ในสภาพแวดล้อมที่รันจริง (Codespaces) ไม่ได้อยู่ใน Snapshot นี้ ตัวเลขผลลัพธ์จริงของ `v8` จึงยังต้องรอการแนบและยืนยันอย่างเป็นทางการก่อนปลด Freeze

### 1.2 ข้อจำกัดเชิงสถาปัตยกรรมและเชิงวิธีการของ v8 ที่ v9 ต้องแก้ไข

| ลำดับ | ข้อจำกัดจาก v8 | สาเหตุเชิงเทคนิค (จากโค้ดและสเปกใน Repository) | ผลกระทบต่อเป้าหมาย NGI |
|---:|---|---|---|
| 1 | **Unseen Entity Copy เป็น `N/A` และไม่มี Unseen Entity จริงใน `nagi_500_v3`** | `tools/gen_nagi_500_v3.py` ใช้ Pool เดียวกัน (`E00–E19`) ซ้ำใน `train`, `val`, `test` และแชร์ Template เดียวกัน (`DESIGN: entities REUSED, templates SHARED`) ทำให้ `unseen_entity_count == 0` | ยังพิสูจน์ไม่ได้ว่าโมเดล Generalize ข้าม Entity ที่ไม่เคยเห็นจริงหรือไม่ |
| 2 | **Adaptive Learning ยังมีตัวอย่างล้มเหลวและตื้นเกินไป** | ใน `nagi_500_v3` งาน `adaptive_learning` มีเพียงรูปแบบสั้น `learn: A -> B | predict A ?` ยังไม่มีสถานการณ์ปรับทับความรู้เดิมหรือความขัดแย้ง | โมเดลอาจจำรูปแบบคีย์เวิร์ด `learn:` แทนการปรับสถานะความเชื่อ/กฎใหม่ในบริบท |
| 3 | **`mean_p_gen` ต่ำและการพึ่งพา Shallow Copy** | Pointer-Copy Gate (`p_gen`) มีแนวโน้มพึ่งพา `copy_dist` เมื่อคำตอบตรงกับโทเคนในอินพุต แต่เมื่อต้องสังเคราะห์คำตอบเชิงเหตุผลที่ไม่ใช่โทเคนตรงตัว (เช่น คำตอบเชิงตรรกะ/การสรุปขั้น) เกตต้องสลับไป `vocab_dist` ได้อย่างแม่นยำ | เสี่ยงเกิด Copy Bias (ลอกคำจากอินพุตโดยไม่เข้าใจโครงสร้างเหตุผล) |
| 4 | **ยังไม่แยกผลของ Attention กับ Pointer-Copy (Missing Ablation)** | `v8` เพิ่ม `BiGRU + Bahdanau Attention` และ `Pointer-Copy` พร้อมกันในรอบเดียว ยังไม่มี Baseline ตัวกลาง `Seq2Seq + Attention (ไม่มี Pointer-Copy)` | ไม่สามารถสรุปทางวิทยาศาสตร์ได้ว่าผลที่เปลี่ยนมาจาก Attention หรือ Pointer-Copy |
| 5 | **Parameter Count เพิ่มเกือบ 2 เท่า (`273,955` → `523,708`)** | ตามบันทึกอ้างอิงของโครงการ การเพิ่ม BiGRU, Attention, และ Pointer Gate ขยายพารามิเตอร์เกือบสองเท่าที่ `hid_dim=128` | ประสิทธิภาพต่อพารามิเตอร์ (Parameter Efficiency) และแนวโน้มการ Overfit บนชุดข้อมูลขนาดเล็กยังไม่ได้รับการควบคุม |
| 6 | **ข้อจำกัดความลึกของการให้เหตุผลและการวางแผน** | `relational_reasoning` ใน `v3` จำกัดที่ 2 hops ตายตัว และ `planning_decomposition` เป็นเพียงการดึงตำแหน่ง `first/middle/last/second step` จากลิสต์ 3 ตัว | ยังไม่ใช่ Multi-hop Reasoning หรือ Task Decomposition จริง |
| 7 | **Exposure Bias ระหว่าง Teacher-Forced กับ Free-Generation** | แม้ `v8` จะลด `teacher_forcing_ratio` ลงแบบเส้นตรง (`1.0 → 0.5`) ระหว่างฝึก แต่การ Generate หลายโทเคนแบบ Autoregressive ยังเสี่ยงคลาดเคลื่อนเมื่อเกิด Error สะสม | จำเป็นต้องวัดและลด `TF exact - FG exact` ใน v9 อย่างเป็นระบบ |

> **หลักการสำคัญก่อนเปิด v9:** ตามข้อสรุปของ `v8` การเพิ่ม Attention และ Pointer-Copy เป็นเพียงก้าวทดลองด้านสถาปัตยกรรม ยังไม่ใช่หลักฐานว่า ZYRQUEN บรรลุ NGI แล้ว การออกแบบ `v9` จึงต้องมุ่งที่ **โครงสร้างการให้เหตุผลและการเรียนรู้ข้ามสิ่งที่ยังไม่เคยเห็น (Out-of-Distribution Generalization)** ไม่ใช่แค่เพิ่มพารามิเตอร์หรือปรับรูปแบบแชท

---

## 2. Unseen Entity Generalization — เรียนรู้และประยุกต์ใช้กับ Entity ใหม่

### 2.1 ปัญหาที่ต้องแก้
หาก Embedding ของ Entity ผูกติดกับ Token ID เฉพาะตัวใน Training Set (เช่น `E00..E19`) โมเดลจะไม่สามารถใช้เหตุผลกับ Entity ใหม่ใน Test Set (`Unseen Entity`) ได้ ยิ่งไปกว่านั้น แม้ `v8` จะมี `dynamic local vocab` สำหรับ Copy Entity OOV แต่การ *ให้เหตุผล* เกี่ยวกับความสัมพันธ์ของ Entity ใหม่ (เช่นเปรียบเทียบหรือติดตามห่วงโซ่ก่อน Copy คำตอบ) ต้องอาศัยความเข้าใจตำแหน่งและบทบาท (Structural Role Binding) ไม่ใช่จำ Token

### 2.2 แนวทางออกแบบสำหรับ v9 (แก้ปัญหา `<unk>` Collision และ Leakage พร้อมกัน)
1. **การแยก Entity Pool ข้าม Split โดยสมบูรณ์:**
   - กำหนด Pool แยกขาด: `Train` (`TR_E000..`, `node_tr_*`, `item_tr_*`), `Validation` (`VA_E000..`, `node_va_*`, `item_va_*`), และ `Test` (`TE_E000..`, `node_te_*`, `item_te_*`) โดยให้ทุก Eval Split มี Distinct Unseen Entities **`>= 40` ตัว** (สูงกว่าเกณฑ์ขั้นต่ำ `EL-07 >= 30`) และ Entity-Target **`>= 45` ตัวอย่าง** เพื่อการันตี **ไม่มี `N/A`** ใน `unseen_entity_copy_acc`
2. **Context-Local Ephemeral Entity Slotizer & Slot Permutation Equivariance (แก้ `<unk>` Collision ใน Encoder):**
   - จากการตรวจสอบ `tools/eval_nagi_500_v8.py` พบว่า `v8` ส่ง Unseen Entity เข้า Encoder ผ่าน `stoi.get(t, unk_id)` ทำให้ Entity ใหม่ตั้งแต่ 2 ตัวขึ้นไปในโจทย์เดียวกันชนกันเป็น `<unk>` เดียวกันทั้งหมด
   - ใน `v9` ให้แยก Structural/Operator Vocab (`train-only`) ออกจาก Local Entity Slots `<slot_0>..<slot_31>` ภายในแต่ละ Prompt โดย Entity เดิมใน Prompt เดียวกันจะได้ `<slot_k>` เดียวกัน (และสุ่มสลับหมายเลข Slot ระหว่าง Training เพื่อกันการจำตำแหน่ง) ส่วน `slot_to_surface` เก็บเฉพาะในบริบท Prompt นั้นเพื่อให้ Pointer-Copy ถอดรหัสกลับเป็น Entity ต้นทางโดย **ไม่ต้องนำ Entity ของ Val/Test เข้า Static Vocab (`EL-05 = 0`)**
3. **Role-Agnostic Structural Attention & Controlled Copy-Reasoning Separation:**
   - ใช้ Bidirectional Multi-Layer Transformer Encoder (`4` layers, `d_model=160`) ทำงานเป็น Multi-step Parallel Message Passing ร่วมกับ Pointer-Generator Decoder (`2` layers, รวม `~1.15M–1.35M` params ใต้เพดาน CPU `5M`)
   - แยกงาน Copy Unseen Entity ออกจากงาน Infer Symbol (`true`, `false`, `unknown`, `conflict`, `impossible`, `>`, `<`, `=`) พร้อม **Distractor Entities** `3–5` รายการ เพื่อป้องกัน Copy Bias (`mean_p_gen` collapse)

---

## 3. Relational Reasoning — ให้เหตุผลกับความสัมพันธ์หลายขั้น

### 3.1 การยกระดับจาก v8
ใน `nagi_500_v3` งาน `relational_reasoning` มีเพียง 2 hops แบบเรียงลำดับเดียว (`A > B, B > C | A ? C`) ซึ่งโมเดลสามารถเดาจากรูปแบบประโยคหรือความถี่ของคำตอบได้ ใน `v9` ต้องพิสูจน์ว่าโมเดลทำ **Multi-hop Graph Traversal** ได้จริง

### 3.2 ข้อกำหนดความสามารถใน v9
1. **Multi-Hop & Depth Generalization:**
   - ฝึกที่ความลึก `2–3 hops` และแยก Test Subset ที่ **`4–5 hops`** (Compositional Length/Depth Generalization)
2. **Shuffled Premise Ordering:**
   - สลับลำดับข้อเท็จจริงในบริบท (เช่น `B > C, A > B | A ? C` แทน `A > B, B > C`) เพื่อบังคับให้โมเดลเชื่อมโยง Node แทนการอ่านซ้ายไปขวาตามลำดับข้อความ
3. **Mixed Relations & Directionality:**
   - รองรับการผสมความสัมพันธ์ที่มีความหมายเชื่อมโยงและทิศทาง เช่น Transitive Order (`>`, `<`), Equivalence (`=`), Directed Dependency (`causes`, `requires`), และ Inverse Query (`C ? A` จาก `A > B, B > C` ต้องตอบ `<`)
4. **Distractor Branches & Unreachable Queries:**
   - มี Branch อื่นที่ไม่เชื่อมโยงกับคู่ที่ถาม และมีกรณี `unknown` / `undetermined` เมื่อกราฟไม่มีเส้นทางเชื่อมถึงกัน เพื่อลดการเดาสุ่ม (`>`, `<`, `=`)

---

## 4. Adaptive Learning — เรียนรู้ข้อมูลใหม่และปรับความรู้เดิม

### 4.1 ปัญหาจาก v8
`v8` มีเพียงรูปแบบ `learn: A -> B | predict A ?` โดยไม่มีความขัดแย้งหรือการเปลี่ยนค่า จึงแยกไม่ออกระหว่าง "การค้นหาคู่ในบริบท" กับ "การปรับเปลี่ยนความรู้เดิม"

### 4.2 ข้อกำหนดความสามารถใน v9
1. **In-Context Rule Override (การแก้ไขความรู้เดิม):**
   - ตัวอย่างมีลำดับเวลา/ลำดับความสำคัญ: เช่น `base: A -> B | update: A -> C | predict A ?` → ต้องตอบ `C` (ความรู้ล่าสุดแทนที่ความรู้เดิม)
2. **Selective Retention (จำสิ่งที่ไม่ได้แก้):**
   - เมื่ออัปเดต `A -> C` แต่ถามถึง `D` จาก `base: D -> E` คำตอบสำหรับ `D` ต้องยังคงเป็น `E` (ไม่เกิด Catastrophic Forgetting ภายในบริบท)
3. **Chained Adaptation (ประยุกต์ความรู้ใหม่ร่วมกับความรู้เดิม):**
   - ตัวอย่าง: `base: B -> C | learn: A -> B | query 2-hop A ?` → ต้องเชื่อมโยง `A -> B -> C` เพื่อตอบ `C`
4. **Negation / Retraction (การเพิกถอนข้อเท็จจริง):**
   - รองรับการยกเลิกข้อเท็จจริงเดิม (เช่น `retract: A -> B`) เพื่อให้คำถามถัดไปตอบ `unknown` แทนการตอบค่าเก่าที่ถูกถอนไปแล้ว

---

## 5. Knowledge Integration — รวมความรู้และตรวจจับความขัดแย้ง

### 5.1 เป้าหมาย
ระบบ NGI ต้องสามารถรวบรวมข้อเท็จจริงย่อยจากหลายส่วนของบริบทเข้าเป็นโมเดลความจริงเดียวกัน และ **ต้องไม่สร้างคำตอบที่มั่นใจผิดๆ เมื่อข้อมูลขัดแย้งกัน**

### 5.2 ข้อกำหนดความสามารถใน v9
1. **Multi-Source Fact Synthesis:**
   - รวมข้อมูลที่มีรูปแบบประโยคหลากหลาย (เช่น `fact:`, `obs:`, `rule:`) เพื่อสรุปข้อเท็จจริงรวมของ Entity เป้าหมาย
2. **Contradiction & Cycle Detection:**
   - ตรวจจับความขัดแย้งเชิงตรรกะโดยตรง (เช่น `A = B` ร่วมกับ `A != B` หรือ `A -> B` ร่วมกับ `A -> C` ที่ขัดแย้งกันโดยไม่มีตัวบ่งชี้ `update:`)
   - ตรวจจับวงจรขัดแย้งเชิงลำดับ (เช่น `A > B, B > C, C > A`) และส่งผลลัพธ์เชิงโครงสร้างว่า `conflict` พร้อมระบุ Entity/ความสัมพันธ์ต้นเหตุหากกำหนดไว้ใน Target Schema
3. **Distinguish Override vs Conflict:**
   - แยกให้ชัดเจนระหว่าง `update:` (เจตนาแก้ไขจากเจ้าของ/ลำดับเวลาใหม่ → ใช้ค่าใหม่) กับ `fact:` สองชุดที่ขัดแย้งกันเองโดยไม่มีลำดับแก้ไข (→ รายงาน `conflict`)

---

## 6. Planning & Decomposition — แบ่งปัญหาและวางแผนแก้ไข

### 6.1 การยกระดับจาก v8
`planning_decomposition` ใน `v8` เป็นเพียงการดึงคำจากสตริง `plan: A then B then C | middle step ?` ซึ่งเป็นการทำ Sequence Indexing ไม่ใช่ Planning

### 6.2 ข้อกำหนดความสามารถใน v9
1. **Dependency-Driven Topological Planning:**
   - กำหนดเงื่อนไขความเชื่อมโยงที่ไม่ได้เรียงตามลำดับการเขียน เช่น `goal: C | deps: C after B, B after A, D after C` → ต้องสร้างแผนลำดับที่ถูกต้อง `A -> B -> C` (ไม่รวม `D` ที่ไม่จำเป็นต่อ `goal: C`)
2. **Subgoal Decomposition:**
   - แตกเป้าหมายหลักที่มีหลายเงื่อนไขย่อย (`goal: X & Y`) ออกเป็น Sub-steps ตาม Prerequisite ที่พบในบริบท
3. **Resource / Precondition Awareness & Impossible Plan Detection:**
   - หากมีเงื่อนไขที่ขาดจุดตั้งต้น (`missing_prereq`) หรือมี Dependency วนลูป (`A after B, B after A`) โมเดลต้องรายงาน `impossible` แทนการสร้างลำดับขั้นตอนเท็จ

---

## 7. Verification — ตรวจสอบเหตุผลและผลลัพธ์

### 7.1 การยกระดับจาก v8
ใน `v8` การ Verify มี 6 เทมเพลตคงที่ที่จับคู่คำตรงๆ เช่น `equals` คู่กับ `is same as` ซึ่งเสี่ยงต่อ Shortcut Learning (จำ Keyword Mapping)

### 7.2 ข้อกำหนดความสามารถใน v9
1. **Structural Claim Verification:**
   - ตรวจสอบข้ออ้าง (Claim) เทียบกับชุดข้อเท็จจริงหลายขั้น เช่น `claim: A > C | facts: A > B, B > C | verdict ?` → `true` หรือเทียบกับข้อเท็จจริงที่ขัดแย้ง → `false` หรือหลักฐานไม่พอ → `unknown`
2. **Plan Feasibility Verification:**
   - ตรวจสอบแผนที่เสนอ (`proposed_plan: B -> A -> C`) เทียบกับ Dependency Constraints (`B after A`) เพื่อตอบ `invalid` พร้อมระบุชนิดความผิดพลาด (`order_violation`, `missing_step`, `cycle`)
3. **Self-Verification Signal Integration:**
   - เชื่อมแนวคิดกับ Validation Interface ในแกนระบบของ ZYRQUEN (เช่น โครงสร้าง Contract ที่มีอยู่ใน `apps/core/intelligence/` โดยไม่แก้โค้ดเดิมก่อนได้รับอนุมัติ) เพื่อให้ผลจากโมเดลสามารถถูกตรวจสอบย้อนกลับแบบ Deterministic บน Test Harness ได้

---

## 8. Evaluation Protocol — กำหนด Train/Validation/Test ที่ป้องกัน Entity และ Template Leakage

เพื่อแก้ไขจุดอ่อนของ `nagi_500_v3` และคืนความเข้มงวดตามหลักการ 3 ชั้นของ `docs/NATIVE_TRAINING_500_SPEC.md` ร่วมกับการทดสอบ Out-of-Distribution (OOD) ใน `v9` กำหนดโปรโตคอลการแบ่งข้อมูลและประเมินผลดังนี้:

### 8.1 Split Architecture และการแยก Leakage 4 ชั้น

| ชั้นการตรวจสอบ (Leakage Layer) | เงื่อนไขบังคับข้าม `train` / `val` / `test` | เกณฑ์ผ่าน Integrity Gate |
|---|---|---|
| **1. Exact & Normalized Input Duplicate** | ห้ามมีข้อความ `input` ซ้ำทั้งแบบตรงตัวและหลัง normalize whitespace/lowercase | Overlap = `0` |
| **2. Entity Disjointness (Entity Leakage)** | แยก Entity Pool คนละชุด (`TR_*`, `VA_*`, `TE_*`) โดยไม่นำ Entity ใน Train ไปใส่ใน Val/Test (`Entity_Train ∩ Entity_Val = ∅`, `Entity_Train ∩ Entity_Test = ∅`, `Entity_Val ∩ Entity_Test = ∅`) | Entity Overlap = `0` |
| **3. Template & Phrasing Disjointness (Template Leakage)** | แยก Template Phrasing สำหรับ Held-out Split (`template_id` ใน OOD Val/Test ต้องไม่ปรากฏใน Train) | Template Overlap (OOD Slice) = `0` |
| **4. Structural Signature & Abstract Pattern Isolation** | แปลง Entity เป็น Canonical Placeholder (`<E0>`, `<E1>`, ...) เพื่อตรวจ `abstract_pattern` ข้าม Split สำหรับ Generalization Test | Abstract Pattern Overlap (Generalization Slice) = `0` |

> **หมายเหตุเรื่อง Compositional Depth Split:** ควรแยกชุดทดสอบ `Test` ออกเป็น 2 กลุ่มชัดเจนในรายงาน:
> - **`Test-Unseen-Entity`:** โครงสร้างระดับเดียวกับ Train แต่ใช้ Entity ใหม่ 100% + Distractors
> - **`Test-OOD-Generalization`:** Entity ใหม่ + Template ใหม่ + Hop/Dependency Depth ที่ลึกกว่า Train (เช่น 4–5 hops เมื่อ Train อยู่ที่ 2–3 hops)

### 8.2 กฎ Integrity Gate ก่อนอนุญาตให้ Train หรือ Eval
- ตรวจสอบ `empty_target == 0` ทุก Split
- ตรวจสอบ `train_ids ∩ val_ids == ∅`, `train_ids ∩ test_ids == ∅`, `val_ids ∩ test_ids == ∅`
- ตรวจสอบความสมดุลของ Label (`true`/`false`/`unknown`/`conflict`/`>`/`<`/`=`) ในทุก Capability เพื่อกัน Majority-Class Shortcut
- คำนวณ `SHA-256` ของไฟล์ชุดข้อมูลทั้งหมดลงใน `manifest.json`
- **Vocab Policy:** สร้าง Vocabulary จาก `train` เท่านั้น (ห้ามแอบเก็บ Entity ของ `val`/`test` ลงใน Static Vocab เด็ดขาด; การจัดการ Unseen Entity ให้ทำผ่าน Copy/Dynamic Index ในขณะ Inference เท่านั้น)

### 8.3 ตัวชี้วัดบังคับ (Evaluation Metrics)
ต้องรายงานทั้ง **Teacher-Forced** และ **Free-Generation (Autoregressive)** แยกกันอย่างชัดเจนทั้งภาพรวมและราย Capability:
1. `free_gen_exact_match` (ตัวชี้วัดหลัก) และ `teacher_forced_exact_match`
2. `exposure_bias_gap` = `TF_exact - FG_exact`
3. `unseen_entity_copy_acc` และ `unseen_entity_reasoning_acc` (ต้องคำนวณได้จริง ไม่เป็น `N/A`)
4. `multi_hop_acc` แยกตามจำนวน Hop (2-hop, 3-hop, 4+ hop)
5. `adaptive_override_acc` และ `adaptive_retention_acc`
6. `conflict_detection_f1` / `contradiction_acc`
7. `plan_validity_acc` และ `impossible_plan_acc`
8. `eos_hit_rate`, `premature_eos_rate`, `repetition_rate`, `first_token_acc`
9. `mean_p_gen` แยกตามประเภทงาน (Copy-intensive vs Reasoning/Classification)

---

## 9. Baseline Comparison — กำหนดวิธีเปรียบเทียบกับ v7 และ v8 อย่างเป็นธรรม

### 9.1 หลักการเปรียบเทียบที่เป็นธรรม (Apples-to-Apples Control)
- **ห้าม** นำคะแนน `v9` บน Dataset `v9` ไปเทียบข้ามกับคะแนนเดิมของ `v7`/`v8` บน `nagi_500_v3` โดยตรง
- เมื่อได้รับอนุมัติเริ่มทดลอง ต้องประเมิน **ทุก Arm บนชุดข้อมูล `v9` Benchmark Split เดียวกัน** (และสามารถรันเทียบเฉพาะงานที่โครงสร้างรองรับบน `nagi_500_v3` เป็น Regression Check เพิ่มเติมได้)

### 9.2 ตาราง 4-Arm Controlled Comparison

| Arm | ชื่อรุ่น / สถาปัตยกรรม | บทบาทในการทดลอง | สิ่งที่ถูกควบคุมให้เท่ากัน |
|---|---|---|---|
| **Arm A** | **`v7` Baseline** (`TinyNGI` 2-layer LSTM) | Baseline ลำดับพื้นฐาน (ไม่มี Attention, ไม่มี Pointer) | Dataset Split เดียวกัน, Seed (`42`), Train-only Vocab, `batch_size=4`, `seq=256`, Compute/Steps Budget |
| **Arm B** | **`v8-Ablation` (Attention-Only)** (`BiGRU + Bahdanau Attention`, **ไม่มี Pointer-Copy**) | **Ablation ตัวกลางที่ขาดไปใน v8** เพื่อแยกผลของ Attention ออกจาก Pointer-Copy | ชุดข้อมูล, Hyperparameter, Early-stop และ Evaluator เดียวกับ Arm C |
| **Arm C** | **`v8` Baseline** (`BiGRU + Bahdanau Attention + Pointer-Copy`) | Baseline ปัจจุบันที่มีกลไก Copy | เงื่อนไขเดียวกับ Arm A/B |
| **Arm D** | **`v9` Candidate** (สถาปัตยกรรม Reasoning + Dynamic Entity Binding) | ผู้ท้าชิงรุ่นใหม่สำหรับ Generalization & Reasoning | อยู่ใต้เพดานพารามิเตอร์ `<= 5M`, `seq <= 256` (หรือขยายเฉพาะเมื่อได้รับอนุมัติในแผน), Train-only Vocab, Evaluator เดียวกัน 100% |

### 9.3 เกณฑ์การเปรียบเทียบต้นทุนและพฤติกรรม
ทุก Arm ต้องรายงานควบคู่กับ:
- `params` (จำนวนพารามิเตอร์รวม) และ Efficiency Ratio (`FG_exact / (params / 100k)`)
- `elapsed_sec` และ `max_rss_kb` (Peak RAM)
- Error Case Breakdown ราย Capability (`val_errors`, `test_errors`) เพื่อพิสูจน์ว่าข้อจำกัดของ `v8` (เช่น Adaptive Learning ล้มเหลว, Copy Bias) ลดลงจริง

---

## 10. Acceptance Criteria — กำหนดเกณฑ์ผ่านและเกณฑ์หยุดการทดลอง

### 10.1 Pre-Conditions (ต้องผ่านก่อนเริ่มสร้างโค้ดหรือฝึก v9)
1. เจ้าของโครงการอนุมัติปิดการทดลอง `v8` อย่างเป็นทางการ พร้อมแนบหลักฐานผลรันจริง (`eval/nagi_500_v8/report.json` และ `eval/nagi_500_v7_500/report.json`) จาก Codespaces เพื่อปลดสถานะ `BLOCKED` ใน `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` และ `docs/V8_SUMMARY.md`
2. เจ้าของโครงการอนุมัติ `docs/V9_BLUEPRINT.md` ฉบับนี้ และอนุมัติแผนย่อยสำหรับการสร้าง Dataset `v9` + Arm B (`Attention-Only` Ablation) แยกต่างหาก
3. ไฟล์และ Artifact ของ `v7` และ `v8` ยังคงอยู่ครบถ้วนโดยไม่ถูกเขียนทับหรือลบ Checkpoint เดิม

---

### 10.2 เกณฑ์ตัวเลขสำหรับการตรวจสอบ Entity Leakage และ Data Integrity (Hard Numeric Gates)

เพื่อแก้ปัญหาจาก `nagi_500_v3` (ที่ `tools/audit_leakage_v3.py` พบว่าไม่ผ่าน strict entity-disjoint และ `unseen_entity_copy_acc` เป็น `N/A`) ชุดข้อมูลและ Tokenizer ของ `v9` ต้องผ่านเกณฑ์ตัวเลขด้านล่าง **ทุกข้อ (`100%` Zero-Tolerance)** ก่อนอนุญาตให้เข้าสู่ขั้นตอน Training:

| รหัสเกณฑ์ | ตัวชี้วัดการตรวจ Leakage (Audit Metric) | นิยามการคำนวณ | เกณฑ์ตัวเลขที่ต้องผ่าน |
|---|---|---|---|
| **EL-01** | **Train–Val Entity Overlap (`\|E_train ∩ E_val\|`)** | จำนวน Entity Token ที่ปรากฏทั้งใน `train` และ `val` (ตรวจทั้ง `input` และ `target`) | **`= 0` tokens (`0.00%`)** |
| **EL-02** | **Train–Test Entity Overlap (`\|E_train ∩ E_test\|`)** | จำนวน Entity Token ที่ปรากฏทั้งใน `train` และ `test` (ตรวจทั้ง `input` และ `target`) | **`= 0` tokens (`0.00%`)** |
| **EL-03** | **Val–Test Entity Overlap (`\|E_val ∩ E_test\|`)** | จำนวน Entity Token ที่ปรากฏทั้งใน `val` และ `test` (กันการ Tune บน Entity ของ Test) | **`= 0` tokens (`0.00%`)** |
| **EL-04** | **Entity Leakage Rate (`entity_leakage_rate`)** | สัดส่วนตัวอย่างใน `val` และ `test` ที่มี Entity ใดๆ ซ้ำกับ `train` (`leaked_examples / total_eval_examples`) | **`= 0.00%` (`0 / N_val` และ `0 / N_test`)** |
| **EL-05** | **Static Vocab Entity Leakage (`\|Vocab_train ∩ (E_val ∪ E_test)\|`)** | จำนวน Entity Token ของ `val`/`test` ที่หลุดเข้าไปอยู่ใน Vocabulary ของโมเดลตอนสร้าง Vocab | **`= 0` tokens (`0.00%`)** |
| **EL-06** | **Unseen Entity Sample Coverage (`unseen_entity_ratio`)** | สัดส่วนตัวอย่างที่มี Entity ใน `Test-Unseen-Entity` และ `Val-Unseen-Entity` ที่ใช้ Entity ใหม่ทั้งหมด | **`= 100.00%`** (`unseen_entity_count >= 100%` ของตัวอย่างที่มี Entity) |
| **EL-07** | **Minimum Distinct Unseen Entities (`\|E_val\|`, `\|E_test\|`)** | จำนวน Entity ใหม่ที่ไม่ซ้ำกันขั้นต่ำใน `val` และ `test` เพื่อป้องกันการสุ่ม/จำตัวเดียวและไม่ให้เป็น `N/A` | **`\|E_val\| >= 30`** และ **`\|E_test\| >= 30`** Entities (และ **`>= 5`** รูปแบบผสมต่อ Split) |
| **EL-08** | **Entity Pattern Coverage (Audit Regex/Parser)** | ตัวตรวจ Leakage ต้องจับครบทุก Format (`E\d+`, `*_e\d+`, `TR_*`, `VA_*`, `TE_*`, entity slots ทั้งหมด) | **Uncovered Entity Format `= 0`** |
| **TL-01** | **Template Overlap (`\|T_train ∩ T_val_ood\|`, `\|T_train ∩ T_test_ood\|`)** | จำนวน `template_id` และ Raw Phrasing Template ที่ซ้ำข้าม Split ใน OOD Slice | **`= 0` (`0.00%`)** |
| **SL-01** | **Abstract Structural Pattern Overlap** | จำนวน `abstract_pattern` (หลังแทน Entity ด้วย `<E0>`, `<E1>`, ...) ที่ซ้ำระหว่าง `train` กับ `OOD val/test` | **`= 0` (`0.00%`)** |
| **DL-01** | **Exact / Normalized Input & ID Duplicate** | จำนวน `id`, `input` ตรงตัว, และ `input` หลัง normalize (lowercase + collapse whitespace) ที่ซ้ำข้าม/ใน Split | **`= 0` (`0.00%`)** และ `empty_target == 0` |

> **กฎการ Fail-Closed ของ Data Gate:** หากตัวเลขข้อใดข้อหนึ่งจาก `EL-01` ถึง `DL-01` **ไม่เท่ากับค่าที่กำหนดแม้แต่ 1 ตัวอย่าง (`>= 1`)** ให้ถือว่า Data Integrity **FAIL** ทันที และห้ามนำชุดข้อมูลนั้นไปรัน Training หรือ Evaluation โดยเด็ดขาด

---

### 10.3 เกณฑ์ผ่านเชิงปริมาณของโมเดล (Model Performance, Generalization & Stability Criteria)

เมื่อชุดข้อมูลผ่าน Data Gate ในข้อ 10.2 ครบทุกข้อแล้ว โมเดล `v9` (Arm D) ต้องผ่านเกณฑ์เชิงตัวเลขและการเปรียบเทียบกับ Arm A (`v7`), Arm B (`v8-Ablation Attention-Only`), และ Arm C (`v8`) บน Benchmark เดียวกันดังนี้:

| หมวดเกณฑ์ | ตัวชี้วัด (Evaluation Metric) | เกณฑ์ตัวเลขที่ต้องผ่าน (Numeric Acceptance Threshold) | หมายเหตุการตรวจวัด |
|---|---|---|---|
| **1. Unseen Entity Copy** | `unseen_entity_copy_acc` (Free-Gen) | **`>= 0.85` (`85.0%`)** และต้อง **ไม่เป็น `N/A`** พร้อมสูงกว่า Arm A/B/C อย่างมีนัยสำคัญ | วัดผ่าน `dynamic local vocab` ในโหมด Free-Generation |
| **2. Unseen Entity Reasoning** | `unseen_entity_reasoning_acc` (Free-Gen) | **`>= 0.75` (`75.0%`)** บน `Test-Unseen-Entity` และชนะ Arm C (`v8`) **`>= +0.05` (`+5.0 pp`)** | วัดงานที่ไม่ใช่การ Copy ตรงตัวแต่ต้องใช้เหตุผลบน Entity ใหม่ |
| **3. OOD Generalization** | `free_gen_exact_match` บน `Test-OOD-Generalization` | ชนะ `max(Arm A, Arm B, Arm C)` ด้วยส่วนต่าง **`>= +0.05` (`+5.0 pp`)** และสูงกว่า Random/Majority Baseline **`>= +0.20`** | วัดบน Unseen Template และความลึก `4–5 hops` |
| **4. Multi-Hop Reasoning** | `multi_hop_acc` (แยก `2-hop`, `3-hop`, `4+ hop`) | **`>= 0.80`** ที่ `2–3 hops` และ **`>= 0.65`** ที่ `4+ hops` (ไม่ดิ่งลงระดับเดาสุ่ม `<= 0.33`) | ป้องกันโมเดลใช้ทางลัดเฉพาะ 2-hop แบบ `v3` |
| **5. Adaptive Learning** | `adaptive_override_acc` & `adaptive_retention_acc` | `override >= 0.75` และ `retention >= 0.85` พร้อมสูงกว่า Arm C (`v8`) อย่างชัดเจน | ต้องปรับคำตอบเมื่อมี `update:` และไม่ลืมกฎที่ไม่ได้แก้ |
| **6. Conflict & Knowledge** | `conflict_detection_f1` & `contradiction_acc` | **`F1 >= 0.80`** และไม่ทำนาย Label ปกติอย่างมั่นใจเมื่อมี `conflict` / cycle ในบริบท | แยก `update:` ออกจาก `conflict` ได้จริง |
| **7. Planning & Verification** | `plan_validity_acc`, `impossible_plan_acc`, `verification_acc` | แต่ละกลุ่ม **`>= 0.75`** และไม่มี Capability ใดต่ำกว่าคะแนนของ `v8` บน Benchmark เดียวกัน (**`0` Regression**) | วัดทั้งการเรียงลำดับ Topological และการจับแผนที่เป็นไปไม่ได้ |
| **8. Exposure Bias Gap** | `exposure_bias_gap` (`TF_exact - FG_exact`) | **`<= 0.10` (`<= 10.0 pp`)** และ **`< exposure_bias_gap(v8)`** | ยืนยันว่าโมเดลไม่ได้เก่งเฉพาะตอน Teacher-Forced |
| **9. Generation Stability** | `eos_hit_rate`, `premature_eos_rate`, `repetition_rate` | `eos_hit_rate >= 0.95` (`95%`), `premature_eos_rate <= 0.02` (`2%`), `repetition_rate <= 0.05` (`5%`) | วัดในโหมด Free-Generation เท่านั้น |
| **10. Pointer Gate Discipline** | `mean_p_gen` แยกตามประเภทงาน | Copy tasks **`<= 0.45`** (เปิด Copy) vs Reasoning/Verdict tasks **`>= 0.60`** (ใช้ Vocab Inference) | ป้องกัน Shallow Copy Collapse (`p_gen -> 0` ทุกงาน) |
| **11. Compute & Model Cap** | `params`, `seq_len`, Peak RAM, Elapsed Time | `params <= 5,000,000`, `seq <= 256` (เว้นแต่อนุมัติขยายเป็นลายลักษณ์อักษร), `NaN/Inf == 0` | คงวินัยทรัพยากรตามสเปกโครงการ |

---

### 10.4 เกณฑ์หยุดการทดลอง (Stop / Abort Criteria)
ให้ **หยุดการทดลอง v9 ทันที** เพื่อกลับไปวิเคราะห์หาสาเหตุ (ห้ามฝืนเพิ่ม Steps หรือปรับแต่งบน Test Set) หากเกิดข้อใดข้อหนึ่งต่อไปนี้:
1. **Leakage Violation (`EL-01..DL-01` ข้อใดข้อหนึ่ง `> 0`):** พบ Entity, Template, Abstract Pattern หรือ Input Overlap ข้าม Split แม้แต่ `1` รายการ → ยกเลิกผลรอบนั้นทั้งหมดและแก้ไข Dataset Generator ทันที
2. **Insufficient Unseen Coverage:** `unseen_entity_copy_acc` ออกมาเป็น `N/A` หรือ `|E_val| < 30` / `|E_test| < 30` → ถือว่าชุดทดสอบใช้ไม่ได้ ต้องแก้ Split ก่อน
3. **Training Instability:** Validation Loss เกิด `NaN`/`Inf` หรือ Diverge ต่อเนื่องจน Early-stop (`no_improve >= 2`) โดย Loss ไม่ลดลงจาก Initial Baseline
4. **No-Gain Complexity Bloat:** `v9` มีพารามิเตอร์หรือเวลาฝึกสูงกว่า `v8` แต่ `free_gen_exact_match` บน `Validation` หรือ `Test-OOD` ไม่ชนะทั้ง Arm B (`Attention-Only`) และ Arm C (`v8`) อย่างน้อย `+0.05` (`+5.0 pp`)
5. **Shallow Copy / Majority-Class Collapse:** `mean_p_gen < 0.15` ในงาน Reasoning/Verdict ที่ต้องตอบจาก Vocab หรือโมเดลตอบ Label ยอดนิยมซ้ำเดียว (`> 80%` ของคำตอบในงาน `verification`/`conflict`)
6. **Autoregressive Degeneration:** `repetition_rate > 0.10` (`> 10%`) หรือ `eos_hit_rate < 0.85` (`< 85%`) ใน Free-Generation

---

### 10.5 ข้อจำกัดเชิงธรรมาภิบาลและคำเตือนทางวิทยาศาสตร์
- **ห้ามใช้ Test Set ในการ Tuning:** การปรับ Hyperparameter, Model Selection, และ Early Stopping ต้องอิงจาก `Validation` เท่านั้น ส่วน `Test-Unseen-Entity` และ `Test-OOD-Generalization` ใช้ประเมินครั้งสุดท้ายแบบ Read-only
- **ห้าม Auto-Promote:** แม้โมเดล `v9` ผ่านเกณฑ์ข้างต้นทั้งหมด ก็เป็นเพียงความก้าวหน้าเชิงวิจัยภายในขอบเขต NGI Benchmark **ยังไม่ถือว่าบรรลุ AGI/NGI สมบูรณ์** และห้ามนำไปแทนที่ระบบหรือเปิดใช้ใน Production จนกว่าจะผ่านกระบวนการอนุมัติแยกต่างหาก
- **คงขอบเขต Roadmap 11–20:** เอกสารนี้ไม่เปิด Phase 21 และไม่แก้ไขโค้ด/Spec ของ Phase 11–20 (`phases/phase11.py`–`phase20.py`)

---

## 11. ขั้นตอนถัดไปเมื่อได้รับอนุมัติการทดลอง

1. **(Gate 1 — ยืนยันฐาน v8 & ปิดตัวเลข Codespaces เมื่อพร้อม):** ใช้ `docs/V8_SUMMARY.md` และ `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` เป็นฐานอ้างอิง Arm A/C และแนบ `report.json` จริงจาก Codespaces เมื่อซิงก์สภาพแวดล้อม
2. **(Gate 2 — จัดทำ Dataset v9 + Leakage Gate 4 ชั้น):** สร้าง `tools/gen_nagi_v9.py` และ `tools/audit_leakage_v9.py` แยกอิสระใน `data/nagi_v9/` ให้ผ่าน `EL-01..DL-01 == 0` และ `>= 40` Distinct Unseen Entities ต่อ Eval Split
3. **(Gate 3 — รัน 4-Arm Controlled Benchmark + 6 Principle Probes):** สร้าง `tools/train_nagi_v9.py` และ `tools/eval_nagi_v9.py` ทดสอบ Arm A/B/C/D บน `data/nagi_v9/` ภายใต้เพดาน CPU `<= 5M` (`docs/V9_EXPERIMENT_PLAN.md`) ก่อนพิจารณาขยายสู่ `v10 Relational & Multi-step Reasoning`

---

## 12. แนวทางรองรับ Capabilities ใหม่ของ v9 ใน Web & Conversation Layer (Analysis Only — ไม่แก้ Source Code เดิม)

จากการวิเคราะห์ไฟล์ **`apps/web/src/lib/conversation-api.ts`** และ **`apps/web/src/lib/native-chat.ts`** (ร่วมกับ `apps/web/src/lib/types.ts` และ `apps/api/routers/inference.py` โดย **ไม่แก้ไขซอร์สโค้ดแม้แต่บรรทัดเดียว**) พบข้อจำกัดและแนวทางวางสถาปัตยกรรมรองรับ Capabilities ของ `v9` ในอนาคตดังนี้:

### 12.1 ผลการวิเคราะห์ไฟล์ `apps/web/src/lib/native-chat.ts`
| ประเด็นจากซอร์สโค้ดจริง | ผลกระทบต่อ Capabilities `v9` | แนวทางออกแบบรองรับ (ไม่เปลี่ยนเป็น Chatbot-only) |
|---|---|---|
| **`buildNativeInferencePrompt` (บรรทัด 5–25):** ห่อ Prompt ปัจจุบันด้วย `user: ...\nassistant:` และต่อ History ย้อนหลัง | แทรก Wrapper Chat Tokens เข้าไปในโจทย์เชิงโครงสร้างของ `v9` (`fact:`, `deps:`, `claim:`, `update:`) ซึ่งรบกวน Tokenizer ของ Native Model และเสี่ยงชนเพดาน `max_seq_len=256` ของ `inference.py` บรรทัด 125 (`HTTP 422`) | วางแนวทางแยก **"Task Mode / Context Assembler"** ในอนาคต: โหมด `native_task` ส่ง Input เชิงโครงสร้างตรงเข้า NGI Model โดยไม่ห่อ `user:/assistant:` และเปลี่ยนการคุมขนาดจาก Character (`4096`) เป็น **Token-Aware Context Packing (`<= 256` tokens)** สำหรับ Working Memory |
| **`consumeNativeInferenceStream` (บรรทัด 27–112):** อ่านเฉพาะ SSE JSON `{ text: string, is_final: boolean }` และ `[DONE]` | ยังไม่มีช่องทางแยกแสดง **Reasoning Verdict (`true`/`false`/`unknown`/`conflict`/`impossible`)**, **Plan Steps**, **Adaptive Memory Delta**, หรือ **Pointer Gate Confidence (`mean_p_gen`)** | ออกแบบ Extension แบบ Non-Breaking บน SSE payload เดิม: คง `text` + `is_final` ให้เข้ากันได้กับ UI/Test เดิม 100% และเพิ่ม Optional Field `ngi_meta?: { capability, verdict, plan_steps, memory_ops, slot_bindings, model_version }` ผ่าน Callback แยกในอนาคต |

### 12.2 ผลการวิเคราะห์ไฟล์ `apps/web/src/lib/conversation-api.ts`
| ประเด็นจากซอร์สโค้ดจริง | ผลกระทบต่อ Capabilities `v9` | แนวทางออกแบบรองรับ (รักษา Auth/DB Schema เดิม) |
|---|---|---|
| **`ConversationMessage` & `saveConversationMessage` (บรรทัด 108–126):** รับเฉพาะ `role: "user"` และ `content: string` (`ConversationMessageCreate`) | โครงสร้างปัจจุบันเก็บเฉพาะข้อความ User/Assistant แบนราบ ยังไม่มี State แยกสำหรับ Working Memory (`base:` / `update:` / `retract:`) ในการทำ Adaptive Learning หรือ Knowledge Integration ข้าม Turn | **ระยะสั้น (Zero DB Migration):** Pack Working-Memory State ให้อยู่ใน canonical syntax (`base: ... \| update: ...`) ที่ตรวจย้อนกลับได้บน Session ฝั่ง Client โดยไม่แก้ DB Schema ตามข้อห้ามใน `HONOR_X6B_MOBILE_PLAN.md`; **ระยะยาว (`v11–v12+`):** เมื่อได้รับอนุมัติ จึงขยาย `ConversationResponse` ให้แนบ `session_knowledge_state` เพิ่มเติม |
| **Tenant & Idempotency Isolation (`identityHeaders` บรรทัด 43–45, `updateConversationMessage` บรรทัด 138–161):** ส่ง `X-Zyrquen-Expected-User-ID` และ Deduplicate ด้วย `message.id` (`request_id`) | รองรับการทำงานแบบ Multi-step Verification/Planning ต่อ 1 Turn ได้ดี เพราะ Backend (`inference.py`) ผูก `request_id` กับ `request_fingerprint` อยู่แล้ว | เมื่อ `v9–v14` ทำงาน Multi-step (Plan → Verify → Answer) ต้องให้คำตอบสุดท้ายและ Trace ทั้งหมดจบใน `request_id` เดียวกันและบังคับ Header `X-Zyrquen-Expected-User-ID` ในทุก Session Memory Store เพื่อกันความรู้ของ User A รั่วไปหา User B |

> **ข้อสรุปด้าน Integration:** ไม่ต้องแก้ไข `apps/web/src/lib/conversation-api.ts` หรือ `apps/web/src/lib/native-chat.ts` ในรอบนี้ การผสานเข้า Web/API จะเกิดขึ้นเฉพาะเมื่อ Model `v9` ผ่าน Acceptance Gate (`Section 10`) และได้รับอนุมัติแยกต่างหากแล้วเท่านั้น

---

**สถานะเอกสาร:** ปรับปรุง Blueprint และบทวิเคราะห์ Integration สำหรับ `v9 — Generalization` เรียบร้อย — **หยุดรออนุมัติจากเจ้าของโครงการ**


