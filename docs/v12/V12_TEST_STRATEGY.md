# ZYRQUEN Ω∞ — V12 Test Strategy & Verification Plan

- **Document ID:** `V12-DOC-18`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Reporting Taxonomy:** `IMPLEMENTED | STATIC PASS | RUNTIME PASS | BLOCKED | NOT RUN | FAILED`
- **Rule:** ห้ามรายงาน `PASS` หาก Test ถูก Skip เพราะ Missing Dependency (`torch`, `pytest`) — ต้องรายงาน `BLOCKED` หรือ `NOT RUN` อย่างตรงไปตรงมา

---

## 1. Five-Layer Verification Pyramid

| Layer | Test Scope | Execution Mode | Blocking Requirement |
|---|---|---|---|
| **L1: Static & Contract Integrity** | `compileall`, AST External-Model Scan, Config/Schema Bounds, `phases/phase11..20` Immutability | Pure Python (No Torch Required) | Required Before Any Commit/PR/Run |
| **L2: Data & Anti-Leakage Suite** | `EL-01..06`, `TL-01`, `SL-01`, `DL-01`, Exhaustive Solver Verification, Token Length Budget | Pure Python + `ZyrquenTokenizer` | Required Before Dataset Manifest Signing |
| **L3: Workflow & Security Governance** | Tier-2 Token Single-Use/Expiry, ResourceGuard Soft/Hard Reject, Zero Auto-Promote, Path Traversal | Unit + Integration Tests | Required Before Stage 1 Execution |
| **L4: PyTorch CPU Runtime & Recovery** | Real `ZyrquenModel` Forward/Backward, SFT `-100` Loss Masking, Resume Parity (`parent_sha256`), `weights_only=True`, NaN/OOM Abort | Requires Real `torch` Runtime | **Hard Block** ถ้าไม่มี `torch` -> สถานะ `BLOCKED` |
| **L5: Multi-Stage Intelligence & E2E** | Stage 1–6 Exit Gates, RB-01..06, Slot Permutation Consistency, Phase 17 Tenant Isolation, Anti-Regression vs V10 & V11 | Real `torch` + `EvaluationEngine` | Required for V12 Final Release Gate |

---

## 2. Specific Anti-Fake & Anti-Shortcut Test Cases

1. **`test_v12_no_external_model_imports`:** ตรวจ AST ทั้ง `apps/` และ `tools/` ยืนยัน 0 Imports ของ LLM APIs หรือ Pretrained Checkpoints
2. **`test_v12_step_accounting_rejects_failed_run`:** จำลอง Training Run ที่ล้มเหลวด้วย NaN/OOM ที่ Step 300 -> ยืนยัน `global_step` ไม่เพิ่ม, Checkpoint ถูก Quarantine, และ Resume ใช้ Parent เดิมเท่านั้น
3. **`test_v12_evaluation_rejects_missing_ood_or_empty_regression`:** ส่งผล Eval ที่ขาด `ood` หรือ `regression_comparison == {}` -> `handle_evaluation_gate` ต้องคืน `FAIL / BLOCKED` (Zero False-PASS)
4. **`test_v12_slot_permutation_invariance_harness`:** ป้อนโจทย์ Reasoning ชุดเดียวกันโดยสลับ Slot Binding `<slot_i>` 3 Seeds -> ตรวจการคงความหมายและความสามารถเทียบ Baseline
5. **`test_v12_cross_tenant_memory_isolation`:** ทดสอบ Stage 5 Retrieval ข้าม Tenant IDs -> ต้องได้ `0%` Cross-Tenant Leak

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เมื่อเปิดเฟส V12 จริง สภาพแวดล้อมทดสอบจะมีทั้ง `unittest` (stdlib) และ `torch` (CPU) ติดตั้งครบ รวมถึง `pytest` หากใช้รัน Test Suite เดิมที่มีอยู่

### OPEN DECISIONS
- **OD-V12-TST-01:** การรวม Test Suite ทั้งหมดให้รันได้ด้วย Pure `unittest` ควบคู่ `pytest` เพื่อไม่ให้เกิดสถานะ `BLOCKED` ใน Container ที่ขาด `pytest`

### NOT VERIFIED
- Test Cases ของ V12 ทั้ง 5 Layers ข้างต้นอยู่ในสถานะ **SPECIFIED ONLY / NOT IMPLEMENTED / NOT RUN** จนกว่า V10 และ V11 จะปิด Gate ครบ
