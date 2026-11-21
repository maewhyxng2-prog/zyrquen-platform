# Phase 17 — Memory & Knowledge Integration — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 16:** `CODE DONE`
- **Phase 18:** `PROPOSED — รอคิวหลัง 17`
- **Phase 19-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
สร้างระบบ Memory และ Knowledge Integration ที่รองรับการจัดเก็บบริบท การค้นคืนความรู้แบบมีหลักฐาน และการแยกข้อมูลอย่างปลอดภัย เพื่อรองรับ Native Intelligence ของ ZYRQUEN

## 1. Tiered Memory
- **User Story:** Memory แบ่งระดับชัดเจน — ระยะสั้น / ระยะยาว / บริบทของงาน
- **Design:** `MemoryStore {short: [], long: [], task: {}}` + `store(tier, key, value)` / `recall(tier, key)` — tier ต้องเป็น `short|long|task` เท่านั้น นอกนั้น BLOCK
- **ห้าม:** ห้ามเก็บข้าม tier โดยไม่ระบุ, ห้ามเก็บ PII

## 2. Grounded Retrieval
- **User Story:** ค้นคืนความรู้โดยอ้างอิงแหล่งที่มา แยกข้อมูลที่ตรวจสอบแล้วออกจากที่ยังไม่ยืนยัน
- **Design:** `retrieve(query)` คืน `[{text, source, verified: true/false}]` — ทุกผลลัพธ์ต้องมี `source` ถ้าไม่มี source = ไม่คืนผลลัพธ์นั้น
- **ห้าม:** ห้ามคืนความรู้ที่ไม่มี source, ห้ามอ้าง unverified ว่าเป็น verified

## 3. Multi-tenant Integrity
- **User Story:** ข้อมูลแยกตามผู้ใช้และ Workspace เรียกคืนข้ามผู้ใช้ไม่ได้
- **Design:** ทุก Memory มี `owner_id + workspace_id` — `recall()` ต้องเช็ค `owner_id + workspace_id` ตรงกันเท่านั้น ไม่ตรง = คืน `[]` + `blocked`
- **ห้าม:** ห้าม recall ข้าม owner/workspace, ห้าม bypass การเช็คสิทธิ์

## ข้อห้าม Phase 17 ทั้งหมด
- ไม่ Training, ไม่แก้ Model Weights, ไม่ Download Dataset
- ไม่ใช้ External AI APIs, ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่ Deploy, ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_17_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Tiered Memory / Grounded Retrieval / Multi-tenant อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] ไม่มี Memory ที่ไม่มี owner/workspace
- [ ] Retrieval ข้ามผู้ใช้ถูก BLOCK
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
