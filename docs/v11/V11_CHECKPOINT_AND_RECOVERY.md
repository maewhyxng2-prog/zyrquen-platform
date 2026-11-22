# ZYRQUEN Ω∞ — V11 Checkpoint, Resume & Recovery Specification

- **Document ID:** `V11-DOC-15`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Core Modules:**
  - `apps/core/training_infrastructure/recovery/checkpoint_recovery.py::CheckpointManager`
  - `apps/core/native/checkpoint.py::VersionedCheckpointManager`
  - `apps/core/native/registry.py::ModelRegistry`

---

## 1. Checkpoint Immutability & Security Contract

1. **Zero Overwrite of Prior Generation Checkpoints:** Checkpoints ของ `v7`, `v8`, `v9`, และ `v10` ห้ามถูกแก้ไขหรือลบ Directory ของ V11 แยกเป็น `checkpoints/nagi_v11/` (และ Stage/Run subdirs) เท่านั้น
2. **Atomic Write-Replace & SHA-256 Manifest:** `CheckpointManager.save(step, state)` เขียนไปยัง `.tmp` แล้ว `os.replace()` พร้อมบันทึก `size_bytes` และ `sha256` ลงใน `manifest.json` (`zyrquen.checkpoint-manifest.v1`)
3. **Safe Deserialization (`weights_only=True`):** `CheckpointManager` และ `ModelRegistry` ใช้ `_safe_torch_load` (`torch.load(..., map_location="cpu", weights_only=True)`) เป็นค่าเริ่มต้น พร้อมตรวจ path containment และห้าม symlink (`_safe_checkpoint_path`)

---

## 2. Canonical Checkpoint Payload (`train_sft` Contract)

ทุก Checkpoint ของ V11 ที่บันทึกโดย `apps/core/native/train.py::train_sft` ต้องมีครบทุก Field:

```python
{
    "model": model.state_dict(),
    "optimizer": optimizer.state_dict(),
    "step": step,                      # Cumulative global step (0..10000)
    "experiment_index": exp_idx,       # Monotonic experiment counter (1..20+)
    "experiment_steps": exp_steps,     # Executed steps in this run (<= 500)
    "global_step_start": start_step,   # Exact previous global step (no gap/overlap)
    "batch_rng": rng.getstate(),       # Python RNG state
    "rng": capture_rng_state(),        # Python + Torch CPU RNG state
    "config": cfg.__dict__,            # TrainConfig snapshot
    "model_config": model.cfg.to_dict(),
    "tokenizer_sha256": tokenizer_fingerprint,
    "dataset_version": dataset_version,
    "prompt_format": "zyrquen.sft.v1",
    "sep": "\n### Response:\n",
}
```

---

## 3. Resume & Recovery Scenarios

| Failure / Stop Scenario | Expected Behavior | Verification Rule |
|---|---|---|
| **Normal Segment Budget Stop** (`step = 500`, `stopped_reason = None` or `cost_exceeded`) | บันทึก Checkpoint ล่าสุด (`step > start_step`), Segment ถัดไปเรียก `load_latest()` และฝึกต่อจาก `step` เดิม | `resumed_from == previous_step`, `tokenizer_sha256` ตรงกัน |
| **Loss Divergence / NaN** (`stopped_reason = "loss_diverged"`) | **ห้าม** บันทึก Checkpoint ที่ Diverge (`train.py` lines 186/348); คง Checkpoint ดีล่าสุดก่อนหน้าไว้และหยุด Workflow ด้วย `FAIL` | Manifest ไม่ชี้ไปยัง Checkpoint ที่เป็น NaN |
| **RAM Hard Stop** (`RSS >= 3.5 GB`) | `RamMonitor` / Handler ตัดจบและคืน `BLOCKED (ram_hard_stop)`; ห้ามลงทะเบียน Checkpoint หากไม่ครบเงื่อนไข | Process ป้องกัน OOM ก่อน Crash |
| **Corrupted Latest `.pt` File** | `CheckpointManager.latest_valid()` ตรวจ `size_bytes` และ `sha256`; หากไฟล์ล่าสุดพัง จะถอยไปโหลดไฟล์ก่อนหน้าที่ SHA-256 ผ่าน | Corruption recovery test ใน `test_checkpoint_recovery.py` |
| **Worker Crash Mid-Stage** | `RecoveryManager.reconcile_orphaned_runs` (`apps/core/workflow/recovery.py`) เปลี่ยน orphan `RUNNING` steps กลับเป็น `PENDING` / `FAILED` และบันทึก Audit Log | Workflow engine consistency preserved |

---

## 4. Stage Milestone Retention Strategy

เพราะ `CheckpointManager` เก็บ Rolling Window (`keep_last`, เช่น 3 ไฟล์ล่าสุด), ในแผน 10,000 Steps / 6 Stages (`>= 20` Experiments):
- **End-of-Stage Milestones** (`step 1000, 3000, 5000, 7000, 9000, 10000`) ควรลงทะเบียนเข้า `ModelRegistry` (`register_next_native_version` -> Immutable Snapshot ใน `artifacts/ZYRQUEN-Native-X.Y.Z/`) หรือเก็บใน milestone manifest เพื่อไม่ให้ `keep_last` ลบ Checkpoint ปิด Stage ทิ้ง และป้องกันพื้นที่ Disk เกินงบ `<= 1.0 GB` ต่อ run

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `torch.load(..., weights_only=True)` รองรับ `state` dictionary ที่มี Python RNG tuple + Optimizer state tensors ของ `ZyrquenModel` ในเวอร์ชัน PyTorch ที่จะติดตั้ง (หมายเหตุ: `checkpoint_recovery.py` มี `allow_unsafe_pickle=False` เป็นค่าเริ่มต้น หาก PyTorch version ปฏิเสธ Python tuple RNG ภายใต้ `weights_only=True` อาจต้องเก็บ RNG แยกเป็น JSON/primitive หรือเปิด fallback เฉพาะหลังตรวจ SHA-256)
- ขนาดไฟล์ 1 Checkpoint (`V11-Tier0` `3.74M` params + AdamW states ≈ `~45–60 MiB`) ทำให้เก็บ 10 Checkpoints ได้สบายในงบ `< 1.0 GB`

### OPEN DECISIONS
- **OD-CR-01:** ตรวจสอบใน PyTorch จริงว่า `rng["python"]` (nested tuples) โหลดผ่าน `weights_only=True` หรือควรแยกเก็บ `batch_rng`/`python_rng` เป็น JSON sidecar หรือ primitive list
- **OD-CR-02:** เมื่อเปลี่ยน Stage (เช่น Stage 1 -> Stage 2) และ Dataset Mixture เปลี่ยน `dataset_version` อาจเปลี่ยนเป็น `11.0.0-stage2` หรือคง `11.0.0` (มี `stage_tags` ในไฟล์เดียว) — หากคง `dataset_version = "11.0.0"` เดียวตลอด 6 Stages จะลดปัญหา checkpoint provenance mismatch

### NOT VERIFIED
- ความเข้ากันได้ของ `weights_only=True` กับ `optimizer.state_dict()` + `rng` tuple ใน PyTorch เวอร์ชันปลายทาง ยัง **NOT VERIFIED** (เพราะไม่มี `torch` ใน container)
- ขนาดไฟล์ Checkpoint จริงบน Disk ของ `V11-Tier0` ยัง **NOT VERIFIED**
