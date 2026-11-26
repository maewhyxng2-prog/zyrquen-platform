# Phase 11 — Workspace Intelligence — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 10.9.9:** `PASSED / CLOSED`
- **Phase 12-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
เพิ่มความฉลาดให้ Workspace โดยใช้บริบทงานเดิมที่มีอยู่แล้ว ไม่ใช้ AI ภายนอก ไม่เทรนโมเดลใหม่

## 1. Follow-up Suggestions
- **User Story:** เมื่อผู้ใช้จบงานชิ้นหนึ่ง ระบบเสนอขั้นตอนต่อไปที่สมเหตุสมผลจากบริบทนั้น
- **UX:** แสดงเป็นรายการแนะนำ 3-5 ข้อใต้ข้อความงาน ไม่ auto-run
- **API/UX ที่จะเปลี่ยน:** เพิ่ม endpoint อ่านคำแนะนำเท่านั้น ไม่แก้ endpoint งานเดิม
- **ห้าม:** ห้าม auto-execute, ห้ามเดาจากข้อมูลนอก Workspace

## 2. Conversation Context Awareness
- **User Story:** ระบบจำบริบทการสนทนาปัจจุบัน เช่น งานที่กำลังคุยอยู่ ไฟล์ที่เปิดอยู่
- **UX:** แสดงบริบทปัจจุบันแบบย่อด้านบน Workspace
- **API/UX ที่จะเปลี่ยน:** เพิ่มการเก็บ context ใน session เท่านั้น ไม่เก็บข้ามผู้ใช้
- **ห้าม:** ห้ามส่งบริบทออกนอกระบบ, ห้ามใช้ AI ภายนอก

## 3. Workspace Interaction Improvements
- **User Story:** การโต้ตอบใน Workspace เร็วขึ้น ชัดขึ้น เช่น ปุ่มลัด, การจัดกลุ่มงาน, การค้นหาใน Workspace
- **UX:** ปรับปุ่ม/การจัดวางที่มีอยู่ ไม่เปลี่ยนโครงหลัก
- **API/UX ที่จะเปลี่ยน:** ปรับ UI เท่านั้น ไม่เปลี่ยน schema หลัก
- **ห้าม:** ห้ามเปลี่ยน auth, ห้ามเปลี่ยน quota, ห้ามเปลี่ยน migration

## ข้อห้าม Phase 11 ทั้งหมด
- ไม่เทรน, ไม่โหลด Dataset, ไม่เช่า GPU, ไม่ Provision Cloud
- ไม่ Deploy, ไม่แก้ Phase อื่น, ไม่ใช้ AI ภายนอก
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_11_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Follow-up Suggestions อย่างน้อย 1 ชุด
- [ ] มีเทสสำหรับ Context Awareness อย่างน้อย 1 ชุด
- [ ] ไม่มีการเปลี่ยน auth/quota/migration
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
