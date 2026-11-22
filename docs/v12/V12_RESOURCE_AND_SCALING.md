# ZYRQUEN Ω∞ — V12 Resource Management & Scaling Policy

- **Document ID:** `V12-DOC-14`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Guard Anchor:** `apps/core/workflow/resource_guard.py`, `apps/core/workflow/autonomous_training_loop.py`
- **Cost & Hardware Rule:** CPU-Only Baseline; Zero Paid GPU/Cloud Compute Without Separate Approval

---

## 1. Hard Resource Guardrails (Inherited & Enforced Every Experiment)

| Guard Parameter | Current Enforced Value | Code Anchor | Action on Breach |
|---|---|---|---|
| **`RAM_SOFT_GB`** | `3.0 GB` | `autonomous_training_loop.py` | Throttle / Reject New Training Queue Dispatch |
| **`RAM_HARD_GB`** | `3.5 GB` | `autonomous_training_loop.py` | **Immediate Abort** Training Process + Preserve Last Verified Checkpoint |
| **`DISK_RESERVE_GB`** | `2.0 GB` free minimum | `autonomous_training_loop.py` | **Hard Block** New Training Run & Checkpoint Write (Cleanup Only Approved Temp Cache, Never Old Versions) |
| **`MAX_STEPS` (per run)** | `500` steps/experiment | `autonomous_training_loop.py` | Requires >= `100` Sequential Disjoint Runs for `50,000` Cumulative Steps |
| **`CPU Threads`** | `<= 2` threads (`torch.set_num_threads(2)`) | `V11/V12 Tier0 Policy` | Prevent Host Lockup & Thermal Throttling |
| **`MAX_V10_PARAMETERS`** | `5,000,000` (Entry Ceiling) | `apps/core/native/config.py` | Reject Configs >5M Unless Tier-1 Escalation Approved |

---

## 2. Wall-Clock & Disk Budget Accounting for `50,000` Steps

การฝึก `50,000` Steps (`100` Experiments × `500` Steps) บน CPU ต้องบริหาร 2 ปัจจัยหลักอย่างซื่อสัตย์:

1. **Wall-Clock Budget Planning (Contingent on V11 Actual Benchmark):**
   - ตัวอย่างสมมติฐานเชิงคำนวณเท่านั้น *(ยังไม่ใช่วัดจริง)*:
     - หาก Benchmark จริงบน Target CPU อยู่ที่ `0.30 sec/step` -> `50,000` steps = `~4.17 ชั่วโมง` (+ Evaluation Overhead)
     - หากอยู่ที่ `1.50 sec/step` -> `50,000` steps = `~20.8 ชั่วโมง` (ต้องรันแบบ Multi-Day Segmented Schedule)
   - **Rule:** ห้ามอนุมัติแผนเวลา V12 จนกว่าจะกรอก **Measured `sec/step` จาก V11 Stage 1–6 จริง** ลงในตารางคำนวณ
2. **Checkpoint Disk Lifecycle (Zero Blind Overwrite, Zero Disk Exhaustion):**
   - Checkpoints ที่เป็น **Stage Boundaries (`Step 5K, 13K, 23K, 33K, 41K, 50K`)** และ **Promoted Milestones** เป็น **Immutable Forever**
   - Intermediate Experiment Checkpoints (`EXP-001..100`) ที่เก็บ Optimizer State เต็มรูปแบบ (`weights + AdamW m/v`) ใช้พื้นที่มากกว่า Weights ล้วน ~3–4x; การ Retain/Archive Optimizer State ระดับ Intermediate (หลัง Verify & Promote Checkpoint ระดับ Stage แล้ว) ต้องทำผ่าน Policy ที่ได้รับอนุมัติและไม่ลบ Model Weights ของ Baseline (`v7..v11`)

---

## 3. Tier Escalation Protocol (`V12-Tier0` -> `V12-Tier1` -> `V12-Tier2`)

ห้ามอัปขนาดโมเดลเกิน `5,000,000` Parameters (`V12-Tier0`) ด้วยการเดา เงื่อนไขบังคับก่อนเปิด `V12-Tier1` (`12.19M`):
1. มีหลักฐาน **Capacity Saturation** จาก V11/V12-Tier0 (เช่น `train` loss & accuracy อิ่มตัวทั้งที่ Data Coverage พอแล้ว)
2. รัน **Dry-Run Memory & Latency Benchmark** บน Target CPU (10–20 steps) ยืนยันว่า `Peak RSS < 2.8 GB` (มี Margin ปลอดภัยใต้ `RAM_SOFT_GB = 3.0 GB`)
3. ได้รับ **Tier-2 Governance Approval** (และอนุมัติงบประมาณแยก หากต้องใช้ Hardware/Compute ที่แรงขึ้น)

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Target Execution Environments คือ Workspace CPU (`>= 4 cores`, `>= 12GB RAM`) หรือ Resource-Constrained Edge CPU (`HONOR X6b 6GB` สำหรับ Lightweight Verification / Inference)

### OPEN DECISIONS
- **OD-V12-RES-01:** นโยบายจัดเก็บ Optimizer State (`optimizer.pt`) ของ Intermediate 500-step Runs (เก็บเฉพาะ Weight-Only สำหรับ Intermediate Non-Boundary Runs หลังผ่าน Next-Stage Gate เพื่อประหยัด Disk หรือ Archive ทั้งชุด)
- **OD-V12-RES-02:** การขออนุมัติปรับ `MAX_STEPS` ต่อ Run จาก `500` เป็น `1,000` หาก CPU Latency จริงต่ำพอและต้องการลด Overhead การเปิด/ปิด Process

### NOT VERIFIED
- ตัวเลข `sec/step` จริง, `Peak RSS` จริง (MB/GB), และ Checkpoint Disk Footprint จริงบน PyTorch CPU ยัง **NOT VERIFIED / NOT RUN** (container ปัจจุบันไม่มี `torch`)
