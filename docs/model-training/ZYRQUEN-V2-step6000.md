# ZYRQUEN V2 — Training Progress Record (Step 6000)

- Record date: 2026-11-28
- Repository: `maewhyxng2-prog/zyrquen-platform`
- Training line: Native V2 continuation / teacher-transfer run
- Starting checkpoint: global_step 5000
- Target reached in the Colab trainer: global_step 6000
- Training chunk size: 25 optimizer updates
- Training examples reported by the run: 16
- Validation split: kept separate from training

## Step 5000 baseline

- File: `v2_teacher_transfer_step5000.json.gz`
- SHA-256: `76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed`
- Baseline SHA-256 was rechecked after the continuation and matched.

## Step 6000 candidate checkpoint

- Colab path: `/content/zyrquen-resume/checkpoints/v2_teacher_transfer_run5000_step6000.json.gz`
- Size: 700,611 bytes
- SHA-256: `3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7`
- In-memory trainer global_step reported: 6000
- Checkpoint file existence: confirmed
- Checkpoint SHA-256: computed and recorded

## Verification status

- [x] Step 5000 baseline exists and SHA-256 matches the previously verified value.
- [x] Step 6000 checkpoint file exists in the Colab runtime.
- [x] Step 6000 checkpoint SHA-256 recorded.
- [x] In-memory trainer reports global_step 6000.
- [ ] Reload Step 6000 checkpoint into a separate trainer and verify global_step 6000.
- [ ] Verify restored optimizer state and continual-learning state after reload.

**Important:** This GitHub record stores provenance and verification metadata only. The 700,611-byte checkpoint itself has **not** been uploaded to this repository. The checkpoint must not be described as load-verified until the separate reload checks pass. This record does not promote the candidate checkpoint to production/primary weights.

## Training loss samples

The run output reported these selected values:
- Step 5025: 2.1464
- Step 5275: 0.7587
- Step 5500: 1.1642
- Step 5750: 1.3095
- Step 5775: 1.2486
- Step 5800: 1.1556
- Step 5825: 1.6173

These are training-loss observations, not held-out validation metrics and not evidence by themselves of general capability improvement.
