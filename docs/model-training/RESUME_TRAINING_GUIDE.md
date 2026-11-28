# ZYRQUEN Native V2 — Resume Training & Verification Guide

คู่มือนี้กำหนดขั้นตอนมาตรฐานของ ZYRQUEN สำหรับการตั้งค่าสภาพแวดล้อม ตรวจสอบความถูกต้องของ Checkpoint ตาม manifest ใน **PR #56** และฝึกต่อจากจุดที่ค้างอยู่ (`v2_continued_step4025.json.gz`, `v2_teacher_transfer_step5000.json.gz`, หรือ `v2_teacher_transfer_run5000_step6000.json.gz`) โดยไม่ละเมิดนโยบาย Native-Only

---

## 1. ขอบเขตและหลักเกณฑ์การทดลอง (ZYRQUEN Standard Policy)

- **Native Core Only:** ใช้ `PureNativeTransformerLMV2` และ `PureContinualTrainerV2` เท่านั้น ห้ามใช้ pretrained weights จากภายนอก และห้ามเรียก external inference API
- **Storage Boundary:** ไฟล์ checkpoint (`.json.gz`) ถูกเก็บใน Colab / Cloud Storage (`/content/zyrquen-resume/checkpoints/`) ส่วน GitHub เก็บเฉพาะรายงานการทดลองและ SHA-256 manifest
- **Non-Overwrite:** ห้ามเขียนทับไฟล์ checkpoint เดิม ให้บันทึกชื่อไฟล์ run ใหม่เสมอ (เช่น `v2_teacher_transfer_run4025_step...` หรือ `v2_teacher_transfer_run6000_step...`)
- **Candidate Hold:** Checkpoint ใหม่ทุกตัวมีสถานะ `CANDIDATE — NOT PROMOTED` จนกว่าจะผ่านการโหลดซ้ำใน runtime ใหม่และเทียบผลบนชุด held-out ที่แยกขาดจากข้อมูลฝึก

---

## 2. รายการตรวจสอบ Checkpoint ก่อนเริ่มฝึกใหม่ (Pre-Training Verification Checklist)

ก่อนรัน `train_steps()` ให้ตรวจสอบตามลำดับทั้ง 6 ข้อต่อไปนี้:

1. **ตรวจพื้นที่เก็บไฟล์ (`OUT_DIR`)**
   - ยืนยันว่าโฟลเดอร์ `/content/zyrquen-resume/checkpoints` มีไฟล์ `.json.gz` อยู่จริง
   - หมายเหตุใน Colab: คำสั่ง shell ต้องนำหน้าด้วย `!` เสมอ (เช่น `!python3 tools/resume_v2_lab.py ...`)
2. **ตรวจ SHA-256 เทียบ PR #56 Manifest**
   - ตรวจ `v2_continued_step4025.json.gz` (`f4b33c82a27a0a3f05b468d2ff1cf297746f7a3aa85ecbc03ff0093f34c75314`)
   - ตรวจ `v2_teacher_transfer_step5000.json.gz` (`76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed`)
   - ตรวจ `v2_teacher_transfer_run5000_step6000.json.gz` (`3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7`) และชุด 5025–5975 ทั้งหมด
   - หากมีไฟล์ใด `MISMATCH` ให้หยุดทันทีและห้ามโหลดเข้าฝึกต่อ
3. **ตรวจ Fresh-Runtime Reload**
   - โหลดด้วย `PureContinualTrainerV2.load_checkpoint(..., expected_sha256=..., resume_optimizer=True, restore_continual_state=True)`
   - ยืนยันว่า `trainer.global_step` ตรงกับเลข step ในชื่อไฟล์ (เช่น `4025` หรือ `6000`)
4. **ตรวจ Optimizer และ Continual-Learning State**
   - ยืนยันว่า `trainer.m_state` และ `trainer.v_state` ไม่ว่างเปล่า
   - ตรวจจำนวน `trainer.replay_buffer`, `trainer.anchor_params` และ `trainer.importance_diag`
5. **แยก Held-Out Validation Split ให้ชัดเจน**
   - ตรวจสอบว่าชุด `transfer_val` (4 ตัวอย่าง) และชุดทดสอบอิสระไม่ซ้ำซ้อนกับ `train_texts`
6. **บันทึกผล Baseline เทียบก่อนฝึก (Pre-Resume Benchmark)**
   - รัน `evaluate_texts()` บนชุด `transfer_val` เทียบ Step 5000 baseline ก่อนเริ่มอัปเดตน้ำหนักรอบใหม่

---

## 3. วิธีใช้งานใน Jupyter Notebook (`experiments_native_training_lab.ipynb`)

1. เปิด `experiments_native_training_lab.ipynb` บน Google Colab
2. รัน **Cell 1** เพื่อตั้งค่า `REPO_DIR`, `OUT_DIR` และนำเข้าฟังก์ชันจาก `python_core` และ `tools`
3. รัน **Cell 2** (`verify_all_pr56_checkpoints` + `verify_checkpoint_against_pr56_manifest`) เพื่อตรวจความถูกต้องของ SHA-256 ก่อนโหลด
4. ใน **Cell 3** เลือก `TARGET_CHECKPOINT`:
   - เลือก `"v2_continued_step4025.json.gz"` เพื่อฝึกต่อจากจุด Step 4025
   - หรือเลือก `"latest_auto"` / `"v2_teacher_transfer_run5000_step6000.json.gz"` เพื่อฝึกต่อจาก Step 6000
5. รัน **Cell 4** เพื่อทดสอบ Step 6000 เทียบ Step 5000 บนชุด `transfer_val` (กำหนด `VAL_FILE`)
6. รัน **Cell 5** เพื่อฝึกต่อทีละ 25 steps พร้อมสร้าง `.sha256` sidecar อัตโนมัติ และรัน **Cell 6** เพื่อตรวจความสมบูรณ์หลังฝึกจบ

---

## 4. คำสั่ง CLI สำหรับ Terminal หรือ Colab Shell (`!` นำหน้าเมื่ออยู่ใน Colab)

- ตรวจ SHA-256 และ fresh-runtime reload จาก `v2_continued_step4025.json.gz`:
  ```bash
  !python3 tools/resume_v2_lab.py \
    --out-dir /content/zyrquen-resume/checkpoints \
    --checkpoint /content/zyrquen-resume/checkpoints/v2_continued_step4025.json.gz \
    --verify-only
  ```
- ฝึกต่อจาก `v2_continued_step4025.json.gz` ไปยัง Step 5000:
  ```bash
  !python3 tools/resume_v2_lab.py \
    --out-dir /content/zyrquen-resume/checkpoints \
    --checkpoint /content/zyrquen-resume/checkpoints/v2_continued_step4025.json.gz \
    --train-file /path/to/train.jsonl \
    --target-step 5000 \
    --chunk-steps 25
  ```
- โหลด Step 6000 และวัดผลเทียบ Step 5000 บนชุด held-out transfer-validation:
  ```bash
  !python3 tools/eval_step6000_vs_step5000.py \
    --out-dir /content/zyrquen-resume/checkpoints \
    --val-file /path/to/transfer_val.jsonl
  ```
