# ZYRQUEN Ω∞

![ZYRQUEN logo](apps/web/public/zyrquen-logo.svg)

ZYRQUEN Ω∞ เป็นโครงการวิจัยและวิศวกรรมระยะยาวเพื่อพัฒนาแพลตฟอร์ม AI และระบบ **Native General Intelligence (NGI)** ที่เรียนรู้ ให้เหตุผล วางแผน ตรวจสอบ และพัฒนาความสามารถได้ด้วยตนเองบนโครงสร้างพื้นฐานอิสระ (ไม่ใช่ Chatbot-only และไม่นำโมเดลภายนอกมาควบคุมหลัก)

> **ข้อเท็จจริงสำคัญของสถานะปัจจุบัน:** Repository ปัจจุบันยัง **ไม่มี trained model weights ของ ZYRQUEN เอง**, **ไม่มีข้อมูล Mock/จำลองคะแนนที่ไม่มีอยู่จริง**, และ **ยังไม่ผ่านการรับรอง Production Deployment**

---

## สถานะตามหลักฐานใน Repository

| ระดับหลักฐาน | สถานะปัจจุบัน | รายละเอียดที่ตรวจสอบได้จริง |
| :--- | :--- | :--- |
| **Implementation** | มีโค้ดต้นฉบับใน Repository | Web Client (`apps/web/`), FastAPI Service (`apps/api/`), Native Runtime / Tokenizer / Model / Dataset / Training (`apps/core/`), Legacy Intelligence Phase 9 (`apps/core/intelligence/`), Phase 11–20 (`phases/phase11.py`–`phases/phase20.py`), Alembic Migrations (`apps/api/migrations/`), และ Experiment Scripts (`tools/train_nagi_500_v7.py`, `tools/train_nagi_500_v8.py`, `tools/eval_nagi_500_v8.py`) |
| **Phase 11–20 Unit Tests** | **Local Final Gate 11–20: `60 / 60 PASSED`** | `tests_phases/test_phase11.py`–`tests_phases/test_phase20.py` (แต่ละ Phase `6 passed`, ไม่สร้าง Phase 21 เพิ่ม) |
| **Integration Verification** | **Phase 10.9.9 Gate: `PASSED / CLOSED`** | CI Run `44893016007`, SHA `466b58a75419708a86469f59a903e322d85081d2`, 4/4 `web / docker / test / postgres-integration` |
| **GitHub CI สำหรับ 11–20** | **ยังไม่ยืนยัน** | ห้ามอ้างว่า CI 4/4 สำหรับ Phase 11–20 ผ่านจนกว่าจะเห็น Workflow 4 Jobs สำเร็จบน Commit SHA เดียวกัน |
| **Native Model `v8` Experiment** | **ปิดการทดลองแล้ว (`FROZEN`)** | รายละเอียดโค้ดและข้อจำกัดบันทึกใน [`docs/V8_SUMMARY.md`](docs/V8_SUMMARY.md) และ [`docs/V8_EXPERIMENT_CLOSURE_REPORT.md`](docs/V8_EXPERIMENT_CLOSURE_REPORT.md) *(ตัวเลขรันไทม์จริงจาก Codespaces ยังสถานะ `BLOCKED IN WORKSPACE` จนกว่าจะแนบ `report.json`)* |
| **Native Model `v9` Experiment** | **`CLOSED_FAIL` (runtime + evaluation completed)** | arm_d ฝึกและประเมินบน Colab จริง; test_unseen FG 29.2%, test_ood FG 9.2%, unseen copy 27.7%; ไม่ผ่าน generalization / planning / conflict / stability gates. หลักฐานสรุป: [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](docs/V9_EXPERIMENT_CLOSURE_REPORT.md) *(ไฟล์ report/checkpoint ต้นฉบับยังอยู่นอก GitHub)* |
| **Production Deployment** | ยังไม่พร้อมและยังไม่ได้ Deploy | ยังไม่มี trained ZYRQUEN model weights และยังไม่ได้ provision Cloud / PostgreSQL / GPU / Monitoring / Backup |

---

## เส้นทางพัฒนา Native Model สู่ NGI (Capability-Driven Progression)

การพัฒนาโมเดลเดินตามความสามารถจริงที่ทดสอบได้ (ไม่เพิ่มรุ่นเพียงเพื่อไล่เลขเวอร์ชัน และคง Roadmap **Phase 11–20** เดิมโดยไม่สร้าง Phase 21 เพิ่ม):

| รุ่น | หัวข้อพัฒนา | สถานะปัจจุบัน | เอกสารอ้างอิง |
| :--- | :--- | :--- | :--- |
| **v7** | Baseline Foundation (`TinyNGI` 2-layer LSTM) | ผ่านการทดลองฐาน (`FROZEN`) | `tools/train_nagi_500_v7.py` |
| **v8** | Attention + Pointer-Copy (`BiGRU + Bahdanau + p_gen`) | ปิดการทดลองแล้ว (`FROZEN`) | [`docs/V8_SUMMARY.md`](docs/V8_SUMMARY.md), [`docs/V8_EXPERIMENT_CLOSURE_REPORT.md`](docs/V8_EXPERIMENT_CLOSURE_REPORT.md) |
| **v9** | **Generalization** — Unseen Entity & OOD Template | **`CLOSED_FAIL` — retained as measured baseline** | [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](docs/V9_EXPERIMENT_CLOSURE_REPORT.md) |
| **v10** | Relational & Multi-step Reasoning | **Preparation only; V10-D runtime closure BLOCKED** | [`docs/v10/V10_CLOSURE_STATUS.md`](docs/v10/V10_CLOSURE_STATUS.md) |
| **v11** | Knowledge Integration | **BLUEPRINT ONLY — LOCKED until V10 runtime closure PASS** | [`docs/v11/README.md`](docs/v11/README.md) |
| **v12** | Adaptive Learning | **BLUEPRINT ONLY — LOCKED until V10 and V11 gates PASS** | [`docs/v12/README.md`](docs/v12/README.md) |
| **v13** | Planning & Decomposition | แผนขั้นถัดไป | [`docs/PHASE_16_SPEC.md`](docs/PHASE_16_SPEC.md) |
| **v14** | Verification & Self-Correction | แผนขั้นถัดไป | [`docs/V9_BLUEPRINT.md`](docs/V9_BLUEPRINT.md) |
| **v15** | Autonomous Capability | แผนขั้นถัดไป | [`docs/PHASE_19_SPEC.md`](docs/PHASE_19_SPEC.md) |
| **v16+** | Integrated Native Intelligence → **ZYRQUEN Ω∞ — NGI** | เป้าหมายระยะยาว | [`docs/PHASE_20_SPEC.md`](docs/PHASE_20_SPEC.md), [`docs/SCALING_POLICY.md`](docs/SCALING_POLICY.md) |

---

## เว็บแพลตฟอร์มและกฎความซื่อสัตย์ของข้อมูล (No Mock / Fail-Closed)

ส่วนติดต่อเว็บใน [`apps/web/`](apps/web/README.md) เชื่อมต่อกับ FastAPI Backend เท่านั้น โดยไม่ใช้ Mock Backend หรือสร้างผลประเมินจำลอง:

- **Version Indicator (Topbar & PageHeader):** แสดงเวอร์ชันที่ได้รับจาก Endpoint `/v1/native-ai/health` ของ Backend จริงเท่านั้น และแจ้ง `ยังไม่ระบุรุ่นจาก Backend` หรือ `ไม่ทราบรุ่น (Backend ไม่พร้อม)` เมื่อไม่มีข้อมูลจริง
- **Dashboard (`/`):** แสดงความพร้อมบริการ API/Runtime พร้อมส่วน **ตัวชี้วัดความก้าวหน้า ZYRQUEN Ω∞** (`Generalization Score` และ `Relational Reasoning Success Rate`) จาก Backend — หากยังไม่มีผลประเมินจริงจะไม่แสดงตัวเลขหรือแถบความคืบหน้าปลอม
- **Training Workspace (`/training`):** แสดงโมดูล Core (`apps/core/native/dataset.py`, `train.py`) ร่วมกับ **Capability Radar Chart (Recharts)** ซึ่งจะวาดกราฟเฉพาะเมื่อ Backend ส่งผลคะแนนความสามารถที่วัดผลจริงกลับมาเท่านั้น หากไม่มีจะแจ้งสถานะไม่มีข้อมูลจริง
- **Branding SVG Assets (`apps/web/public/*.svg`):** ชุดเวกเตอร์ Color และ Monochrome รองรับ `prefers-reduced-motion` และผ่านเกณฑ์โครงสร้างตาม `tests/test_branding_svgs.py`

---

## ZYRQUEN — Phase 11–20 (CLOSED)

| Phase | สถานะ | Commit | ผล Local |
| :--- | :--- | :--- | :--- |
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

**กติกาที่ยึดไว้ตลอดโครงการ:** ห้ามปลอมผลประเมิน, ห้ามใช้ Mock Runtime แทนโมเดลจริง, ไม่เอาโมเดลภายนอกมาควบคุมหลัก, ไม่แก้ไฟล์ `v7`/`v8` ที่ปิดแล้ว, แยกสถานะ `PASS / FAIL / BLOCKED / NOT RUN` ชัดเจน

---

## เอกสารอ้างอิงหลักและคำสั่งตรวจสอบ

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — สถาปัตยกรรมและขอบเขตระบบ
- [`API_ACCESS.md`](API_ACCESS.md) — การใช้งาน API Key และ Native Inference Endpoint
- [`docs/V8_SUMMARY.md`](docs/V8_SUMMARY.md) & [`docs/V8_EXPERIMENT_CLOSURE_REPORT.md`](docs/V8_EXPERIMENT_CLOSURE_REPORT.md) — สรุปการปิดการทดลอง `v8` และข้อจำกัด
- [`docs/V9_BLUEPRINT.md`](docs/V9_BLUEPRINT.md) & [`docs/V9_EXPERIMENT_PLAN.md`](docs/V9_EXPERIMENT_PLAN.md) — พิมพ์เขียว/แผน `v9`; [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](docs/V9_EXPERIMENT_CLOSURE_REPORT.md) — ผลทดลองจริงและข้อสรุป `CLOSED_FAIL`
- [`docs/NATIVE_TRAINING_500_SPEC.md`](docs/NATIVE_TRAINING_500_SPEC.md) & [`docs/SCALING_POLICY.md`](docs/SCALING_POLICY.md) — สเปกการฝึกและการขยายขนาดโมเดล
- [`docs/PHASES_11_20_INDEX.md`](docs/PHASES_11_20_INDEX.md) & [`docs/PHASE_9_STATUS.md`](docs/PHASE_9_STATUS.md) — ดัชนีสถานะ Phase 9 และ Phase 11–20
- [`docs/engineering/ZYRQUEN_PHASE_READINESS.md`](docs/engineering/ZYRQUEN_PHASE_READINESS.md) & [`docs/operations/KNOWN_LIMITATIONS.md`](docs/operations/KNOWN_LIMITATIONS.md)

```bash
# ตรวจสอบชุดทดสอบ Phase 11-20 (ต้องมี pytest: 60 passed)
python -m pytest tests_phases/ -v

# ตรวจสอบ Pure-Python Native Runtime & Branding SVG Tests
python3 -m apps.core.test_native_runtime
python -m pytest tests/test_branding_svgs.py -v

# ตรวจสอบ Frontend (Web Workspace)
npm run test
npm run lint
npm run typecheck
npm run build
