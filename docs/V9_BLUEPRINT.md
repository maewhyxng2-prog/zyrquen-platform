# ZYRQUEN Ω∞ — v9 — Generalization & Native Reasoning Blueprint

- **สถานะเอกสาร:** `DRAFT BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION OR TRAINING`
- **สถานะ v8 ปัจจุบัน:** `FROZEN` (รอการปิดการทดลองและการตรวจหลักฐานรันไทม์อย่างเป็นทางการตาม `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`)
- **เป้าหมายหลัก:** วางแผนพัฒนาความสามารถ **Native General Intelligence (NGI)** ของโมเดล ZYRQUEN ต่อจากผลการทดลอง `v8` โดยรักษาทิศทาง NGI (Native Representation, Knowledge Acquisition & Integration, Relational Reasoning, Planning & Decomposition, Verification, Adaptive Learning) และ **ไม่เปลี่ยนทิศทางเป็น Chatbot-only หรือ HTML/App Generator**
- **ขอบเขตเอกสาร:** เอกสารวางแผนล่วงหน้าเท่านั้น ยังไม่มีการแก้ไข Source Code, Dataset, Checkpoint, Evaluation Report, หรือ Roadmap Phase 11–20 และยังไม่มีการรัน Training หรือ Evaluation

---

## 1. วิเคราะห์ผล v8 และข้อจำกัดที่ต้องแก้ใน v9

### 1.1 สิ่งที่ v8 วางรากฐานไว้ (อ้างอิงสถานะจริงใน Repository)
การทดลอง `v8` (`tools/train_nagi_500_v8.py` และ `tools/eval_nagi_500_v8.py`) ทดลองเปลี่ยนสถาปัตยกรรมจาก `TinyNGI` 2-layer LSTM ใน `v7` (`tools/train_nagi_500_v7.py`) มาเป็น `Seq2Seq` (`BiGRU Encoder + Bahdanau Additive Attention + Pointer-Copy Gate` ที่ `hid_dim=128`) โดยใช้ชุดข้อมูล `data/nagi_500_v3` และตั้งค่าควบคุมให้สอดคล้องกับ `v7` (`batch_size=4`, sequential batch order, `seq=256`, `Adam lr=0.001`, `seed=42`, train-only vocab)

ในพื้นที่ทำงานปัจจุบัน สถานะของการปิดการทดลอง `v8` ยังเป็น **`PARTIAL / BLOCKED IN WORKSPACE`** และ **`FROZEN`** เนื่องจากไฟล์ `checkpoints/nagi_500_v8/*.pt`, `eval/nagi_500_v8/report.json`, `eval/nagi_500_v7_500/report.json`, และ `data/nagi_500_v3/*.jsonl` อยู่ในสภาพแวดล้อมที่รันจริง (Codespaces) ไม่ได้อยู่ใน Snapshot นี้ ตัวเลขผลลัพธ์จริงของ `v8` จึงยังต้องรอการแนบและยืนยันอย่างเป็นทางการก่อนปลด Freeze

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

### 2.2 แนวทางออกแบบสำหรับ v9
1. **การแยก Entity Pool ข้าม Split โดยสมบูรณ์:**
   - กำหนด Pool แยกขาด: `Train` (`TR_E000..`), `Validation` (`VA_E000..`), และ `Test` (`TE_E000..`) รวมถึงรูปแบบผสม เช่น `obj_val_*`, `node_test_*` เพื่อทดสอบ Unseen Token Forms
2. **Role-Agnostic Representation & Relative Positional / Structural Binding:**
   - ออกแบบ Representation ให้โมเดลแยก "โครงสร้างความสัมพันธ์/ตัวดำเนินการ" (`->`, `>`, `<`, `=`, `before`, `conflicts`) ออกจาก "ตัวระบุ Entity"
   - พิจารณาใช้สถาปัตยกรรมที่มี Self-Attention / Cross-Attention หรือ Slot-Indexed Memory (ภายใต้เพดานพารามิเตอร์ของโครงการ) เพื่อสร้าง Dynamic Entity Representation จากบริบทแทนการจำ Static Embedding
3. **Controlled Copy-Reasoning Separation:**
   - แยกงานที่ต้อง Copy Unseen Entity (เช่น `A` จาก `A -> B`) ออกจากงานที่ต้อง Infer Symbol (`true`, `false`, `conflict`, `>`, `impossible`) เพื่อป้องกันไม่ให้ `p_gen` collapse ลงไป Copy Entity ตัวหลอกในอินพุต
   - เพิ่มตัวอย่างที่มี **Distractor Entities** (Entity ที่ไม่เกี่ยวข้องกับคำถาม) เพื่อทดสอบว่า Pointer/Attention ชี้ถูกตัวจริง ไม่ใช่เลือกตัวแรกหรือตัวสุดท้ายแบบสุ่ม

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
1. เจ้าของโครงการอนุมัติปิดการทดลอง `v8` อย่างเป็นทางการ พร้อมแนบหลักฐานผลรันจริง (`eval/nagi_500_v8/report.json` และ `eval/nagi_500_v7_500/report.json`) จาก Codespaces
2. เจ้าของโครงการอนุมัติ `docs/V9_BLUEPRINT.md` ฉบับนี้ และอนุมัติแผนย่อยสำหรับการสร้าง Dataset `v9` + Arm B (`Attention-Only` Ablation) แยกต่างหาก
3. `v7` และ `v8` ยังคงไม่ถูกเขียนทับหรือลบ Checkpoint เดิม

### 10.2 เกณฑ์ผ่าน (Pass / Acceptance Criteria) สำหรับ v9

| หมวดเกณฑ์ | เงื่อนไขขั้นต่ำที่ต้องผ่านครบทุกข้อ |
|---|---|
| **1. Data & Leakage Gate** | ผ่าน Leakage Check ทั้ง 4 ชั้น (`entity_overlap = 0`, `template_overlap_ood = 0`, `abstract_pattern_overlap_ood = 0`, `exact_dup = 0`, `norm_dup = 0`) และมี `manifest.json` พร้อม `SHA-256` |
| **2. Unseen Entity Generalization** | `unseen_entity_copy_acc` และ `unseen_entity_reasoning_acc` คำนวณได้จริง (ไม่เป็น `N/A`) และ `v9` ทำ Free-generation บน `Test-Unseen-Entity` ชนะทั้ง `v7` และ `v8` |
| **3. Multi-hop & OOD Generalization** | บน `Test-OOD-Generalization` (เช่น Unseen Template / Depth 4+ hops) `v9` มี Free-gen Exact Match สูงกว่า Arm A (`v7`), Arm B (`Attn-only`), และ Arm C (`v8`) อย่างชัดเจน ไม่ใช่แค่เท่าเดิม |
| **4. Capability Integrity (Zero Regression)** | ไม่มี Capability ใดใน 6 กลุ่ม (`native_representation`, `knowledge_acquisition/integration`, `relational_reasoning`, `planning_decomposition`, `verification`, `adaptive_learning`) ที่มีคะแนน Free-gen ถดถอยต่ำกว่า `v8` |
| **5. Adaptive & Conflict Resolution** | `adaptive_override_acc` > Majority-Class Baseline และสูงกว่า `v8`; สามารถแยก `conflict` ออกจากข้อมูลสอดคล้องโดยไม่เดาคำตอบเดียวแบบผิดพลาด |
| **6. Generation Stability & Exposure Bias** | `eos_hit_rate >= 0.95`, `repetition_rate <= 0.05`, และ `exposure_bias_gap` (`TF - FG`) ลดลงเมื่อเทียบกับ `v8` |
| **7. Resource & Budget Compliance** | จำนวนพารามิเตอร์ `<= 5,000,000` (ตามเพดานสเปกโครงการ) และ Peak RAM/เวลาฝึกไม่เกินขีดจำกัดสภาพแวดล้อมที่อนุมัติ |

### 10.3 เกณฑ์หยุดการทดลอง (Stop / Abort Criteria)
ให้ **หยุดการทดลอง v9 ทันที** เพื่อกลับไปวิเคราะห์หาสาเหตุ (ไม่ฝืนเพิ่ม Steps หรือปรับแต่งบน Test Set) หากเกิดข้อใดข้อหนึ่งต่อไปนี้:
1. **ตรวจพบ Leakage ใดๆ (`> 0`)** ระหว่าง `train`, `val`, `test` หลังเริ่มการทดลอง → ยกเลิกผลรอบนั้นทั้งหมดและแก้ Generator ก่อน
2. **Training Instability:** Validation Loss เกิด `NaN`/`Inf` หรือ Diverge ต่อเนื่องหลังปรับ Checkpoint Best Val State
3. **No-Gain Complexity Bloat:** `v9` มีพารามิเตอร์หรือเวลาฝึกสูงกว่า `v8` แต่ผล Free-generation บน `Validation` และ `Test-OOD` ไม่ชนะทั้ง `v8` และ `v8-Ablation (Attention-Only)`
4. **Shallow Copy / Shortcut Collapse:** โมเดลแก้ปัญหาด้วยการลด `p_gen` ใกล้ `0` เพื่อ Copy โทเคนในงานที่ไม่ใช่การ Copy หรือตอบ Label ยอดนิยมเพียงค่าเดียวในงาน Verification/Conflict
5. **Autoregressive Degeneration:** `repetition_rate` พุ่งสูง หรือ `eos_hit_rate` ตกต่ำจน Free-generation ไม่จบประโยค

### 10.4 ข้อจำกัดเชิงธรรมาภิบาลและคำเตือนทางวิทยาศาสตร์
- **ห้ามใช้ Test Set ในการ Tuning:** การปรับ Hyperparameter และเลือก Checkpoint ต้องอิงจาก `Validation` เท่านั้น `Test` ใช้ประเมินครั้งสุดท้ายแบบ Read-only
- **ห้าม Auto-Promote:** แม้โมเดล `v9` ผ่านเกณฑ์ข้างต้น ก็ยังไม่ถือว่าบรรลุ NGI สมบูรณ์ และห้ามนำไปแทนที่ระบบหรือเปิดใช้ใน Production จนกว่าจะผ่านกระบวนการอนุมัติแยกต่างหาก
- **คงขอบเขต Roadmap 11–20:** เอกสารนี้ไม่เปิด Phase 21 และไม่แก้ไขโค้ด/Spec ของ Phase 11–20 (`phases/phase11.py`–`phase20.py`)

---

## 11. ขั้นตอนถัดไปเมื่อได้รับอนุมัติจากเจ้าของโครงการ

1. **(Gate 1 — ปิด v8):** รวบรวม `report.json` จริงของ `v7` และ `v8` ใน Codespaces เพื่อปิด `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` ให้สมบูรณ์ (ปลดล็อกสถานะ `BLOCKED` จาก Workspace)
2. **(Gate 2 — อนุมัติ Blueprint v9):** เจ้าของโครงการตรวจและอนุมัติ `docs/V9_BLUEPRINT.md` ฉบับนี้ (หรือระบุจุดที่ต้องปรับ)
3. **(Gate 3 — จัดทำ Dataset Spec & Generator v9 + Arm B Ablation Plan):** เมื่อได้รับอนุญาต จึงจะสร้างสเปกและเครื่องมือสร้างข้อมูล `v9` (แยกอิสระจาก `v8`) พร้อม Script ตรวจสอบ Leakage 4 ชั้น ก่อนขออนุมัติ Training รอบแรกต่อไป

---

**สถานะเอกสาร:** จัดทำเสร็จสมบูรณ์ตามคำขอวางแผนล่วงหน้า — **หยุดรออนุมัติจากเจ้าของโครงการ**
