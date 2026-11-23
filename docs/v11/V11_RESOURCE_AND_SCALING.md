# ZYRQUEN Ω∞ — V11 Resource & Scaling Specification

- **Document ID:** `V11-DOC-14`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`
- **Policy Anchor:** `docs/SCALING_POLICY.md` + `docs/HONOR_X6B_MOBILE_PLAN.md` + `apps/core/workflow/resource_guard.py` + `apps/core/workflow/autonomous_training_loop.py`

---

## 1. Verified Hardware & Runtime Environment Facts (Evidence Snapshot)

| Environment | Verified Specifications | Runtime Status |
|---|---|---|
| **Mobile Baseline Target** (`HONOR_X6B_MOBILE_PLAN.md`) | HONOR X6b, RAM `6 GB`, Mali-G52 (Non-CUDA GPU), CPU-only | `NOT VERIFIED` สำหรับ 10k-step training load |
| **Current Workspace Host** (Measured `2026-11-22`) | CPU cores: `4`, MemTotal: `12,582,912 kB` (~`12.0 GB`), MemAvailable: `10,654,012 kB` (~`10.16 GB`), Disk Free: `755.05 GB` | `torch` **NOT INSTALLED** (`ModuleNotFoundError`) |

> **กฎความซื่อสัตย์ของ Scaling:** ตาม `docs/SCALING_POLICY.md`, 5M คือจุดเริ่มต้นและ `10M / 25M / 50M+` เป็นเป้าหมายทดลองระยะยาว **ไม่ใช่การรับรองว่า Hardware ปัจจุบันรองรับได้** ห้ามปรับเพิ่ม Parameter Limit โดยไม่มี PyTorch Peak RSS + Step-Time Benchmark จริงรองรับ

---

## 2. Active Locked CPU Budget (`V11-Tier0`, Verified in Code)

V11 เริ่มต้นภายใต้ Budget Lock เดียวกับที่บังคับใช้อยู่ใน `autonomous_training_loop.py`, `resource_guard.py`, และ `training/orchestrator.py`:

| Resource Parameter | `autonomous_training_loop.py` Lock | `resource_guard.py` Lock | V11 Tier-0 Policy |
|---|---|---|---|
| **CPU Threads** | `<= 2` (via controller) | CPU-only when no CUDA | `<= 2` threads |
| **Model Parameters** | `MAX_PARAMS = 5,000,000` | `MAX_CPU_MODEL_PARAMETERS = 5,000,000` | `<= 5,000,000` (`3.74M` / `4.75M`) |
| **Sequence Length** | `MAX_SEQ = 256` | `MAX_CPU_SEQUENCE_LENGTH = 256` | `<= 256` |
| **Batch Size** | `MAX_BATCH = 4` | `MAX_CPU_BATCH_SIZE = 4` | `<= 4` |
| **Steps per Invocation** | `MAX_STEPS = 500` | `MAX_CPU_TRAINING_STEPS = 1,000` | `500` per segment (resumed across `20` segments = `10,000` total) |
| **RAM Soft / Hard Limit** | `3.0 GB` soft / `3.5 GB` hard | `ResourceManager.max_ram_mb` | Soft `3.0 GB` / Hard Stop `3.5 GB` |
| **Disk Reserve** | `DISK_RESERVE_GB = 2.0` | `min_free_disk_gb` + `step.min_disk_gb` | `>= 2.0 GB` free disk always |
| **Checkpoints per Run** | `MAX_CHECKPOINTS_PER_RUN = 10` | `keep_last` in `CheckpointManager` | Rolling `keep_last <= 3..10` + stage milestones |
| **Paid Cloud GPU** | `FORBIDDEN` (`False`) | `requires_paid_gpu` blocked without Tier-2 token | **FORBIDDEN** (`use_paid_gpu = False`) |
| **Cost/Time Failsafe** | Experiment timeout `1200s` | `cost_controller_from_env()` fail-closed (`3600s` default) | Fail-closed `CostController` enabled always |

---

## 3. Scaling Gate Protocol (`V11-Tier0` → `V11-Tier1` 12.19M / `V11-Tier2` 27.80M)

ห้ามอัปเกรดขนาดโมเดลเกิน `5,000,000` params จนกว่าจะผ่าน **ทุกข้อ** ของ Scaling Gate:
1. `V11-Tier0` (<= 5M) ฝึกและผ่าน Verification บนข้อมูล V11 พร้อม Baseline Metrics จริง
2. รัน CPU Benchmark จริงกับ `torch` วัด:
   - Peak RSS (`RamMonitor` + `/proc/self/status`) ต้อง `< 2.5 GB` (เผื่อ margin ต่ำกว่า Soft Cap `3.0 GB`)
   - Step latency (`sec/step`) และ Projected Wall-Clock Time สำหรับ `10,000` steps
3. Checkpoint Save/Resume integrity test บนขนาดใหม่ผ่าน 100%
4. ได้รับ **Tier-2 Human Approval แยกต่างหาก** (`architecture.modify` และ `compute.paid_gpu` หากใช้ GPU) ก่อนแก้ Config Limit

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `V11-Tier0` (`3.74M – 4.75M` params, `seq=256`, `batch=4`) สามารถทำงานได้ต่ำกว่า RAM Hard Limit `3.5 GB` ทั้งบน Workspace CPU (`12 GB`) และ HONOR X6b (`6 GB` physical RAM, หากมี Python+PyTorch environment ที่เหมาะสม)
- การแบ่ง `10,000` steps ออกเป็น Segments ละ `500` steps ไม่ทำให้ Optimizer momentum เสียหายเมื่อ resume `optimizer.state_dict()` ครบถ้วน

### OPEN DECISIONS
- **OD-RS-01:** อนุมัติตัวเลข `steps_per_segment` (`500` vs `1,000`) และรอบ `eval_interval` หลังวัด `sec/step` จริงบนเครื่องเป้าหมาย
- **OD-RS-02:** จะเก็บ Stage Milestone Checkpoints (`step_1000`, `step_3000`, `step_5000`, `step_7000`, `step_9000`, `step_10000`) แยกต่างหากจาก Rolling `keep_last=3` ของ `CheckpointManager` เพื่อประหยัดพื้นที่ `< 1.0 GB` ต่อ Experiment อย่างไร

### NOT VERIFIED
- **Peak RAM (RSS) & CPU Step Latency:** ยัง **NOT VERIFIED** 100% เนื่องจากไม่มี `torch` ใน environment ปัจจุบัน
- **10,000-Step Wall-Clock Time:** ยังไม่ทราบระยะเวลารวมจริง (อาจใช้หลายชั่วโมงบน CPU 2 threads ซึ่งต้องนำมาคำนวณ segment timeout)
- **Thermal Throttling on Mobile Hardware:** ประสิทธิภาพต่อเนื่องบน HONOR X6b ระหว่างการฝึกยาว ยัง **NOT VERIFIED**
