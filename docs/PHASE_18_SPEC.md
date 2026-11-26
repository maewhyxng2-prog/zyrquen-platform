# Phase 18 — Adaptive Learning & Improvement — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 17:** `CODE DONE`
- **Phase 19-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
วางระบบ Adaptive Learning ที่ควบคุมได้ รองรับ Feedback, Replay และ Evaluation โดยแยกการเรียนรู้ออกจาก Online Runtime และป้องกันการเปลี่ยน Model Weights โดยไม่ได้รับอนุมัติ

## 1. Controlled Learning
- **User Story:** รับ Feedback ได้ แต่ต้องผ่าน Validation และ Approval ก่อนถึงจะเอาไปใช้
- **Design:** `submit_feedback(feedback)` → `validate_feedback()` → สถานะ `pending / approved / rejected` — ถ้าไม่มี source / ไม่มี evidence = `rejected`
- **ห้าม:** ห้ามเอา Feedback ที่ไม่ผ่าน Validation ไปใช้

## 2. Feedback / Replay Loops
- **User Story:** Feedback ที่อนุมัติแล้ว เอามา Replay ทดสอบซ้ำได้ เปรียบเทียบผลได้
- **Design:** `replay(feedback_id)` คืน `[{run_id, result, trace}]` — ทุก Replay มี `trace_id` ตรวจสอบย้อนกลับได้ และเชื่อม Evaluation / Regression Gate จาก Phase 14
- **ห้าม:** ห้าม Replay โดยไม่มี trace, ห้ามข้าม Regression Gate

## 3. Zero Online Weight Mutation
- **User Story:** ระหว่าง Online Runtime ห้ามเปลี่ยน Model Weights เด็ดขาด
- **Design:** `try_mutate_weights()` ต้องคืน `blocked` เสมอเมื่อ `mode == "online"` — การฝึกต้องเกิดใน `mode == "offline-approved"` เท่านั้น และต้องผ่าน Evaluation + Approval ก่อน Promote
- **ห้าม:** ห้าม Auto-promote, ห้าม mutate weights ตอน online

## ข้อกำหนด Phase 18 ทั้งหมด
- Feedback ต้องผ่าน Validation
- Replay ต้องตรวจสอบย้อนกลับได้
- ต้องเชื่อม Evaluation / Regression Gate
- Zero Online Weight Mutation
- ห้าม Auto-promote

## ข้อห้าม Phase 18 ทั้งหมด
- ไม่ Training จริงใน Phase นี้, ไม่แก้ Model Weights ระหว่าง Online Runtime
- ไม่ Download Dataset เพิ่ม, ไม่เช่า GPU / Cloud Resources
- ไม่ Deploy, ไม่ใช้ External AI APIs
- ไม่เปลี่ยน Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_18_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Controlled Learning / Replay / Zero Mutation อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] Feedback ไม่ผ่าน Validation ถูก reject
- [ ] Mutate weights ตอน online ถูก BLOCK
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
