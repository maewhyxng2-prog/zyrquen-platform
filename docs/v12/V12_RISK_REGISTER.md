# ZYRQUEN Ω∞ — V12 Risk Register & Mitigations

- **Document ID:** `V12-DOC-20`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Scope:** Algorithmic, Resource, Data, Governance & Operational Risks Over a `50,000`-Step Horizon

---

## 1. Risk Matrix & Deterministic Stop / Mitigation Controls

| Risk ID | Category | Risk Description | Impact | Mitigation in V12 Blueprint | Hard Stop Trigger |
|---|---|---|---|---|---|
| **R-V12-01** | **Optimization** | **Catastrophic Forgetting:** Stage 4–6 ทำลายความรู้หรือ Pattern จาก Stage 1–3 ในระยะ 50,000 Steps | High | บังคับ `35%–50%` Multi-Stage Replay Mix + Anti-Regression Check ทุก Boundary | Regression เกิน Tolerance บน Stage ใดก็ตาม |
| **R-V12-02** | **Capacity** | **Model Saturation at `<= 5M` (`Tier0`):** ความจุพารามิเตอร์ `3.74M–4.95M` อิ่มตัวก่อนครบ 50,000 Steps หรือรับมือ 6–10 Hops ไม่ไหว | High | วัด Saturation Probe จาก V11 ก่อน; เตรียม `V12-Tier1` (`12.19M`) ไว้เป็น Locked Escalation Path | `train` & `val` Loss หยุดลดต่อเนื่อง 5 Experiments ทั้งที่ Replay/LR เหมาะสม |
| **R-V12-03** | **Compute / Time** | **CPU Wall-Clock Bottleneck:** `50,000` Steps (`100` runs) บน CPU อาจใช้เวลาหลายสิบชั่วโมงหรือเกิด Thermal Throttling | High | วัด `sec/step` จริงจาก V11 ก่อนวางตาราง V12; จำกัด `CPU threads <= 2`; รันแบบ Segmented Schedule | Thermal/CPU Timeout หรือ Latency เกิน Budget ที่อนุมัติ |
| **R-V12-04** | **Memory / Disk** | **OOM หรือ Disk เต็มจาก `100` Checkpoints:** AdamW States ของ 100 Runs สะสมจนเกิน `DISK_RESERVE_GB` หรือ Peak RSS เกิน `3.5 GB` | High | Enforce `WorkflowResourceGuard` ก่อนทุก Run; กำหนด Policy จัดการ Intermediate Optimizer States หลัง Verify | `RSS >= 3.5 GB` หรือ `free_disk < 2.0 GB` |
| **R-V12-05** | **Evaluation** | **Exposure Bias / Silent Overfitting:** Loss ต่ำใกล้ 0 แต่ Free Generation (`eos_hit_rate` / `ood`) พังลง | High | วัด `tf_fg_gap` + Free-Gen Exact Match บน `unseen`/`ood` ทุก Level A/B Gate | `eos_hit_rate < 0.85` หรือ `unseen`/`ood` ร่วงขณะ Train Loss ลด |
| **R-V12-06** | **Data** | **Subtle Shortcut / Leakage Across 251K Examples:** Entity หรือ Template รั่วข้าม 4 Splits | Critical | Exhaustive Solver + `EL-01..06`, `TL-01`, `SL-01`, `DL-01` Audit + Manifest SHA-256 Pinning | Leakage Violation `>= 1` record |
| **R-V12-07** | **Governance** | **Scope Creep / Premature V12 Execution:** ข้าม V10 Closure หรือ V11 เพื่อมารัน 50K ก่อนเวลา | Critical | Hard Prerequisite Gate (`G-V12-ENTRY`), Status Locks ในเอกสาร, และ Tier-2 Token Rejection | พยายามรัน V12 ขณะที่ V10/V11 ยังไม่ `PASS` |
| **R-V12-08** | **Integrity** | **External Model / Scripted Fake Fallback:** แอบต่อ External API หรือ Hardcoded Rules เพื่อโชว์ผลผ่าน | Critical | AST Import Gate, Native-Only Policy, Standalone vs System Score Separation | ตรวจพบ External Import/API/Fake Answer |
| **R-V12-09** | **SE Execution** | **Uncompilable Code / UI-Only Illusion (`CAP-SE`):** โมเดลสร้าง UI หรือข้อความที่ดูคล้ายแอปแต่ Build ไม่ผ่านหรือ State ไม่ทำงานจริง | High | Mandatory Sandbox Compile/Unit/Integration/Hidden Gates + Hard Disqualification Rule | Compile fail หรือ UI ไม่มี Executable Pass |
| **R-V12-10** | **SE Data / Eval** | **Test Memorization / Reward Hacking (`CAP-SE`):** โมเดลจำ Visible Unit Tests หรือ Hardcode เฉพาะ Case ตัวอย่าง | High | `CL-01..03` AST Clone/Hidden-Test Isolation + Unseen Spec Variations | Hidden Test Fail ขณะ Visible Test Pass |
| **R-V12-11** | **SE Security** | **Insecure Generated Apps (`CAP-SE-09`):** แอปที่สร้างมีช่องโหว่ SQLi, XSS, Broken RBAC, Path Traversal หรือ Execute Arbitrary Commands | Critical | Isolated Sandbox + Static/Dynamic Security Gate (`CAP-SE-09`) + Zero Host Exec | ตรวจพบ Security Violation `>= 1` จุด |

---

## 2. Mandatory Truthfulness Sections

### ASSUMPTIONS
- ความรุนแรงและลำดับความสำคัญของความเสี่ยงจะถูกทบทวนซ้ำ (Re-rank) ทันทีหลังจากได้รับข้อมูลจริงจาก **V10 Runtime Closure** และ **V11 10K Training**

### OPEN DECISIONS
- **OD-V12-RSK-01:** แนวทางรับมือกรณี **R-V12-03** (CPU ช้ากว่าที่คาดสำหรับ 50K Steps) — ระหว่างลด Batch/Seq Budget, ขอเปลี่ยน Tier Hardware CPU (ไม่เสียเงิน), หรือขออนุมัติ Compute Policy แยกต่างหาก

### NOT VERIFIED
- ความน่าจะเป็นเชิงสถิติของการเกิด Loss Collapse, Catastrophic Forgetting, และ SE Multi-File Compilation Failure บน `50,000` Steps สำหรับ `ZyrquenModel` ยัง **NOT VERIFIED / NOT RUN**
