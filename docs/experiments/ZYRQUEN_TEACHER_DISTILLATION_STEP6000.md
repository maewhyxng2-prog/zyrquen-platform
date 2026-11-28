# ZYRQUEN — Teacher Transfer Continuation (Step 6000)

- **Date:** 2026-11-28
- **Repository role:** experiment record and checkpoint-integrity manifest; checkpoint binaries remain in Colab / cloud storage
- **Status:** `CANDIDATE — NOT PROMOTED`
- **Model:** native `PureNativeTransformerLMV2` with `PureContinualTrainerV2`
- **Training data:** teacher-generated transfer dataset; 16 training examples, 4 held-out transfer-validation examples
- **Policy:** no pretrained third-party weights and no external AI inference API used; no tensor/weight merge

## 1. Continuation baseline

| Item | Value |
|---|---|
| Baseline checkpoint | `/content/zyrquen-resume/checkpoints/v2_teacher_transfer_step5000.json.gz` |
| Baseline global step | 5000 |
| Baseline SHA-256 | `76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed` |
| Baseline verification | Reported as `BASELINE VERIFIED` before continuation |

The earlier Step 4000 checkpoint remains a separate historical baseline:
`v2_continued_step4000.json.gz`, SHA-256
`0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d`.

## 2. Training continuation

- Starting global step: 5000
- Final in-memory global step reported: 6000
- Target: 6000
- Training examples: 16
- Checkpoint interval: every 25 optimizer steps
- Checkpoint sequence: Step 5025 through Step 6000 (40 checkpoints)
- Training loss values were emitted for the logged intermediate steps; this report does not infer a validation improvement from training loss.
- A subsequent runtime check reported `IN-MEMORY GLOBAL STEP: 6000`, Step 6000 checkpoint present, size 700,611 bytes, and the SHA-256 below.

## 3. Final checkpoint

| Item | Value |
|---|---|
| File | `v2_teacher_transfer_run5000_step6000.json.gz` |
| Colab path | `/content/zyrquen-resume/checkpoints/v2_teacher_transfer_run5000_step6000.json.gz` |
| Global step reported | 6000 |
| Size | 700,611 bytes |
| SHA-256 | `3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7` |

The Step 5000 baseline SHA-256 was also re-reported unchanged:
`76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed`.

## 4. Checkpoint SHA-256 manifest

All entries below were reported as matching the files in the Colab checkpoint directory.

| Global step | Checkpoint SHA-256 |
|---:|---|
| 5025 | `1de745e95b02653a9dc4d9cd07a61c408553ac041256082e99fbbdf00e00e140` |
| 5050 | `3755c25a2e3c7e42e86349f3e283bfe1bc0e53cb836e4bb9b4d9cb5ce288dda0` |
| 5075 | `b289b0d6c588431b7a0443d6f5ef28cd99e8fe0dccfd70f4a560a17d5bd7b653` |
| 5100 | `ceef223f2751f2031a4a92516d4f42a108e3e387bd9f78c869504ea3954498fc` |
| 5125 | `4aa6ceab1132809647158b1b3ac0261c764217c744ec04c9e1df38611e3c0181` |
| 5150 | `53a5095ee2b74fd1094919141e5cbd4ff5f3521b28d7a6e9612f66813347ac72` |
| 5175 | `ff38aca43560457101fd5f0357f71767b42c717e86ba89366a3b665389399159` |
| 5200 | `801f1c064173b480bd75cc707d1795ef194b9673b5006835a8b6eb0a0ddfccc9` |
| 5225 | `499dfa5dc6e05dda0dc8ae04d160e645632b6dd146017c8c89e4733b08b4027e` |
| 5250 | `a185f847cec9ae4a73cd48998c612917adbf3d45e3ee50b4fb2e2612bfa869d3` |
| 5275 | `8b10636e775762cc1f4d7ee895baf5750f8850a1b7da9aaced90221dce050fc2` |
| 5300 | `285a473675c630dca1ff9b147d3e54e510a9233e83e83d3ecbad3859e9358df2` |
| 5325 | `56931475194b881be9e9d8c48007a764bf3a557e31702909af5bd8a21ed46294` |
| 5350 | `5fdc2aefcf9f77b54ca4ba36bcf498f0c7dfd37617f74be325cf76200fb65839` |
| 5375 | `a9c124e59116bf760aeab1273d6fe617b98c599258e2b9ed4c7450ef2a2e0b58` |
| 5400 | `8f93f6a1f996e755febf427c74779c35489a0b13e66c9dd6ff962ed4308effc7` |
| 5425 | `439a549e948c46a480a1aa1f465ba17dfc02e3a9b49c4e71b56e39977f75a09d` |
| 5450 | `001164a3fdf834a958dfad45028d941dba714590e039e7eed65e8ec246946fce` |
| 5475 | `eae1b6fa9798145bc4f77d566d2b1fdc8d0450addfa19e4cd80e5278a69691e7` |
| 5500 | `6b37593ef67a24729f8de2ec9349f7b3ccb2eb8a9e6054430f289a26070207a2` |
| 5525 | `bf1cc85e9e6221d8ec59bfcd182084735d4fa4792560d2c3ba89376d677d61fa` |
| 5550 | `883fd165bea22121e5d66813cc3357425ac7206e75126b79f1f7db0a697568c0` |
| 5575 | `b2f4e8575add3d5700b59c4d40b7bf1d64e10d7d27f1e5634a9ae6a296e21263` |
| 5600 | `8ba6e33f6eaa7d60911ee9ba3d3449a95b23b93711deddd27e368a2bed0b12b4` |
| 5625 | `8e52f2674096c054ccf6c846fcb3570232021ef9f11c58d9b685941bd0f7338e` |
| 5650 | `4fdce60b3ad836bd9a63b371d8c610a3efb135e14a94b3588c2cff8fad50c20a` |
| 5675 | `9fe00d7f6e73ff06cd18b65786b75109e7b3eacdcfb4f9a48ab415e3bb5441ad` |
| 5700 | `e3bfb82ce41c07ea009ac19ade9b4dadb11d26fb58e68fe10c3b9acc2d54900b` |
| 5725 | `adef12a38c715269bde139b88a20dba040501a7e05b8e03274f127ef48df36ed` |
| 5750 | `55549e8f24c4b4dd62e43a898dc035aa5fa9275b779395e98d06179c13b52e69` |
| 5775 | `cc4ccb15343175f32424fcca16b814996859ffb0c12d73412d0f06eab1b3f029` |
| 5800 | `9d17996720e8c72a3eeae61761aefd0495188911a83d152e89f3d8f42605c6f1` |
| 5825 | `ec0097e331167d81b13f92d6910962d68d7ba890cf21d925a6344b88310eec2f` |
| 5850 | `fba66bb041aae9cca57b43372e2159a94eefcbd682a3f40314a8bbd2adcbe5a8` |
| 5875 | `9ac2a73357d8a084e1a259c48a4b8eb3197415d9d29e585db2f5e4cf641f3a1f` |
| 5900 | `0b6d0b0e88f007ad663f30ce9a86f556a72d807814e5821e10c16f98558c431c` |
| 5925 | `6f078a01867a54545a24dede3fc4d982774c95a80fcb35111cfccf199f4034df` |
| 5950 | `afad144ed48bec461e9e22bfd8a4b1a7513cffa945a8e3a4f48ae98e2bf6c854` |
| 5975 | `abbc4c214d72a8f79339a89dc8c4b4ca97826a7df9e519d0f24c5bf4f7d6bd3a` |
| 6000 | `3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7` |

## 5. Storage and integrity boundaries

- Checkpoint binaries are intentionally **not committed to Git**; they remain in Colab / cloud storage.
- GitHub stores this experiment record and the SHA-256 manifest for traceability.
- The Step 5000 baseline is retained unchanged.
- The Step 6000 checkpoint is an unpromoted candidate; no production weights or default checkpoint were replaced.
- The runtime output establishes the reported in-memory step and file hash. A fresh-runtime checkpoint reload and held-out evaluation are still required before claiming verified model-quality improvement.

## 6. Evaluation and promotion

No before/after held-out evaluation metrics for the Step 5000-to-6000 continuation were supplied in this run record. Training loss alone is not a capability or generalization measure.

**Decision: preserve Step 6000 as an unpromoted candidate.** Before promotion:
1. Load Step 6000 in a fresh runtime with optimizer and continual state restored.
2. Verify its embedded global step equals 6000 and recompute the SHA-256.
3. Evaluate the same held-out validation and independent test sets against Step 5000.
4. Run task-level capability and regression checks.
5. Promote only after explicit review.
