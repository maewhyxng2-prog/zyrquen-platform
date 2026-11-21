# ZYRQUEN Ω∞ — สรุปงานทดลอง v8 และข้อกำหนดการระงับการเปลี่ยนแปลง (v8 Summary & Freeze Rules)

- **ขอบเขตงาน:** การทดลองควบคุมสถาปัตยกรรม `v8` (`Seq2Seq + Bahdanau Attention + Pointer-Copy`, `hid_dim=128`) เพื่อเปรียบเทียบอย่างยุติธรรมกับ Baseline `v7` (`TinyNGI` 2-layer LSTM)
- **สถานะปัจจุบัน:** ระงับการเปลี่ยนแปลงทั้งหมด (Frozen) เพื่อรอการตรวจสอบและอนุมัติจากเจ้าของโครงการ
- **ขอบเขตข้อสรุปทางวิทยาศาสตร์:** การเพิ่ม Attention และ Pointer-Copy เป็นเพียงการทดลองเชิงสถาปัตยกรรม **ไม่ใช่หลักฐานว่า ZYRQUEN บรรลุความสามารถ NGI แล้ว**

---

## 1. รายการไฟล์ทั้งหมดของงาน v8 และความเชื่อมโยงกับ Baseline v7

### 1.1 ไฟล์ที่สร้าง/จัดทำขึ้นสำหรับงาน v8 ใน Workspace

| ไฟล์ | หน้าที่ในงานทดลอง v8 | ขนาด (bytes) | SHA-256 (ตรวจจากไฟล์จริง) | ความเชื่อมโยงกับ v7 Baseline |
|---|---|---:|---|---|
| `tools/train_nagi_500_v8.py` | สคริปต์ฝึกโมเดล v8 (`BiGRU Encoder + Bahdanau Attention + PointerDecoder`, `hid_dim=128`) | `14,215` | `6f242f66c990b5112b2ba69839fa05c43f70e1ba112eb884e1df3e6792133bd4` | แยกไฟล์อิสระจาก `train_nagi_500_v7.py` แต่ใช้ Dataset (`data/nagi_500_v3`), `tokenize()`, train-only vocab, `batch_size=4`, sequential batch, `Adam(lr=0.001, weight_decay=0.01)`, `--seq 256`, `--seed 42` และ early-stop เหมือน `v7`; แยกโฟลเดอร์เซฟไปที่ `checkpoints/nagi_500_v8` |
| `tools/eval_nagi_500_v8.py` | สคริปต์ประเมินผล v8 แบบ Read-only (Teacher-forced vs Free-generation แยกราย Capability) | `27,226` | `47c271981598363ab0f5e1ba745dd07a65f83ae4ccd9efa662c83f02511dff1f` | ตรวจ `arch == "seq2seq_attn_pointer"` เพื่อไม่ให้ปะปนกับ `v7`; ใช้ `val.jsonl` / `test.jsonl` ชุดเดียวกัน; อ่าน `--v7_report` (`eval/nagi_500_v7_500/report.json`) แบบ Read-only เพื่อทำตารางเปรียบเทียบ `v7_baseline_comparison` |
| `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` | รายงานปิดการทดลอง v8 (`PASS` / `BLOCKED` / `NOT RUN`) และโครงสร้างเทียบผล Teacher-forced vs Free-gen | อัปเดตล่าสุด | *(ดูจากไฟล์ใน `docs/`)* | สรุปผลการตรวจความสอดคล้องกับ `v7`, ข้อจำกัดที่พบ, และแยกสิ่งที่ตรวจได้ใน Workspace ออกจากผลรันใน Codespaces |
| `tools/v8_summary.md` | เอกสารสรุปรายการไฟล์ ความเชื่อมโยงกับ Baseline และกฎข้อห้ามระหว่างรอตรวจ | เอกสารฉบับนี้ | — | ยืนยันความแยกอิสระจาก `v7` และตรึงสถานะห้ามแก้ไข/รัน/ลบ/Commit |

> **หมายเหตุเกี่ยวกับ Artifact รันไทม์:** ในคอนเทนเนอร์ AI Studio นี้ไม่มี `data/nagi_500_v3/`, `checkpoints/`, `eval/` และ `torch` ดังนั้น Checkpoint (`checkpoints/nagi_500_v8/*.pt`), `metrics.json` และรายงานรันจริง (`eval/nagi_500_v8/report.json`, `report.md`) จะอยู่ในสภาพแวดล้อม Codespaces ที่รันจริงเท่านั้น

### 1.2 ไฟล์ Baseline เดิมที่ต้องคงไว้โดยห้ามแก้ไข

| ไฟล์ | หน้าที่ | ขนาด (bytes) | SHA-256 | สถานะ |
|---|---|---:|---|---|
| `tools/train_nagi_500_v7.py` | Trainer Baseline `v7` (`TinyNGI`) | `8,503` | `fa70ecb1354088eaf5d5438788019fb5dd127f6224d9084d70edd93c9ef52ed6` | ไม่ถูกแก้ไข (Intact) |
| `tools/eval_nagi_500_v5.py` | Evaluator เดิมใน Repository | `9,390` | `7990eb6c2098a24de537f9702085215b971045860811f1aceb8812490c76ea2a` | ไม่ถูกแก้ไข (Intact) |

---

## 2. สรุปความสอดคล้องของสถาปัตยกรรมและชุดข้อมูล (Scope Cross-Reference)

1. **แยกส่วนจาก v7 อย่างสมบูรณ์:** ไม่มีคำสั่งเขียนทับไฟล์ `v7`, Checkpoint ของ `v7`, หรือรายงาน `eval/nagi_500_v7_500/*`
2. **ชุดข้อมูล Split เดียวกัน:** ทั้ง Trainer และ Evaluator ใช้ `--data data/nagi_500_v3` (`train.jsonl`, `val.jsonl`, `test.jsonl`) ตรวจ `empty_tgt == 0` และ `train_ids & test_ids == set()` พร้อม Vocab จาก `train.jsonl` เท่านั้น
3. **Attention + Pointer-Copy (`hid_dim=128`):**
   - `Encoder`: Bidirectional GRU (`hid_dim=128`) ส่ง `encoder_outputs` ทุกตำแหน่ง `[B, S, 256]`
   - `Attention`: Bahdanau additive attention พร้อม mask `<pad>` (`src != 0`)
   - `PointerDecoder`: ผสาน `p_gen * vocab_dist + (1 - p_gen) * copy_dist` และขยาย `ext_dist` ด้วย dynamic local vocab ในโหมด Free-generation เพื่อคัดลอก Entity ที่ไม่เคยอยู่ใน Vocab (`E00–E99`, `*_e000`)
4. **การวัดผลราย Capability (Teacher-forced vs Free-generation):** คำนวณ `exact_match`, `first_token_acc`, `eos_hit_rate`, `avg_eos_position`, `premature_eos_rate`, `repetition_rate`, `entity_copy_acc`, `unseen_entity_copy_acc`, `exposure_bias_gap`, และ `mean_p_gen` ครบทั้ง `val` และ `test` แยกราย Capability และภาพรวม

---

## 3. ข้อจำกัดบังคับเด็ดขาด (Strict Freeze Restrictions)

เพื่อรักษาความถูกต้องเชิงทดลองและความสามารถในการทำซ้ำของ **ZYRQUEN Ω∞** จนกว่าเจ้าของโครงการจะอนุมัติอย่างเป็นทางการ **ห้ามดำเนินการต่อไปนี้โดยเด็ดขาด**:

- **ห้ามแก้ไขไฟล์:** ห้ามแก้โค้ดใน `tools/train_nagi_500_v7.py`, `tools/eval_nagi_500_v5.py`, `tools/train_nagi_500_v8.py`, `tools/eval_nagi_500_v8.py` รวมถึง Web App, API และ Database
- **ห้าม Commit:** ห้ามใช้ `git add` หรือ `git commit` ใด ๆ
- **ห้าม Push:** ห้ามใช้ `git push` ขึ้น Remote Repository
- **ห้ามลบ Checkpoint:** ห้ามลบ เคลื่อนย้าย หรือเขียนทับไฟล์ Checkpoint (`checkpoints/*`) และรายงานผลประเมินเดิม (`eval/*`)
- **ห้ามเริ่มกระบวนการ Training หรือ Evaluation ซ้ำ:** ห้ามรัน `train_nagi_500_v8.py` หรือฝึกโมเดลเพิ่มเติม
- **ห้ามสร้าง Phase ใหม่หรือรุ่นถัดไป:** ห้ามเปิดงาน `v9`, Ablation หรือ Phase ใหม่ (`Phase 11–20` / `Phase 21`) ก่อนปิดและอนุมัติผล `v8`
