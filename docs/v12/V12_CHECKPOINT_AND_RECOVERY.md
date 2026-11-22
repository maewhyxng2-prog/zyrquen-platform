# ZYRQUEN Ω∞ — V12 Checkpoint & Recovery Specification

- **Document ID:** `V12-DOC-15`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Code Anchors:** `apps/core/native/checkpoint.py`, `apps/core/training_infrastructure/recovery/checkpoint_recovery.py`, `apps/core/native/registry.py`
- **Immutability Law:** Zero Overwrite of Historical Baselines (`v7`, `v8`, `v9`, `v10`, `v11`) and Zero Deletion of Promoted Checkpoints

---

## 1. Versioned Checkpoint Naming & Directory Isolation

ทุก Experiment ใน V12 (`EXP-001..EXP-100`) ต้องบันทึก Checkpoint ลงใน Path ที่แยกขาดตาม Version และ Step:

```text
artifacts/checkpoints/v12/
  lineage_<lineage_id>/
    stage_01_representation/
      exp_001_step_000500/
        model_weights.pt
        training_state.pt
        checkpoint_manifest.json
        eval_micro_report.json
      ...
      exp_010_step_005000_STAGE1_EXIT/
    stage_02_knowledge/
      ...
    stage_06_verification/
      exp_100_step_050000_V12_FINAL/
```

**ห้าม** ใช้ Path ซ้ำหรือเขียนทับ Checkpoint ก่อนหน้า (`overwrite=False` ใน `VersionedCheckpointManager`)

---

## 2. Mandatory Checkpoint Manifest Schema

ทุก `checkpoint_manifest.json` ต้องเชื่อมโยงโซ่ Provenance กลับไปได้ครบ 100%:
- `version_tag`: e.g., `"v12.0-s3-exp035"`
- `parent_checkpoint_path` และ `parent_checkpoint_sha256` (ต้อง Match 100% ก่อน Load Resume)
- `global_step_start`, `global_step_end`, `experiment_steps_executed`
- `stage_id` (`1..6`), `experiment_id` (`EXP-001..100`)
- `model_config` + `model_config_sha256`
- `tokenizer_sha256` + `dataset_manifest_sha256`
- `weights_sha256` + `training_state_sha256`
- `seed`, `optimizer_type`, `lr_at_exit`, `final_train_loss`, `eval_report_sha256`
- `status`: `"VERIFIED_STAGE_STEP"` / `"STAGE_EXIT_PASSED"` / `"ABORTED_NOT_COUNTED"`

---

## 3. Safe Loading & Atomic Write Protocol

1. **Strict `weights_only=True` Rule:** การโหลด Weights สำหรับ Inference หรือ Registry Inspection ต้องใช้ `torch.load(..., map_location="cpu", weights_only=True)` เสมอ ห้ามใช้ Unsafe Pickle Deserialization จากไฟล์ที่ไม่ได้ Verify SHA-256
2. **Atomic Staging & Rename:** เขียนไฟล์ลง Directory ชั่วคราว (`.tmp_<uuid>`), คำนวณ SHA-256, `fsync`, แล้วจึง Atomic Rename เข้า Final Path เพื่อกันไฟล์ขาดครึ่งหากไฟดับ/OOM
3. **Resume Consistency:** เมื่อ Resume `EXP-(k+1)` จาก `EXP-k` ต้องโหลดทั้ง Model Weights, Optimizer State, LR Scheduler Step, และ `global_step` พร้อม Assert ค่า `parent_checkpoint_sha256`

---

## 4. Failure & Corruption Recovery Playbook

| Failure Event | Immediate Action | Step Accounting Impact | Recovery Source |
|---|---|---|---|
| **NaN / Loss Spike / Collapse** | Abort Run ทันที, Quarantine `exp_k` directory เป็น `FAILED` | `0` steps added to `global_step` | Rollback ไปยัง `last_verified_checkpoint`, ลด LR/ตรวจ Data Batch, ขอ Tier-2 อนุมัติ Re-run |
| **RAM Hard Limit / OOM** | OS/Guard Terminates Process; Cleanup `.tmp_*` | `0` steps added (เว้นแต่มี Intra-Run Verified Boundary ที่ Hash ผ่านครบ) | Rollback ไปยัง `last_verified_checkpoint`, ลด Batch Size/Sequence Length |
| **SHA-256 Mismatch** | **Hard Stop** — ห้าม Resume ต่อ | Lock Lineage เพื่อตรวจสอบ Integrity | ตรวจ Storage Hardware / กู้จาก Mirror Backup ของ `last_verified_checkpoint` |

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `apps/core/native/checkpoint.py` และ `CheckpointManager` รองรับการขยาย Metadata Fields (`global_step`, `stage_id`, `parent_checkpoint_sha256`) โดยไม่ทำลาย Backward Compatibility ของ Checkpoints V10/V11

### OPEN DECISIONS
- **OD-V12-CKP-01:** การเปิดใช้ Intra-Experiment Mid-Run Recovery Checkpoint ทุก `250` Steps (เมื่อ 1 Run มี `500` Steps) เทียบกับการ Save เฉพาะตอนจบ `500` Steps เพื่อลด Disk I/O

### NOT VERIFIED
- การทำงานจริงของ PyTorch Save/Load (`weights_only=True`) และ SHA-256 Atomic Verification บน `EXP-001..100` ยัง **NOT VERIFIED / NOT RUN**
