import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

export interface PR56ManifestEntry {
  filename: string;
  sha256: string;
}

export interface CheckpointVerificationResult {
  verified: true;
  step: number;
  filename: string;
  path: string;
  expectedSha256: string;
  actualSha256: string;
  sizeBytes: number;
}

export const DEFAULT_CHECKPOINTS_DIR = '/content/zyrquen-resume/checkpoints';

/**
 * PR #56 SHA-256 manifest for ZYRQUEN Native V2 checkpoints.
 */
export const PR56_CHECKPOINT_MANIFEST: Record<number, PR56ManifestEntry> = {
  4000: {
    filename: 'v2_continued_step4000.json.gz',
    sha256: '0ca27a632e85bc7fde764b9948ceb9ed16a53911d5773bd51b5cd7c722a5237d',
  },
  4025: {
    filename: 'v2_continued_step4025.json.gz',
    sha256: 'f4b33c82a27a0a3f05b468d2ff1cf297746f7a3aa85ecbc03ff0093f34c75314',
  },
  5000: {
    filename: 'v2_teacher_transfer_step5000.json.gz',
    sha256: '76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed',
  },
  5025: {
    filename: 'v2_teacher_transfer_run5000_step5025.json.gz',
    sha256: '1de745e95b02653a9dc4d9cd07a61c408553ac041256082e99fbbdf00e00e140',
  },
  5050: {
    filename: 'v2_teacher_transfer_run5000_step5050.json.gz',
    sha256: '3755c25a2e3c7e42e86349f3e283bfe1bc0e53cb836e4bb9b4d9cb5ce288dda0',
  },
  5075: {
    filename: 'v2_teacher_transfer_run5000_step5075.json.gz',
    sha256: 'b289b0d6c588431b7a0443d6f5ef28cd99e8fe0dccfd70f4a560a17d5bd7b653',
  },
  5100: {
    filename: 'v2_teacher_transfer_run5000_step5100.json.gz',
    sha256: 'ceef223f2751f2031a4a92516d4f42a108e3e387bd9f78c869504ea3954498fc',
  },
  5125: {
    filename: 'v2_teacher_transfer_run5000_step5125.json.gz',
    sha256: '4aa6ceab1132809647158b1b3ac0261c764217c744ec04c9e1df38611e3c0181',
  },
  5150: {
    filename: 'v2_teacher_transfer_run5000_step5150.json.gz',
    sha256: '53a5095ee2b74fd1094919141e5cbd4ff5f3521b28d7a6e9612f66813347ac72',
  },
  5175: {
    filename: 'v2_teacher_transfer_run5000_step5175.json.gz',
    sha256: 'ff38aca43560457101fd5f0357f71767b42c717e86ba89366a3b665389399159',
  },
  5200: {
    filename: 'v2_teacher_transfer_run5000_step5200.json.gz',
    sha256: '801f1c064173b480bd75cc707d1795ef194b9673b5006835a8b6eb0a0ddfccc9',
  },
  5225: {
    filename: 'v2_teacher_transfer_run5000_step5225.json.gz',
    sha256: '499dfa5dc6e05dda0dc8ae04d160e645632b6dd146017c8c89e4733b08b4027e',
  },
  5250: {
    filename: 'v2_teacher_transfer_run5000_step5250.json.gz',
    sha256: 'a185f847cec9ae4a73cd48998c612917adbf3d45e3ee50b4fb2e2612bfa869d3',
  },
  5275: {
    filename: 'v2_teacher_transfer_run5000_step5275.json.gz',
    sha256: '8b10636e775762cc1f4d7ee895baf5750f8850a1b7da9aaced90221dce050fc2',
  },
  5300: {
    filename: 'v2_teacher_transfer_run5000_step5300.json.gz',
    sha256: '285a473675c630dca1ff9b147d3e54e510a9233e83e83d3ecbad3859e9358df2',
  },
  5325: {
    filename: 'v2_teacher_transfer_run5000_step5325.json.gz',
    sha256: '56931475194b881be9e9d8c48007a764bf3a557e31702909af5bd8a21ed46294',
  },
  5350: {
    filename: 'v2_teacher_transfer_run5000_step5350.json.gz',
    sha256: '5fdc2aefcf9f77b54ca4ba36bcf498f0c7dfd37617f74be325cf76200fb65839',
  },
  5375: {
    filename: 'v2_teacher_transfer_run5000_step5375.json.gz',
    sha256: 'a9c124e59116bf760aeab1273d6fe617b98c599258e2b9ed4c7450ef2a2e0b58',
  },
  5400: {
    filename: 'v2_teacher_transfer_run5000_step5400.json.gz',
    sha256: '8f93f6a1f996e755febf427c74779c35489a0b13e66c9dd6ff962ed4308effc7',
  },
  5425: {
    filename: 'v2_teacher_transfer_run5000_step5425.json.gz',
    sha256: '439a549e948c46a480a1aa1f465ba17dfc02e3a9b49c4e71b56e39977f75a09d',
  },
  5450: {
    filename: 'v2_teacher_transfer_run5000_step5450.json.gz',
    sha256: '001164a3fdf834a958dfad45028d941dba714590e039e7eed65e8ec246946fce',
  },
  5475: {
    filename: 'v2_teacher_transfer_run5000_step5475.json.gz',
    sha256: 'eae1b6fa9798145bc4f77d566d2b1fdc8d0450addfa19e4cd80e5278a69691e7',
  },
  5500: {
    filename: 'v2_teacher_transfer_run5000_step5500.json.gz',
    sha256: '6b37593ef67a24729f8de2ec9349f7b3ccb2eb8a9e6054430f289a26070207a2',
  },
  5525: {
    filename: 'v2_teacher_transfer_run5000_step5525.json.gz',
    sha256: 'bf1cc85e9e6221d8ec59bfcd182084735d4fa4792560d2c3ba89376d677d61fa',
  },
  5550: {
    filename: 'v2_teacher_transfer_run5000_step5550.json.gz',
    sha256: '883fd165bea22121e5d66813cc3357425ac7206e75126b79f1f7db0a697568c0',
  },
  5575: {
    filename: 'v2_teacher_transfer_run5000_step5575.json.gz',
    sha256: 'b2f4e8575add3d5700b59c4d40b7bf1d64e10d7d27f1e5634a9ae6a296e21263',
  },
  5600: {
    filename: 'v2_teacher_transfer_run5000_step5600.json.gz',
    sha256: '8ba6e33f6eaa7d60911ee9ba3d3449a95b23b93711deddd27e368a2bed0b12b4',
  },
  5625: {
    filename: 'v2_teacher_transfer_run5000_step5625.json.gz',
    sha256: '8e52f2674096c054ccf6c846fcb3570232021ef9f11c58d9b685941bd0f7338e',
  },
  5650: {
    filename: 'v2_teacher_transfer_run5000_step5650.json.gz',
    sha256: '4fdce60b3ad836bd9a63b371d8c610a3efb135e14a94b3588c2cff8fad50c20a',
  },
  5675: {
    filename: 'v2_teacher_transfer_run5000_step5675.json.gz',
    sha256: '9fe00d7f6e73ff06cd18b65786b75109e7b3eacdcfb4f9a48ab415e3bb5441ad',
  },
  5700: {
    filename: 'v2_teacher_transfer_run5000_step5700.json.gz',
    sha256: 'e3bfb82ce41c07ea009ac19ade9b4dadb11d26fb58e68fe10c3b9acc2d54900b',
  },
  5725: {
    filename: 'v2_teacher_transfer_run5000_step5725.json.gz',
    sha256: 'adef12a38c715269bde139b88a20dba040501a7e05b8e03274f127ef48df36ed',
  },
  5750: {
    filename: 'v2_teacher_transfer_run5000_step5750.json.gz',
    sha256: '55549e8f24c4b4dd62e43a898dc035aa5fa9275b779395e98d06179c13b52e69',
  },
  5775: {
    filename: 'v2_teacher_transfer_run5000_step5775.json.gz',
    sha256: 'cc4ccb15343175f32424fcca16b814996859ffb0c12d73412d0f06eab1b3f029',
  },
  5800: {
    filename: 'v2_teacher_transfer_run5000_step5800.json.gz',
    sha256: '9d17996720e8c72a3eeae61761aefd0495188911a83d152e89f3d8f42605c6f1',
  },
  5825: {
    filename: 'v2_teacher_transfer_run5000_step5825.json.gz',
    sha256: 'ec0097e331167d81b13f92d6910962d68d7ba890cf21d925a6344b88310eec2f',
  },
  5850: {
    filename: 'v2_teacher_transfer_run5000_step5850.json.gz',
    sha256: 'fba66bb041aae9cca57b43372e2159a94eefcbd682a3f40314a8bbd2adcbe5a8',
  },
  5875: {
    filename: 'v2_teacher_transfer_run5000_step5875.json.gz',
    sha256: '9ac2a73357d8a084e1a259c48a4b8eb3197415d9d29e585db2f5e4cf641f3a1f',
  },
  5900: {
    filename: 'v2_teacher_transfer_run5000_step5900.json.gz',
    sha256: '0b6d0b0e88f007ad663f30ce9a86f556a72d807814e5821e10c16f98558c431c',
  },
  5925: {
    filename: 'v2_teacher_transfer_run5000_step5925.json.gz',
    sha256: '6f078a01867a54545a24dede3fc4d982774c95a80fcb35111cfccf199f4034df',
  },
  5950: {
    filename: 'v2_teacher_transfer_run5000_step5950.json.gz',
    sha256: 'afad144ed48bec461e9e22bfd8a4b1a7513cffa945a8e3a4f48ae98e2bf6c854',
  },
  5975: {
    filename: 'v2_teacher_transfer_run5000_step5975.json.gz',
    sha256: 'abbc4c214d72a8f79339a89dc8c4b4ca97826a7df9e519d0f24c5bf4f7d6bd3a',
  },
  6000: {
    filename: 'v2_teacher_transfer_run5000_step6000.json.gz',
    sha256: '3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7',
  },
};

/**
 * Read the checkpoint file in `checkpointsDir` (default `/content/zyrquen-resume/checkpoints/`)
 * for `step` and verify its SHA-256 digest against the PR #56 manifest before loading.
 */
export function verify_checkpoint_hash(
  step: number,
  checkpointsDir: string = DEFAULT_CHECKPOINTS_DIR,
  manifest: Record<number, PR56ManifestEntry> = PR56_CHECKPOINT_MANIFEST,
): CheckpointVerificationResult {
  const entry = manifest[step];
  if (!entry) {
    throw new Error(
      `Checkpoint step ${step} is not recorded in the PR #56 SHA-256 manifest.`,
    );
  }

  const targetPath = path.join(checkpointsDir, entry.filename);
  if (!fs.existsSync(targetPath)) {
    throw new Error(
      `Checkpoint file not found for step ${step}: ${targetPath}`,
    );
  }

  const bytes = fs.readFileSync(targetPath);
  const actualSha256 = crypto
    .createHash('sha256')
    .update(bytes)
    .digest('hex')
    .toLowerCase();
  const expectedSha256 = entry.sha256.toLowerCase();

  if (actualSha256 !== expectedSha256) {
    throw new Error(
      `SHA-256 mismatch for step ${step} (${entry.filename}): expected ${expectedSha256}, got ${actualSha256}.`,
    );
  }

  return {
    verified: true,
    step,
    filename: entry.filename,
    path: targetPath,
    expectedSha256,
    actualSha256,
    sizeBytes: fs.statSync(targetPath).size,
  };
}
