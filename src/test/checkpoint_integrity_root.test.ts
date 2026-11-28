import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CHECKPOINTS_DIR,
  PR56_CHECKPOINT_MANIFEST,
  verify_checkpoint_hash,
} from '../../lib/checkpoint-integrity';

describe('lib/checkpoint-integrity verify_checkpoint_hash', () => {
  it('defaults to /content/zyrquen-resume/checkpoints and includes PR #56 Step 5000/6000 digests', () => {
    expect(DEFAULT_CHECKPOINTS_DIR).toBe('/content/zyrquen-resume/checkpoints');
    expect(PR56_CHECKPOINT_MANIFEST[5000]).toEqual({
      filename: 'v2_teacher_transfer_step5000.json.gz',
      sha256: '76c85f56c615590906bee1f7893e22301f7be1d430130cd2b882e1921d9d72ed',
    });
    expect(PR56_CHECKPOINT_MANIFEST[6000]).toEqual({
      filename: 'v2_teacher_transfer_run5000_step6000.json.gz',
      sha256: '3b7f0ed4de259a0b1db2135caf193c074409cadb3a599ae4656cfd4b3dffbca7',
    });
  });

  it('rejects unknown steps, missing files, and corrupted payloads while passing matching SHA-256', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-lib-ckpt-'));
    try {
      expect(() => verify_checkpoint_hash(9999, tmpDir)).toThrow(
        'not recorded in the PR #56',
      );
      expect(() => verify_checkpoint_hash(6000, tmpDir)).toThrow(
        'Checkpoint file not found',
      );

      const ckpt6000 = path.join(
        tmpDir,
        PR56_CHECKPOINT_MANIFEST[6000].filename,
      );
      fs.writeFileSync(ckpt6000, Buffer.from('corrupted-bytes'));
      expect(() => verify_checkpoint_hash(6000, tmpDir)).toThrow(
        'SHA-256 mismatch for step 6000',
      );

      const validPayload = Buffer.from('verified-checkpoint-payload');
      const validDigest = crypto
        .createHash('sha256')
        .update(validPayload)
        .digest('hex');
      fs.writeFileSync(ckpt6000, validPayload);

      const result = verify_checkpoint_hash(6000, tmpDir, {
        6000: {
          filename: PR56_CHECKPOINT_MANIFEST[6000].filename,
          sha256: validDigest,
        },
      });
      expect(result.verified).toBe(true);
      expect(result.step).toBe(6000);
      expect(result.actualSha256).toBe(validDigest);
      expect(result.sizeBytes).toBe(validPayload.length);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
