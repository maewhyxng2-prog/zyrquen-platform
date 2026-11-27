# ZYRQUEN Ω∞

![ZYRQUEN logo](public/zyrquen-logo.svg)

ZYRQUEN Ω∞ เป็นโครงการวิจัยและวิศวกรรมเพื่อพัฒนาแพลตฟอร์ม AI และระบบ **Native General Intelligence (NGI)** ที่ทำงานบนโครงสร้างพื้นฐานอิสระ (ไม่ใช่ Chatbot-only และไม่นำโมเดลภายนอกมาควบคุมหลัก)

> **ข้อเท็จจริงสำคัญของสถานะปัจจุบัน:**
> - **Native Model Weights:** Repository ปัจจุบัน **ไม่มี trained model weights ของ ZYRQUEN เอง** (`v7`/`v8` `FROZEN`, `v9` `CLOSED_FAIL`, `v10` `V10-D BLOCKED`)
> - **No Fake Results / Fail-Closed:** ไม่มีการสร้างคะแนนประเมินจำลอง และระบบ Production ปฏิเสธการทำงานแบบ Fail-Closed (`503`) เมื่อไม่มีรันไทม์จริง
> - **Deployment Verdict:** **ยังไม่พร้อม Merge/Deploy สู่ Production** (ยังขาด PyTorch runtime/trained weights, FastAPI pytest environment, Next.js production build check และ Git/backup metadata ในสภาพแวดล้อมปัจจุบัน)

---

## 1. สถาปัตยกรรมเว็บและ Backend ตามโค้ดจริง

Repository มีส่วนติดต่อผู้ใช้และ Backend ทำงานอยู่ **2 ชุด** ที่ต้องแยกออกจากกันให้ชัดเจน:

1. **Root Workspace App (`src/` + `server.ts`, พอร์ต `3000`):**
   - Frontend แบบ Vite + React SPA ให้บริการผ่าน Express (`server.ts`)
   - Backend หลักเรียก `python_core/worker.py` (`zyrquen_core.py`, `db_bridge.py`, SQLite, `python_core/tool_center/`) และมี `server_fallback.ts` เฉพาะกรณีที่ไม่พบ `python3`
   - รองรับ Workflow Orchestration, `/api/v1/workflows/logs`, `/api/tool-center/execute`, Multi-file App Builder และ RestoreProof
2. **Next.js App Workspace (`apps/web/`) และ FastAPI Service (`apps/api/`):**
   - `apps/web/` (Next.js App Router) ส่งคำขอผ่าน Proxy ไปยัง FastAPI (`apps/api/`) ตามค่า `ZYRQUEN_API_BASE_URL`
   - **ข้อเท็จจริงเกี่ยวกับ Fallback:** `apps/web/` ไม่ได้เชื่อม FastAPI เพียงอย่างเดียวในโหมดพัฒนา — หากไม่ได้ตั้งค่า External URL (`ZYRQUEN_API_BASE_URL`) และไม่พบ FastAPI บนเครื่องในโหมด **non-production**, [`apps/web/src/lib/in-memory-backend.ts`](apps/web/src/lib/in-memory-backend.ts) จะทำงานเป็นตัวจำลอง In-Memory ชั่วคราว; ส่วนในโหมด **Production** จะ Fail-Closed (`503`) ทันทีเมื่อ Backend ไม่พร้อม
   - เส้นทาง `/training` ใน `apps/web/` Redirect ไปยัง `/developer/console` (ซึ่งเป็นที่ตั้งของ `WorkflowConsole`, `WorkflowLogsPanel` และ `TrainingPipelinePanel`)

---

## 2. ความสามารถใหม่: Multi-file App Builder และ Orchestration Logs Console

### 2.1 Multi-file Persistent App Builder & Real Build Runner (`python_core/tool_center/`)
- **โมดูลหลัก:** [`python_core/tool_center/app_builder.py`](python_core/tool_center/app_builder.py), [`sandbox.py`](python_core/tool_center/sandbox.py), [`software_engineering.py`](python_core/tool_center/software_engineering.py), [`toolkits/development.py`](python_core/tool_center/toolkits/development.py)
- **ความสามารถจริง:**
  - สร้างและแก้ไขโปรเจกต์หลายไฟล์ (`python_cli_app`, `python_service_app`, `python_data_app`, `files`, `patches`, `delete_files`)
  - **Persistent Workspace & History:** เก็บไฟล์ถาวรใต้ `DATA_DIR/sandbox_workspaces/<workspace>` พร้อมระบบ Snapshot, Unified Diff, `read_file` และ Atomic Rollback ใน `.zyrquen_history/`
  - **Isolated Sandbox:** รันโค้ดและชุดทดสอบผ่าน `python -I` ใน Temp directory ที่ตัด Environment variables, จำกัดทรัพยากร OS (`rlimit`), และตรวจ AST Policy ห้ามนำเข้า External LLM หรือโมดูลอันตราย (`subprocess`, `os`, `socket`, `eval`, `open` ฯลฯ)
  - **Real Build Runner:** ตรวจจริง 3 ด่าน (`python -I -m compileall -q .` + AST/Policy/Secret Lint + `python -I -m unittest discover`) โดยจะ **ไม่รายงาน `VERIFIED`** หากด่านใดไม่ผ่านหรือ `tests_run == 0`
  - **Path Confinement:** ป้องกัน `../`, `\`, Null bytes (`\x00`), Absolute path, Symlink escape และห้ามอ่าน/แก้ไข `.zyrquen_history/` หรือ `.git/`

### 2.2 Orchestration Logs Console
- **Endpoint & UI:**
  - Backend FastAPI: `GET /v1/workflows/logs` ([`apps/api/routers/workflows.py`](apps/api/routers/workflows.py))
  - Next.js Proxy & In-Memory Adapter: `GET /api/v1/workflows/logs` ([`apps/web/src/app/api/v1/workflows/logs/route.ts`](apps/web/src/app/api/v1/workflows/logs/route.ts), [`in-memory-backend.ts`](apps/web/src/lib/in-memory-backend.ts))
  - Root Express Server: `GET /api/v1/workflows/logs` และ `GET /api/workflows/logs` ([`server.ts`](server.ts))
  - UI Component: [`apps/web/src/components/WorkflowLogsPanel.tsx`](apps/web/src/components/WorkflowLogsPanel.tsx) แสดงผลบนหน้า `/developer/console`
- **กติกา HTTP Status และ Workflow Isolation:**
  - `401 Unauthorized`: เมื่อยังไม่ได้ยืนยันตัวตน
  - `200 OK`: เมื่อยืนยันตัวตนแล้วและยังไม่มี Log หรือ Workflow Run ของผู้ใช้ จะคืนค่า `{ items: [], active_runs: [] }` (**ไม่คืน `403`**)
  - `403 Forbidden`: เมื่อผู้ใช้ทั่วไป (`user`) ระบุ `run_id` ของผู้ใช้อื่น
  - `400 Bad Request`: เมื่อรูปแบบ `run_id` ไม่ผ่านการตรวจสอบ (`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)
  - `404 Not Found`: เมื่อไม่พบ `run_id` ที่ร้องขอ

---

## 3. เส้นทางพัฒนา Native Model (`v7`–`v16+`) vs โครงสร้าง Phase 11–20

> **คำชี้แจงเพื่อไม่ให้ข้อมูลขัดแย้งกัน:**
> - **`Phase 11–20` (`phases/phase11.py`–`phase20.py`)** คือโมดูลโครงสร้าง/สัญญาเชิงสถาปัตยกรรม (Scaffolding Modules) ใน Python — ไม่ใช่การฝึกโมเดล PyTorch จริง
> - **`Native Model v11 / v12` (`docs/v12/README.md`)** ยังคงสถานะ **`BLUEPRINT ONLY — LOCKED`** จนกว่า `V10-D` Runtime Closure (PyTorch training + artifact verification) จะผ่านจริง

### 3.1 สถานะ Native Model Versions
| รุ่น | หัวข้อพัฒนา | สถานะปัจจุบัน | น้ำหนักโมเดล (Trained Weights) | เอกสารอ้างอิง |
| :--- | :--- | :--- | :--- | :--- |
| **v7** | Baseline Foundation (`TinyNGI` 2-layer LSTM) | `FROZEN` | ไม่มีใน Repository | `tools/train_nagi_500_v7.py` |
| **v8** | Attention + Pointer-Copy (`BiGRU + Bahdanau + p_gen`) | `FROZEN` | ไม่มีใน Repository | [`docs/V8_SUMMARY.md`](docs/V8_SUMMARY.md), [`docs/V8_EXPERIMENT_CLOSURE_REPORT.md`](docs/V8_EXPERIMENT_CLOSURE_REPORT.md) |
| **v9** | Generalization — Unseen Entity & OOD Template | **`CLOSED_FAIL`** | ไม่มี checkpoint ใน Repository | [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](docs/V9_EXPERIMENT_CLOSURE_REPORT.md) |
| **v10** | Relational & Multi-step Reasoning | **Static Contracts Pass; `V10-D` Runtime `BLOCKED`** | ไม่มีใน Repository | [`docs/v10/V10_CLOSURE_STATUS.md`](docs/v10/V10_CLOSURE_STATUS.md) |
| **v11** | Knowledge Integration | **`BLUEPRINT ONLY — LOCKED`** (รอ V10 closure) | ไม่มี | [`docs/PHASE_17_SPEC.md`](docs/PHASE_17_SPEC.md) *(หมายเหตุ: ไม่มีโฟลเดอร์ `docs/v11/` ใน Repo)* |
| **v12** | Adaptive Learning | **`BLUEPRINT ONLY — LOCKED`** (รอ V10/V11) | ไม่มี | [`docs/v12/README.md`](docs/v12/README.md) |
| **v13–v16+** | Planning, Verification, Autonomous NGI | แผนระยะยาว | ไม่มี | [`docs/PHASE_16_SPEC.md`](docs/PHASE_16_SPEC.md), [`docs/PHASE_19_SPEC.md`](docs/PHASE_19_SPEC.md), [`docs/PHASE_20_SPEC.md`](docs/PHASE_20_SPEC.md) |

### 3.2 สถานะ Phase 11–20 Scaffolding Modules (แยก Code / Blueprint / Tested / CI Verified)
*(คงขอบเขตเดิมที่ Phase 20 เป็น Phase สุดท้าย และไม่สร้าง Phase 21 เพิ่ม)*

| Phase | Code Done | Blueprint | Tested (สภาพแวดล้อมปัจจุบัน) | CI Verified |
| :--- | :--- | :--- | :--- | :--- |
| 11 Workspace Intelligence (`phases/phase11.py`) | `CODE DONE` | [`docs/PHASE_11_SPEC.md`](docs/PHASE_11_SPEC.md) | **`NOT RUN / BLOCKED`** (`tests_phases/test_phase11.py` ใช้รูปแบบ `pytest`; ไม่มี `pytest` ในเครื่อง) | `NOT VERIFIED` |
| 12 Native Intelligence Foundation (`phases/phase12.py`) | `CODE DONE` | [`docs/PHASE_12_SPEC.md`](docs/PHASE_12_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 13 Knowledge & Data Pipeline (`phases/phase13.py`) | `CODE DONE` | [`docs/PHASE_13_SPEC.md`](docs/PHASE_13_SPEC.md) | **`PASS`** (`6 passed` via `python3 -m unittest`) | `NOT VERIFIED` |
| 14 Evaluation & Capability Measurement (`phases/phase14.py`) | `CODE DONE` | [`docs/PHASE_14_SPEC.md`](docs/PHASE_14_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 15 Native Model Readiness (`phases/phase15.py`) | `CODE DONE` | [`docs/PHASE_15_SPEC.md`](docs/PHASE_15_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 16 Native Reasoning & Planning (`phases/phase16.py`) | `CODE DONE` | [`docs/PHASE_16_SPEC.md`](docs/PHASE_16_SPEC.md) | **`PASS`** (`6 passed` via `python3 -m unittest`) | `NOT VERIFIED` |
| 17 Memory & Knowledge Integration (`phases/phase17.py`) | `CODE DONE` | [`docs/PHASE_17_SPEC.md`](docs/PHASE_17_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 18 Adaptive Learning & Improvement (`phases/phase18.py`) | `CODE DONE` | [`docs/PHASE_18_SPEC.md`](docs/PHASE_18_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 19 Autonomous Capability & Safety Governance (`phases/phase19.py`) | `CODE DONE` | [`docs/PHASE_19_SPEC.md`](docs/PHASE_19_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |
| 20 Native Intelligence System Maturity (`phases/phase20.py`) | `CODE DONE` | [`docs/PHASE_20_SPEC.md`](docs/PHASE_20_SPEC.md) | **`NOT RUN / BLOCKED`** (ต้องใช้ `pytest`) | `NOT VERIFIED` |

*(หมายเหตุ: ตัวเลข `60/60 PASSED` ใน [`docs/PHASES_11_20_INDEX.md`](docs/PHASES_11_20_INDEX.md) เป็นผลรันในเครื่องพัฒนาเดิมก่อนการแก้ไขล่าสุด ไม่ใช่ผลยืนยันบน Commit/Workspace ปัจจุบัน และ CI Gate `44893016007` เป็นของ Phase 10.9.9 SHA `466b58a75419708a86469f59a903e322d85081d2` ไม่ครอบคลุมงาน Logs Console และ Multi-file App Builder)*

---

## 4. สถานะผลทดสอบจริงบน Workspace ปัจจุบัน (แยก `PASS` / `FAIL` / `BLOCKED` / `NOT RUN`)

ห้ามนำผลทดสอบจาก Commit เก่ามารวมกับผลบน Workspace ล่าสุด:

| ชุดทดสอบ / การตรวจสอบ | สถานะ | ผลที่วัดได้จริงบน Workspace ปัจจุบัน |
| :--- | :--- | :--- |
| **Root Vitest + Express E2E** (`npm run test`) | **`PASS`** | 6/6 ไฟล์, 50/50 tests ผ่าน (รวม `/api/v1/workflows/logs` `401`/`200` empty/`403`/`400`/`404` และ App Builder E2E) |
| **Root TypeScript Check** (`npm run typecheck`) | **`PASS`** | 0 errors |
| **Root ESLint** (`npm run lint`) | **`PASS`** | 0 errors (มี React `exhaustive-deps` warnings 8 จุด) |
| **Root Vite Build** (`npm run build`) | **`PASS`** | สร้าง `dist/` สำเร็จ |
| **Next.js Lib Vitest** (`npx vitest run --root apps/web --config vitest.config.mts`) | **`PASS`** | 14/14 ไฟล์, 47/47 tests ผ่าน (รวม `workflow-logs.test.ts` `401`/`200` empty/`403`/`400`/`404`) |
| **Python App Builder & Tool Center** (`python3 -m unittest python_core/tests/test_app_builder_e2e.py python_core/tests/test_tool_center.py -v`) | **`PASS`** | 24/24 tests ผ่าน (9 tests ใน `test_app_builder_e2e.py` + 15 tests ใน `test_tool_center.py` รวม path traversal/symlink/sandbox) |
| **Pure-Python Native Runtime** (`python3 -m apps.core.test_native_runtime`) | **`PASS` (Partial Skip)** | `passed=14`, `skipped_no_runtime_deps=6` (ไม่มี `torch`) |
| **Phase 13 & 16 Unittest** (`tests_phases/test_phase13.py`, `test_phase16.py`) | **`PASS`** | 12/12 tests ผ่านผ่าน `unittest` |
| **Branding SVG Tests** (`python3 tests/test_branding_svgs.py`) | **`FAIL`** | ล้มเหลว 2 จุด (`polygon` ใน `apps/web/public/zyrquen-logo.svg` และ `zyrquen-icon.svg` ไม่อยู่ใน `ALLOWED_ELEMENTS`) |
| **Python `tests/` Discovery** (`python3 -m unittest discover -s tests -p "test_*.py"`) | **`FAIL`** | รัน 285 tests: `failures=2` (SVG), `errors=5` (ขาด `fastapi`, `sqlalchemy` และ `STRICT_BLOCK_SIZE`/`resolve_amp_dtype`), `skipped=5` |
| **FastAPI `pytest` (`apps/api/`)** | **`BLOCKED / NOT RUN`** | ไม่มี `pytest`, `fastapi`, `sqlalchemy` และ `pip` ใน Container ปัจจุบัน (รวม `apps/api/test_workflow_logs.py` ที่เพิ่มใหม่) |
| **Next.js `tsc --noEmit`, `next build`, Playwright E2E (`apps/web/`)** | **`BLOCKED / NOT RUN`** | ไม่มี `apps/web/node_modules` (`next` และ `@playwright/test` ยังไม่ถูกติดตั้ง) |
| **Phase 11, 12, 14, 15, 17–20 Tests (`tests_phases/`)** | **`BLOCKED / NOT RUN`** | ใช้รูปแบบ `pytest` functions; ไม่สามารถรันด้วย `unittest` และไม่มี `pytest` ในเครื่อง |
| **Git Diff / Branch / Backup Verification** | **`BLOCKED / NOT RUN`** | ไม่มี `.git` และไม่พบ `/tmp/zyrquen_backups/20261127_095257/` ใน Container จึงยังไม่สามารถยืนยัน Git branch/diff หรือเทียบไฟล์สำรองได้ |

---

## 5. เอกสารอ้างอิงหลัก

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — สถาปัตยกรรมและขอบเขตระบบ
- [`API_ACCESS.md`](API_ACCESS.md) — การใช้งาน API Key และ Native Inference Endpoint
- [`apps/web/README.md`](apps/web/README.md) — รายละเอียด Next.js Workspace
- [`docs/V8_SUMMARY.md`](docs/V8_SUMMARY.md) & [`docs/V8_EXPERIMENT_CLOSURE_REPORT.md`](docs/V8_EXPERIMENT_CLOSURE_REPORT.md) — สรุปการปิดการทดลอง `v8`
- [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](docs/V9_EXPERIMENT_CLOSURE_REPORT.md) — ผลทดลองจริง `v9` และข้อสรุป `CLOSED_FAIL`
- [`docs/v10/V10_CLOSURE_STATUS.md`](docs/v10/V10_CLOSURE_STATUS.md) & [`docs/v12/README.md`](docs/v12/README.md) — สถานะ `V10-D BLOCKED` และ Blueprint `v12` ที่ยัง `LOCKED`
- [`docs/PHASES_11_20_INDEX.md`](docs/PHASES_11_20_INDEX.md) & [`docs/engineering/ZYRQUEN_PHASE_READINESS.md`](docs/engineering/ZYRQUEN_PHASE_READINESS.md) — ดัชนีและสถานะความพร้อม
