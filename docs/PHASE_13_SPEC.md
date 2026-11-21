# Phase 13 — Knowledge & Data Pipeline — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 12:** `CODE DONE`
- **Phase 14-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
เตรียมระบบจัดการข้อมูลและ Dataset Governance เพื่อรองรับการพัฒนา Native Model ของ ZYRQUEN ในระยะถัดไป โดยต้องตรวจสอบแหล่งที่มา ใบอนุญาต Attribution และคุณภาพข้อมูลได้ — ยังไม่โหลด Dataset จริง ยังไม่เทรน

## 1. Data Ingestion
- **User Story:** รับข้อมูลเข้ามาแบบมีที่มา รู้ว่าใครส่งมา เมื่อไหร่ จากไหน
- **Design:** `ingest_record(source, license, attribution, text)` สร้าง record ที่มี `id, source, license, attribution, created_at` ทุกครั้ง ไม่มี record ที่ไม่มีที่มา
- **ห้าม:** ห้าม Download Dataset จริง, ห้าม ingest โดยไม่มี license/attribution

## 2. Dataset Governance
- **User Story:** ระบบบอกได้ว่า dataset ไหนใช้ได้ / ใช้ไม่ได้ ตามใบอนุญาต
- **Design:** `Governance` ตรวจ `license` ต้องอยู่ในรายการที่อนุญาต (`public-domain, mit, apache-2.0, cc-by-4.0, proprietary-approved`) นอกนั้น = `blocked` พร้อมเหตุผล
- **ห้าม:** ห้ามอ้างว่าใช้ได้ทั้งที่ license ไม่ชัด, ห้าม fake attribution

## 3. Data Validation
- **User Story:** ตรวจคุณภาพข้อมูลก่อนใช้ เช่น ข้อความว่าง, สั้นเกินไป, ซ้ำ, มี PII
- **Design:** `validate_record(record)` คืน `valid / invalid` + `issues[]` — เช่น `empty_text, too_short, duplicate, possible_pii`
- **ห้าม:** ห้ามเก็บ PII, ห้ามผ่าน validation แบบมั่ว

## ข้อห้าม Phase 13 ทั้งหมด
- ไม่ Training, ไม่ Download Dataset จริง, ไม่ Download Model Weights
- ไม่เช่า GPU / Cloud Resources, ไม่ Deploy, ไม่ใช้ External AI APIs
- ไม่แก้ Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_13_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Ingestion / Governance / Validation อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] ไม่มี record ที่ไม่มี source/license/attribution
- [ ] ไม่มี fake success — blocked ต้องบอกเหตุผล
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
