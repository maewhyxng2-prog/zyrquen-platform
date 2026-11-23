# ZYRQUEN Ω∞ — V11 Documentation Changelog

- **Document ID:** `V11-DOC-22`
- **Status:** `STAGE 1 CODE READINESS APPROVED (NO TRAINING / NO AUTO-PROMOTE)`

---

## 1. Change History

| Version | Date (Local) | Authoring Scope | Summary of Changes | Approval / Verification State |
|---|---|---|---|---|
| `v11.0-blueprint.1` | `2026-11-22` | `docs/v11/` (22 Specification/Control Docs + `README.md`) | จัดทำชุดเอกสาร V11 Blueprint Package ครบทั้ง 4 กลุ่มหลัก (Strategic & Architecture, Training & Data, Evaluation & Intelligence, Infrastructure & Governance) และ 6 เอกสารควบคุมเพิ่มเติม พร้อม Document Consistency Alignment กับ Codebase จริงของ V10 และ Roadmap Phases 11–20 | **BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION**; ยังไม่มีการแก้ Source Code, ยังไม่ปิด V10 Final Gate, และยังไม่มี PyTorch Runtime Execution |
| `v11.0-blueprint.2` | `2026-11-22` | `V11_DATASET_SPECIFICATION.md`, `V11_EVALUATION_PLAN.md` | ขยายรายละเอียดเชิงลึกของ Dataset สำหรับ `abstract_reasoning` และ `ood_transfer` (พร้อม Matrix แยก `train`/`validation`/`unseen`/`ood`, Solvers, ตัวอย่าง JSONL v2.0) และกำหนด Evaluation Stages สำหรับเป้าหมาย 10,000 Steps ครบทั้ง 6 Stages บน 4 Splits และ Report Schema `zyrquen.v11.evaluation_report.v1` | **BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION**; รอปิด V10 Final Gate และยืนยัน Open Decisions (`OD-DS-*`, `OD-EP-*`) |
| `v11.0-blueprint.3` | `2026-11-22` | `V11_MASTER_PLAN`, `V11_TRAINING_PLAN`, `V11_EVALUATION_PLAN`, `V11_DATASET_SPECIFICATION`, `V11_CHECKPOINT_AND_RECOVERY`, `V11_RESOURCE_AND_SCALING`, `V11_RELEASE_GATE`, `V11_SELF_VERIFICATION` | ปิดความไม่สอดคล้องของพิมพ์เขียว V11 ทั้ง 3 จุด: (1) ปรับ Stage 5/6 เป็น `2,000 / 1,000` (จุดสิ้นสุด `1,000 → 3,000 → 5,000 → 7,000 → 9,000 → 10,000`), (2) ล็อกการขยาย `sft.py::_V10_ENTITY_RE` (`UN`/`OO`) ไว้หลัง V10 Runtime Closure และอนุมัติแยก, และ (3) แยกบัญชี Global Steps vs Experiment Steps (`<= 500`/exp, อย่างน้อย `20` experiments) ชัดเจน | **BLUEPRINT ONLY — LOCKED UNTIL V10 RUNTIME CLOSURE GATE PASS** |
| `v11.0-stage1-readiness.1` | `2026-11-23` | `docs/v11/*`, `apps/core/native/{sft,dataset,registry,train,evaluation/engine}.py`, `apps/core/workflow/handlers/groups.py`, `tests/test_v11_stage1_readiness.py` | เปิด Gate 0 สู่ **Stage 1 Code Readiness** ภายใต้นโยบาย V10 `CLOSED_FAIL` Immutable Baseline + อัปเดตสถานะ `V10-B` ที่ปิดแล้วใน `workflows.py`; เพิ่ม superset `UN`/`OO` slot regex, 4-split dataset verification (`train/validation/unseen/ood`), `TrainConfig.tier0_v11` + segmented global-step resume continuity, และ `zyrquen.v11.evaluation_report.v1` gate พร้อม unit tests (ยังไม่เริ่ม Training, ไม่แก้ V7–V10) | **STAGE 1 CODE READINESS VERIFIED** (PyTorch training/eval still requires Tier-2 approval & `torch` runtime) |

---

## 2. Consistency & Baseline Anchor Record (`v11.0-blueprint.1`)

การตรวจสอบเทียบกับ Source Code จริง ณ วันที่ `2026-11-22`:
- Verified `ZyrquenConfig` (`apps/core/native/config.py`): `3,737,856` params (default), `4,262,144` params (`vocab=4096`), `4,754,688` params (`6L, d_ff=576`).
- Verified `ZyrquenTokenizer` (`apps/core/native/tokenizer.py`): `SCHEMA_V2 = "zyrquen.tokenizer.v2"`, `SLOT_COUNT = 32`, `BASE_VOCAB = 292` (for V2: `36 + 256`).
- Verified `sft.py`: `SFT_FORMAT_VERSION = "zyrquen.sft.v1"`, `SFT_SEP = "\n### Response:\n"`, `IGNORE_INDEX = -100`.
- Verified Budget Locks (`autonomous_training_loop.py` & `resource_guard.py`): `MAX_PARAMS = 5,000,000`, `MAX_SEQ = 256`, `MAX_BATCH = 4`, `MAX_STEPS = 500` (loop) / `1,000` (resource_guard), `RAM_SOFT_GB = 3.0`, `RAM_HARD_GB = 3.5`, `DISK_RESERVE_GB = 2.0`.
- Verified Governance Gap in V10 (`apps/api/routers/workflows.py` lines 253–334): บันทึกเป็น Hard Prerequisite (`Gate 0 / V10-B`) ใน `V11_SECURITY_AND_GOVERNANCE.md`, `V11_RELEASE_GATE.md`, และ `V11_RISK_REGISTER.md`.
- Verified Host Snapshot: 4 CPU cores, ~12 GB RAM, 755.05 GB free disk, `torch` NOT installed.

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- การเปลี่ยนแปลงเอกสารครั้งถัดไปก่อนเปิด Training จะต้องตัดสินใจประเด็น `OPEN DECISIONS` (`OD-*`) และบันทึกหลักฐาน SHA-256 ของรายงาน V10 (`CLOSED_FAIL`) ให้ครบถ้วน

### OPEN DECISIONS
- **OD-CL-01:** กำหนด Rule ID สำหรับการเปลี่ยนแปลงเอกสาร V11 หลังเปิด Implementation (ทุก PR/การแก้สเปกต้องอัปเดต `V11_CHANGELOG.md` และรัน Document Consistency Audit ซ้ำ)

### NOT VERIFIED
- การฝึกและประเมิน `ZyrquenModel` บน PyTorch (`10,000` Steps, Resume 20 Segments จริง, และ V11 4-split native inference) ยัง **NOT RUN / NOT VERIFIED** เพราะ `torch` ยังไม่ติดตั้งในสภาพแวดล้อมนี้ และยังไม่ได้รับ Tier-2 Approval สำหรับเริ่ม Training
