# ZYRQUEN Ω∞

ZYRQUEN Ω∞ เป็นโครงการวิจัยและวิศวกรรมระยะยาวเพื่อพัฒนาแพลตฟอร์ม AI และระบบ Native General Intelligence (NGI) ที่ทำงานได้ด้วยตนเองบนโครงสร้างพื้นฐานอิสระ Repository ปัจจุบันประกอบด้วย Next.js Web Client, FastAPI Backend, โมดูล Native Model Runtime / Training Infrastructure และชั้นสัญญา Intelligence Phase 9 โดย **ยังไม่มี model weights ที่ผ่านการฝึกของ ZYRQUEN เอง** และ **ยังไม่ผ่านการรับรอง Production Deployment**

<picture>
  <source media="(forced-colors: active)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <img src="apps/web/public/zyrquen-logo.svg" width="640" height="128" alt="ZYRQUEN animated geometric logo">
</picture>

---

## สถานะตามหลักฐานใน Repository

| ระดับหลักฐาน | สถานะปัจจุบัน | รายละเอียดที่ตรวจสอบได้จริง |
| --- | --- | --- |
| **Implementation** | มีโค้ดต้นฉบับใน Repository | Web Client (`apps/web/`), FastAPI Service (`apps/api/`), Native Runtime / Tokenizer / Model / Dataset / Training (`apps/core/`), Intelligence Phase 9.1–9.10 (`apps/core/intelligence/`), Phase 11–20 (`phase11.py` - `phase20.py`), Alembic Migrations (`apps/api/migrations/`), เอกสาร (`docs/`) |
| **Unit Tests** | **Local Final Gate 11–20: `60 / 60 PASSED`** | `test_phase11.py` - `test_phase20.py` แต่ละ Phase `6 passed` รวม `60 passed in 0.20s` บนเครื่องท้องถิ่น (Local) |
| **Integration Verification** | **Phase 10.9.9 Gate: `PASSED / CLOSED`** | CI Run `44893016007`, SHA `466b58a75419708a86469f59a903e322d85081d2`, 4/4 `web / docker / test / postgres-integration` สำเร็จ, docs commit `7a3c3be` |
| **GitHub CI สำหรับ 11–20** | **ยังไม่ยืนยัน** | ห้ามอ้างว่า CI 4/4 สำหรับ 11–20 ผ่าน จนกว่าจะเห็น Workflow 4 Jobs สำเร็จบน SHA เดียวกัน — ตอนนี้มีแค่ Local `60/60` |
| **Production Deployment** | ยังไม่พร้อมและยังไม่ได้ Deploy | ยังไม่มี trained ZYRQUEN model weights, ยังไม่ได้ provision Cloud / PostgreSQL / GPU / Monitoring / Alerting / Backup และห้ามระบุว่าเป็น Production Ready |

เอกสารอ้างอิงหลัก:
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`docs/PHASE_9_STATUS.md`](docs/PHASE_9_STATUS.md)
- [`docs/PHASES_11_20_INDEX.md`](docs/PHASES_11_20_INDEX.md) — สารบัญ Phase 11–20 ครบ
- [`docs/engineering/ZYRQUEN_PHASE_READINESS.md`](docs/engineering/ZYRQUEN_PHASE_READINESS.md)
- [`docs/operations/KNOWN_LIMITATIONS.md`](docs/operations/KNOWN_LIMITATIONS.md)
- [`API_ACCESS.md`](API_ACCESS.md)

---

## ZYRQUEN — Phase 11–20 — CLOSED

| Phase | สถานะ | Commit | ผล Local |
|---|---|---|---|
| 11 Workspace Intelligence | `CODE DONE` | `ade8e2f` | `6 passed` |
| 12 Native Intelligence Foundation | `CODE DONE` | `93dbbf8` | `6 passed` |
| 13 Knowledge & Data Pipeline | `CODE DONE` | `7b32fb7` | `6 passed` |
| 14 Evaluation & Capability Measurement | `CODE DONE` | `b710c57` | `6 passed` |
| 15 Native Model Readiness | `CODE DONE` | `c235c98` | `6 passed` |
| 16 Native Reasoning & Planning | `CODE DONE` | `d68301a` | `6 passed` |
| 17 Memory & Knowledge Integration | `CODE DONE` | `a9ade14` | `6 passed` |
| 18 Adaptive Learning & Improvement | `CODE DONE` | `b1cd6cd` | `6 passed` |
| 19 Autonomous Capability & Safety Governance | `CODE DONE` | `b1500f3` | `6 passed` |
| 20 Native Intelligence System Maturity | `CODE DONE` | `fa7a65e` | `6 passed` |
| 21 | `ไม่มี — 20 คือ Phase สุดท้าย` | — | — |

**กติกาที่ยึดไว้ตลอด 11–20:** ไม่ Training จริง, ไม่แก้ Model Weights ตอน online, ไม่ใช้ External AI APIs, ไม่ Auto-promote, ไม่แก้ Auth / Quota / Database Schema / Migration, ไม่ Deploy Production อัตโนมัติ, แยก PASS / FAIL / BLOCKED / NOT RUN ชัดเจน — ห้ามนับ NOT RUN เป็น PASS

```bash
python -m pytest test_phase11.py test_phase12.py test_phase13.py test_phase14.py test_phase15.py test_phase16.py test_phase17.py test_phase18.py test_phase19.py test_phase20.py -v
# ต้องขึ้น 60 passed
