# Phase 12 — Native Intelligence Foundation — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 11:** `CODE DONE`
- **Phase 13-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
เตรียม Foundation สำหรับ Native Intelligence ของ ZYRQUEN และรองรับเส้นทางการพัฒนา Native Model ใน Phase ถัดไป โดยยังไม่เทรน ไม่โหลดโมเดล ไม่ใช้ AI ภายนอก

## 1. Native Intelligence Architecture
- **User Story:** มีโครงสร้างพื้นฐานที่แยกชั้น Intelligence ออกจาก API / Auth / Quota / DB ชัดเจน
- **Design:** โฟลเดอร์/โมดูล `intelligence/` มีแค่ pure logic + interface ไม่ผูกกับ DB หรือ API ตรงๆ
- **ห้าม:** ห้ามแก้ Auth / Quota / Database Schema / Migration

## 2. Core Intelligence Interfaces
- **User Story:** ทุกความสามารถของ Intelligence เรียกผ่าน interface เดียวกัน เปลี่ยน implementation ทีหลังได้โดยไม่แก้ caller
- **Design:** กำหนด `IntelligenceProvider` interface: `capabilities()`, `can_handle(task)`, `run(task, context)` — ยังไม่ต้องมีโมเดลจริง
- **ห้าม:** ห้ามเรียก External AI APIs, ห้ามโหลด Model Weights

## 3. Capability Management
- **User Story:** ระบบรู้ว่าตัวเองทำอะไรได้ / ทำอะไรไม่ได้ และบอกผู้ใช้ตรงๆ ไม่แอบอ้าง
- **Design:** มี `CapabilityRegistry` เก็บรายการ capability + สถานะ `available / not_available / blocked` พร้อมเหตุผล
- **ห้าม:** ห้ามอ้างว่ามี capability ที่ยังไม่มี, ห้าม fake success

## ข้อห้าม Phase 12 ทั้งหมด
- ไม่ Training, ไม่ Download Dataset หรือ Model Weights
- ไม่ใช้ GPU / Cloud Resources ที่มีค่าใช้จ่าย
- ไม่ Deploy, ไม่ใช้ External AI APIs
- ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_12_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Architecture / Interfaces / Capability อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] ไม่มีการเปลี่ยน auth/quota/migration/schema
- [ ] ไม่มีการเรียก External AI / โหลด Weights
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
