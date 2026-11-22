# ZYRQUEN Ω∞ — V11 Test Strategy (Unit, Integration, Regression & Runtime)

- **Document ID:** `V11-DOC-18`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Test Truth Rule:** ห้ามรายงาน Test PASS หาก Test ถูก Skip (`HAS_TORCH=False`), Mock ที่ข้าม Core Invariant, หรือไม่มี Terminal Output จริงยืนยัน

---

## 1. Four-Tier Testing Pyramid for V11

### Tier 1: Pure-Python Unit & Contract Tests (No `torch` Required, `unittest` Compatible)
1. **Model & Budget Contracts:**
   - ตรวจ `ZyrquenConfig.estimated_num_parameters` ทุก Tier (`Tier0-Default`, `Tier0-Vocab4096`, `Tier0-Deep6L`)
   - ตรวจ Rejection เมื่อเกิน `MAX_CPU_MODEL_PARAMETERS` หรือ `vocab_size` mismatch
2. **Tokenizer & Ephemeral Slot Contracts:**
   - Unicode NFC round-trip (Thai + English + symbols)
   - `<slot_0>..<slot_31>` atomic preservation + `train_slot_safe_tokenizer` `EL-05 == 0`
   - Slot permutation invariance และ `UN_E*`/`OO_E*` entity binding/restoration
3. **Dataset Generator & Read-Only Leakage Auditor Tests:**
   - Unique-answer solver agreement 100% บน sample graphs/plans/beliefs (รวม negative traps)
   - Adversarial leakage injection tests: verify Auditor FAILS เมื่อแอบใส่ entity ซ้ำ (`EL-01..04`), static vocab leak (`EL-05`), phrasing leak (`TL-01`), structural OOD leak (`SL-01`), duplicate input (`DL-01`), หรือ token `> 250` (`SEQ_BUDGET`)
4. **Memory & Verification Contracts:**
   - Phase 17 multi-tenant blocking (`owner_id` / `workspace_id` mismatch) + PII block + empty-source block
   - Phase 16 `validate_dag` cycle/missing block + `verify_step` fail-closed + `ExecutionSafetyPolicy` default-deny

### Tier 2: Workflow, Security & Governance Integration Tests
1. **Tier-2 HMAC Approval Enforcement:**
   - `/v1/workflows/runs` หยุดที่ `WAITING_APPROVAL` ก่อนรัน `training.execute`
   - Forged / expired / wrong-action / replayed `approval_id` ต้องถูก `403` / `409` บนทั้ง Workflow Engine และ Registry REST endpoints (`/stage`, `/promote`, `/rollback`)
2. **Anti-False-PASS Gate Tests:**
   - `handle_evaluation_gate` ต้องปฏิเสธ (`NOT RUN` / `BLOCKED` / `FAIL`) เมื่อรายงานขาด split (`unseen` หรือ `ood`), มี `NOT RUN`/`N/A`, `inference_executed=False`, `regression_comparison=[]`, หรือ `stop_criteria_triggered` ไม่ว่าง
3. **V7/V8/V9/V10 Freeze Protection:**
   - `ModelRegistry` ปฏิเสธการแก้/promote ทับ frozen baselines และไฟล์เดิมของ v7/v8/v9/v10 ไม่เปลี่ยน SHA-256

### Tier 3: Regression & Compatibility Tests
1. **Existing Suites Must Stay Green:** `test_v10a_contracts.py`, `test_v10c_integration_hook.py`, `test_workflow_engine.py`, `test_v9_static_contracts.py`, `tests_phases/test_phase11..20.py`, `apps/api/test_*.py`, และ `apps/web` (`typecheck`, `lint`, `build`, `e2e`)
2. **Schema Cross-Version Isolation:** ตรวจว่า v11 schema parser ไม่ทำให้ v9/v10 evaluation reports ล้มเหลว

### Tier 4: PyTorch CPU Runtime Tests (Blocked Until `torch` Installed)
1. **Smoke Training & Parameter Mutation:** รัน `train_sft` 4–10 steps บน CPU ตรวจ `parameter_changed=True`, finite loss, และ `eos_id` learning
2. **Segmented Resume Continuity:** ฝึก 5 steps -> save ckpt -> resume โหลด `model`, `optimizer`, `step`, `rng`, `batch_rng` -> ฝึกต่อถึง step 10 เทียบกับ continuous 10-step run และตรวจ `weights_only=True`
3. **Real Native Inference Evaluation (`EvaluationEngine.evaluate_native_model`):** ตรวจ greedy generation, slot restoration, และ zero-metric-fabrication on actual saved `.pt`
4. **Budget & Guard Stress Tests:** ตรวจ NaN injection (must NOT save corrupt checkpoint), `RamMonitor` soft/hard stop trigger, `CostController` timeout stop, and corrupt `.pt` fallback to previous valid checkpoint

---

## 2. Environment Compatibility Requirement (Lessons Learned in Repo)

- Test suites หลักใน `tests/` ควรเขียนด้วย `unittest` (Pure stdlib compatible) หรือแยก dependency-guarded tests ชัดเจน เพื่อให้รันได้ทั้งใน container ที่ไม่มี `pytest` และใน CI ที่มี `pytest` (`api-tests.yml`)

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- สามารถสร้าง Synthetic mini-checkpoints และ mock `_train_fn` ใน Tier 1–3 tests เพื่อตรวจ Control/Governance Flow โดยไม่ปลอมแปลง PyTorch Training Result
- Environment ที่ใช้เปิด V11 Training จริงจะมี `torch`, `pytest`, `pydantic`, `fastapi` ครบถ้วน

### OPEN DECISIONS
- **OD-TS-01:** เกณฑ์การกำหนด Test Coverage ของ Tier 4 (เช่น ต้องรัน `test_train_torch.py` + V11 10-step resume test เป็น Blocking Gate ก่อนอนุมัติ Stage 1 จริงหรือไม่ — แนะนำให้เป็น **Mandatory Blocking Gate**)
- **OD-TS-02:** จัดการ Tests ที่ Skip เมื่อขาด `pydantic`/`torch` ใน Summary Reporting อย่างไร (`SKIPPED` ต้องไม่ถูกนับเป็น `PASS` ใน Release Gate)

### NOT VERIFIED
- Tier 4 PyTorch CPU Runtime Tests ทั้งหมดยัง **NOT VERIFIED** ในสภาพแวดล้อมปัจจุบันเพราะยังไม่มี `torch`
- สถานะรันจริงของ `apps/api/test_*.py` และ `tests_phases/` บน environment นี้ยังไม่ได้ติดตั้ง `pytest`/`pydantic`/`sqlalchemy`
