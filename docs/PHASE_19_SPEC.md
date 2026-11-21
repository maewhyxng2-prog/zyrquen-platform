# Phase 19 — Autonomous Capability & Safety Governance — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 18:** `CODE DONE`
- **Phase 20:** `PROPOSED — รอคิวหลัง 19`
- **Phase 21:** `ไม่มี — Phase 20 คือ Phase สุดท้าย`

## เป้าหมาย
วางระบบควบคุมความสามารถในการดำเนินงานอัตโนมัติของ ZYRQUEN ให้ปลอดภัย ตรวจสอบได้ และต้องมีอำนาจอนุมัติที่ถูกต้องก่อนดำเนินการสำคัญ

## 1. Tool / Sandbox Boundaries
- **User Story:** Tools ทำงานได้เฉพาะในขอบเขตที่อนุมัติ แยก Sandbox ออกจากระบบหลัก
- **Design:** `check_tool_access(tool, resource)` → `allowed / denied` — ถ้า tool/resource ไม่อยู่ใน allowlist = `denied` + `default-deny` — Sandbox แยกจากระบบหลักเสมอ
- **ห้าม:** ห้ามเข้าถึงไฟล์/ระบบ/ทรัพยากรนอก allowlist, ห้าม bypass Sandbox

## 2. Cryptographic Server-signed Approval
- **User Story:** การดำเนินการสำคัญต้องใช้ Approval Token ที่ลงลายเซ็นจาก Server เท่านั้น
- **Design:** `issue_approval(action, scope)` → `{token, signature, expires_at}` / `verify_approval(token)` → `valid / invalid / expired / replayed` — Token ผูกกับ `action + scope` ใช้ซ้ำไม่ได้ หมดอายุ = ใช้ไม่ได้
- **ห้าม:** ห้ามใช้ Token ที่ไม่มีลายเซ็น Server, ห้ามใช้ Token ปลอม / หมดอายุ / ใช้ซ้ำ

## 3. Human-in-the-loop / Auditability
- **User Story:** จุดสำคัญต้องให้มนุษย์อนุมัติ และตรวจสอบย้อนหลังได้ทุก Action
- **Design:** `execute_with_approval(action, approval)` → ถ้าไม่มี approval ที่ valid = `blocked` — ทุกการดำเนินการบันทึก `audit_log [{action, actor, approval_id, reason, result, timestamp}]`
- **ห้าม:** ห้ามข้าม Approval Gate, ห้ามดำเนินการโดยไม่มี Audit Log, ห้าม AI ยกระดับสิทธิ์ตัวเอง

## ข้อห้าม Phase 19 ทั้งหมด
- ไม่เปิด Autonomous Execution แบบไม่มีการอนุมัติ
- ไม่อนุญาตให้ AI ยกระดับสิทธิ์ตัวเอง
- ไม่ใช้ Approval Token ที่ไม่ได้ลงลายเซ็นจาก Server
- ไม่ Training, ไม่แก้ Model Weights, ไม่ใช้ External AI APIs
- ไม่ Deploy ระบบอัตโนมัติจริง
- ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_19_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Tool/Sandbox / Server-signed Approval / Human-in-the-loop อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] Tool นอก allowlist ถูก DENY
- [ ] Token ปลอม / หมดอายุ / ใช้ซ้ำ ถูก BLOCK
- [ ] Action ไม่มี Approval ถูก BLOCK + มี Audit Log
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
