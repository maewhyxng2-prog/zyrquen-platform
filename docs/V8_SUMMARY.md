# ZYRQUEN Ω∞ — v8 Summary (Experiment Closure, Limitations & Freeze Status)

- **สถานะเอกสาร:** `V8 BASELINE SUMMARY FOR V9 PLANNING`
- **สถานะการทดลอง v8:** **ปิดการทดลองแล้วตามทิศทางเจ้าของโครงการ (Transition Baseline → `v9 Generalization`)** / `FROZEN` — ใน Snapshot พื้นที่ทำงานนี้ยังคงสถานะหลักฐานรันไทม์เป็น `PARTIAL — BLOCKED IN WORKSPACE` จนกว่าจะแนบ `report.json` จริงจาก Codespaces ตาม `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`
- **วัตถุประสงค์ของเอกสาร:** สรุปผลการทดลอง ข้อจำกัดเชิงโครงสร้าง และสถานะล่าสุดของรุ่น `v8` เพื่อใช้เป็นฐานข้อมูลอ้างอิงสำหรับการเริ่มวางแผน `docs/V9_BLUEPRINT.md` และ `docs/V9_EXPERIMENT_PLAN.md` โดย **ไม่แต่งตัวเลขผลรันที่ไม่มีใน Workspace**

---

## 1. ภาพรวมสถาปัตยกรรมและขอบเขตของ v8

รุ่น `v8` ถูกออกแบบเป็นการทดลองควบคุมด้านสถาปัตยกรรม (Controlled Architecture Experiment) เพื่อเทียบกับ Baseline `v7` (`TinyNGI`) โดยเพิ่มกลไก Attention และ Pointer-Copy บนชุดข้อมูลเดิม `data/nagi_500_v3`:

| รายการ | Baseline `v7` (`tools/train_nagi_500_v7.py`) | รุ่นทดลอง `v8` (`tools/train_nagi_500_v8.py`) |
|---|---|---|
| **Architecture** | `TinyNGI` — Embedding(128) + 2-layer LSTM(128, dropout=0.2) + Linear Head | `Seq2Seq` — Bidirectional GRU Encoder(128→256) + Bahdanau Additive Attention + `PointerDecoder` GRU(128) + `p_gen` Gate |
| **Parameter Count** | `273,955` *(ตามบันทึกอ้างอิงของเจ้าของโครงการ)* | `523,708` *(ตามบันทึกอ้างอิงของเจ้าของโครงการ — เพิ่มขึ้น ~1.91x)* |
| **Dataset & Split** | `data/nagi_500_v3` (`train=400`, `val=50`, `test=50`) | `data/nagi_500_v3` (`train=400`, `val=50`, `test=50`) |
| **Vocabulary** | Token-level, train-only (`<pad>`, `<bos>`, `<eos>`, `<unk>`) | Token-level, train-only (`<pad>`, `<unk>`, `<bos>`, `<eos>`) + dynamic local vocab ขณะ Free-gen ใน `eval_nagi_500_v8.py` |
| **Training Config (ฉบับล่าสุดใน Repo)** | `batch=4`, sequential batch, `seq=256`, `Adam(lr=0.001, weight_decay=0.01)`, `steps=500`, `eval_every=50`, early-stop (`no_improve >= 2`) | `batch=4`, sequential batch, `seq=256`, `Adam(lr=0.001, weight_decay=0.01)`, `steps=500`, `eval_every=50`, `seed=42`, `tf_ratio: 1.0 → 0.5`, grad clip `1.0`, early-stop (`no_improve >= 2`) |
| **หมายเหตุ Revision** | คงที่ (`SHA-256: fa70ecb1...`) | โค้ดฉบับแรกเคยใช้ `random.sample` (`batch=16`, `AdamW lr=2e-3`) ก่อนปรับในฉบับปัจจุบัน (`SHA-256: 6f242f66...`) ให้เทียบเท่า `v7` |

---

## 2. สรุปผลการตรวจสอบใน Workspace และสิ่งที่ยังไม่ยืนยัน (Audit Status)

### 2.1 สิ่งที่ยืนยันได้จากไฟล์โค้ดและเอกสารจริงใน Workspace (`PASS`)
- **Trainer & Evaluator พร้อมสมบูรณ์เชิงโครงสร้าง:**
  - `tools/train_nagi_500_v8.py` (`14,215` bytes, `SHA-256: 6f242f66c990b5112b2ba69839fa05c43f70e1ba112eb884e1df3e6792133bd4`)
  - `tools/eval_nagi_500_v8.py` (`27,226` bytes, `SHA-256: 47c271981598363ab0f5e1ba745dd07a65f83ae4ccd9efa662c83f02511dff1f`)
  - ทั้งสองไฟล์แยกอิสระจาก `v7` (`tools/train_nagi_500_v7.py` `SHA-256: fa70ecb1...`, `tools/eval_nagi_500_v5.py` `SHA-256: 7990eb6c...`) และผ่านการตรวจไวยากรณ์ (`ast.parse`)
- **กลไก Evaluation ของ `v8` ครบมิติกว่าเดิม:** แยกรายงาน **Teacher-Forced** เทียบกับ **Free-Generation (Autoregressive)**, คำนวณ Exposure Bias Gap (`TF exact - FG exact`), EOS Hit Rate, Premature EOS Rate, Repetition Rate, Entity Copy Accuracy, Unseen Entity Copy Accuracy (dynamic local vocab รองรับ `E\d+` และ `*_e\d+`), `mean_p_gen` และเปรียบเทียบ `v7_baseline_comparison` แบบ Read-only
- **ผลการ Audit ชุดข้อมูล `nagi_500_v3` จากโค้ด `tools/audit_leakage_v3.py` และ `tools/gen_nagi_500_v3.py`:**
  - **Combination-disjoint (`PASS`):** ไม่มีสตริง `input` ซ้ำข้าม Split
  - **Entity & Template disjoint (`FAIL`):** `nagi_500_v3` ใช้ Entity Pool `E00–E19` ซ้ำทั้ง `train`, `val`, `test` และแชร์ Template เดียวกัน (`entities: REUSED`, `templates: SHARED`)

### 2.2 สิ่งที่ติดสถานะ `BLOCKED` / `NOT RUN` ใน Workspace ปัจจุบัน
- **ไม่มี Artifact รันไทม์ใน Snapshot นี้:** ไม่พบโฟลเดอร์ `checkpoints/nagi_500_v8/`, `eval/nagi_500_v8/`, `eval/nagi_500_v7_500/`, หรือ `data/nagi_500_v3/` และไม่มี `torch` ในคอนเทนเนอร์นี้
- **ไม่มีตัวเลขผลประเมินจริงของ `v7` และ `v8` ใน Workspace:** ค่าตัวเลข `exact_match`, `first_token_acc`, `loss_avg`, `eos_hit_rate`, `repetition_rate`, `mean_p_gen`, `elapsed_sec`, และ `max_rss_kb` ทั้งในโหมด Teacher-Forced และ Free-Generation จึงยังคงสถานะ **`BLOCKED`** (ห้ามคัดลอกหรือแต่งตัวเลข จนกว่าจะนำไฟล์ `report.json` จริงจาก Codespaces มาแนบ)

---

## 3. ข้อจำกัดของ v8 ที่ส่งผลโดยตรงต่อการวางแผน v9

อ้างอิงจาก `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`, `tools/v8_summary.md`, `tools/gen_nagi_500_v3.py`, และ `tools/audit_leakage_v3.py`:

| รหัส | ข้อจำกัดที่พบใน `v8` | รายละเอียดเชิงเทคนิค | แนวทางแก้ที่ส่งต่อไปยัง `v9` Blueprint |
|---|---|---|---|
| **L1** | **Unseen Entity Copy เป็น `N/A`** | `nagi_500_v3` ใช้ `E00–E19` ซ้ำทุก Split ทำให้ `unseen_entity_count == 0` ใน Split จริง (และโค้ดรุ่นก่อนหน้าไม่จับแพตเทิร์น `*_e\d+`) จึงวัดความสามารถกับ Unseen Entity ไม่ได้ | บังคับ Entity Disjointness `100%` (`|E_train ∩ E_val| = 0`, `|E_train ∩ E_test| = 0`, `|E_val ∩ E_test| = 0`) และมี Unseen Entity เพียงพอในทุก Split |
| **L2** | **Adaptive Learning ยังมีตัวอย่างล้มเหลวและรูปแบบตื้น** | รูปแบบใน `v3` มีเพียง `learn: A -> B | predict A ?` (1-step lookup) ไม่มีกรณี Rule Override หรือการคงความรู้เดิมเมื่อมีกฎใหม่ขัดแย้ง | เพิ่ม In-Context Rule Override, Selective Retention, Chained Adaptation และ Fact Retraction |
| **L3** | **`mean_p_gen` ต่ำและเสี่ยง Shallow Copy Bias** | Pointer-Copy Gate อาจเอนเอียงไปทาง `copy_dist` มากกว่าการให้เหตุผลเชิงโครงสร้างเมื่อคำตอบปรากฏในบริบท | แยกงาน Copy-Entity ออกจาก Reasoning/Verdict และตรวจเกณฑ์ `mean_p_gen` ตามชนิดงานเพื่อกัน Gate Collapse |
| **L4** | **ขาด Ablation แยกผล Attention vs Pointer-Copy** | `v8` เพิ่ม `BiGRU + Bahdanau Attention` และ `Pointer-Copy` พร้อมกัน ทำให้แยกไม่ได้ว่าผลที่เปลี่ยนมาจากส่วนใด | กำหนด **Arm B (`Attention-Only` ไม่มี Pointer-Copy)** เป็นแขนบังคับใน 4-Arm Benchmark ของ `v9` |
| **L5** | **Parameter Count เพิ่มเกือบ 2 เท่า (`273,955` → `523,708`)** | การขยายเป็น BiGRU + Attention + Pointer-Copy ใช้พารามิเตอร์เกือบ 2 เท่าของ `v7` ที่ `hid_dim=128` | บังคับเทียบ Efficiency (`FG_exact / params`) คุมเพดาน `<= 5M` และตั้ง Stop Criterion สำหรับ No-Gain Complexity Bloat |
| **L6** | **การให้เหตุผลและการวางแผนจำกัดความลึก/Template** | `relational_reasoning` ใน `v3` มีเพียง 2 hops คงที่; `planning_decomposition` เป็นเพียง Position Indexing (`first/middle/last`); `verification` ใช้คู่คำตายตัว | ขยายสู่ Multi-hop Graph Traversal (ฝึก 2–3 hops, ทดสอบ 4–5 hops), Topological Dependency Planning และ Conflict/Contradiction Detection |
| **L7** | **Template & Structural Leakage ข้าม Split ใน `v3`** | `audit_leakage_v3.py` ยืนยันว่า `v3` ไม่ผ่าน Strict Entity-Disjoint และ Strict Template-Disjoint | บังคับ Leakage Gate 4 ชั้นใน `v9` (Exact/Norm Dup = 0, Entity = 0, OOD Template = 0, OOD Abstract Pattern = 0) |
| **L8** | **`<unk>` Collision ใน Encoder เมื่อมี Unseen Entity ตั้งแต่ 2 ตัวขึ้นไป** | ใน `eval_nagi_500_v8.py` บรรทัด 233 Encoder รับ `stoi.get(t, unk_id)` จึงยุบ Entity ใหม่ทุกตัวในโจทย์เดียวกันเป็น `<unk>` เดียวกัน แม้ Decoder มี `local_stoi` สำหรับ Copy ก็แยก Entity ต้นทางระหว่างใช้เหตุผลไม่ได้ | ออกแบบ Context-Local Ephemeral Entity Slotizer (`<slot_0>.. <slot_31>` + Slot Permutation Equivariance) ใน `v9` โดยไม่ใส่ Entity Test เข้า Static Vocab |

---

## 4. สถานะล่าสุดและกฎการระงับการเปลี่ยนแปลง (Freeze Status)

- **สถานะปัจจุบันของ `v8`:** **ปิดการทดลองแล้วและคงสถานะ `FROZEN`** — ห้ามแก้ไข `tools/train_nagi_500_v7.py`, `tools/eval_nagi_500_v5.py`, `tools/train_nagi_500_v8.py`, `tools/eval_nagi_500_v8.py`, `tools/gen_nagi_500_v3.py`, Checkpoint, Dataset หรือ Report เดิม โดยใช้เป็น Baseline อ้างอิง (Arm A / Arm C) สำหรับ `v9`
- **ความเชื่อมโยงสู่เส้นทาง `v9` และถัดไป:**
  1. ใช้ `v8` เป็นฐานเปรียบเทียบแบบควบคุมควบคู่กับ Arm B (`Attention-Only` Ablation) บน Dataset `v9` ที่ปลอด Leakage
  2. นำหลักฐานรันไทม์จริงจาก Codespaces (`report.json`, `SHA-256`) มาแนบใน `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` เมื่อซิงก์สภาพแวดล้อมเพื่อปลดล็อกตัวเลขที่ยัง `BLOCKED` ใน Workspace
  3. ดำเนินการวางแผน `v9 — Generalization` ตาม `docs/V9_BLUEPRINT.md` และ `docs/V9_EXPERIMENT_PLAN.md` ก่อนขออนุมัติเริ่มสร้างสคริปต์และรัน Training จริง
- **ความสอดคล้องเชิงเป้าหมาย:** `v8` วางรากฐาน Attention + Pointer-Copy และปิดการทดลองแล้ว แต่ยังไม่ถือเป็น NGI สมบูรณ์ ต้องต่อยอดสู่ `v9 (Generalization)` และ `v10+` ต่อไปภายใต้ Roadmap Phase 11–20 เดิม
