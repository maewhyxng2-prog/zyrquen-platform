// @vitest-environment node
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { RestoreProofUiPayload } from '../types';

describe('RestoreProof Real HTTP + Python CLI E2E (Isolated Data Dir)', () => {
  let server: http.Server;
  let baseUrl = '';
  let tmpDataDir = '';
  let prevDataDir: string | undefined;
  let prevNoAutostart: string | undefined;
  let prevAdminPasscode: string | undefined;

  beforeAll(async () => {
    tmpDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-rp-e2e-'));
    prevDataDir = process.env.ZYRQUEN_DATA_DIR;
    prevNoAutostart = process.env.ZYRQUEN_NO_AUTOSTART;
    prevAdminPasscode = process.env.ZYRQUEN_ADMIN_PASSCODE;
    process.env.ZYRQUEN_DATA_DIR = tmpDataDir;
    process.env.ZYRQUEN_NO_AUTOSTART = '1';
    process.env.ZYRQUEN_ADMIN_PASSCODE = 'e2e-admin-passcode-only';

    const { createApp } = await import('../../server');
    const app = await createApp({ attachVite: false });
    await new Promise<void>((resolve) => {
      server = app.listen(0, '127.0.0.1', () => resolve());
    });
    const addr = server.address();
    if (!addr || typeof addr === 'string') {
      throw new Error('Failed to bind RestoreProof E2E port');
    }
    baseUrl = `http://127.0.0.1:${addr.port}`;
  }, 30_000);

  afterAll(async () => {
    await new Promise<void>((resolve) => {
      if (!server) return resolve();
      server.close(() => resolve());
    });
    if (prevDataDir === undefined) {
      delete process.env.ZYRQUEN_DATA_DIR;
    } else {
      process.env.ZYRQUEN_DATA_DIR = prevDataDir;
    }
    if (prevNoAutostart === undefined) {
      delete process.env.ZYRQUEN_NO_AUTOSTART;
    } else {
      process.env.ZYRQUEN_NO_AUTOSTART = prevNoAutostart;
    }
    if (prevAdminPasscode === undefined) {
      delete process.env.ZYRQUEN_ADMIN_PASSCODE;
    } else {
      process.env.ZYRQUEN_ADMIN_PASSCODE = prevAdminPasscode;
    }
    fs.rmSync(tmpDataDir, { recursive: true, force: true });
  });

  it('enforces auth, fail-closed empty status, real valid/3-failure scenarios, custom bundle tampering, and history reset', async () => {
    // 1. Unauthenticated request blocked with 401
    const unauthRes = await fetch(`${baseUrl}/api/restoreproof/status`);
    expect(unauthRes.status).toBe(401);

    // 2. Claim admin
    const claimRes = await fetch(`${baseUrl}/api/auth/claim-admin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: 'rp-admin@zyrquen.local',
        displayName: 'RP Admin',
        password: 'StrongPassword123!',
        passcode: 'e2e-admin-passcode-only',
      }),
    });
    expect(claimRes.status).toBe(201);
    const { token } = (await claimRes.json()) as { token: string };
    const headers = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    };

    // 3. Initial status is strictly fail-closed (no fake PASS or 100%)
    const initRes = await fetch(`${baseUrl}/api/restoreproof/status`, { headers });
    expect(initRes.status).toBe(200);
    const initJson = (await initRes.json()) as { ok: boolean; ui_payload: RestoreProofUiPayload };
    expect(initJson.ok).toBe(true);
    expect(initJson.ui_payload.is_demo).toBe(false);
    expect(initJson.ui_payload.summary.total_runs).toBe(0);
    expect(initJson.ui_payload.summary.pass_rate_pct).toBeNull();
    expect(initJson.ui_payload.latest_run).toBeNull();
    expect(initJson.ui_payload.reliability.score_pct).toBeNull();

    // 4. Valid SQLite backup scenario passes with real CLI evidence
    const validRes = await fetch(`${baseUrl}/api/restoreproof/verify-scenario`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ scenario: 'valid_sqlite_backup' }),
    });
    expect(validRes.status).toBe(201);
    const validJson = (await validRes.json()) as {
      ok: boolean;
      reports: Array<{ overall_passed: boolean; verified_restorable: boolean }>;
      ui_payload: RestoreProofUiPayload;
    };
    expect(validJson.ok).toBe(true);
    expect(validJson.reports[0].overall_passed).toBe(true);
    expect(validJson.ui_payload.summary.total_runs).toBe(1);
    expect(validJson.ui_payload.summary.pass_rate_pct).toBe(100);
    expect(validJson.ui_payload.reliability.score_pct).toBe(100);
    expect(validJson.ui_payload.steps.every((s) => s.status === 'passed')).toBe(true);

    // 5. Run all 3 real failure cases -> total 4 runs (1 passed, 3 failed)
    const failAllRes = await fetch(`${baseUrl}/api/restoreproof/verify-scenario`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ scenario: 'run_all_3_failures' }),
    });
    expect(failAllRes.status).toBe(201);
    const failAllJson = (await failAllRes.json()) as {
      ok: boolean;
      reports: Array<{
        overall_passed: boolean;
        verified_restorable: boolean;
        completeness_ok: boolean;
        health_check_ok: boolean;
        metrics: { missing_files: string[]; hash_mismatches: string[]; health_cmd_rc: number | null };
      }>;
      ui_payload: RestoreProofUiPayload;
    };
    expect(failAllJson.reports).toHaveLength(3);
    expect(failAllJson.reports[0].verified_restorable).toBe(false); // corrupt archive
    expect(failAllJson.reports[1].completeness_ok).toBe(false); // missing + tampered
    expect(failAllJson.reports[1].metrics.missing_files).toContain('app.sqlite');
    expect(failAllJson.reports[1].metrics.hash_mismatches).toContain('config.json');
    expect(failAllJson.reports[2].health_check_ok).toBe(false); // health probe exit 3
    expect(failAllJson.reports[2].metrics.health_cmd_rc).toBe(3);

    expect(failAllJson.ui_payload.summary.total_runs).toBe(4);
    expect(failAllJson.ui_payload.summary.passed_runs).toBe(1);
    expect(failAllJson.ui_payload.summary.failed_runs).toBe(3);
    expect(failAllJson.ui_payload.summary.pass_rate_pct).toBe(25);
    expect(failAllJson.ui_payload.latest_run?.status).toBe('failed');

    // 6. Custom bundle blocks path traversal & detects real tampering
    const travRes = await fetch(`${baseUrl}/api/restoreproof/verify-bundle`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        files: [{ path: '../../etc/passwd', content: 'bad' }],
      }),
    });
    expect(travRes.status).toBe(400);

    const tamperBundleRes = await fetch(`${baseUrl}/api/restoreproof/verify-bundle`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        sourceName: 'Custom Tamper Check',
        files: [
          { path: 'cfg.json', content: '{"ok": true}' },
          { path: 'data.txt', content: 'row1\n' },
        ],
        simulateTamper: 'tamper_first_file',
      }),
    });
    expect(tamperBundleRes.status).toBe(201);
    const tamperJson = (await tamperBundleRes.json()) as {
      report: { overall_passed: boolean; metrics: { hash_mismatches: string[] } };
      ui_payload: RestoreProofUiPayload;
    };
    expect(tamperJson.report.overall_passed).toBe(false);
    expect(tamperJson.report.metrics.hash_mismatches).toEqual(['cfg.json']);
    expect(tamperJson.ui_payload.summary.total_runs).toBe(5);

    // 7. DELETE /api/restoreproof/history restores fail-closed empty state
    const delRes = await fetch(`${baseUrl}/api/restoreproof/history`, {
      method: 'DELETE',
      headers,
    });
    expect(delRes.status).toBe(200);
    const delJson = (await delRes.json()) as { ok: boolean; ui_payload: RestoreProofUiPayload };
    expect(delJson.ok).toBe(true);
    expect(delJson.ui_payload.summary.total_runs).toBe(0);
    expect(delJson.ui_payload.latest_run).toBeNull();
  }, 60_000);
});
