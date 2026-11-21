# ZYRQUEN Ω∞

ZYRQUEN Ω∞ เป็นโครงการวิจัยและวิศวกรรมระยะยาวเพื่อพัฒนาแพลตฟอร์ม AI และระบบ Native General Intelligence (NGI) ที่ทำงานได้ด้วยตนเองบนโครงสร้างพื้นฐานอิสระ Repository ปัจจุบันประกอบด้วย Next.js Web Client, FastAPI Backend, โมดูล Native Model Runtime / Training Infrastructure และชั้นสัญญา Intelligence Phase 9 โดย **ยังไม่มี model weights ที่ผ่านการฝึกของ ZYRQUEN เอง** และ **ยังไม่ผ่านการรับรอง Production Deployment**

<picture>
  <source media="(forced-colors: active)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/zyrquen-logo-mono.svg">
  <img src="apps/web/public/zyrquen-logo.svg" width="640" height="128" alt="ZYRQUEN animated geometric logo">
</picture>

โลโก้เป็นไฟล์ vector SVG ที่เขียนขึ้นโดยตรงพร้อมแอนิเมชัน CSS และรองรับ `prefers-reduced-motion` ดูรายละเอียดไฟล์ทั้งหมดได้ที่หัวข้อ [Brand Assets และ Dashboard Integration](#brand-assets-และ-dashboard-integration)

---

## สถานะตามหลักฐานใน Repository

ตารางนี้แยกสถานะระหว่าง **Implementation**, **Unit Tests**, **Integration Verification** และ **Production Deployment** ตามหลักฐานที่มีอยู่จริงในโค้ดปัจจุบัน:

| ระดับหลักฐาน | สถานะปัจจุบัน | รายละเอียดที่ตรวจสอบได้จริง |
| --- | --- | --- |
| **Implementation** | มีโค้ดต้นฉบับใน Repository | Web Client (`apps/web/`), FastAPI Service (`apps/api/`), Native Runtime / Tokenizer / Model / Dataset / Training (`apps/core/`), Training Infrastructure (`apps/core/training_infrastructure/`), Intelligence Phase 9.1–9.10 (`apps/core/intelligence/`), Alembic Migrations (`apps/api/migrations/`) และเอกสารปฏิบัติการ (`docs/operations/`) |
| **Unit Tests** | มีชุดทดสอบแยกส่วน (ไม่ใช่หลักฐานว่าผ่านทั้ง Repository) | ชุดสัญญา Phase 9 และ SVG safety (`tests/`), Web unit/static checks (`apps/web/`), และ targeted tests ตามอ้างอิง Git commit `6f4b5bd` (`apps/api/test_auth_gate.py`: 4 passed, `apps/api/test_evaluation.py`: 1 passed) ดูรายละเอียดใน [Verification](#verification) |
| **Integration Verification** | ยังติดข้อจำกัด (Blocked / Conditional) | `apps/api/test_pg_integration.py` ข้ามการทำงานหากไม่ตั้งค่า `ZYRQUEN_PG_INTEGRATION=1` และ Test PostgreSQL; PostgreSQL quota concurrency, Alembic upgrade/downgrade บน Test PostgreSQL จริง และ production-like HTTP/multi-user E2E ยังไม่มีผลยืนยันในเครื่องท้องถิ่น (ดู [`docs/operations/KNOWN_LIMITATIONS.md`](docs/operations/KNOWN_LIMITATIONS.md)) |
| **Production Deployment** | ยังไม่พร้อมและยังไม่ได้ Deploy | ยังไม่มี trained ZYRQUEN model weights, ยังไม่ได้ provision โครงสร้างพื้นฐาน Cloud / PostgreSQL / GPU / Monitoring / Alerting / Backup storage และห้ามระบุว่าเป็น Production Ready |

เอกสารอ้างอิงหลัก:
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — ขอบเขตสถาปัตยกรรมและสถานะการพัฒนาภาพรวม
- [`docs/PHASE_9_STATUS.md`](docs/PHASE_9_STATUS.md) — ขอบเขตและข้อจำกัดของ Phase 9.1–9.10
- [`docs/operations/KNOWN_LIMITATIONS.md`](docs/operations/KNOWN_LIMITATIONS.md) — รายการ blocker ของ Phase 6–7 และสิ่งที่ยังไม่ได้ตรวจ/ยังไม่ได้ตั้งค่า
- [`API_ACCESS.md`](API_ACCESS.md) — แนวทางการใช้งาน API keys สำหรับ server-to-server inference

---

## ภาพรวมสถาปัตยกรรม (Architecture at a Glance)

| ชั้นระบบ (Layer) | ตำแหน่งใน Repository | ขอบเขตการทำงานจริงในปัจจุบัน |
| --- | --- | --- |
| **Web Client (Next.js)** | `apps/web/` | Next.js App Router (`output: "standalone"`): หน้า `/` (Dashboard), `/login`, `/workspace`, `/training`, `/system`, `/settings` และ `/admin` โดยเรียก Backend ผ่าน server-side BFF/Proxy แบบ same-origin |
| **API Service (FastAPI)** | `apps/api/` | `apps/api/main.py` รวม 9 routers (`/auth`, `/v1/native-ai`, `/training`, `/v1/evaluation`, `/conversations`, `/users`, `/users/me/usage` & `/quota`, `/users/me/api-keys`, `/admin`) พร้อม `/livez`, `/readyz`, `/health`, structured JSON logging และ SQLAlchemy/Alembic guards |
| **Native Model Runtime** | `apps/core/` | `NativeRuntime`, `NativeModelLoader`, `NativeInferenceEngine`, `StreamingInferenceEngine` และโมดูล Phase 3 (`apps/core/native/`): ต้องมี model artifact ท้องถิ่นที่ `ZYRQUEN_MODEL_PATH` จึงจะประมวลผลได้ มิฉะนั้นจะทำงานในโหมด `not_configured` หรือ `degraded` |
| **Training Infrastructure** | `apps/core/training/`, `apps/core/training_infrastructure/` | `TrainingOrchestrator` (จำกัดขนาดบน CPU), `TrainingJobService` (single-process `ThreadPoolExecutor`), `CostController`, `CheckpointManager`, `TrainingMonitor`, `ModelValidator`, `ResourceManager`, `LocalProvider` และ `DistConfig` |
| **Intelligence Contracts (Phase 9)** | `apps/core/intelligence/` | ชั้นสัญญาซอฟต์แวร์สำหรับ Knowledge, Reasoning, Planning, Feedback, Tool Policy, Coding, Application Contracts, Capability Evaluation และ `IntelligenceRuntime` (ไม่เชื่อมต่อเป็น model reasoning engine) |
| **Local Containers & Ops** | `docker-compose.yml`, `apps/api/Dockerfile`, `apps/web/Dockerfile` | คอนฟิกสำหรับรันบนเครื่องท้องถิ่นหรือ single-host และสคริปต์ตรวจ backup (`scripts/verify_backup_integrity.py`) ไม่ใช่หลักฐานการ deploy จริงบน Cloud |

คำขอจากเบราว์เซอร์ทั้งหมดถูกส่งผ่าน same-origin Next.js proxy (`/api/backend/[...path]`, `/api/session`, `/api/logout`) ที่จำกัดเฉพาะเส้นทางใน allowlist (`apps/web/src/lib/backend-routes.ts`), ตรวจขนาด request body สูงสุด 64 KiB, ตรวจ `Origin` สำหรับคำขอที่มีผลเปลี่ยนแปลงข้อมูล และตรวจยืนยัน `X-Zyrquen-Expected-User-ID` กับ `GET /auth/me` ก่อนส่งต่อคำขอของผู้ใช้

---

## Intelligence Phase 9 และ Native Model

เพื่อไม่ให้เกิดความเข้าใจผิดระหว่าง **สัญญาซอฟต์แวร์ (Software Contracts)** กับ **ความสามารถจริงของโมเดล (Model Capability)** โครงการกำหนดขอบเขตไว้อย่างชัดเจนดังนี้:

1. **ขอบเขตของ Phase 9 (`apps/core/intelligence/`):**
   - มีโมดูลระดับสัญญาและการตรวจสอบสำหรับ **Knowledge** (`KnowledgeSystem` แบบ rule-based), **Reasoning** (`ReasoningEngine` + `contract.py`), **Planning** (`PlanningEngine` + `plan_contract.py` ที่ตรวจโครงสร้างแผนซึ่งผู้เรียกส่งมาเท่านั้น), **Feedback** (`feedback_contract.py`, `FeedbackLog`, `summarize`), **Tool Policy** (`ToolRegistry`, `tool_contract.py`, `PermissionGate`), **Coding** (`code_contract.py`, `ProgrammingLanguageRegistry`, `PythonSyntaxValidator` ด้วย `ast.parse`, `ExecutionSafetyPolicy`), **Application Contracts** (`application_contract.py`, `ProjectStructureRegistry`, `file_manifest_contract.py`, `DependencyDeclarationPolicy`, `WorkspaceBoundaryPolicy`, `BuildValidationInterface`) และ **Capability Evaluation** (`TestCaseRegistry`, `evaluate_capability`)
   - **Phase 9.10 (`IntelligenceRuntime` ใน `apps/core/intelligence/integration.py`)** เป็นเพียง **software-level integration** ที่เชื่อมสัญญาและตรวจ wiring ภายในด้วย probe (`validate_contracts()`) โดยบังคับค่า `model_inference=False`, `external_tools_called=False`, `code_executed=False`, `files_created=False` และ `model_weights_changed=False` เสมอ
   - **ยังไม่มีหลักฐานว่า Native Model สามารถเรียนรู้ ให้เหตุผล วางแผน เรียกใช้เครื่องมือ เขียนโค้ด หรือสร้างแอปพลิเคชันได้เอง** (ดูรายละเอียดทุกข้อจำกัดใน [`docs/PHASE_9_STATUS.md`](docs/PHASE_9_STATUS.md))
2. **สถานะจริงของ Native Model Training และ Inference:**
   - **Inference:** API ใช้ `NativeModelLoader` โหลดโมเดลจาก `ZYRQUEN_MODEL_PATH` (`local_files_only=True`, `trust_remote_code=False`) โดยไม่ fallback ไปยัง OpenAI, Gemini, Claude หรือผู้ให้บริการภายนอก หากไม่มี artifact หรือไม่มี `torch` API จะเปิดในโหมด `not_configured` หรือ `degraded` และปฏิเสธคำขอ inference ด้วย `503` นอกจากนี้คำขอ inference ยัง fail-closed หากบัญชีผู้ใช้ไม่มี active quota policy
   - **Training:** `apps/api/routers/training.py` (`POST /training/runs`, `GET /training/runs/{run_id}`, `GET /training/runs/{run_id}/telemetry`) จำกัดสิทธิ์เฉพาะอีเมลใน `ZYRQUEN_TRAINING_ADMIN_EMAILS` และต้องมี `ZYRQUEN_DATASET_DIR` (พร้อม `manifest.json` ที่ผ่านการตรวจ provenance), `ZYRQUEN_TOKENIZER_PATH`, `ZYRQUEN_TRAINING_ROOT` ที่เขียนได้ และ `torch` โดย `TrainingOrchestrator` จำกัดสเกลสำหรับ CPU (`MAX_CPU_MODEL_PARAMETERS = 5_000_000`, `MAX_CPU_SEQUENCE_LENGTH = 256`, `MAX_CPU_TRAINING_STEPS = 1_000`)
   - **Utility สำหรับทดสอบ Runtime:** `apps/core/download_model.py` มีไว้สำหรับดาวน์โหลด open-source base model (ค่าเริ่มต้น `Qwen/Qwen2.5-0.5B`) เพื่อทดสอบ runtime เท่านั้น ไม่ใช่โมเดลที่ ZYRQUEN ฝึกเอง
   - **บทบาทของ Tatoeba:** `data/processed/tatoeba-pilot-2026-11-20/pilot_en_th.jsonl` ที่อ้างอิงใน `apps/core/native/evaluation/engine.py` เป็นเพียง **dataset เริ่มต้น (pilot dataset)** ไม่ใช่จุดมุ่งหมายหลักหรือทิศทางระยะยาวของโครงการ

---

## Brand Assets และ Dashboard Integration

ไฟล์สินทรัพย์แบรนด์ทั้งหมดใน `apps/web/public/` เป็น vector SVG ที่ไม่มี bitmap, script หรือ external resource ฝังอยู่ (ตรวจสอบโดย `tests/test_branding_svgs.py`):

| รายการ | Color | Monochrome |
| --- | --- | --- |
| Animated lockup | [`zyrquen-logo.svg`](apps/web/public/zyrquen-logo.svg) | [`zyrquen-logo-mono.svg`](apps/web/public/zyrquen-logo-mono.svg) |
| Animated symbol | [`zyrquen-icon.svg`](apps/web/public/zyrquen-icon.svg) | [`zyrquen-icon-mono.svg`](apps/web/public/zyrquen-icon-mono.svg) |
| Wordmark | [`zyrquen-wordmark.svg`](apps/web/public/zyrquen-wordmark.svg) | [`zyrquen-wordmark-mono.svg`](apps/web/public/zyrquen-wordmark-mono.svg) |

หลักฐานการเชื่อมต่อกับ Web Client (`apps/web/`):
- **Dashboard และ Navigation (`apps/web/src/components/AppShell.tsx`):** ใช้ `/zyrquen-icon.svg` แสดงที่ brand lockup ของแถบด้านข้างและแถบด้านบนของหน้า auth
- **Login (`apps/web/src/app/login/page.tsx`):** ใช้ `/zyrquen-icon.svg` ในส่วนหัวของการ์ดเข้าสู่ระบบและสมัครสมาชิก
- **Browser Tab Icon (`apps/web/src/app/layout.tsx`):** กำหนด `icons: { icon: "/zyrquen-icon.svg" }`
- **Accessibility และ Color Modes:** ไฟล์แอนิเมชัน (`zyrquen-logo.svg`, `zyrquen-icon.svg`, `zyrquen-logo-mono.svg`, `zyrquen-icon-mono.svg`) ปิดการเคลื่อนไหวด้วย `@media (prefers-reduced-motion: reduce)` และไฟล์ `-mono.svg` ใช้ `currentColor` รองรับทั้ง `@media (prefers-color-scheme: dark)` และ `@media (forced-colors: active)`

---

## โครงสร้าง Repository ที่สำคัญ

- `apps/web/`: Next.js App Router frontend สำหรับ `/`, `/login`, `/workspace`, `/training`, `/system`, `/settings` และ `/admin` (หมายเหตุ: หน้า `/training` ในเว็บเป็นหน้าแสดงข้อมูลโมดูล Phase 3.3–3.4 และไม่สั่งรันหรือจำลองงานฝึกโมเดล; backend proxy allowlist ใน `apps/web/src/lib/backend-routes.ts` เปิดเฉพาะเส้นทางสุขภาพ, auth, users/me, api-keys, conversations, native-ai inference และ admin)
- `apps/api/`: FastAPI backend (`main.py`), routers, models/schemas, authentication/JWT revocation, persistent login rate limiting (`login_rate_limits`), usage & quota accounting, API access keys และ `admin_bootstrap.py`
- `apps/api/migrations/`: Alembic migrations (`20261120_01` ถึง `20261120_07`) ที่มี guard ป้องกันไม่ให้รันนอก Test PostgreSQL และไม่รันอัตโนมัติเมื่อ API เริ่มทำงาน
- `apps/core/`: Native runtime (`runtime.py`, `model_loader.py`, `inference.py`, `streaming.py`), native architecture/tokenizer/dataset/train/evaluation (`apps/core/native/`), training orchestration (`apps/core/training/`, `apps/core/training_infrastructure/`) และ Intelligence Phase 9 (`apps/core/intelligence/`)
- `tests/`: ชุดทดสอบ Phase 9 contracts, integration probe และ SVG branding assets
- `scripts/verify_backup_integrity.py`: สคริปต์ตรวจสอบความสมบูรณ์ของไฟล์สำรองข้อมูลและ checksum

---

## การติดตั้งและพัฒนาในเครื่องท้องถิ่น (Local Development)

> **ข้อกำหนดด้านความปลอดภัย:** ห้ามใส่ credentials จริงลงในเอกสาร, source control หรือฝั่งเบราว์เซอร์ ใช้ `.env.example` ที่ root เป็นรายการชื่อตัวแปรอ้างอิง และแทนค่าทุก `<placeholder>` เฉพาะในไฟล์ `.env` / `.env.local` ที่ไม่ถูกติดตามโดย Git

### 1. Web Client (`apps/web/`)

Root `package.json` จัดการ workspace (`apps/*`) และส่งต่อคำสั่งไปยัง `apps/web`:

```bash
npm install
npm run dev
```

- ในโหมดพัฒนา Web Server บนพอร์ต `3000` จะเชื่อมต่อไปยัง `http://localhost:8000` เป็นค่าเริ่มต้น (อ้างอิง `apps/web/src/lib/api-config.ts`)
- หากต้องการเปลี่ยนปลายทาง API ให้สร้างไฟล์ `apps/web/.env.local` (หมายเหตุ: Repository ไม่มีไฟล์ `apps/web/.env.example` มีเฉพาะ `.env.example` ที่ root) แล้วกำหนด:

```bash
ZYRQUEN_API_BASE_URL=http://localhost:8000
```

### 2. API Service (`apps/api/`) และ PostgreSQL Environment

ติดตั้ง Python dependencies จาก `apps/api/requirements.txt` และกำหนดตัวแปรสภาพแวดล้อมให้ตรงกับ PostgreSQL target ที่ได้รับอนุญาต (`apps/api/database_safety.py` ตรวจความตรงกันของ host, port, database name และปฏิเสธ SQLite นอก `ZYRQUEN_ENV=unit_test`):

```bash
python -m pip install -r apps/api/requirements.txt
export PYTHONPATH="$PWD:$PWD/apps/api"
export ZYRQUEN_ENV=development
export DATABASE_URL="postgresql+psycopg://<user>:<password>@<host>:<port>/<database>"
export ZYRQUEN_DEVELOPMENT_DATABASE_HOST="<host>"
export ZYRQUEN_DEVELOPMENT_DATABASE_PORT="<port>"
export ZYRQUEN_DEVELOPMENT_DATABASE_NAME="<database>"
export JWT_SECRET_KEY="<server-secret>"
uvicorn apps.api.main:app --reload
```

หมายเหตุเพิ่มเติม:
- `apps/api/requirements.txt` มี `tokenizers` และ `transformers` แต่ **ไม่รวม `torch`** หากต้องการโหลดโมเดลจริงหรือรัน test ที่ต้องใช้ PyTorch ต้องติดตั้ง `torch` แยก (เช่น CPU build ใน `.github/workflows/api-tests.yml`)
- เมื่อไม่มี model artifact ที่ `ZYRQUEN_MODEL_PATH` API ยังสามารถเริ่มต้นในโหมด degraded ได้ แต่ endpoint `/v1/native-ai/infer` และ `/v1/native-ai/infer/stream` จะคืนสถานะ `503`
- ดูรายการตัวแปรสภาพแวดล้อมทั้งหมดได้ที่ [`docs/operations/CONFIGURATION_REFERENCE.md`](docs/operations/CONFIGURATION_REFERENCE.md) และ [`.env.example`](.env.example)

### 3. Alembic Migrations (เฉพาะ Test PostgreSQL เท่านั้น)

`apps/api/migrations/env.py` บังคับให้ Alembic ทำงานเฉพาะเมื่อ `ZYRQUEN_ENV=test` และตรวจยืนยันตัวตนฐานข้อมูลจากตาราง `public.zyrquen_environment_identity` พร้อมตรวจไม่ให้ตรงกับรายการ `ZYRQUEN_PRODUCTION_DATABASE_HOSTS` / `ZYRQUEN_PRODUCTION_DATABASE_NAMES` ห้ามชี้คำสั่ง migration ไปยัง Production โดยเด็ดขาด:

```bash
export PYTHONPATH="$PWD:$PWD/apps/api"
export ZYRQUEN_ENV=test
export DATABASE_URL="postgresql+psycopg://<user>:<password>@<test-host>:<test-port>/<test-database>"
export ZYRQUEN_TEST_DATABASE_HOST="<test-host>"
export ZYRQUEN_TEST_DATABASE_PORT="<test-port>"
export ZYRQUEN_TEST_DATABASE_NAME="<test-database>"
export ZYRQUEN_TEST_DATABASE_ID="<test-database-id>"
export ZYRQUEN_PRODUCTION_DATABASE_HOSTS="<protected-prod-hosts>"
export ZYRQUEN_PRODUCTION_DATABASE_NAMES="<protected-prod-names>"
alembic -c apps/api/alembic.ini upgrade head
```

### 4. Docker Compose (Local Stack)

คัดลอกเทมเพลต `.env.example` ไปยัง `.env` ที่ root และระบุค่าที่จำเป็น (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `JWT_SECRET_KEY` และตัวแปรเสริมตาม `docker-compose.yml`) แล้วรัน:

```bash
cp .env.example .env
docker compose up --build
```

Stack นี้เปิดบริการ Web บนพอร์ต `3000`, API บนพอร์ต `8000` และ PostgreSQL 16 ภายใน Docker network โดยไม่ได้ติดตั้ง model weights หรือรัน Alembic migrations ให้อัตโนมัติ

### 5. Trusted Admin Bootstrap

ผู้ใช้ที่สมัครสมาชิกใหม่จะได้รับบทบาท `user` เสมอ การกำหนดสิทธิ์ `admin` ใช้บทบาทที่อ่านจากฐานข้อมูลเท่านั้น และ bootstrap ได้จากฝั่ง backend ด้วยรายการ user UUIDs ของบัญชีที่มีอยู่แล้วในฐานข้อมูล (ต้องกำหนดตัวแปรเชื่อมต่อฐานข้อมูลและ `ZYRQUEN_ENV` ให้ครบก่อนรัน):

```bash
export PYTHONPATH="$PWD:$PWD/apps/api"
export ZYRQUEN_ADMIN_USER_IDS="<user-uuid>[,<user-uuid>...]"
python -m apps.api.admin_bootstrap
```

คำสั่งจะล้มเหลวทันทีหาก `ZYRQUEN_ADMIN_USER_IDS` ว่างเปล่า รูปแบบ UUID ไม่ถูกต้อง หรือไม่พบ user ID ดังกล่าวในฐานข้อมูล

### 6. Login Proxy Configuration

ระบบจำกัดความถี่การเข้าสู่ระบบที่ผิดพลาด (`LOGIN_FAILURE_LIMIT = 5` ต่อหน้าต่าง 15 นาทีใน `apps/api/routers/auth.py`) โดยค่าเริ่มต้นจะใช้ direct peer IP และไม่เชื่อถือ `X-Forwarded-For` หากวาง API หลัง reverse proxy ให้กำหนด `ZYRQUEN_TRUSTED_PROXY_IPS` เป็นรายการ exact IP หรือ CIDR ของ proxy ที่เชื่อถือได้เท่านั้น เพื่อป้องกันการปลอมแปลง forwarded header

---

## Verification

### สถานะการทดสอบล่าสุดตามหลักฐาน (Git Commit `6f4b5bd`)

จากการแก้ไขและตรวจซ้ำใน commit `6f4b5bd`:
- `apps/api/test_auth_gate.py`: **4 passed** (ครอบคลุมการตรวจสิทธิ์ routes, การเพิกถอน token เมื่อ logout, token หมดอายุ/บัญชีถูกระงับ และ multi-user isolation กับ `TrainingRun` / `EvaluationRun`)
- `apps/api/test_evaluation.py`: **1 passed** (ตรวจ `POST /v1/evaluation/runs` เมื่อไม่ยืนยันตัวตนต้องคืน `401`)

คำสั่งสำหรับรัน targeted tests ชุดดังกล่าว:

```bash
PYTHONPATH="$PWD:$PWD/apps/api" \
PYTHON_DOTENV_DISABLED=1 \
DATABASE_URL="sqlite:///./test.db" \
ZYRQUEN_ENV=unit_test \
JWT_SECRET_KEY="<test-secret>" \
python -m pytest -v apps/api/test_auth_gate.py apps/api/test_evaluation.py
```

**ข้อควรระวังในการตีความผล:**
- ผลข้างต้นเป็น **targeted tests ที่ผ่านหลังการแก้ไข** ไม่ใช่หลักฐานว่า Full Repository Test Suite ผ่านทั้งหมด
- ในโครงสร้างไฟล์ปัจจุบัน `apps/core/native/test_evaluation.py` ยังอ้างอิง `from apps.core.native.evaluation import EvaluationEngine` ซึ่งถูกแพ็กเกจ `apps/core/native/evaluation/__init__.py` บังชื่อไฟล์ `apps/core/native/evaluation.py` อยู่ จึงยังไม่สามารถสรุปว่าชุดทดสอบทั้งหมดของ repository ผ่านพร้อมกันโดยไม่มีข้อผิดพลาด

### ชุดคำสั่งตรวจสอบใน Repository

1. **Phase 9 Contract Suite และ SVG Brand Assets:**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD:$PWD/apps/api" pytest -q tests
```

2. **Web Tests และ Static Checks (รันจาก repository root):**

```bash
npm run test
npm run typecheck
npm run lint
npm run build
```

สำหรับ Playwright E2E tests (`apps/web/e2e/platform.spec.ts`):

```bash
npx playwright install chromium
npm run test:e2e --workspace=apps/web
```

3. **API และ Native Core Python Tests (รันด้วย SQLite ในโหมด `unit_test`):**

```bash
PYTHONPATH="$PWD:$PWD/apps/api" \
PYTHON_DOTENV_DISABLED=1 \
DATABASE_URL="sqlite:///./test.db" \
ZYRQUEN_ENV=unit_test \
JWT_SECRET_KEY="<test-secret>" \
python -m pytest -v apps/api apps/core/test_*.py apps/core/native \
  apps/core/training_infrastructure apps/core/training
```

หมายเหตุ: `apps/api/test_pg_integration.py` จะถูกข้ามเมื่อไม่ได้ตั้งค่า `ZYRQUEN_PG_INTEGRATION=1` และ `apps/core/native/test_model.py` / `apps/core/native/test_train_torch.py` จะถูกข้ามเมื่อไม่ได้ติดตั้ง `torch`

4. **PostgreSQL Integration Tests (เฉพาะ Test PostgreSQL ที่ยืนยันตัวตนแล้วเท่านั้น):**

```bash
PYTHONPATH="$PWD:$PWD/apps/api" \
PYTHON_DOTENV_DISABLED=1 \
ZYRQUEN_PG_INTEGRATION=1 \
ZYRQUEN_ENV=test \
DATABASE_URL="postgresql+psycopg://<user>:<password>@<test-host>:<test-port>/<test-database>" \
ZYRQUEN_TEST_DATABASE_HOST="<test-host>" \
ZYRQUEN_TEST_DATABASE_PORT="<test-port>" \
ZYRQUEN_TEST_DATABASE_NAME="<test-database>" \
ZYRQUEN_TEST_DATABASE_ID="<test-database-id>" \
ZYRQUEN_PRODUCTION_DATABASE_HOSTS="<protected-prod-hosts>" \
ZYRQUEN_PRODUCTION_DATABASE_NAMES="<protected-prod-names>" \
JWT_SECRET_KEY="<test-secret>" \
python -m pytest -v apps/api/test_pg_integration.py
```

---

## Production Operations และข้อจำกัดที่ยังเปิดอยู่

Repository มีเอกสารแนวทางปฏิบัติการและการตรวจสุขภาพระบบใน `docs/operations/` ดังนี้:
- [`docs/operations/PRODUCTION_OPERATIONS.md`](docs/operations/PRODUCTION_OPERATIONS.md)
- [`docs/operations/DEPLOYMENT_READINESS.md`](docs/operations/DEPLOYMENT_READINESS.md)
- [`docs/operations/HEALTH_READINESS.md`](docs/operations/HEALTH_READINESS.md)
- [`docs/operations/LOGGING_MONITORING.md`](docs/operations/LOGGING_MONITORING.md)
- [`docs/operations/BACKUP_RECOVERY_RUNBOOK.md`](docs/operations/BACKUP_RECOVERY_RUNBOOK.md)
- [`docs/operations/INCIDENT_RESPONSE_RUNBOOK.md`](docs/operations/INCIDENT_RESPONSE_RUNBOOK.md)
- [`docs/operations/CONFIGURATION_REFERENCE.md`](docs/operations/CONFIGURATION_REFERENCE.md)
- [`docs/operations/SECURITY_OPERATIONS_CHECKLIST.md`](docs/operations/SECURITY_OPERATIONS_CHECKLIST.md)
- [`docs/operations/KNOWN_LIMITATIONS.md`](docs/operations/KNOWN_LIMITATIONS.md)

Operational Endpoints ที่เปิดใช้งานใน `apps/api/main.py`:
- `GET /livez`: ตรวจ process liveness เท่านั้น ไม่เชื่อมต่อ database และไม่ตรวจ model
- `GET /readyz`: ตรวจความพร้อมของ database (`SELECT 1` และ identity verification ในโหมด `test`) ร่วมกับสถานะจริงของ native runtime (`ready`, `degraded` หรือ `not_configured`) โดยไม่สร้างสถานะเท็จ
- `GET /health`: aggregate health endpoint แบบ backward-compatible พร้อมสถานะของ `database` และ `native_ai`

รายการ Blocker ที่ยังต้องปิดก่อนจึงจะพิจารณา Production Readiness ได้:
1. การทดสอบ **PostgreSQL quota concurrency** บนฐานข้อมูล PostgreSQL จริง
2. การทดสอบ **Alembic migration execution** (upgrade/downgrade) บน Test PostgreSQL ที่ยืนยันตัวตนแล้ว
3. การทดสอบ **production-like HTTP E2E และ multi-user** ครบวงจร

ดูแผนงานระยะยาวเพิ่มเติมได้ที่ [`docs/roadmap/01_ZYRQUEN_Roadmap.md`](docs/roadmap/01_ZYRQUEN_Roadmap.md), [`docs/roadmap/02_Phase3_Native_AI_Architecture.md`](docs/roadmap/02_Phase3_Native_AI_Architecture.md) และ snapshot ประวัติศาสตร์ใน [`docs/NEXT_STEPS_STATUS.md`](docs/NEXT_STEPS_STATUS.md)
