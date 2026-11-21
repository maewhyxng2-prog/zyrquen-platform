# Phase 15 — Native Model Readiness — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 14:** `CODE DONE`
- **Phase 16:** `APPROVED / OPEN — รอคิวหลัง 15`
- **Phase 17-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
เตรียมสถาปัตยกรรม Native Model, Training-to-Inference Contracts, KV-cache และ Model Lifecycle ให้พร้อมสำหรับการพัฒนา Native Model ของ ZYRQUEN ในระยะถัดไป — ยังไม่เทรนจริง ยังไม่โหลด Weights

## 1. Model Architecture Readiness
- **User Story:** มีโครงสร้าง Native Model ที่แยก Model Components ออกจาก API ชัดเจน
- **Design:** กำหนด `ModelConfig` (vocab, hidden, layers, kv_cache_size) + `ModelComponent` interface — ยังไม่มี weights จริง ใช้ config + placeholder state
- **ห้าม:** ห้ามโหลด Weights, ห้ามอ้างว่ามีโมเดลที่เทรนแล้ว

## 2. Training-to-Inference Design
- **User Story:** เส้นทาง Training → Inference มี Contract ชัดเจน ตรวจได้ว่าโมเดลที่ฝึกเข้ากับ Inference ได้ไหม
- **Design:** กำหนด `ModelInput / ModelOutput Contracts` + `check_compatibility(config, checkpoint_meta)` — ถ้า config ไม่ตรง checkpoint = `incompatible` ต้อง BLOCK
- **ห้าม:** ห้าม Training จริง, ห้าม auto-promotion

## 3. Versioning & Lifecycle
- **User Story:** ทุกโมเดลมี Version + Checkpoint Identity ตรวจย้อนหลังได้ และ Rollback ได้
- **Design:** `register_model(version, checkpoint_id, config)` → `validate()` → `promote()` / `rollback()` — ทุกขั้นมีสถานะ `registered / validated / promoted / rolled_back` พร้อมเหตุผล
- **ห้าม:** ห้ามแก้ Atomic Version Reservation ที่มีอยู่โดยไม่ได้รับอนุมัติ, ห้าม promotion แบบไม่มี validation

## ข้อห้าม Phase 15 ทั้งหมด
- ไม่ Training จริง, ไม่ Download Dataset หรือ Model Weights
- ไม่เช่า GPU / Cloud Resources, ไม่ Deploy, ไม่เปิด Auto-promotion
- ไม่แก้ Atomic Version Reservation โดยไม่ได้รับอนุมัติ
- ไม่ใช้ External AI APIs, ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_15_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Architecture / Training-to-Inference / Lifecycle อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] ไม่มี Weights จริง ไม่มีการ Training
- [ ] Incompatible checkpoint ถูก BLOCK ไม่ใช่ PASS
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
