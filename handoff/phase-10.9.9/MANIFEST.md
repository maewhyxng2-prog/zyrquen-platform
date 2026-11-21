# ZYRQUEN — Phase 10.9.9 Patch Handoff Manifest

* **สถานะงาน:** `HANDOFF PREPARATION ONLY — NO COMMIT / NO PUSH / NO SYNC`
* **ประเภทการส่งมอบ:** **Full File Snapshot** (11 Python files, โครงสร้างไดเรกทอรีตรงกับ Repository)
* **Base Commit SHA:** `UNKNOWN` (ดูรายละเอียดใน `BASELINE.md`)
* **วันที่จัดเตรียม:** 2026-11-21
* **ผลตรวจ Syntax (AI Studio Sandbox, Python 3.11):** `11/11` ไฟล์ผ่าน `ast.parse` (`0` syntax errors)

---

## รายการไฟล์ส่งมอบทั้ง 11 ไฟล์

| # | Repository Path | ขนาด (Bytes) | บรรทัด | SHA-256 | สรุปการเปลี่ยนแปลงและจุดประสงค์ |
| :-: | :--- | :---: | :---: | :--- | :--- |
| 1 | `apps/api/migrations/env.py` | 2350 | 82 | `ca029c6e210c9e3e656d2e7208bad868068c558dc1d612fb7b0e54c584526a87` | ใช้ `from sqlalchemy.pool import NullPool` และ `poolclass=NullPool,`; คง `verify_test_database_connection(connection, target)` และเพิ่ม `if connection.in_transaction(): connection.rollback()` (บรรทัด 65–66) เพื่อล้าง transaction ที่ SQLAlchemy 2.0 autobegin เปิดขึ้นระหว่างตรวจตัวตนฐานข้อมูลทดสอบก่อนเปิด `with context.begin_transaction():` |
| 2 | `apps/api/test_migration_chain.py` | 1119 | 36 | `cc5683f4229411b587f1d6e958969b161d7f2eaab5205a3226657c227f68ab0f` | เปลี่ยนจากการอ้างอิง relative path `Path("apps/api/migrations/versions")` เป็น `VERSIONS_DIR = Path(__file__).resolve().parent / "migrations" / "versions"` เพื่อให้ทดสอบผ่านไม่ว่าจะรัน `pytest` จาก Repo Root หรือ `working-directory: apps/api` ใน CI |
| 3 | `apps/api/main.py` | 6527 | 200 | `f5e087ad350336675afc6956d16f33e4983fd128002bcc17b167f99a43c7f489` | Canonicalize module imports จาก bare imports (`routers.*`, `database`, `operations`, `api_access_models`, `usage_models`) เป็น `apps.api.*` เพื่อป้องกันการโหลด module ซ้ำซ้อนและการลงทะเบียนตารางใน `Base.metadata` ซ้ำ |
| 4 | `apps/api/routers/training.py` | 7654 | 226 | `97908ff1f9195b50fcabf14a36cca254d31b50c350ef5ec074669881e81c956f` | Canonicalize imports (`database`, `models`, `security`, `training_jobs`, `training_models`, `training_schemas`) เป็น `apps.api.*` |
| 5 | `apps/api/routers/inference.py` | 15121 | 416 | `48219a4c4d76051b394de9604340ee5fab4444ab17712f0c212453c023b6f6ae` | Canonicalize import ของ `routers.conversations` เป็น `apps.api.routers.conversations` และรักษา canonical imports ของ `apps.api.*` |
| 6 | `apps/api/training_jobs.py` | 8528 | 236 | `1e02bbf211cc61c67ec5e9ad5a4d09e7ef263dc3fa9a325ed55390655a9a9931` | Canonicalize import ของ `training_models` เป็น `apps.api.training_models` โดยคง `reserve_next_native_version` และกฎ Atomic Version Reservation เดิมไว้ครบถ้วน |
| 7 | `apps/api/test_pg_integration.py` | 12629 | 405 | `8567339fb72677f69d45f5128ad4e728324ff16f1ef41cf7537fe8885415b9e1` | Canonicalize `from apps.api.main import app`; ใช้ `TestClient(app, client=("127.0.0.1", 12345))` เพื่อให้ `_client_ip()` ผ่าน IP validation ใน `/auth/login`; และปรับเคส `rollback_id` ให้ทดสอบ `complete_inference` + `db.rollback()` + `finish_inference(..., "failed")` เนื่องจาก `reserve_inference()` commit ในตัวเอง |
| 8 | `apps/api/test_main.py` | 2121 | 65 | `d8355ef7265f9b04acee9d37394220b7b669cc58411c2de0ebc432514b2cd34d` | Canonicalize import เป็น `from apps.api.main import app` และ `from apps.api.operations import install_exception_logging` |
| 9 | `apps/api/test_auth_gate.py` | 6605 | 221 | `ae8116a9c67186590f671ab677d3f66044bc830dbb1dd5069d924c78b5f15f55` | Canonicalize imports (`database`, `evaluation_models`, `main`, `models`, `security`, `training_models`) เป็น `apps.api.*` |
| 10 | `apps/api/test_training.py` | 5653 | 188 | `a1fea24375e77edbce18c1d31d755571c82fa0fd6367df4cda2174d44a0d09f8` | Canonicalize imports (`database`, `main`, `models`, `routers.training`, `training_models`) เป็น `apps.api.*` |
| 11 | `apps/api/test_training_registry.py` | 8994 | 262 | `c6ffd07388c5e51ff72ee7ecf6e0e2717c826406561997d20bb28d423d652342` | Canonicalize imports (`database`, `models`, `training_jobs`, `training_models`) เป็น `apps.api.*` โดยไม่แก้พฤติกรรม Atomic Version Reservation หรือ No Auto-Promotion |

---

## ผลตรวจความพร้อมก่อนส่งมอบ (AI Studio Sandbox)

1. **`env.py` (`NullPool` & Transaction Lifecycle):**
   * พบ `from sqlalchemy.pool import NullPool` และ `poolclass=NullPool,`
   * พบ `verify_test_database_connection(connection, target)` ตามด้วย `if connection.in_transaction(): connection.rollback()` ก่อน `with context.begin_transaction():`
2. **`test_migration_chain.py` (`__file__` path):**
   * พบ `VERSIONS_DIR = Path(__file__).resolve().parent / "migrations" / "versions"`
   * รัน `test_revision_01_bootstraps_users_for_empty_database()` ผ่านทั้งจาก Repo Root และ `apps/api/` (ส่วน `test_migration_chain_is_linear_and_heads_at_07()` ต้องใช้ `alembic` ซึ่งไม่มีใน AI Studio Sandbox)
3. **Import Canonicalization (`apps.api.*`):**
   * ตรวจสอบ AST ทุกไฟล์ภายใต้ `apps/api/` ไม่พบ bare internal module imports หลงเหลือ (`0 hits`)
4. **PostgreSQL Integration & Database Safety:**
   * `apps/api/test_pg_integration.py` import `apps.api.main` โดยตรง
   * `apps/api/database_safety.py` ไม่ได้ถูกแก้ไข และยังคงการตรวจ fail-closed สำหรับ `ZYRQUEN_ENV=test`, ปฏิเสธ Production host/name, และตรวจ `public.zyrquen_environment_identity`
5. **ไฟล์นอกขอบเขตชุด 11 ไฟล์ใน Workspace ปัจจุบัน (แจ้งเพื่อความโปร่งใส — ไม่รวมในชุด Patch 11 ไฟล์นี้):**
   * `apps/core/test_native_runtime.py` และ `apps/core/test_token_generation.py` (แก้ไขเพิ่มเติมจากผล CI Run `44887483286` สำหรับ `test_12_streaming_stops_at_eos` และ `test_04_sampling_and_eos` — ต้องนำไปพร้อมกันในรอบ Push แก้ CI)
   * `docs/engineering/ZYRQUEN_PHASE_READINESS.md` และ `docs/engineering/ZYRQUEN_PHASE_11_20_MASTER_ROADMAP.md` (งานเอกสาร Phase 11–20)
   * `README.md` (อัปเดตเอกสารจากรอบก่อนหน้า)
   * `apps/web/tsconfig.tsbuildinfo` (TypeScript incremental build cache — ห้าม commit เข้า Git)
   * `apps/api/main.py.save` (ไฟล์ค้างเดิมใน repo ตั้งแต่ก่อนหน้า — ไม่ได้อยู่ในชุด 11 ไฟล์)
   * ไม่มีไฟล์ `.env` และไม่พบ pattern secrets ในทั้ง 11 ไฟล์
