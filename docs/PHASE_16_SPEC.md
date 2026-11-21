# Phase 16 — Native Reasoning & Planning — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 15:** `CODE DONE`
- **Phase 17-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
สร้าง Reasoning และ Planning Foundation ที่รองรับการคิดเป็นขั้นตอน การแบ่งงานด้วย DAG และการตรวจสอบผลลัพธ์ เพื่อพัฒนา ZYRQUEN ไปสู่ Native Intelligence ที่มีความสามารถมากกว่าระบบสนทนาทั่วไป

## 1. Reasoning Architecture
- **User Story:** ระบบคิดเป็นขั้นตอน แยกข้อเท็จจริง / สมมติฐาน / ผลลัพธ์ที่ยังไม่ผ่านการตรวจสอบออกจากกัน
- **Design:** `ReasoningStep {kind: fact|assumption|unverified, text, evidence}` + `ReasoningPipeline` เก็บ steps ตามลำดับ ไม่รวมกันมั่ว
- **ห้าม:** ห้ามอ้างสมมติฐานว่าเป็นข้อเท็จจริง, ห้ามข้าม verification

## 2. Planning & DAG Task Decomposition
- **User Story:** แยกงานใหญ่เป็นงานย่อย มี Dependency ด้วย DAG ตรวจลำดับก่อนทำ
- **Design:** `Plan {tasks: [{id, depends_on: []}]}` + `validate_dag(plan)` — ถ้ามีวงจร (cycle) หรือ depend งานที่ไม่มี = `invalid` ต้อง BLOCK
- **ห้าม:** ห้ามรันงานที่ depend ยังไม่เสร็จ, ห้ามรัน DAG ที่มี cycle

## 3. Verification
- **User Story:** ตรวจผลลัพธ์แต่ละขั้นก่อนยอมรับ มี Verification Gate
- **Design:** `verify_step(step, checker)` คืน `PASS / FAIL / BLOCKED` + `ExecutionSafetyPolicy` แบบ default-deny — ถ้าไม่มี Human Approval Token ห้ามรัน action ที่เป็น `execution`
- **ห้าม:** ห้ามเปิด Autonomous Execution โดยไม่มีการอนุมัติ, ห้ามรันคำสั่งอันตรายอัตโนมัติ

## ข้อกำหนด Phase 16 ทั้งหมด
- Step/Token Hard Cap — จำกัด steps / tokens ไม่ให้รันไม่จบ
- Human Approval Token — ต้องมี token ถึงจะรัน execution ได้
- Isolated Sandbox — execution ต้องอยู่ใน sandbox เท่านั้น
- Default-deny ExecutionSafetyPolicy — ไม่ได้รับอนุญาต = ห้ามรัน
- Verification ก่อนยอมรับผลลัพธ์

## ข้อห้าม Phase 16 ทั้งหมด
- ไม่ Training, ไม่แก้ไข Model Weights
- ไม่เปิด Autonomous Execution โดยไม่มีการอนุมัติ
- ไม่รันคำสั่งอันตรายโดยอัตโนมัติ, ไม่ใช้ External AI APIs, ไม่ Deploy
- ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_16_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Reasoning / Planning DAG / Verification อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] DAG ที่มี cycle ถูก BLOCK
- [ ] Execution โดยไม่มี Human Approval Token ถูก BLOCK
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
