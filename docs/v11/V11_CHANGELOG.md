# ZYRQUEN Ω∞ — V11 Documentation Changelog

- **Document ID:** `V11-DOC-22`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`

---

## 1. Change History

| Version | Date (Local) | Authoring Scope | Summary of Changes | Approval / Verification State |
|---|---|---|---|---|
| `v11.0-blueprint.1` | `2026-11-22` | `docs/v11/` (22 Specification/Control Docs + `README.md`) | จัดทำชุดเอกสาร V11 Blueprint Package ครบทั้ง 4 กลุ่มหลัก (Strategic & Architecture, Training & Data, Evaluation & Intelligence, Infrastructure & Governance) และ 6 เอกสารควบคุมเพิ่มเติม พร้อม Document Consistency Alignment กับ Codebase จริงของ V10 และ Roadmap Phases 11–20 | **BLUEPRINT ONLY — NOT APPROVED FOR IMPLEMENTATION**; ยังไม่มีการแก้ Source Code, ยังไม่ปิด V10 Final Gate, และยังไม่มี PyTorch Runtime Execution |

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
- การเปลี่ยนแปลงเอกสารครั้งถัดไป (`v11.0-blueprint.2` หรือ `v11.0-approved`) จะเกิดขึ้นเมื่อปิด V10 Final Gate และตัดสินใจประเด็น `OPEN DECISIONS` (`OD-*`) เรียบร้อยแล้ว

### OPEN DECISIONS
- **OD-CL-01:** กำหนด Rule ID สำหรับการเปลี่ยนแปลงเอกสาร V11 หลังเปิด Implementation (ทุก PR/การแก้สเปกต้องอัปเดต `V11_CHANGELOG.md` และรัน Document Consistency Audit ซ้ำ)

### NOT VERIFIED
- ความสอดคล้องเชิง Runtime ระหว่างเอกสารชุดนี้กับผลการฝึก `10,000` Steps จริง (ยัง **NOT RUN / NOT VERIFIED** เพราะยังไม่อนุมัติเปิด V11 และไม่มี `torch`)
