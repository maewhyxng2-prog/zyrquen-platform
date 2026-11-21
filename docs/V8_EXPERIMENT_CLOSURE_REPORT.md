# ZYRQUEN Ω∞ — v8 Experiment Closure & Reproducibility Audit Report

- **Status:** `PARTIAL / BLOCKED IN WORKSPACE` (รอการอนุมัติและตรวจหลักฐานรันไทม์จากสภาพแวดล้อมที่มี Checkpoint / Eval Report จริง)
- **Scope:** Controlled Architecture Experiment `v8` (`Seq2Seq + Bahdanau Attention + Pointer-Copy`, `hid_dim=128`) vs `v7` Baseline (`TinyNGI` 2-layer LSTM)
- **Constraint Compliance:** ไม่มีการแก้ไข `v7` และ `v8`, ไม่มีการรัน Training ซ้ำ, ไม่มีการสร้าง `v9` หรือ Phase ใหม่, ไม่มีการลบ/เขียนทับ Checkpoint, ไม่มีการแก้ไข Web App/API/Database, และไม่มีการ Commit/Push

---

## 1. สรุปสถานะการปิดการทดลอง (PASS / BLOCKED / NOT RUN)

| รายการตรวจสอบ | สถานะ | หลักฐาน / ข้อเท็จจริงในพื้นที่ทำงาน (Workspace) |
|---|---|---|
| **Trainer v8 (`tools/train_nagi_500_v8.py`)** | **PASS** | มีไฟล์อยู่จริง (`393` บรรทัด, `14,215` bytes) ผ่าน `ast.parse` (`AST_OK`) |
| **Evaluator v8 (`tools/eval_nagi_500_v8.py`)** | **PASS** | มีไฟล์อยู่จริง (`652` บรรทัด, `27,226` bytes) ผ่าน `ast.parse` (`AST_OK`) |
| **Baseline Isolation (`v7`)** | **PASS** | `tools/train_nagi_500_v7.py` (`8,503` bytes) และ `tools/eval_nagi_500_v5.py` (`9,390` bytes) ไม่ถูกแก้ไข |
| **Web / API / DB / Phase Isolation** | **PASS** | ไม่มีการแก้ไขส่วนอื่นและไม่เปิด `v9` หรือ Phase ใหม่ |
| **Trained Checkpoint (`checkpoints/nagi_500_v8/*.pt`)** | **BLOCKED** | ไม่พบโฟลเดอร์ `checkpoints/` ในพื้นที่ทำงาน AI Studio นี้ |
| **Evaluation Reports (`report.json`, `report.md`)** | **BLOCKED** | ไม่พบโฟลเดอร์ `eval/` (ทั้งของ `v7` และ `v8`) ในพื้นที่ทำงาน AI Studio นี้ |
| **Dataset Split (`data/nagi_500_v3/*.jsonl`)** | **BLOCKED** | ไม่พบโฟลเดอร์ `data/` ในพื้นที่ทำงาน AI Studio นี้ |
| **PyTorch Runtime Execution** | **BLOCKED** | คอนเทนเนอร์นี้ไม่มีไลบรารี `torch` (`ModuleNotFoundError: No module named 'torch'`) |
| **Training & Evaluation Execution** | **NOT RUN** | ไม่ได้รันคำสั่งฝึกหรือประเมินผลตามข้อจำกัดห้ามรันซ้ำ |
| **Git Commit / Push** | **NOT RUN** | ไม่ได้ Commit หรือ Push และพื้นที่ทำงานนี้ไม่มี `.git` |

---

## 2. หลักฐานที่ตรวจสอบได้จริงในพื้นที่ทำงาน (Code & SHA-256)

### 2.1 SHA-256 ของไฟล์โค้ดสำคัญ
ตรวจสอบด้วยคำสั่ง `sha256sum` บนไฟล์จริงในพื้นที่ทำงาน:

| ไฟล์ | ขนาด (bytes) | SHA-256 | สถานะ |
|---|---:|---|---|
| `tools/train_nagi_500_v7.py` | `8,503` | `fa70ecb1354088eaf5d5438788019fb5dd127f6224d9084d70edd93c9ef52ed6` | Baseline (ห้ามแก้) |
| `tools/eval_nagi_500_v5.py` | `9,390` | `7990eb6c2098a24de537f9702085215b971045860811f1aceb8812490c76ea2a` | Baseline Eval เดิม (ไม่แก้) |
| `tools/train_nagi_500_v8.py` | `14,215` | `6f242f66c990b5112b2ba69839fa05c43f70e1ba112eb884e1df3e6792133bd4` | v8 Trainer (`AST_OK`) |
| `tools/eval_nagi_500_v8.py` | `27,226` | `47c271981598363ab0f5e1ba745dd07a65f83ae4ccd9efa662c83f02511dff1f` | v8 Evaluator (`AST_OK`) |

### 2.2 สถาปัตยกรรมและพารามิเตอร์ควบคุมที่กำหนดในโค้ด `v8`
- **Architecture (`arch="seq2seq_attn_pointer"`):**
  - `Encoder`: `Embedding(V, 128, padding_idx=0)` + Bidirectional `GRU(128, 128)` → `encoder_outputs [B, S, 256]`, `hidden [B, 128]`
  - `Attention`: Bahdanau additive attention (`Linear(384, 128) → tanh → Linear(128, 1)`) พร้อม `src_mask = (src != 0)` กัน `<pad>`
  - `PointerDecoder`: `GRU(256 + 128, 128)` → `vocab_dist = softmax(fc_out(...))`, Gate `p_gen = sigmoid(...)`, `copy_dist = scatter_add(1, src, attn_dist)` → `final_dist = p_gen * vocab_dist + (1 - p_gen) * copy_dist`
  - Unseen-Entity Copy ใน `eval_nagi_500_v8.py`: สร้าง `local_stoi`, `local_itos`, และ `ext_dist` ต่อตัวอย่างขณะ Free-generation (รองรับทั้งรูปแบบ `E00–E99` และ `*_e000`)
- **Configuration ใน `tools/train_nagi_500_v8.py` ฉบับล่าสุดในพื้นที่ทำงาน:**
  - `--data`: `data/nagi_500_v3` (`train.jsonl`, `val.jsonl`, `test.jsonl`)
  - `--out`: `checkpoints/nagi_500_v8`
  - `--seed`: `42`
  - `--steps`: `500`, `--batch_size` / `--batch`: `4`, `--seq`: `256`, `--lr`: `0.001`, `--eval_every`: `50`
  - `Optimizer`: `torch.optim.Adam(lr=0.001, weight_decay=0.01)`
  - `Early Stop`: `no_improve >= 2 and args.steps >= 500` และกู้คืน `best_val_state`
  - **หมายเหตุเรื่อง Batch Order / Hyperparameter ระหว่าง Revision:**
    - โค้ด `tools/train_nagi_500_v8.py` ฉบับแรกๆ (ก่อนปรับให้ตรง `v7`) เคยใช้ `random.sample(..., batch_size=16)` และ `AdamW(lr=2e-3)` ซึ่งต่างจาก `v7` ที่ใช้การจัด Batch แบบวนเรียงลำดับ `((step - 1) * batch + i) % len(train)` (`batch=4`, `Adam(lr=0.001)`)
    - ฉบับปัจจุบันในพื้นที่ทำงาน (`SHA-256: 6f242f6...`) ปรับให้ใช้การจัด Batch แบบวนเรียงลำดับ `batch=4` และ `Adam(lr=0.001)` เหมือน `v7` แล้ว ดังนั้นหาก Checkpoint ที่ฝึกจริงใน Codespaces ถูกฝึกจาก Revision ก่อนหน้า จะมี Batch Order, Batch Size และ Optimizer ต่างจาก `v7` ต้องตรวจสอบค่าใน `metrics.json` / `report.json` ของเครื่องที่รันจริงควบคู่กัน

---

## 3. ผลการทดลองเปรียบเทียบ `v7` vs `v8` (Empirical Results)

> **ข้อจำกัดตามกฎห้ามสร้างตัวเลขที่ไม่มีอยู่จริง:** ในพื้นที่ทำงาน AI Studio นี้ **ไม่มี** ไฟล์ `checkpoints/nagi_500_v8/*.pt`, `eval/nagi_500_v7_500/report.json`, `eval/nagi_500_v8/report.json`, `eval/nagi_500_v8/report.md`, หรือ `data/nagi_500_v3/*.jsonl` อยู่จริง จึง **ไม่สามารถตรวจยืนยันหรือคัดลอกตัวเลขผลลัพธ์จริง** ในพื้นที่ทำงานนี้ได้

| เมตริกเปรียบเทียบ (`v7` vs `v8`) | สถานะใน Workspace | ค่าที่ยืนยันได้ใน Workspace |
|---|---|---|
| Validation / Test Exact Match (`v7` vs `v8`) | **BLOCKED** | ไม่มี `report.json` ของ `v7` และ `v8` ใน Workspace |
| First-token Accuracy | **BLOCKED** | ไม่มี `report.json` ใน Workspace |
| EOS Hit และ EOS Position / Premature EOS | **BLOCKED** | ไม่มี `report.json` ใน Workspace |
| Repetition Rate | **BLOCKED** | ไม่มี `report.json` ใน Workspace |
| Entity Copy Accuracy & Unseen Entity Copy | **BLOCKED** | ไม่มี `report.json` ใน Workspace |
| ผลแยกราย Capability (Teacher-forced vs Free-gen) | **BLOCKED** | ไม่มี `report.json` ใน Workspace |
| Parameter Count (`v7` vs `v8`) | **BLOCKED** | คำนวณจริงไม่ได้เพราะไม่มี `vocab` จาก `data/nagi_500_v3/train.jsonl` และไม่มี `torch` |
| Training Time & Peak Memory (`elapsed_sec`, `max_rss_kb`) | **BLOCKED** | ไม่มี `metrics.json` / Checkpoint ใน Workspace |

---

## 4. บันทึกข้อจำกัดที่ยังไม่ผ่าน (ตามรายการที่เจ้าของโครงการระบุให้บันทึก)

รายการข้อจำกัดเชิงพฤติกรรมและโครงสร้างที่ต้องบันทึกไว้เพื่อการปิดการทดลอง (สถานะการตรวจยืนยันหลักฐานตัวเลขใน Workspace นี้คือ **BLOCKED** เนื่องจากไฟล์รายงานจริงอยู่ในสภาพแวดล้อม Codespaces ไม่ได้อยู่ใน Snapshot ของ AI Studio):

1. **Adaptive Learning ยังมีตัวอย่างล้มเหลว** — ต้องตรวจดูรายละเอียดใน `val_errors["adaptive_learning"]` / `test_errors["adaptive_learning"]` ของ `report.json` จริง (สถานะใน Workspace: `BLOCKED` ไม่มี `report.json`)
2. **Unseen Entity Copy เป็น `N/A`** — จากโค้ด `eval_nagi_500_v8.py` ค่านี้จะคำนวณเป็น `None` (`N/A` ใน `report.md`) เมื่อ `unseen_entity_count == 0` หรือตรวจหา Entity ไม่พบใน Split นั้น (หรือใน Revision ก่อนปรับ `is_entity_token` ที่รองรับเฉพาะ `E\d+` ยังไม่รองรับ `*_e\d+` จาก `gen_ngi_500.py`) (สถานะการตรวจผลจริงใน Workspace: `BLOCKED`)
3. **`mean_p_gen` ต่ำในหลายตัวอย่าง** — ต้องตรวจสอบค่า `mean_p_gen` ต่อ Capability และใน error cases เพื่อพิสูจน์ว่าโมเดลเลือก Copy กับ Generate เหมาะสมหรือไม่ (สถานะใน Workspace: `BLOCKED`)
4. **Parameter Count เพิ่มขึ้น (`273,955` → `523,708` ตามที่เจ้าของโครงการบันทึกไว้)** — การเพิ่ม Bidirectional Encoder + Bahdanau Attention + Pointer-Copy Gate ทำให้จำนวนพารามิเตอร์เกือบ 2 เท่าเมื่อเทียบกับ `TinyNGI` ที่ `hid_dim=128` (ตัวเลข `273,955` และ `523,708` มาจากการบันทึกของเจ้าของโครงการ ยังไม่ได้ตรวจซ้ำจาก Checkpoint จริงใน Workspace นี้)
5. **ยังแยกผลของ Attention กับ Pointer-Copy ไม่ได้** — `v8` เพิ่มทั้ง Attention และ Pointer-Copy พร้อมกันในการทดลองเดียว โดยยังไม่มีการทดลอง Ablation ตัวกลาง (`Seq2Seq + Attention` แบบไม่มี Pointer-Copy) จึงยังสรุปไม่ได้ว่าสัดส่วนผลที่เปลี่ยนมาจาก Attention หรือ Pointer-Copy (ยืนยันเชิงโครงสร้าง: **PASS**; ยืนยันเชิงตัวเลข: **BLOCKED**)
6. **ข้อสำคัญเชิงเป้าหมาย:** การเพิ่ม Attention และ Pointer-Copy เป็นเพียงการทดลองด้านสถาปัตยกรรม ไม่ใช่หลักฐานว่า ZYRQUEN มีความสามารถ NGI แล้ว

---

## 5. ความสามารถในการทำซ้ำ (Reproducibility Checklist)

### 5.1 คำสั่งอ้างอิงตามโค้ด `tools/train_nagi_500_v8.py` และ `tools/eval_nagi_500_v8.py` (ยังไม่ได้รันใน AI Studio)
> หมายเหตุ: คำสั่งด้านล่างเป็นคำสั่งตาม CLI Interface ของไฟล์ใน Workspace (`--data`, `--out`, `--ckpt`) สำหรับตรวจสอบ/ทำซ้ำในสภาพแวดล้อมที่มี Dataset และ PyTorch โดย **ยังไม่ได้รันจริงใน Workspace นี้ (`NOT RUN`)**

```bash
# Training (ตัวอย่างตาม default args ของ train_nagi_500_v8.py)
python3 tools/train_nagi_500_v8.py \
  --data data/nagi_500_v3 \
  --out checkpoints/nagi_500_v8 \
  --steps 500 \
  --batch_size 4 \
  --seq 256 \
  --lr 0.001 \
  --eval_every 50 \
  --seed 42

# Evaluation (ต้องระบุ --ckpt, --data, --out)
python3 tools/eval_nagi_500_v8.py \
  --ckpt checkpoints/nagi_500_v8/step_500.pt \
  --data data/nagi_500_v3 \
  --out eval/nagi_500_v8 \
  --v7_report eval/nagi_500_v7_500/report.json
```

### 5.2 สิ่งที่ต้องรวบรวมเพิ่มเติมใน Codespaces เพื่อปิด Audit 100%
- SHA-256 ของ `data/nagi_500_v3/train.jsonl`, `val.jsonl`, `test.jsonl`
- SHA-256 ของ Checkpoint ที่ใช้ประเมินจริงใน `checkpoints/nagi_500_v8/`
- ไฟล์ `eval/nagi_500_v8/report.json`, `eval/nagi_500_v8/report.md`, และ `eval/nagi_500_v7_500/report.json` จากเครื่องที่ใช้ฝึกจริง
- คำสั่งจริง (Command history) ที่ใช้รันใน Codespaces เพื่อยืนยันว่าใช้ Revision ใดของ `train_nagi_500_v8.py` และ `eval_nagi_500_v8.py`

---

## 6. รายชื่อไฟล์ที่สร้างขึ้นในขั้นตอนปิดการทดลองนี้

- `docs/V8_EXPERIMENT_CLOSURE_REPORT.md` (สร้างใหม่ในพื้นที่ทำงานเท่านั้น; ไม่มีการแก้ `v7`, `v8`, Web App, API, Database และไม่มีการ Commit/Push)

**สถานะ:** หยุดรอการตรวจสอบและอนุมัติจากเจ้าของโครงการครับ
