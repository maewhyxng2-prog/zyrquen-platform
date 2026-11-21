# Phase 14 — Evaluation & Capability Measurement — SPEC

- **Status:** `APPROVED / OPEN`
- **Phase 13:** `CODE DONE`
- **Phase 15-20:** `NOT APPROVED / DO NOT START`

## เป้าหมาย
สร้างระบบประเมินความสามารถ วัด Benchmark ตรวจสอบ Regression และวัด Reliability ของ ZYRQUEN เพื่อกำหนดหลักฐานความพร้อมก่อนเข้าสู่ Native Model Readiness ใน Phase 15

## 1. Evaluation Framework
- **User Story:** ทุกการประเมินมีผลเป็น PASS / FAIL / BLOCKED / NOT RUN ชัดเจน ไม่ปนกัน
- **Design:** `evaluate_case(case)` คืน `{"status": "PASS|FAIL|BLOCKED|NOT RUN", "evidence": "...", "reason": "..."}` — ถ้าไม่ได้รัน ต้องเป็น `NOT RUN` เท่านั้น ห้ามเป็น PASS
- **ห้าม:** ห้ามนับ NOT RUN เป็น PASS, ห้าม fake evidence

## 2. Benchmark & Regression
- **User Story:** วัด Benchmark ครั้งนี้ เทียบกับครั้งก่อนได้ และรู้ว่าแย่ลงหรือไม่
- **Design:** `compare_benchmark(prev, curr)` คืน `{"regression": true/false, "diff": {...}}` — ถ้า `regression == true` ต้อง BLOCK การยอมรับการเปลี่ยนแปลง
- **ห้าม:** ห้ามยอมรับ regression โดยไม่มีเหตุผล, ห้ามแก้ benchmark ย้อนหลัง

## 3. Reliability
- **User Story:** วัด Reliability จากผลประเมินจริง เช่น PASS rate จากเฉพาะที่รันแล้วเท่านั้น
- **Design:** `reliability_score(results)` = `PASS / (PASS + FAIL)` — ไม่นับ BLOCKED / NOT RUN ในตัวหาร ห้ามบวกเพิ่มเอง
- **ห้าม:** ห้ามนับ BLOCKED / NOT RUN เป็น PASS

## ข้อกำหนด Phase 14 ทั้งหมด
- แยก PASS / FAIL / BLOCKED / NOT RUN
- ห้ามนับการทดสอบที่ไม่ได้รันเป็น PASS
- ผล Evaluation ต้องตรวจสอบย้อนกลับได้ — มี evidence + reason ทุกเคส
- ต้องมี Regression Gate ก่อนยอมรับการเปลี่ยนแปลง

## ข้อห้าม Phase 14 ทั้งหมด
- ไม่ Training, ไม่ Download Dataset หรือ Model Weights
- ไม่เช่า GPU / Cloud Resources, ไม่ Deploy, ไม่ใช้ External AI APIs
- ไม่เปลี่ยน Auth / Quota / Database Schema / Migration
- ไม่แก้ไฟล์เดิมนอกเหนือจากขอบเขตที่อนุมัติ
- ไม่ Commit/Push จนกว่าจะสั่งแยก

## Acceptance Criteria — ถือว่าผ่านเมื่อ
- [ ] มี docs/PHASE_14_SPEC.md ฉบับนี้
- [ ] มีเทสสำหรับ Framework / Benchmark / Reliability อย่างน้อย 1 ชุดต่อหัวข้อ
- [ ] NOT RUN ไม่ถูกนับเป็น PASS ในทุกสูตร
- [ ] Regression Gate block ได้จริงเมื่อ benchmark แย่ลง
- [ ] CI 4/4 ผ่านบน SHA เดียวกันเหมือน Gate 10.9.9
