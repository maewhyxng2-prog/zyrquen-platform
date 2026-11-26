# ZYRQUEN — HONOR X6b Mobile Development Plan

- **Device:** HONOR X6b — RAM 6GB — Mali-G52 (ไม่ใช่ CUDA GPU)
- **Dev Environment:** โทรศัพท์ + 【entity-GitHub¦canonical_name=GitHub】 Codespaces
- **Status:** แผนพัฒนาต่อด้วยฮาร์ดแวร์จริง — ไม่ใช่เหตุผลให้หยุดโครงการ
- **Production:** ยังไม่อนุมัติ
- **Trained Weights:** ยังไม่มี Model Weights ที่ผ่านการฝึกของ ZYRQUEN เอง

## หลักการ

HONOR X6b RAM 6GB ไม่ใช่เหตุผลให้หยุด ZYRQUEN แต่ต้องแยกงานให้เหมาะกับฮาร์ดแวร์จริง
และ **ไม่เปลี่ยน ZYRQUEN ไปเป็น Chatbot สำเร็จรูป** เพียงเพราะข้อจำกัดฮาร์ดแวร์

## สิ่งที่ทำได้บนโทรศัพท์เครื่องนี้ + Codespaces

- พัฒนา Source Code ผ่าน 【entity-GitHub¦canonical_name=GitHub】 Codespaces
- พัฒนา Native Model Architecture และ Tokenizer
- เตรียม Dataset และระบบตรวจสอบข้อมูล (provenance + SHA-256 + manifest)
- ทดสอบโมเดลขนาดเล็กด้วย CPU หาก Runtime รองรับ
- ทดสอบ API, Web Client และระบบ Intelligence (Phase 11–20)
- สร้างและตรวจสอบ Training Pipeline

## สิ่งที่ยังเป็นข้อจำกัด

- ฝึกโมเดลขนาดใหญ่บน RAM 6GB ไม่เหมาะสม — เสี่ยง OOM / เครื่องค้างก่อนจบ
- Mali-G52 ไม่ใช่ CUDA GPU — ใช้ `torch` CUDA ไม่ได้
- การฝึกจริงอาจต้องใช้ Compute ภายนอกในอนาคต — แต่ไม่จำเป็นต้องตัดสินใจตอนนี้

## ระยะที่ 1 — Mobile-first Development

พัฒนาและตรวจสอบระบบทั้งหมดที่ไม่ต้องใช้ GPU ขนาดใหญ่

- Code, Architecture, Tokenizer, Dataset Validation, API, Web, Intelligence Contracts
- สถานะตอนนี้: Phase 11–20 `CODE DONE` — Local Final Gate `60 passed / 0 failed`
- 【entity-GitHub¦canonical_name=GitHub】 CI Phase 11–20: `NOT VERIFIED` — รอผล Workflow 4 Jobs บน SHA เดียวกัน

## ระยะที่ 2 — Small Native Model Experiment

ทดลองโมเดลขนาดเล็กบน CPU โดยจำกัด RAM และตรวจสอบความเสถียร

- เพดาน CPU ที่มีอยู่แล้ว: `MAX_CPU_MODEL_PARAMETERS = 5_000_000`, `MAX_CPU_SEQUENCE_LENGTH = 256`, `MAX_CPU_BATCH_SIZE = 4`, `MAX_CPU_TRAINING_STEPS = 1_000`
- ต้องมี Dataset ที่ผ่านการตรวจสอบ + Evaluation Gate ผ่านก่อนเริ่ม
- ไม่เร่งให้ใหญ่ ไม่ข้าม Gate

## ระยะที่ 3 — Scalable Native Training

เมื่อพร้อม ค่อยพิจารณา Compute สำหรับการฝึกที่ใหญ่ขึ้น โดยอนุมัติงบประมาณแยกต่างหาก

- ยังไม่ตัดสินใจตอนนี้
- ต้องอนุมัติ Dataset / Evaluation / งบประมาณ แยกต่างหากก่อนฝึกจริง

## ทำไมถึงยังไม่มี Trained Weights?

ไม่ใช่เพราะไม่มีคอมอย่างเดียว แต่เพราะ 3 อย่างนี้ยังไม่ครบพร้อมกัน:

1. Dataset ที่ผ่านการตรวจสอบ (manifest + provenance + SHA-256 ที่ผ่านการอนุมัติ)
2. Evaluation ที่ผ่าน Gate แบบมีหลักฐาน (Phase 14 / Phase 10.9.9)
3. Compute + Approval ที่แยกต่างหาก (การฝึกจริงต้องอนุมัติงบ / ทรัพยากรแยก)

## ข้อห้าม

- ไม่ Training จริงโดยไม่มี Dataset + Evaluation + Approval
- ไม่แก้ Model Weights โดยไม่มี Approval
- ไม่ Auto-promote
- ไม่สร้าง Cloud / GPU ที่มีค่าใช้จ่ายโดยไม่ได้รับอนุมัติ
- ไม่ Deploy Production โดยอัตโนมัติ
- ไม่ใช้ External AI APIs เป็นสมองของ ZYRQUEN
- ไม่เปลี่ยน Auth / Quota / Database Schema / Migration โดยไม่มีอนุมัติ
