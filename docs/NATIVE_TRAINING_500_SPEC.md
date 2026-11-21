# ZYRQUEN — Native Training 500 SPEC

- **Status:** SPEC ONLY — NOT APPROVED FOR TRAINING
- **Goal:** Native General Intelligence (NGI) — Native Model ของ ZYRQUEN เรียนรู้จาก Weights ของตัวเอง
- **Not a Chatbot:** ไม่สร้างบทสนทนา ไม่สร้าง Chatbot สำเร็จรูป
- **Scope:** SPEC + Generator เท่านั้น — ยังไม่ Training / ไม่เปลี่ยน Weights / ไม่ติดตั้ง Dependencies / ไม่ Commit / ไม่ Push / ไม่ Deploy
- **Roadmap:** ไม่เปิด Phase 21 — ไม่รื้อ Phase 11–20

## Dataset — 500 Examples

- Format: JSONL, 1 บรรทัด = 1 Example
- Fields: `id`, `capability`, `split`, `template_id`, `structural_signature`, `input`, `target`, `provenance`
- Provenance: `synthetic_rule_based_v1` — สร้างจากกฎ + Template แบบ Deterministic เท่านั้น
- ไม่ดาวน์โหลด Dataset ภายนอก ไม่ใช้ External AI APIs
- ไม่ใช่บทสนทนา 500 บรรทัด — เป็นตัวอย่างมีโครงสร้าง

### สัดส่วน 6 Capabilities

| Capability | Train | Val | Test | รวม |
|---|---|---|---|---|
| native_representation | 80 | 10 | 10 | 100 |
| knowledge_acquisition | 64 | 8 | 8 | 80 |
| relational_reasoning | 80 | 10 | 10 | 100 |
| planning_decomposition | 64 | 8 | 8 | 80 |
| verification | 64 | 8 | 8 | 80 |
| adaptive_learning | 48 | 6 | 6 | 60 |
| **รวม** | **400** | **50** | **50** | **500** |

### Split

- Train `400` / Validation `50` / Test `50`
- Test ต้องไม่ถูกเห็นตอน Training — ใช้ประเมินอย่างเดียว

## ป้องกัน Leakage — 3 ชั้น

ต้องตรวจทั้ง 3 ชั้น ไม่ใช่แค่ตรวจข้อความซ้ำ:

1. **Entity Leakage:** Entity Pool ของ Train / Val / Test ต้องไม่ทับกันเลย
   - Train ใช้ `*_train_e***` / Val ใช้ `*_val_e***` / Test ใช้ `*_test_e***`
   - ตรวจ Entity ที่ปรากฏใน `input` ข้าม Split ต้อง Intersection = 0

2. **Template Leakage:** `template_id` ของ Train / Val / Test ต้องไม่ทับกันเลย
   - เช่น `RR_TRAIN_01` ห้ามปรากฏใน Val / Test

3. **Structural Leakage (ซ่อนอยู่):** โครงสร้าง / กฎ ต้องไม่ซ้ำข้าม Split แม้เปลี่ยน Entity
   - ตรวจ `structural_signature` = capability + template_id + abstract pattern (Entity แทนด้วย `<E0>`, `<E1>`, `<E2>`)
   - ตรวจ `abstract pattern` อย่างเดียว (ไม่รวม template_id) ข้าม Split ต้องไม่ทับกัน
   - ถ้า Pattern เดียวกันแต่เปลี่ยนแค่ชื่อ Entity = ถือว่า Leakage

## Integrity Checks

Generator ต้องตรวจและ Fail ถ้าไม่ผ่าน:

- Count: Train 400 / Val 50 / Test 50 / Total 500 / ต่อ Capability ตรงตาราง
- Exact Duplicate: `input` ซ้ำ = 0
- Normalized Duplicate: `input` lower + ตัด whitespace ซ้ำ = 0
- Template Overlap ข้าม Split = 0
- Entity Overlap ข้าม Split = 0
- Structural Signature Overlap ข้าม Split = 0
- Abstract Pattern Overlap ข้าม Split = 0
- SHA-256: คำนวณทุกไฟล์ `train.jsonl`, `val.jsonl`, `test.jsonl` เก็บใน `manifest.json`

## Training Configuration — เพดานห้ามเกิน

| Parameter | เพดาน |
|---|---|
| Parameters | 5M |
| Sequence Length | 256 |
| Batch Size | 4 |
| Initial Steps | 100 |

- เริ่ม 100 Steps ก่อน — ผ่านเกณฑ์ค่อยไต่ 200 -> 300 -> 400 -> 500
- ไม่ Auto-promote — Weights จากการทดลองยังไม่เอาไปใช้จริงจนกว่าจะอนุมัติแยก

## เกณฑ์อนุมัติก่อน Training 100 Steps

ต้องครบทุกข้อจึงพิจารณาอนุมัติ Training:

1. Generator รันผ่าน ไม่มี Leakage / Duplicate
2. Dataset 500 ตัวอย่างจริง ถูกตรวจด้วยตาแล้วว่าตรง Capability
3. Manifest มี SHA-256 ครบ 3 ไฟล์
4. Split ถูกต้อง Train 400 / Val 50 / Test 50
5. Training Pipeline + Checkpoint ถูกตรวจแล้ว
6. เพดาน 5M / 256 / 4 / 100 ถูกล็อกไว้
7. มีเกณฑ์ประเมินหลัง 100 Steps: Loss, RAM, ความสามารถที่เรียนรู้ได้

## ข้อห้าม

- ไม่อ้างว่า 500 Steps = AGI / NGI สำเร็จ — ใช้เป็นหลักฐานแรกว่า Native Model เริ่มเรียนรู้จาก Weights ตัวเองได้
- ไม่ใช้ Dataset ที่ไม่มี Provenance / ลิขสิทธิ์ไม่ชัด
- ไม่ใช้ Test Set ในการ Training

## ขั้นต่อไป

1. สร้าง 2 ไฟล์นี้ + ตรวจ
2. รัน Generator -> ตรวจ Dataset 500 ตัวอย่างจริง
3. แยกอนุมัติ Training 100 Steps ต่างหาก
