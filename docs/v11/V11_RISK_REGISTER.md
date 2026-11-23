# ZYRQUEN Ω∞ — V11 Risk Register & Safe-Stop Playbook

- **Document ID:** `V11-DOC-20`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`

---

## 1. Risk Matrix & Mitigations

| Risk ID | Category | Risk Description | Severity | Trigger / Early Warning | Mitigation & Safe-Stop Action |
|---|---|---|---|---|---|
| **RSK-01** | Runtime / Environment | PyTorch (`torch`) ไม่พร้อม หรือ mismatch ABI บน Target Host / HONOR X6b | **Critical** | `ModuleNotFoundError: torch` หรือ `EvaluationNotConfiguredError` | **BLOCK IMMEDIATELY**; รายงาน `BLOCKED (torch_not_installed)`; ห้ามรันแบบ mock หรือ fallback external AI |
| **RSK-02** | Governance / Security | เปิด V11 ก่อนปิดช่องโหว่ `verify_and_consume_by_id` ใน `apps/api/routers/workflows.py` (`/stage`, `/promote`, `/rollback`) | **Critical** | Acceptance ของ arbitrary approval strings หรือ missing audit logs | **HARD BLOCKER (Gate 0):** ต้องแก้และทดสอบใน V10-B ก่อนเริ่มงาน V11 ใดๆ |
| **RSK-03** | Resource / OOM | RAM เกิน Soft (`3.0 GB`) / Hard (`3.5 GB`) หรือ Wall-clock timeout ระหว่าง 10,000-step CPU training | **High** | `RamMonitor.exceeded_soft` หรือ `exceeded_hard` หรือ `CostController.should_stop()` | แบ่งรัน Segment `<= 500` steps; จำกัด `CPU threads <= 2`, `batch <= 4`, `Tier0 <= 5M`; ถ้าเกิน Hard Stop ตัดจบและคืน `BLOCKED` |
| **RSK-04** | Capacity / Architecture | โมเดล `<= 5M` พารามิเตอร์ อาจมีความจุไม่พอสำหรับ OOD 5–6 hops + 6 capabilities พร้อมกันใน 10,000 Steps | **Medium-High** | Stage 3–6 loss plateau สูง หรือ `ood` exact match ต่ำกว่าเกณฑ์แม้ `train` สูง | วัด 4L vs 6L under 5M ก่อน; หากไม่พอจริง ให้เปิด **Scaling Gate** พร้อม CPU Benchmark เพื่อขอ Tier-2 approval ขยายเป็น `Tier1 (12.19M)` |
| **RSK-05** | Data / Leakage | Entity, Template, หรือ Structural Pattern รั่วข้าม `train`/`validation`/`unseen`/`ood` หรือมีหลายคำตอบในกราฟ | **High** | `audit_leakage_v11` fail (`EL-*`, `TL-01`, `SL-01`, `UNIQUE_ANSWER`) | Fail-closed `LeakageGateFailedError`; ห้ามแก้ไขผล Audit; แก้ Generator แล้ว Re-audit ใหม่ทั้งหมด |
| **RSK-06** | Optimization / Forgetting | Catastrophic Forgetting: Stage 4–5 ทำให้ความแม่นยำ Stage 2–3 ลดลง | **Medium** | Validation accuracy ของ Stage ก่อนหน้าลดเกิน tolerance | บังคับ Replay Mixture (`15%–55%` ใน Stage 2–5) + Cosine Decay + Stage Gate Check; Rollback ไป Checkpoint Stage ก่อนหน้า |
| **RSK-07** | Evaluation / False-PASS | `TF - FG` exposure gap สูง, copy bias, หรือ report schema mismatch ทำให้ gate ตัดสินผิด | **High** | `exposure_gap` กว้าง, `eos_hit_rate` ต่ำ, หรือ missing splits | บังคับ `evaluate_native_model` Greedy Free-Gen จริงบน 4 Splits; ตรวจครบ every capability และ non-empty `regression_comparison` |
| **RSK-08** | Disk / Corruption | Disk เต็มจากเก็บ Checkpoint 10,000 Steps หรือไฟล์ `.pt` เสียหายขณะเขียน | **Medium** | `free_disk_gb < 2.0 GB` หรือ SHA-256 verify fail | `check_disk_reserve` ก่อนรันทุก segment; `CheckpointManager` atomic `.tmp` + `os.replace` + `keep_last` + fallback checkpoint ก่อนหน้า |

---

## 2. Emergency Safe-Stop Procedure

เมื่อพบ Trigger ระดับ Critical/High ระหว่างดำเนินงาน:
1. **Halt Execution:** ยุติ Training/Evaluation Run ทันที (`BLOCKED` / `FAIL`) โดยไม่บันทึก Checkpoint ที่ Diverge
2. **Preserve Evidence:** เก็บ `metrics.jsonl`, Diagnostic logs และ Audit log (`WorkflowAuditLogger`) ไว้ตรวจสอบสาเหตุ
3. **Verify Baseline Integrity:** ตรวจ SHA-256 ของ `v7..v10` และ Active `ModelRegistry` version เพื่อให้มั่นใจว่าไม่มี Artifact ถูกปนเปื้อน
4. **Do Not Auto-Retry Blindly:** ต้องหา Root Cause และขออนุมัติซ้ำก่อนเริ่ม Segment ใหม่

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- ระบบ Safeguard ที่มีอยู่ (`RamMonitor`, `CostController`, `check_disk_reserve`, `CheckpointManager`) ทำงานถูกต้องตาม Unit Tests เมื่อติดตั้ง PyTorch

### OPEN DECISIONS
- **OD-RR-01:** กำหนดตัวเลข Early-Stop Tolerance สำหรับ Catastrophic Forgetting ระหว่าง Stage (เช่น ยอมให้ลดลงระหว่าง Stage ชั่วคราวไม่เกิน `0.05` ก่อน Consolidation ใน Stage 6 หรือห้ามลดเกิน `0.01` ทุก Stage)

### NOT VERIFIED
- ความถี่จริงของ Failure Modes (`OOM`, `Loss Divergence`, `Catastrophic Forgetting`, `5–6 hop saturation`) บน 10,000-step CPU Run จริงยัง **NOT VERIFIED**
