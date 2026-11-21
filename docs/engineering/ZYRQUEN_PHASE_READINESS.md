# ZYRQUEN — Phase Readiness Notes (`Phase 10.9.9` & `Phase 11` Proposal)

* **Repository:** `maewhyxng2-prog/zyrquen-platform`
* **Branch ที่คาดหวัง:** `main`
* **วันที่จัดทำ:** 2026-11-21
* **สถานะเอกสาร:** เอกสารเตรียมความพร้อมเชิงวิศวกรรม (Non-Implementation / No Source Code Changes)
* **ทิศทางสถาปัตยกรรมหลัก:** ZYRQUEN เป็น **Native Intelligence System** ที่พัฒนาขีดความสามารถของตนเองผ่าน Native Model, Tokenizer, Dataset Manifest, Model Registry และ Evaluation Gates — ไม่ใช่ Chatbot-only หรือ External AI API Wrapper

---

## 0. Verified Baseline & Evidence Separation

เอกสารนี้แยกหลักฐานตามสภาพแวดล้อมที่ตรวจสอบจริงเพื่อไม่ให้เกิดการอ้างผลผ่านโดยไม่ได้รันจริง:

| สภาพแวดล้อม / แหล่งหลักฐาน | SHA / ตำแหน่งที่ตรวจ | สถานะที่ยืนยันแล้ว | ข้อจำกัด / ช่องว่าง |
| :--- | :--- | :--- | :--- |
| **Google AI Studio (`/app/applet`)** | ไม่มี `.git` (`git rev-parse --show-toplevel` ล้มเหลว) | `apps/api/migrations/env.py` มี `from sqlalchemy.pool import NullPool` (บรรทัด 9) และ `poolclass=NullPool,` (บรรทัด 48); `AST_PARSE: OK`; `173/173` `.py` AST ผ่าน; `tests/` pure-unittest `128/128` PASS; `apps/web` Vitest (`16/16`), TypeScript, ESLint PASS; External AI API grep = `0 hits` | ไม่มี `.git`, ไม่มี Python runtime deps (`pytest`, `sqlalchemy`, `alembic`, `psycopg`, `torch`), ไม่มี PostgreSQL, ไม่มี Docker |
| **GitHub Codespaces (`/workspaces/zyrquen-platform`)** *(จากหลักฐานภาพหน้าจอ 14:53–15:00)* | Local `HEAD`: `e6f1386719ac6b848b617c46d7a6fb31e169bed0` (`[behind 1]` เทียบ `origin/main` `74aea54`) | `apps/web/package-lock.json` มีอยู่จริง; `apps/web` (`npm test && typecheck && lint && build`) build Next.js สำเร็จ (`12/12` static pages) | `test_pg_integration.py` ได้ `3 skipped` (ไม่มี PG Test DB); `pytest tests` และ `docker build` รอบก่อนพลาดเพราะ Terminal ค้างอยู่ที่ `apps/web/` ไม่ใช่ Repo Root |
| **GitHub Actions (`ZYRQUEN API Tests`)** | Run `44877359816` (`headSha: e6f1386...`, `conclusion: failure`) | ยืนยันความล้มเหลวของ SHA เก่า (`e6f1386`) ใน Job `postgres-integration` (`NameError: name 'pool' is not defined`) | **ยังไม่มีหลักฐานผล CI Run บน `origin/main` Commit `74aea54`** (`refactor(api): fix sqlalchemy pool class import`) |

---

## 1. Phase 10.9.9 — Final Integration Verification

* **สถานะ Gate ปัจจุบัน:** **`NOT CLOSED`** (`BLOCKED`)
* **เป้าหมายหลัก:**
  1. ยืนยัน Migration Fix (`poolclass=NullPool`) ใน Git Working Tree จริงบน GitHub Codespaces ให้ตรงกับ `origin/main` (`74aea54` หรือ commit ล่าสุด)
  2. ตรวจ PostgreSQL Integration Tests ทั้ง 3 รายการบนฐานข้อมูลทดสอบแบบ Disposable (ไม่ใช่ Production):
     * `apps/api/test_pg_integration.py::test_migration_cycle_on_empty_database`
     * `apps/api/test_pg_integration.py::test_quota_concurrency_and_idempotency`
     * `apps/api/test_pg_integration.py::test_http_multi_user_auth_isolation_and_api_keys`
  3. ตรวจ API, Native Core/Registry, Web และ Docker จาก **Repository Root** (`/workspaces/zyrquen-platform`) ตาม Environment ที่มีอยู่
  4. ตรวจผล GitHub Actions Workflow `ZYRQUEN API Tests` บน **Head SHA ปัจจุบันจริง** (ห้ามนำผล SHA เก่ามาใช้อ้างอิง)
  5. สรุป Gate Closure อย่างเป็นทางการก่อนพิจารณา Phase ถัดไป

### 1.1 รายการ Verification Checklist ที่ต้องปิดใน Codespaces / CI
* **Gate 1–2 (Git & Migration Fix):** กลับไป Repo Root (`cd "$(git rev-parse --show-toplevel)"`), ตรวจ `git log -1 --oneline origin/main` และ `git show origin/main:apps/api/migrations/env.py` (ต้องมี `from sqlalchemy.pool import NullPool` และ `poolclass=NullPool,`), หากได้รับอนุมัติ Fast-Forward ให้ sync Working Tree จาก `[behind 1]` เป็น `74aea54`
* **Gate 3 (PostgreSQL Integration):** รันบน CI Job `postgres-integration` (หรือ Codespaces ที่มี PostgreSQL 16 + `public.zyrquen_environment_identity` marker) จนผ่าน `3/3 passed` (ไม่ใช่ `skipped`)
* **Gate 4 (API & Native Regression จาก Repo Root):**
  * รัน `apps/core` + `apps/api` (non-PG) + `tests/` โดยรันจาก Repo Root และระวังปัญหาที่ `.github/workflows/api-tests.yml` ตั้ง `working-directory: apps/api` ซึ่งขัดกับ `apps/api/test_migration_chain.py` ที่อ้าง `Path("apps/api/migrations/versions")` จาก Repo Root
  * ยืนยันสัญญาความปลอดภัยของ `ModelRegistry` (Atomic Version Reservation, dual-lock, ห้าม Auto-Promotion), `checkpoint_recovery.py` (`weights_only=True`, containment, SHA-256), และ `/livez` / `/readyz`
* **Gate 5 (Web Verification):** `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` ผ่านแล้วในภาพหน้าจอ Codespaces; คงเหลือ `npm run test:e2e` ที่ต้องประเมินเรื่อง Localization Drift (`apps/web/e2e/platform.spec.ts` ใช้ข้อความภาษาอังกฤษขณะที่ UI `/system` และ `/training` แสดงผลภาษาไทย)
* **Gate 6 (Docker Verification จาก Repo Root):**
  * API: `docker build -f apps/api/Dockerfile -t zyrquen-api:test .` (Build Context = `.`)
  * Web: `docker build -f apps/web/Dockerfile -t zyrquen-web:test ./apps/web` (Build Context = `./apps/web`)
* **Gate 7 (GitHub Actions Evidence):** รัน `gh run list --repo maewhyxng2-prog/zyrquen-platform --branch main --limit 5 --json databaseId,workflowName,status,conclusion,headSha` และตรวจสอบ Log ของ Run บน SHA `74aea54`

### 1.2 Exit Criteria ของ Phase 10.9.9
1. ไม่มี Test Failure หรือ Docker/CI Failure ที่ยังไม่ทราบสาเหตุ
2. รายการที่ยัง `BLOCKED` (หากมีใน Environment เฉพาะจุด เช่น ไม่มี Local Docker/PG ในบางเครื่อง) ต้องมีหลักฐานทดแทนจาก CI Run ของ SHA ปัจจุบันพร้อมเหตุผลชัดเจน
3. ไม่มีการกล่าวอ้างว่าผ่าน (`PASS`) จากการอ่านโค้ดเชิงสถิต (Static Inspection) เพียงอย่างเดียว
4. มีหลักฐาน Commit SHA, CI Run ID และ `git status` สะอาด

---

## 2. Phase 11 — Native Intelligence Readiness Proposal

* **สถานะ:** **`PROPOSED / NOT APPROVED`**
* **คำเตือน:** ยังไม่อนุมัติ Implementation — ห้ามเริ่ม Training, ห้ามสร้าง Model Weights, ห้ามดาวน์โหลด Dataset, และห้าม Provision Cloud/GPU จนกว่า Phase 10.9.9 จะปิด (`CLOSED`) และเจ้าของโครงการอนุมัติ Scope ของ Phase 11 อย่างเป็นลายลักษณ์อักษร

### 2.1 ขอบเขตข้อเสนอ (Proposed Verification & Readiness Scope)
1. **ตรวจสอบความพร้อมของ Native Model Architecture**
   * ทบทวนโครงสร้างและขีดจำกัดของ `ZyrquenConfig`, `ZyrquenModel`, `NativeTokenizer` และ `DatasetManifest` (`apps/core/native/`)
   * ประเมินจุดคอขวดที่ตรวจพบ: การยังไม่มี KV-Cache ใน `ZyrquenModel`, การจำกัด Inference ด้วย `_semaphore = Semaphore(1)` / `native_generation_lock`, และการประเมินขนาด/Memory footprint ของโมเดลทดสอบในระดับ CPU sandbox เทียบ GPU
2. **ตรวจสอบ Native Model Registry และ Artifact Lifecycle**
   * ยืนยันวงจร `reserve()` -> Artifact staging -> `verify()` -> `commit()` -> Explicit `promote()` ใน `apps/core/native/registry.py`
   * ยืนยันข้อจำกัดของ `fcntl.flock` (ใช้ได้เฉพาะ Single-Host POSIX) และการเตรียมแนวทางแยก File Lock vs Shared Coordinator/DB Lock ในอนาคต
   * ยืนยันความสอดคล้องของ `NativeModelLoader` (`cfg.vocab_size == tokenizer.vocab_size`, SHA-256 verification, `weights_only=True`, `strict=True`, `eval()`)
3. **กำหนดแนวทาง Training-to-Inference Round-Trip Verification (รอการอนุมัติก่อนรัน)**
   * ออกแบบเกณฑ์การทดสอบ Sandbox แบบควบคุมงบประมาณและเวลา (`ZYRQUEN_TRAINING_MAX_BUDGET_USD`, `MAX_RUNTIME_SECONDS`) บนข้อมูลตัวอย่างที่มี Provenance ถูกต้อง (`zyrquen.dataset-manifest.v1`)
   * ยืนยันการ Resume จาก Checkpoint (`checkpoint_recovery.py`) และการโหลดขึ้นเสิร์ฟผ่าน `NativeInferenceEngine` โดยไม่ใช้ Auto-Promotion
4. **กำหนด Evaluation และ Quality Gates**
   * เชื่อมต่อ `apps/core/native/evaluation/engine.py` กับ `EvaluationService` (`apps/api/evaluation_service.py`) และแก้ไขช่องว่างความปลอดภัยที่พบ:
     * `POST /v1/evaluation/runs` ต้องเปลี่ยนจาก `get_current_user` เป็นสิทธิ์ Admin/RBAC + Quota Enforcement ก่อนเปิดรับงานประมวลผลจริง
     * ซิงค์ ORM `EvaluationMetric` (`apps/api/evaluation_models.py`) กับ Alembic Migration (ตาราง `evaluation_metrics` และ `DateTime(timezone=True)`)
     * จัดการ Legacy Mock Engine ใน `apps/core/evaluation/engine.py` (`15.5`, `0.85`)
5. **กำหนด Version Governance และ Rollback Safety**
   * ห้าม Auto-Promotion หลัง Training เสร็จสิ้นทุกกรณี ต้องผ่าน Evaluation Gate และคำสั่ง Promote ที่ตรวจสอบ `verify()` ซ้ำก่อนเปลี่ยน `active` pointer
   * กำหนดขั้นตอน Rollback กลับไปยัง Version ก่อนหน้าใน Registry และยืนยัน Fail-Closed readiness (`/readyz` คืน `503` หาก active artifact เสียหายหรือไม่ผ่าน checksum)

---

## 3. Phase 11.x — Future Work Packages (Long-Term Unapproved Roadmap)

> ทุก Work Package ด้านล่างเป็น **แผนงานระยะยาวระดับข้อเสนอ (Proposed / Not Approved)** เพื่อคงความเป็น **Native Intelligence System** ของ ZYRQUEN โดยเรียงตาม Dependency จากฐานรากไปสู่ Production Reliability

### WP-1: Native Training Pipeline Readiness
* **Dependency:** Phase 10.9.9 `CLOSED`, การอนุมัติงบประมาณ/ฮาร์ดแวร์ และ Dataset License Governance
* **ขอบเขตงาน:**
  * ย้ายการประสานงาน Job จาก Single-process `ThreadPoolExecutor(max_workers=1)` (`apps/api/training_jobs.py`) ไปสู่ Worker Queue ที่ทนต่อ Process Restart
  * เชื่อม `DistConfig` (`apps/core/training_infrastructure/distributed/trainer.py`) เข้ากับ Training Loop จริง (`apps/core/native/train.py`) และพัฒนา Cloud `GpuProvider` adapter ภายใต้ `provisioner.py` เมื่อได้รับอนุมัติ
  * เก็บกวาดไฟล์ซ้ำซ้อน (`apps/core/training/apps/core/training/cost_limits.py`)
* **Acceptance Criteria:** Resume จาก Checkpoint ได้โดยไม่สูญเสีย Lineage, บังคับใช้ Budget/Runtime Guard ก่อนรันทุก Job, และมี Integration Test ยืนยัน Worker Recovery

### WP-2: Native Inference Runtime Verification
* **Dependency:** WP-1 (หรือ Artifact ที่ผ่านการ Commit/Verify แล้วใน Registry)
* **ขอบเขตงาน:**
  * ออกแบบและทดสอบ KV-Cache ใน `ZyrquenModel` เพื่อลด Latency ของ Autoregressive Decoding
  * แยก Inference Execution Pool ออกจาก Single-concurrency `Semaphore(1)` และ `native_generation_lock` พร้อมกำหนด Queue/Timeout Policy สำหรับ Multi-user
  * ปรับ Packaging ของ Inference Worker / API Container ให้รองรับ `torch` อย่างเหมาะสม (แยกจาก API-only image หรือ Multi-stage runtime)
* **Acceptance Criteria:** ผ่าน Latency & Concurrent Throughput Benchmarks, Streaming Token Delivery ทำงานเสถียร, และไม่มี Memory Leak หรือ Race Condition ภายใต้ Load

### WP-3: Model Evaluation & Reproducibility
* **Dependency:** Phase 11 Evaluation Governance Proposal
* **ขอบเขตงาน:**
  * ผูก `apps/core/native/evaluation/engine.py` เข้ากับ `NativeModelLoader` และ `EvaluationRun` persistence อย่างสมบูรณ์
  * บังคับ RBAC (`require_admin` / Quota) บน `POST /v1/evaluation/runs` และซิงค์ Migration สำหรับ `evaluation_metrics`
  * ถอดหรือ Deprecate Legacy Mock Metrics (`apps/core/evaluation/engine.py`) และเชื่อมต่อ `apps/core/intelligence/` (Phase 9) จาก Rule-based Contract ไปสู่การเรียก `ZyrquenModel` จริงพร้อม Persistent Feedback Storage
* **Acceptance Criteria:** Evaluation Run สร้างผลลัพธ์ที่ทำซ้ำได้ (Deterministic seed + Dataset hash + Model hash), ไม่มี Mock/Hardcoded scores, และผ่าน Regression Suite

### WP-4: Artifact Integrity & Version Governance
* **Dependency:** WP-1, WP-3
* **ขอบเขตงาน:**
  * ยกระดับ `ModelRegistry` Lock จาก `fcntl.flock` (Single-host POSIX) เป็น Database/Distributed Coordinator Lock หากขยายสู่ Multi-node Storage
  * บังคับ Signing/Checksum Audit ระหว่าง `reserved` -> `committed` -> `active` และ Audit Trail สำหรับการ Promote / Rollback ทุกครั้ง
  * ปรับ E2E & Web Training/Admin Console ให้สอดคล้องกับ State จริงของ Registry และภาษา UI ปัจจุบัน
* **Acceptance Criteria:** Multi-process/Multi-node Reservation Contention Test ผ่านโดยไม่มี Version Collision, Zero Auto-Promotion, และ Rollback Drill ผ่านภายในเวลาที่กำหนด

### WP-5: Production Reliability & Observability
* **Dependency:** WP-2, WP-3, WP-4
* **ขอบเขตงาน:**
  * แก้ไข CI Workflow (`.github/workflows/api-tests.yml`): แก้ `working-directory` ของ `test_migration_chain.py`, รวมชุด `tests/` (19 ไฟล์) เข้ากับ CI, ตัดการติดตั้ง `torch` ซ้ำซ้อน, และเพิ่ม Security/Dependency Audit checks
  * ตรวจสอบ Policy ของ `Secure` Cookie (`apps/web/src/lib/cookies.ts`) กับการ Deploy ผ่าน TLS Reverse Proxy และปรับ `apps/web/e2e/platform.spec.ts` ให้ตรงกับ UI จริง
  * เพิ่ม Prometheus/OpenTelemetry Metrics, Structured Tracing, Automated Backup Integrity Drill (`scripts/verify_backup_integrity.py`) และเก็บกวาดไฟล์ค้าง (`apps/api/main.py.save`)
* **Acceptance Criteria:** CI/CD ทุก Job ผ่าน (`0` skipped critical suites), ผ่าน Backup-and-Restore Drill บน Disposable Staging Environment, และ Alerting/Health Probes (`/livez`, `/readyz`) แสดงสถานะถูกต้อง
