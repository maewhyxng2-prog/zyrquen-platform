import { execFile } from 'child_process';
import crypto from 'crypto';
import type { Express, NextFunction, Request, Response } from 'express';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export type RestoreProofScenario =
  | 'valid_sqlite_backup'
  | 'corrupt_archive'
  | 'missing_tampered_file'
  | 'failed_health_check'
  | 'run_all_3_failures';

export type BundleTamperSimulation =
  | 'none'
  | 'corrupt_archive'
  | 'drop_first_file'
  | 'tamper_first_file'
  | 'fail_health_check';

const ALLOWED_SCENARIOS = new Set<RestoreProofScenario>([
  'valid_sqlite_backup',
  'corrupt_archive',
  'missing_tampered_file',
  'failed_health_check',
  'run_all_3_failures',
]);

const ALLOWED_SIMULATIONS = new Set<BundleTamperSimulation>([
  'none',
  'corrupt_archive',
  'drop_first_file',
  'tamper_first_file',
  'fail_health_check',
]);

function getDataDir(): string {
  const dir = process.env.ZYRQUEN_DATA_DIR
    ? path.resolve(process.env.ZYRQUEN_DATA_DIR)
    : path.resolve(__dirname, 'data');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function getHistoryPaths() {
  const dir = getDataDir();
  return {
    historyFile: path.join(dir, 'restoreproof_history.json'),
    metaFile: path.join(dir, 'restoreproof_meta.json'),
  };
}

function readStoredHistory(): Record<string, unknown>[] {
  const { historyFile } = getHistoryPaths();
  if (!fs.existsSync(historyFile)) return [];
  try {
    const parsed = JSON.parse(fs.readFileSync(historyFile, 'utf-8'));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStoredHistory(reports: Record<string, unknown>[], sourceName: string, backupType: string): void {
  const { historyFile, metaFile } = getHistoryPaths();
  const capped = reports.slice(-100);
  fs.writeFileSync(historyFile, JSON.stringify(capped, null, 2), 'utf-8');
  fs.writeFileSync(metaFile, JSON.stringify({ sourceName, backupType }, null, 2), 'utf-8');
}

function readStoredMeta(): { sourceName: string; backupType: string } {
  const { metaFile } = getHistoryPaths();
  if (!fs.existsSync(metaFile)) {
    return {
      sourceName: 'ZYRQUEN Backup Verification Sandbox',
      backupType: 'Archive / Backup (.zip)',
    };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(metaFile, 'utf-8')) as {
      sourceName?: string;
      backupType?: string;
    };
    return {
      sourceName: parsed.sourceName || 'ZYRQUEN Backup Verification Sandbox',
      backupType: parsed.backupType || 'Archive / Backup (.zip)',
    };
  } catch {
    return {
      sourceName: 'ZYRQUEN Backup Verification Sandbox',
      backupType: 'Archive / Backup (.zip)',
    };
  }
}

function emptyFailClosedPayload(sourceName: string, backupType: string) {
  return {
    schema_version: '1.0.0',
    product: 'RealityCheck — RestoreProof',
    source_mode: 'live_verification',
    is_demo: false,
    generated_at: new Date().toISOString(),
    summary: {
      total_runs: 0,
      runs_today: 0,
      passed_runs: 0,
      failed_runs: 0,
      pass_rate_pct: null,
      avg_duration_sec: null,
      avg_duration_label: null,
    },
    latest_run: null,
    steps: [],
    technical_details: null,
    history: [],
    reliability: {
      score_pct: null,
      score_label: null,
      computation_rule: 'no_verified_runs_yet',
      checks: [],
      verdict_text: 'ยังไม่มีหลักฐานการตรวจสอบจริง ไม่สามารถยืนยันความพร้อมใช้งานได้',
    },
    meta: { sourceName, backupType },
  };
}

async function buildUiPayloadViaPython(
  reports: Record<string, unknown>[],
  sourceName: string,
  backupType: string
): Promise<Record<string, unknown>> {
  const script = `
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(${JSON.stringify(path.resolve(__dirname, 'python_core'))})))
from restoreproof_cli.engine import RestoreProofReport
from restoreproof_cli.ui_adapter import build_ui_payload
raw = json.loads(sys.stdin.read())
reports = [RestoreProofReport(**r) for r in raw["reports"]]
payload = build_ui_payload(
    history_reports=reports,
    source_name=raw["source_name"],
    backup_type=raw["backup_type"],
    is_demo=False,
)
print(json.dumps(payload, ensure_ascii=False))
`.trim();

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-ui-'));
  try {
    const tmpPy = path.join(tmpDir, 'build_ui.py');
    fs.writeFileSync(tmpPy, script, 'utf-8');
    const childPromise = new Promise<string>((resolve, reject) => {
      const proc = execFile(
        'python3',
        [tmpPy],
        { cwd: __dirname, timeout: 15_000, maxBuffer: 4 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) {
            reject(new Error(stderr || err.message));
            return;
          }
          resolve(stdout);
        }
      );
      proc.stdin?.end(
        JSON.stringify({
          reports,
          source_name: sourceName,
          backup_type: backupType,
        })
      );
    });
    const out = await childPromise;
    return JSON.parse(out) as Record<string, unknown>;
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function invokeRestoreProofCli(args: string[]): Promise<{
  exitCode: number;
  stdout: string;
  stderr: string;
}> {
  const cliPath = path.resolve(__dirname, 'python_core', 'restoreproof_cli', 'cli.py');
  try {
    const { stdout, stderr } = await execFileAsync('python3', [cliPath, ...args], {
      cwd: __dirname,
      timeout: 30_000,
      maxBuffer: 4 * 1024 * 1024,
    });
    return { exitCode: 0, stdout, stderr };
  } catch (err: unknown) {
    const execErr = err as { code?: number; stdout?: string; stderr?: string; message?: string };
    if (typeof execErr.code === 'number' && (execErr.code === 1 || execErr.code === 0)) {
      return {
        exitCode: execErr.code,
        stdout: execErr.stdout || '',
        stderr: execErr.stderr || '',
      };
    }
    throw new Error(execErr.stderr || execErr.message || 'RestoreProof CLI execution failed', {
      cause: err,
    });
  }
}

async function runSingleScenario(
  scenario: Exclude<RestoreProofScenario, 'run_all_3_failures'>,
  priorHistory: Record<string, unknown>[]
): Promise<{
  report: Record<string, unknown>;
  uiPayload: Record<string, unknown>;
  sourceName: string;
  backupType: string;
}> {
  const sandboxDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-rp-scenario-'));
  try {
    const srcDir = path.join(sandboxDir, 'src');
    fs.mkdirSync(srcDir, { recursive: true });
    const prepScript = path.join(sandboxDir, 'prep.py');
    const historyInPath = path.join(sandboxDir, 'history_in.json');
    const outReportPath = path.join(sandboxDir, 'report.json');
    const outUiPath = path.join(sandboxDir, 'ui_payload.json');
    fs.writeFileSync(historyInPath, JSON.stringify(priorHistory), 'utf-8');

    const pyPrep = `
import hashlib, json, shutil, sqlite3
from pathlib import Path

sandbox = Path(${JSON.stringify(sandboxDir)})
src = sandbox / "src"
ledger = src / "ledger.txt"
config = src / "config.json"
db_path = src / "app.sqlite"

ledger.write_text("tx=100\\ntx=200\\ntx=300\\n", encoding="utf-8")
config.write_text('{"mode": "strict", "backup_policy": "fail_closed"}\\n', encoding="utf-8")

with sqlite3.connect(db_path) as conn:
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance INTEGER)")
    conn.execute("INSERT INTO accounts (id, balance) VALUES (1, 500), (2, 750)")
    conn.commit()

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

manifest = {
    "files": {
        "ledger.txt": sha(ledger),
        "config.json": sha(config),
        "app.sqlite": sha(db_path),
    }
}
(sandbox / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

scenario = ${JSON.stringify(scenario)}
if scenario == "corrupt_archive":
    (sandbox / "backup.zip").write_bytes(b"NOT_A_VALID_ZIP_CORRUPT_HEADER_000000")
elif scenario == "missing_tampered_file":
    db_path.unlink()
    config.write_text('{"mode": "tampered_outside_manifest"}\\n', encoding="utf-8")
    shutil.make_archive(str(sandbox / "backup"), "zip", root_dir=str(src))
else:
    shutil.make_archive(str(sandbox / "backup"), "zip", root_dir=str(src))
`.trim();

    fs.writeFileSync(prepScript, pyPrep, 'utf-8');
    await execFileAsync('python3', [prepScript], { cwd: sandboxDir, timeout: 15_000 });

    const sourceMap: Record<Exclude<RestoreProofScenario, 'run_all_3_failures'>, { sourceName: string; backupType: string }> = {
      valid_sqlite_backup: {
        sourceName: 'Production SQLite Vault (Real Restore Test)',
        backupType: 'SQLite + Config (.zip)',
      },
      corrupt_archive: {
        sourceName: 'Corrupt Archive Probe (Failure Case 1)',
        backupType: 'Damaged Archive (.zip)',
      },
      missing_tampered_file: {
        sourceName: 'Tampered/Missing Manifest Probe (Failure Case 2)',
        backupType: 'SQLite + Config (.zip)',
      },
      failed_health_check: {
        sourceName: 'Service Readiness Probe (Failure Case 3)',
        backupType: 'SQLite + Config (.zip)',
      },
    };

    const { sourceName, backupType } = sourceMap[scenario];
    const cliArgs = [
      'verify',
      '--backup',
      path.join(sandboxDir, 'backup.zip'),
      '--min-files',
      '3',
      '--manifest',
      path.join(sandboxDir, 'manifest.json'),
      '--history-in',
      historyInPath,
      '--out',
      outReportPath,
      '--ui-out',
      outUiPath,
      '--source-name',
      sourceName,
      '--backup-type',
      backupType,
    ];

    if (scenario === 'valid_sqlite_backup') {
      cliArgs.push(
        '--health-cmd',
        `python3 -c "import sqlite3; c = sqlite3.connect('app.sqlite'); s = c.execute('SELECT SUM(balance) FROM accounts').fetchone()[0]; assert s == 1250, s; print('SQLITE_HEALTH_OK sum=' + str(s))"`
      );
    } else if (scenario === 'failed_health_check') {
      cliArgs.push(
        '--health-cmd',
        `python3 -c "import sys; print('DB_SCHEMA_MIGRATION_INCOMPLETE', file=sys.stderr); sys.exit(3)"`
      );
    }

    await invokeRestoreProofCli(cliArgs);

    const report = JSON.parse(fs.readFileSync(outReportPath, 'utf-8')) as Record<string, unknown>;
    const uiPayload = JSON.parse(fs.readFileSync(outUiPath, 'utf-8')) as Record<string, unknown>;
    return { report, uiPayload, sourceName, backupType };
  } finally {
    fs.rmSync(sandboxDir, { recursive: true, force: true });
  }
}

function isSafeRelativeFilePath(rawPath: string): boolean {
  const trimmed = rawPath.trim();
  if (!trimmed || trimmed.length > 180) return false;
  if (trimmed.includes('\0') || trimmed.includes('\\') || trimmed.includes(':')) return false;
  if (trimmed.startsWith('/')) return false;
  const segments = trimmed.split('/');
  return segments.every((seg) => seg.length > 0 && seg !== '.' && seg !== '..');
}

export function registerRestoreProofRoutes(
  app: Express,
  requireAuth: (req: Request, res: Response, next: NextFunction) => Promise<void> | void
): void {
  app.get('/api/restoreproof/status', requireAuth, async (_req: Request, res: Response) => {
    const history = readStoredHistory();
    const meta = readStoredMeta();
    if (history.length === 0) {
      res.json({ ok: true, ui_payload: emptyFailClosedPayload(meta.sourceName, meta.backupType) });
      return;
    }
    try {
      const uiPayload = await buildUiPayloadViaPython(history, meta.sourceName, meta.backupType);
      res.json({ ok: true, ui_payload: uiPayload });
    } catch (err) {
      res.status(500).json({
        error: err instanceof Error ? err.message : 'Failed to build RestoreProof status',
      });
    }
  });

  app.post('/api/restoreproof/verify-scenario', requireAuth, async (req: Request, res: Response) => {
    const scenario = String(req.body?.scenario || '') as RestoreProofScenario;
    if (!ALLOWED_SCENARIOS.has(scenario)) {
      res.status(400).json({ error: 'Invalid RestoreProof scenario selected' });
      return;
    }

    try {
      let history = readStoredHistory();
      const newReports: Record<string, unknown>[] = [];
      let latestUiPayload: Record<string, unknown> | null = null;
      let lastSource = 'ZYRQUEN Backup Verification Sandbox';
      let lastType = 'Archive / Backup (.zip)';

      const sequence: Array<Exclude<RestoreProofScenario, 'run_all_3_failures'>> =
        scenario === 'run_all_3_failures'
          ? ['corrupt_archive', 'missing_tampered_file', 'failed_health_check']
          : [scenario];

      for (const item of sequence) {
        const result = await runSingleScenario(item, history);
        history = [...history, result.report];
        newReports.push(result.report);
        latestUiPayload = result.uiPayload;
        lastSource = result.sourceName;
        lastType = result.backupType;
      }

      writeStoredHistory(history, lastSource, lastType);
      res.status(201).json({
        ok: true,
        reports: newReports,
        ui_payload: latestUiPayload,
      });
    } catch (err) {
      res.status(500).json({
        error: err instanceof Error ? err.message : 'RestoreProof verification execution failed',
      });
    }
  });

  app.post('/api/restoreproof/verify-bundle', requireAuth, async (req: Request, res: Response) => {
    const rawFiles = req.body?.files;
    if (!Array.isArray(rawFiles) || rawFiles.length === 0 || rawFiles.length > 50) {
      res.status(400).json({ error: 'files must be a non-empty array (1 to 50 files)' });
      return;
    }

    const sourceName =
      String(req.body?.sourceName || 'Custom Backup Bundle').trim().slice(0, 100) ||
      'Custom Backup Bundle';
    const backupType =
      String(req.body?.backupType || 'Custom Bundle (.zip)').trim().slice(0, 80) ||
      'Custom Bundle (.zip)';
    const minFilesReq = Number(req.body?.minFiles);
    const minFiles =
      Number.isInteger(minFilesReq) && minFilesReq >= 1 ? minFilesReq : rawFiles.length;
    const simulateTamper = String(req.body?.simulateTamper || 'none') as BundleTamperSimulation;
    if (!ALLOWED_SIMULATIONS.has(simulateTamper)) {
      res.status(400).json({ error: 'Invalid simulateTamper option' });
      return;
    }

    const sanitizedFiles: Array<{ path: string; content: string }> = [];
    let totalBytes = 0;
    for (const entry of rawFiles) {
      if (!entry || typeof entry !== 'object') {
        res.status(400).json({ error: 'Each file entry must be an object' });
        return;
      }
      const relPath = String((entry as { path?: unknown }).path || '').trim();
      const content = String((entry as { content?: unknown }).content ?? '');
      if (!isSafeRelativeFilePath(relPath)) {
        res.status(400).json({ error: `Unsafe or invalid relative file path: ${relPath}` });
        return;
      }
      totalBytes += Buffer.byteLength(content, 'utf-8');
      if (totalBytes > 512 * 1024) {
        res.status(400).json({ error: 'Total bundle content exceeds 512 KB limit' });
        return;
      }
      sanitizedFiles.push({ path: relPath, content });
    }

    const sandboxDir = fs.mkdtempSync(path.join(os.tmpdir(), 'zyrquen-rp-bundle-'));
    try {
      const srcDir = path.join(sandboxDir, 'src');
      fs.mkdirSync(srcDir, { recursive: true });
      const manifestHashes: Record<string, string> = {};

      for (const f of sanitizedFiles) {
        const dest = path.resolve(srcDir, f.path);
        if (!dest.startsWith(srcDir + path.sep)) {
          res.status(400).json({ error: `Path escapes bundle root: ${f.path}` });
          return;
        }
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, f.content, 'utf-8');
        manifestHashes[f.path] = crypto.createHash('sha256').update(f.content, 'utf-8').digest('hex');
      }

      const manifestPath = path.join(sandboxDir, 'manifest.json');
      fs.writeFileSync(manifestPath, JSON.stringify({ files: manifestHashes }), 'utf-8');

      const prepScript = path.join(sandboxDir, 'pack.py');
      const pyPack = `
import shutil
from pathlib import Path
sandbox = Path(${JSON.stringify(sandboxDir)})
src = sandbox / "src"
sim = ${JSON.stringify(simulateTamper)}
first_rel = ${JSON.stringify(sanitizedFiles[0].path)}
if sim == "corrupt_archive":
    (sandbox / "backup.zip").write_bytes(b"CORRUPTED_USER_BUNDLE_BYTES")
elif sim == "drop_first_file":
    (src / first_rel).unlink()
    shutil.make_archive(str(sandbox / "backup"), "zip", root_dir=str(src))
elif sim == "tamper_first_file":
    p = src / first_rel
    p.write_text(p.read_text(encoding="utf-8", errors="replace") + "\\n# TAMPERED", encoding="utf-8")
    shutil.make_archive(str(sandbox / "backup"), "zip", root_dir=str(src))
else:
    shutil.make_archive(str(sandbox / "backup"), "zip", root_dir=str(src))
`.trim();
      fs.writeFileSync(prepScript, pyPack, 'utf-8');
      await execFileAsync('python3', [prepScript], { cwd: sandboxDir, timeout: 15_000 });

      const priorHistory = readStoredHistory();
      const historyInPath = path.join(sandboxDir, 'history_in.json');
      const outReportPath = path.join(sandboxDir, 'report.json');
      const outUiPath = path.join(sandboxDir, 'ui_payload.json');
      fs.writeFileSync(historyInPath, JSON.stringify(priorHistory), 'utf-8');

      const cliArgs = [
        'verify',
        '--backup',
        path.join(sandboxDir, 'backup.zip'),
        '--min-files',
        String(minFiles),
        '--manifest',
        manifestPath,
        '--history-in',
        historyInPath,
        '--out',
        outReportPath,
        '--ui-out',
        outUiPath,
        '--source-name',
        sourceName,
        '--backup-type',
        backupType,
      ];
      if (simulateTamper === 'fail_health_check') {
        cliArgs.push(
          '--health-cmd',
          'python3 -c "import sys; print(\'BUNDLE_HEALTH_PROBE_FAILED\', file=sys.stderr); sys.exit(4)"'
        );
      } else {
        cliArgs.push(
          '--health-cmd',
          `python3 -c "from pathlib import Path; assert len([p for p in Path('.').rglob('*') if p.is_file()]) >= ${minFiles}"`
        );
      }

      await invokeRestoreProofCli(cliArgs);

      const report = JSON.parse(fs.readFileSync(outReportPath, 'utf-8')) as Record<string, unknown>;
      const uiPayload = JSON.parse(fs.readFileSync(outUiPath, 'utf-8')) as Record<string, unknown>;
      writeStoredHistory([...priorHistory, report], sourceName, backupType);

      res.status(201).json({ ok: true, report, ui_payload: uiPayload });
    } catch (err) {
      res.status(500).json({
        error: err instanceof Error ? err.message : 'Custom bundle verification failed',
      });
    } finally {
      fs.rmSync(sandboxDir, { recursive: true, force: true });
    }
  });

  app.delete('/api/restoreproof/history', requireAuth, (_req: Request, res: Response) => {
    const { historyFile, metaFile } = getHistoryPaths();
    if (fs.existsSync(historyFile)) fs.unlinkSync(historyFile);
    if (fs.existsSync(metaFile)) fs.unlinkSync(metaFile);
    res.json({
      ok: true,
      ui_payload: emptyFailClosedPayload(
        'ZYRQUEN Backup Verification Sandbox',
        'Archive / Backup (.zip)'
      ),
    });
  });
}
