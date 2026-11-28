# ZYRQUEN — ZYNTHEOR Teacher Distillation Experiment (Step 4025)

- **Date:** 2026-11-28
- **Repository role:** experiment record only; model checkpoints remain in Colab / cloud storage
- **Status:** `CANDIDATE — NOT PROMOTED`
- **Training strategy:** native ZYRQUEN student, text-based teacher distillation from the separately trained native ZYNTHEOR model
- **Weight policy:** no direct tensor/weight merge; no pretrained third-party weights or external AI inference API used

## 1. Source artifacts

| Artifact | SHA-256 |
|---|---|
| ZYNTHEOR target teacher checkpoint (41,527,808 parameters) | `8e974b2ac9485281f2c0deaba384348c099beec1150ebc27159b20b5ae734b3b` |
| Teacher-generated transfer dataset (20 records) | `aa33a742f1f4bac5d9b56a738e6aff9be0357a6ab8eaa2cdb2a2bd50d22180e8` |
| ZYRQUEN baseline checkpoint, Step 4000 | `0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d` |

Teacher dataset split:
- Training: 16 examples
- Transfer validation: 4 examples
- Each training text concatenated its source prompt and teacher-generated continuation.

## 2. Training execution

- Student: `PureNativeTransformerLMV2`
- Trainer: `PureContinualTrainerV2`
- Baseline global step: 4000
- Completed training steps: 25
- Candidate global step: 4025
- Batch size: 2
- Replay ratio: 0.5
- Maximum gradient norm: 1.0
- Final reported training loss: 4.7034
- Baseline optimizer state and continual state were restored before training.
- Existing replay buffer at resume: 24 samples.

## 3. Transfer validation (4 teacher-derived held-out examples)

| Metric | Before | After |
|---|---:|---:|
| Loss | 13.3991 | 9.9323 |
| Perplexity | 659411.151 | 20584.322 |
| Accuracy | 0.0725 | 0.1010 |
| Tokens | 1020 | 1020 |

This is a small transfer-validation split and is not evidence of broad generalization.

## 4. Independent evaluation

- Independent test set: 16 manually authored Thai/English examples
- Test-set SHA-256: `db1213e48aa3bad5a112b38323982d868c2ad992b917e2dafb710e5d9feaf3e1`
- Both checkpoints evaluated using the same `ByteTokenizer` and `evaluate_texts` implementation.
- Both checkpoint files were re-hashed after evaluation and matched their expected SHA-256 values.

| Metric | Baseline Step 4000 | Candidate Step 4025 | Difference |
|---|---:|---:|---:|
| Loss | 11.3512 | 11.3030 | -0.0482 |
| Perplexity | 85068.398 | 81064.262 | -4004.136 |
| Accuracy | 0.0233 | 0.0240 | +0.0007 |
| Tokens | 1414 | 1414 | 0 |

The independent evaluation shows a small numerical improvement on this 16-example test set. The result is preliminary: the sample is too small to establish statistically reliable generalization or broad capability gains.

## 5. Candidate checkpoint

- **Path in Colab:** `/content/zyrquen-resume/checkpoints/v2_teacher_transfer_step4025.json.gz`
- **Candidate SHA-256:** `1dfd79e967602e2a9b3269a1baeb370fa80934dbb9b3eecc89e19563538a8c2d`
- **Verified saved global step:** 4025
- **Baseline path in Colab:** `/content/zyrquen-resume/checkpoints/v2_continued_step4000.json.gz`
- **Baseline SHA-256 after training/evaluation:** `0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d`
- **Baseline preserved:** yes

The checkpoint itself is not included in this repository commit. It remains in the Colab/cloud checkpoint location above; the SHA-256 is recorded here for traceability.

## 6. Decision and follow-up

**Decision: retain as an unpromoted candidate.**

Do not replace the baseline or register/activate this candidate as production based on this experiment alone.

Before promotion or further claims of capability improvement:
1. Expand independent held-out evaluation across more examples and task categories.
2. Compare baseline and candidate on exactly the same deterministic evaluation protocol.
3. Add task-level capability checks and regression tests, not only next-byte loss/perplexity.
4. Verify checkpoint reload and inference from the saved candidate in a fresh runtime.
5. Review results before any explicit promotion decision.

## 7. Evidence classification

- **Runtime training:** executed in Colab; 25 steps reported and global step reached 4025.
- **Checkpoint integrity:** SHA-256 verified; saved checkpoint gzip content reported global step 4025.
- **Independent evaluation:** executed in Colab on 16 examples; preliminary only.
- **GitHub record:** this document records the reported runtime evidence; it does not independently reproduce the Colab run.
- **Production promotion:** not performed.
