import React, { useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Clock,
  FileCheck2,
  FolderUp,
  Loader2,
  Play,
  Plus,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  XCircle,
} from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { apiRequest, ApiError } from '../lib/api';
import type {
  RestoreProofStepStatus,
  RestoreProofUiPayload,
} from '../types';
import { CopyButton } from './CopyButton';

const EMPTY_LIVE_PAYLOAD: RestoreProofUiPayload = {
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
};

const DEMO_FIXTURE_PAYLOAD: RestoreProofUiPayload = {
  schema_version: '1.0.0',
  product: 'RealityCheck — RestoreProof',
  source_mode: 'demo_fixture',
  is_demo: true,
  generated_at: '2026-11-26T06:00:00+00:00',
  summary: {
    total_runs: 6,
    runs_today: 2,
    passed_runs: 5,
    failed_runs: 1,
    pass_rate_pct: 83.33,
    avg_duration_sec: 1.84,
    avg_duration_label: '2 วินาที',
  },
  latest_run: {
    run_id: 'demo_run_20261126',
    status: 'passed',
    status_label: 'ผ่านการตรวจสอบ (DEMO)',
    headline: 'ข้อมูลตัวอย่าง: Backup สามารถกู้คืนได้จริงและผ่าน health check ใน sandbox ตัวอย่าง',
    checked_at: '2026-11-26T05:58:00+00:00',
    source_name: 'demo-postgres-ledger.tar.gz',
    data_size_bytes: 14820480,
    data_size_label: '14.1 MB',
    duration_sec: 1.72,
    duration_label: '2 วินาที',
    discrepancies: [],
  },
  steps: [
    {
      step_key: 'integrity_check',
      title: 'ตรวจสอบข้อมูล Backup (Integrity Check)',
      status: 'passed',
      duration_sec: 0.19,
      duration_label: '190 ms',
      detail: 'ตรวจสอบไฟล์ Backup และคำนวณ SHA-256 เรียบร้อย',
    },
    {
      step_key: 'isolated_restore',
      title: 'ทดลอง Restore ในระบบแยก',
      status: 'passed',
      duration_sec: 0.92,
      duration_label: '920 ms',
      detail: 'ทดลองแตกไฟล์และกู้คืนในพื้นที่แยกสำเร็จ',
    },
    {
      step_key: 'data_completeness',
      title: 'ตรวจสอบความครบถ้วนของข้อมูล',
      status: 'passed',
      duration_sec: 0.28,
      duration_label: '280 ms',
      detail: 'จำนวนไฟล์ 14 ไฟล์ ตรงตามเกณฑ์และ manifest SHA-256',
    },
    {
      step_key: 'service_health',
      title: 'ตรวจสอบการทำงานของบริการ',
      status: 'passed',
      duration_sec: 0.33,
      duration_label: '330 ms',
      detail: 'คำสั่งตรวจสอบสุขภาพบริการผ่าน (exit code 0)',
    },
  ],
  technical_details: {
    backup_type: 'Demo Snapshot (.tar.gz)',
    file_size_label: '14.1 MB',
    checksum_sha256: '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a',
    checksum_short: '4b227777d4....bf8a',
    restore_time_label: '920 ms',
    data_integrity_pct: 100.0,
    data_integrity_label: '100.00%',
    service_status: 'OK',
  },
  history: [
    { date: '2026-11-24', label: '24/11', passed_count: 2, failed_count: 0, pass_rate_pct: 100 },
    { date: '2026-11-25', label: '25/11', passed_count: 1, failed_count: 1, pass_rate_pct: 50 },
    { date: '2026-11-26', label: '26/11', passed_count: 2, failed_count: 0, pass_rate_pct: 100 },
  ],
  reliability: {
    score_pct: 83.33,
    score_label: '83.33%',
    computation_rule: 'min(historical_pass_rate_pct, latest_verified_subchecks_pct)',
    checks: [
      { key: 'restore_verified', label: 'Restore สำเร็จ', passed: true },
      { key: 'data_complete', label: 'ข้อมูลครบถ้วน', passed: true },
      { key: 'service_healthy', label: 'บริการทำงานปกติ', passed: true },
    ],
    verdict_text: 'ข้อมูลตัวอย่าง: รอบล่าสุดผ่าน แต่ประวัติรวมผ่าน 5/6 ครั้ง — ควรตรวจรอบที่ล้มเหลวย้อนหลัง',
  },
};

type ScenarioId =
  | 'valid_sqlite_backup'
  | 'corrupt_archive'
  | 'missing_tampered_file'
  | 'failed_health_check'
  | 'run_all_3_failures';

type TamperSimulation =
  | 'none'
  | 'corrupt_archive'
  | 'drop_first_file'
  | 'tamper_first_file'
  | 'fail_health_check';

interface BundleFileDraft {
  id: string;
  path: string;
  content: string;
}

interface RestoreProofPanelProps {
  token: string;
}

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('th-TH', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function stepStatusDisplay(status: RestoreProofStepStatus): {
  label: string;
  colorClass: string;
  surfaceClass: string;
} {
  switch (status) {
    case 'passed':
      return {
        label: 'PASSED',
        colorClass: 'text-[var(--color-success)]',
        surfaceClass: 'border-[var(--color-success)]/35 bg-[var(--color-success-bg)]',
      };
    case 'failed':
      return {
        label: 'FAILED',
        colorClass: 'text-[var(--color-danger)]',
        surfaceClass: 'border-[var(--color-danger)]/35 bg-[var(--color-danger-bg)]',
      };
    case 'not_run':
      return {
        label: 'NOT RUN',
        colorClass: 'text-[var(--color-warning)]',
        surfaceClass: 'border-[var(--color-warning)]/35 bg-[var(--color-warning-bg)]',
      };
    default:
      return {
        label: 'PENDING',
        colorClass: 'text-[var(--color-text-muted)]',
        surfaceClass: 'border-[var(--color-border)] bg-[var(--color-surface)]',
      };
  }
}

function isValidUiPayload(raw: unknown): raw is RestoreProofUiPayload {
  if (!raw || typeof raw !== 'object') return false;
  const obj = raw as Partial<RestoreProofUiPayload>;
  return (
    typeof obj.schema_version === 'string' &&
    Boolean(obj.summary && typeof obj.summary.total_runs === 'number') &&
    Boolean(obj.reliability && typeof obj.reliability.verdict_text === 'string') &&
    Array.isArray(obj.steps) &&
    Array.isArray(obj.history)
  );
}

export function RestoreProofPanel({ token }: RestoreProofPanelProps) {
  const [payload, setPayload] = useState<RestoreProofUiPayload>(EMPTY_LIVE_PAYLOAD);
  const [liveBackup, setLiveBackup] = useState<RestoreProofUiPayload>(EMPTY_LIVE_PAYLOAD);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);
  const [showCustomForm, setShowCustomForm] = useState(false);

  const [bundleSourceName, setBundleSourceName] = useState('custom-service-backup.zip');
  const [bundleTamper, setBundleTamper] = useState<TamperSimulation>('none');
  const [bundleFiles, setBundleFiles] = useState<BundleFileDraft[]>([
    {
      id: 'f1',
      path: 'config/app.json',
      content: '{"service": "billing-api", "mode": "fail_closed", "version": 1}\n',
    },
    {
      id: 'f2',
      path: 'ledger/entries.csv',
      content: 'id,amount\n1,500\n2,750\n',
    },
  ]);

  const jsonUploadRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(async () => {
      try {
        const res = await apiRequest<{ ok: boolean; ui_payload: RestoreProofUiPayload }>(
          '/api/restoreproof/status',
          { token }
        );
        if (!active) return;
        if (res.ui_payload) {
          setLiveBackup(res.ui_payload);
          setPayload(res.ui_payload);
        }
        setError(null);
      } catch (err) {
        if (!active) return;
        setError(
          err instanceof ApiError
            ? err.message
            : 'ไม่สามารถโหลดสถานะ RestoreProof จากเซิร์ฟเวอร์ได้ (คงสถานะ UNVERIFIED แบบ Fail-Closed)'
        );
        setPayload(EMPTY_LIVE_PAYLOAD);
      } finally {
        if (active) setLoadingStatus(false);
      }
    });
    return () => {
      active = false;
    };
  }, [token]);

  async function handleRunScenario(scenario: ScenarioId) {
    setRunningAction(scenario);
    setError(null);
    setStatusNotice(null);
    try {
      const res = await apiRequest<{
        ok: boolean;
        reports: Array<{ overall_passed: boolean }>;
        ui_payload: RestoreProofUiPayload;
      }>('/api/restoreproof/verify-scenario', {
        method: 'POST',
        token,
        body: { scenario },
      });
      if (res.ui_payload) {
        setLiveBackup(res.ui_payload);
        setPayload(res.ui_payload);
        const passed = res.reports.filter((r) => r.overall_passed).length;
        setStatusNotice(
          `รันการตรวจสอบจริงใน Sandbox เสร็จสิ้น (${res.reports.length} รอบ · ผ่าน ${passed}/${res.reports.length})`
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'รันการตรวจสอบ RestoreProof ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  }

  async function handleRunCustomBundle(e: React.FormEvent) {
    e.preventDefault();
    const cleaned = bundleFiles
      .map((f) => ({ path: f.path.trim(), content: f.content }))
      .filter((f) => f.path.length > 0);
    if (cleaned.length === 0) {
      setError('กรุณาระบุไฟล์อย่างน้อย 1 ไฟล์สำหรับสร้างชุดทดสอบ Backup');
      return;
    }

    setRunningAction('custom_bundle');
    setError(null);
    setStatusNotice(null);
    try {
      const res = await apiRequest<{
        ok: boolean;
        report: { overall_passed: boolean };
        ui_payload: RestoreProofUiPayload;
      }>('/api/restoreproof/verify-bundle', {
        method: 'POST',
        token,
        body: {
          sourceName: bundleSourceName.trim() || 'Custom Backup Bundle',
          backupType: 'Custom Bundle (.zip)',
          minFiles: cleaned.length,
          files: cleaned,
          simulateTamper: bundleTamper,
        },
      });
      if (res.ui_payload) {
        setLiveBackup(res.ui_payload);
        setPayload(res.ui_payload);
        setStatusNotice(
          res.report.overall_passed
            ? 'ตรวจสอบชุด Backup กำหนดเองเสร็จสิ้น: ผ่านทุกเกณฑ์ใน Sandbox'
            : 'ตรวจสอบชุด Backup กำหนดเองเสร็จสิ้น: พบความคลาดเคลื่อนตามหลักฐานจริง'
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ตรวจสอบชุด Backup กำหนดเองไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  }

  async function handleResetHistory() {
    setRunningAction('reset');
    setError(null);
    setStatusNotice(null);
    try {
      const res = await apiRequest<{ ok: boolean; ui_payload: RestoreProofUiPayload }>(
        '/api/restoreproof/history',
        { method: 'DELETE', token }
      );
      const next = res.ui_payload || EMPTY_LIVE_PAYLOAD;
      setLiveBackup(next);
      setPayload(next);
      setStatusNotice('ล้างประวัติผลตรวจสอบจริงเรียบร้อยแล้ว — ระบบกลับสู่สถานะ UNVERIFIED (Fail-Closed)');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ล้างประวัติไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  }

  function handleJsonFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(typeof reader.result === 'string' ? reader.result : '');
        if (!isValidUiPayload(parsed)) {
          setError('ไฟล์ JSON ไม่ตรงกับโครงสร้าง RestoreProof UI Payload (v1.0.0)');
          return;
        }
        setError(null);
        setPayload(parsed);
        setStatusNotice(`โหลดไฟล์รายงานจริง "${file.name}" สำเร็จ`);
      } catch {
        setError(`ไม่สามารถอ่านไฟล์ "${file.name}" เป็น JSON ได้`);
      }
    };
    reader.readAsText(file);
  }

  function handleToggleDemo() {
    setError(null);
    if (payload.is_demo) {
      setPayload(liveBackup);
      setStatusNotice('สลับกลับสู่สถานะการตรวจสอบจริง (Live Verification) แล้ว');
    } else {
      setPayload(DEMO_FIXTURE_PAYLOAD);
      setStatusNotice(null);
    }
  }

  const totalRuns = payload.summary.total_runs;
  const isUnverified = totalRuns === 0 || !payload.latest_run;

  const modeBadge = payload.is_demo
    ? {
        label: 'DEMO FIXTURE',
        classes: 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]',
      }
    : isUnverified
      ? {
          label: 'UNVERIFIED / NO DATA',
          classes: 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)]',
        }
      : {
          label: 'LIVE VERIFICATION',
          classes: 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]',
        };

  const scorePct = payload.reliability.score_pct;
  const ringCircumference = 2 * Math.PI * 44;
  const ringOffset =
    scorePct === null
      ? ringCircumference
      : ringCircumference * (1 - Math.max(0, Math.min(100, scorePct)) / 100);
  const ringStrokeColor =
    scorePct === null
      ? 'var(--color-border)'
      : scorePct >= 90
        ? 'var(--color-success)'
        : scorePct >= 60
          ? 'var(--color-warning)'
          : 'var(--color-danger)';

  return (
    <div className="space-y-6">
      {/* Header + Toolbar */}
      <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <Archive className="h-5 w-5 text-[var(--color-accent)]" />
                <h3 className="text-lg font-bold tracking-tight text-[var(--color-text)]">
                  RealityCheck — RestoreProof
                </h3>
              </div>
              <span
                data-testid="restoreproof-mode-badge"
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 font-mono text-[11px] font-semibold whitespace-nowrap shrink-0 ${modeBadge.classes}`}
              >
                {modeBadge.label}
              </span>
            </div>
            <p className="text-xs text-[var(--color-text-secondary)]">
              เครื่องมือพิสูจน์ว่าไฟล์ Backup กู้คืนได้จริงใน Sandbox แยกส่วน · ตรวจสอบ SHA-256 · รัน Health Probe แบบ Fail-Closed (ไม่ใช้ AI จำลองผล)
            </p>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-text-muted)] tabular-nums">
              <span>Schema v{payload.schema_version}</span>
              <span aria-hidden="true">·</span>
              <span>อัปเดตล่าสุด {formatTimestamp(payload.generated_at)}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={jsonUploadRef}
              type="file"
              accept=".json,application/json"
              onChange={handleJsonFileUpload}
              className="hidden"
              aria-label="อัปโหลดไฟล์ restoreproof_ui_payload.json"
            />
            <button
              type="button"
              onClick={() => jsonUploadRef.current?.click()}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] whitespace-nowrap shrink-0"
            >
              <FolderUp className="h-4 w-4 text-[var(--color-accent)]" />
              <span>เปิดไฟล์ JSON จริง</span>
            </button>

            <button
              type="button"
              onClick={handleToggleDemo}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-warning)] whitespace-nowrap shrink-0"
            >
              <AlertTriangle className="h-4 w-4 text-[var(--color-warning)]" />
              <span>{payload.is_demo ? 'กลับสู่สถานะจริง (Live)' : 'ดูตัวอย่าง (Demo Fixture)'}</span>
            </button>

            <button
              type="button"
              onClick={() => setShowCustomForm((prev) => !prev)}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-primary)] whitespace-nowrap shrink-0"
            >
              <Plus className="h-4 w-4 text-[var(--color-primary)]" />
              <span>ทดสอบชุดไฟล์กำหนดเอง</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null || liveBackup.summary.total_runs === 0}
              onClick={() => void handleResetHistory()}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-danger)] hover:text-[var(--color-danger)] disabled:opacity-45 whitespace-nowrap shrink-0"
            >
              <RotateCcw className="h-4 w-4" />
              <span>รีเซ็ตประวัติจริง</span>
            </button>
          </div>
        </div>

        {/* Real Sandbox Scenario Execution Bar */}
        <div className="mt-5 border-t border-[var(--color-border)] pt-4">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-[var(--color-text)]">
              รันการตรวจสอบจริงใน Isolated Sandbox (เรียก RestoreProof CLI จริง)
            </span>
            <span className="text-[11px] text-[var(--color-text-muted)]">
              ทุกปุ่มสร้างไฟล์ Archive + Manifest SHA-256 จริงและตรวจแยกในโฟลเดอร์ชั่วคราว
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleRunScenario('valid_sqlite_backup')}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {runningAction === 'valid_sqlite_backup' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              <span>ทดสอบ Backup SQLite (Valid)</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleRunScenario('corrupt_archive')}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-semibold text-[var(--color-danger)] hover:bg-[var(--color-danger)]/20 disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {runningAction === 'corrupt_archive' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              <span>Case 1: ไฟล์เสีย (Corrupt Zip)</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleRunScenario('missing_tampered_file')}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-semibold text-[var(--color-danger)] hover:bg-[var(--color-danger)]/20 disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {runningAction === 'missing_tampered_file' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldAlert className="h-4 w-4" />
              )}
              <span>Case 2: ไฟล์หาย / Hash เพี้ยน</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleRunScenario('failed_health_check')}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-semibold text-[var(--color-danger)] hover:bg-[var(--color-danger)]/20 disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {runningAction === 'failed_health_check' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <AlertTriangle className="h-4 w-4" />
              )}
              <span>Case 3: Health Probe ล้มเหลว</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleRunScenario('run_all_3_failures')}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-danger)] disabled:opacity-50 whitespace-nowrap shrink-0"
            >
              {runningAction === 'run_all_3_failures' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FileCheck2 className="h-4 w-4 text-[var(--color-danger)]" />
              )}
              <span>รันครบ 3 กรณีล้มเหลว</span>
            </button>
          </div>
        </div>
      </div>

      {/* Explicit Demo Fixture Warning Banner */}
      {payload.is_demo && (
        <div
          role="status"
          data-testid="restoreproof-demo-banner"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-warning)]/45 bg-[var(--color-warning-bg)] px-4 py-3 text-xs font-medium text-[var(--color-warning)]"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>
              กำลังแสดงข้อมูลตัวอย่าง (DEMO FIXTURE) — ไม่ใช่ผลตรวจสอบจริงของระบบ ห้ามใช้อ้างอิงความพร้อมกู้คืนจริง
            </span>
          </div>
          <button
            type="button"
            onClick={handleToggleDemo}
            className="rounded-lg border border-[var(--color-warning)]/50 px-3 py-1 text-xs font-semibold hover:bg-[var(--color-warning)]/15 whitespace-nowrap shrink-0"
          >
            ปิดโหมดตัวอย่าง
          </button>
        </div>
      )}

      {statusNotice && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-4 py-3 text-xs text-[var(--color-text-secondary)]"
        >
          <span>{statusNotice}</span>
          <button
            type="button"
            onClick={() => setStatusNotice(null)}
            className="text-[11px] font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            ปิดข้อความ
          </button>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/45 bg-[var(--color-danger-bg)] px-4 py-3 text-xs text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด RestoreProof" />
        </div>
      )}

      {/* Optional Custom Bundle Form */}
      {showCustomForm && (
        <form
          onSubmit={handleRunCustomBundle}
          className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-[var(--color-text)]">
              สร้างและตรวจสอบชุด Backup กำหนดเองใน Sandbox
            </h4>
            <button
              type="button"
              onClick={() =>
                setBundleFiles((prev) => [
                  ...prev,
                  {
                    id: `f_${Date.now()}`,
                    path: `extra/file_${prev.length + 1}.txt`,
                    content: 'verified-content\n',
                  },
                ])
              }
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>เพิ่มไฟล์</span>
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="rp-custom-source"
                className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
              >
                ชื่อแหล่งข้อมูล (Source Name)
              </label>
              <input
                id="rp-custom-source"
                type="text"
                value={bundleSourceName}
                onChange={(e) => setBundleSourceName(e.target.value)}
                className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="rp-custom-tamper"
                className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
              >
                เงื่อนไขการทดสอบ (Verification Mode)
              </label>
              <select
                id="rp-custom-tamper"
                value={bundleTamper}
                onChange={(e) => setBundleTamper(e.target.value as TamperSimulation)}
                className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              >
                <option value="none">ปกติ (แพ็กตรงตาม Manifest SHA-256)</option>
                <option value="corrupt_archive">จำลองไฟล์ Archive เสียหาย</option>
                <option value="drop_first_file">จำลองไฟล์แรกสูญหายหลังสร้าง Manifest</option>
                <option value="tamper_first_file">จำลองแก้ไขเนื้อหาไฟล์แรก (Hash Mismatch)</option>
                <option value="fail_health_check">จำลอง Health Command ล้มเหลว (rc=4)</option>
              </select>
            </div>
          </div>

          <div className="space-y-3">
            {bundleFiles.map((fileItem, idx) => (
              <div
                key={fileItem.id}
                className="grid gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 sm:grid-cols-12"
              >
                <div className="sm:col-span-4">
                  <label className="mb-1 block text-[11px] font-medium text-[var(--color-text-muted)]">
                    Path ไฟล์ที่ {idx + 1}
                  </label>
                  <input
                    type="text"
                    value={fileItem.path}
                    onChange={(e) =>
                      setBundleFiles((prev) =>
                        prev.map((row) =>
                          row.id === fileItem.id ? { ...row, path: e.target.value } : row
                        )
                      )
                    }
                    className="h-9 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2.5 font-mono text-xs text-[var(--color-text)]"
                  />
                </div>
                <div className="sm:col-span-7">
                  <label className="mb-1 block text-[11px] font-medium text-[var(--color-text-muted)]">
                    เนื้อหาไฟล์
                  </label>
                  <textarea
                    rows={2}
                    value={fileItem.content}
                    onChange={(e) =>
                      setBundleFiles((prev) =>
                        prev.map((row) =>
                          row.id === fileItem.id ? { ...row, content: e.target.value } : row
                        )
                      )
                    }
                    className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-2 font-mono text-xs text-[var(--color-text)]"
                  />
                </div>
                <div className="flex items-end justify-end sm:col-span-1">
                  <button
                    type="button"
                    disabled={bundleFiles.length <= 1}
                    aria-label={`ลบไฟล์ ${fileItem.path}`}
                    onClick={() =>
                      setBundleFiles((prev) => prev.filter((row) => row.id !== fileItem.id))
                    }
                    className="flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-danger)] disabled:opacity-40"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowCustomForm(false)}
              className="min-h-[40px] rounded-xl border border-[var(--color-border)] px-4 text-xs font-medium text-[var(--color-text-secondary)]"
            >
              ยกเลิก
            </button>
            <button
              type="submit"
              disabled={runningAction !== null}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
            >
              {runningAction === 'custom_bundle' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="h-4 w-4" />
              )}
              <span>แพ็ก Backup และตรวจสอบจริง</span>
            </button>
          </div>
        </form>
      )}

      {/* 4 KPI Summary Row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <p className="text-xs font-medium text-[var(--color-text-secondary)]">จำนวนการตรวจทั้งหมด</p>
          <p className="mt-2 font-mono text-2xl font-bold text-[var(--color-text)] tabular-nums">
            {loadingStatus ? '...' : totalRuns === 0 ? '—' : totalRuns}
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)] tabular-nums">
            วันนี้ {totalRuns === 0 ? '—' : `${payload.summary.runs_today} รอบ`}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <p className="text-xs font-medium text-[var(--color-text-secondary)]">อัตราผ่านการตรวจ</p>
          <p className="mt-2 font-mono text-2xl font-bold text-[var(--color-text)] tabular-nums">
            {payload.summary.pass_rate_pct === null ? '—' : `${payload.summary.pass_rate_pct}%`}
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)]">
            {payload.summary.pass_rate_pct === null
              ? 'ยังไม่เคยรันการตรวจจริง'
              : `คำนวณจาก ${payload.summary.passed_runs}/${totalRuns} รอบ`}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <p className="text-xs font-medium text-[var(--color-text-secondary)]">ผ่าน / ล้มเหลว</p>
          <p className="mt-2 font-mono text-2xl font-bold text-[var(--color-text)] tabular-nums">
            {totalRuns === 0
              ? '—'
              : `${payload.summary.passed_runs} / ${payload.summary.failed_runs}`}
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)]">
            {payload.summary.failed_runs > 0
              ? `ตรวจพบความล้มเหลว ${payload.summary.failed_runs} รอบ`
              : totalRuns === 0
                ? 'ยังไม่มีหลักฐาน'
                : 'ไม่พบความล้มเหลวสะสม'}
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
          <p className="text-xs font-medium text-[var(--color-text-secondary)]">ระยะเวลาเฉลี่ย</p>
          <p className="mt-2 font-mono text-2xl font-bold text-[var(--color-text)] tabular-nums">
            {payload.summary.avg_duration_label || '—'}
          </p>
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)] tabular-nums">
            {payload.summary.avg_duration_sec !== null
              ? `${payload.summary.avg_duration_sec}s avg`
              : 'ไม่มีข้อมูลเวลา'}
          </p>
        </div>
      </div>

      {/* Upper 2-column Detail Row: Latest Run + Reliability Verdict */}
      <div className="grid items-stretch gap-6 lg:grid-cols-12">
        <section className="flex flex-col justify-between rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6 lg:col-span-7">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                ผลการตรวจสอบล่าสุด (Latest Verification Run)
              </h4>
              {payload.latest_run && (
                <span
                  className={`inline-flex items-center gap-1.5 font-mono text-xs font-semibold ${
                    payload.latest_run.status === 'passed'
                      ? 'text-[var(--color-success)]'
                      : 'text-[var(--color-danger)]'
                  }`}
                >
                  {payload.latest_run.status === 'passed' ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  <span>{payload.latest_run.status_label}</span>
                </span>
              )}
            </div>

            {!payload.latest_run ? (
              <div className="rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center">
                <Clock className="mx-auto h-7 w-7 text-[var(--color-text-muted)]" />
                <p className="mt-2.5 text-sm font-semibold text-[var(--color-text)]">
                  ยังไม่มีผลการตรวจสอบ Backup จริง (Fail-Closed)
                </p>
                <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                  ระบบจะไม่แสดงคำว่า PASS หรือคะแนน 100% ล่วงหน้า กดปุ่มทดสอบด้านบนหรือเปิดไฟล์{' '}
                  <code className="font-mono text-[11px]">restoreproof_ui_payload.json</code> เพื่อดูหลักฐานจริง
                </p>
              </div>
            ) : (
              <>
                <div
                  className={`rounded-2xl border p-4 ${
                    payload.latest_run.status === 'passed'
                      ? 'border-[var(--color-success)]/35 bg-[var(--color-success-bg)]'
                      : 'border-[var(--color-danger)]/35 bg-[var(--color-danger-bg)]'
                  }`}
                >
                  <p className="text-sm font-semibold text-[var(--color-text)]">
                    {payload.latest_run.headline}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)] tabular-nums">
                    <span className="font-mono">{payload.latest_run.run_id}</span>
                    <span aria-hidden="true">·</span>
                    <span>{payload.latest_run.source_name}</span>
                    <span aria-hidden="true">·</span>
                    <span>{formatTimestamp(payload.latest_run.checked_at)}</span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                    <p className="text-[11px] text-[var(--color-text-muted)]">ขนาด Archive</p>
                    <p className="mt-1 font-mono text-sm font-semibold text-[var(--color-text)] tabular-nums">
                      {payload.latest_run.data_size_label || '—'}
                    </p>
                  </div>
                  <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                    <p className="text-[11px] text-[var(--color-text-muted)]">เวลารวม</p>
                    <p className="mt-1 font-mono text-sm font-semibold text-[var(--color-text)] tabular-nums">
                      {payload.latest_run.duration_label || '—'}
                    </p>
                  </div>
                  <div className="col-span-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 sm:col-span-1">
                    <p className="text-[11px] text-[var(--color-text-muted)]">ข้อขัดแย้งที่พบ</p>
                    <p className="mt-1 font-mono text-sm font-semibold text-[var(--color-text)] tabular-nums">
                      {payload.latest_run.discrepancies.length}
                    </p>
                  </div>
                </div>

                {payload.latest_run.discrepancies.length > 0 && (
                  <div
                    data-testid="restoreproof-discrepancies"
                    className="rounded-2xl border border-[var(--color-danger)]/45 bg-[var(--color-danger-bg)] p-4"
                  >
                    <p className="text-xs font-semibold text-[var(--color-danger)]">
                      หลักฐานความคลาดเคลื่อน (Discrepancies Detected)
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5 font-mono text-xs text-[var(--color-text)]">
                      {payload.latest_run.discrepancies.map((item, i) => (
                        <li key={`${i}-${item.slice(0, 24)}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* Reliability Verdict Card */}
        <section className="flex flex-col justify-between rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6 lg:col-span-5">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                ความน่าเชื่อถือการกู้คืน (Reliability)
              </h4>
              <span className="font-mono text-[11px] text-[var(--color-text-muted)]">
                {payload.reliability.computation_rule}
              </span>
            </div>

            <div className="flex items-center gap-5">
              <div className="relative flex h-28 w-28 shrink-0 items-center justify-center">
                <svg viewBox="0 0 100 100" className="h-28 w-28 -rotate-90">
                  <circle
                    cx="50"
                    cy="50"
                    r="44"
                    fill="none"
                    stroke="var(--color-surface)"
                    strokeWidth="8"
                  />
                  <circle
                    cx="50"
                    cy="50"
                    r="44"
                    fill="none"
                    stroke={ringStrokeColor}
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={ringCircumference}
                    strokeDashoffset={ringOffset}
                  />
                </svg>
                <span
                  data-testid="restoreproof-reliability-score"
                  className="absolute font-mono text-lg font-bold text-[var(--color-text)] tabular-nums"
                >
                  {payload.reliability.score_label || '—'}
                </span>
              </div>

              <div className="flex-1 space-y-2">
                {payload.reliability.checks.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-muted)]">
                    ยังไม่มีรายการตรวจสอบย่อยที่ยืนยันผล
                  </p>
                ) : (
                  payload.reliability.checks.map((chk) => (
                    <div
                      key={chk.key}
                      className="flex items-center justify-between gap-2 border-b border-[var(--color-border)] pb-1.5 text-xs last:border-none last:pb-0"
                    >
                      <span className="text-[var(--color-text-secondary)]">{chk.label}</span>
                      <span
                        className={`inline-flex items-center gap-1 font-mono text-[11px] font-semibold ${
                          chk.passed ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'
                        }`}
                      >
                        {chk.passed ? (
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        ) : (
                          <XCircle className="h-3.5 w-3.5" />
                        )}
                        <span>{chk.passed ? 'PASS' : 'FAIL'}</span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <p className="mt-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-text-secondary)]">
            {payload.reliability.verdict_text}
          </p>
        </section>
      </div>

      {/* Middle 2-Column Row: 4-Step Breakdown + Technical Details */}
      <div className="grid items-stretch gap-6 lg:grid-cols-12">
        <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6 lg:col-span-7">
          <h4 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
            ลำดับขั้นตอนการพิสูจน์ใน Sandbox (4 Verification Steps)
          </h4>

          {payload.steps.length === 0 ? (
            <p className="text-xs text-[var(--color-text-muted)]">
              ยังไม่มีบันทึกขั้นตอน — ระบบจะแสดงสถานะจริงของทั้ง 4 ขั้นตอน (Integrity, Restore, Completeness, Service Health) เมื่อเริ่มรันการตรวจ
            </p>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {payload.steps.map((step, index) => {
                const badge = stepStatusDisplay(step.status);
                return (
                  <div
                    key={step.step_key}
                    className="flex flex-col gap-2 py-3.5 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 text-xs font-semibold text-[var(--color-text)]">
                        <span className="font-mono text-[var(--color-text-muted)] tabular-nums">
                          0{index + 1}.
                        </span>
                        <span>{step.title}</span>
                      </div>
                      <p className="text-xs text-[var(--color-text-secondary)]">{step.detail}</p>
                    </div>

                    <div className="flex items-center gap-3 sm:shrink-0">
                      <span className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                        {step.duration_label || '—'}
                      </span>
                      <span
                        className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold whitespace-nowrap ${badge.surfaceClass} ${badge.colorClass}`}
                      >
                        {badge.label}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6 lg:col-span-5">
          <h4 className="mb-4 text-sm font-semibold text-[var(--color-text)]">
            รายละเอียดทางเทคนิค (Technical Details)
          </h4>

          {!payload.technical_details ? (
            <p className="text-xs text-[var(--color-text-muted)]">
              ยังไม่มีข้อมูล SHA-256, ขนาดไฟล์ หรือผลคำสั่งตรวจสอบสุขภาพบริการ
            </p>
          ) : (
            <dl className="divide-y divide-[var(--color-border)] text-xs">
              <div className="flex items-center justify-between gap-3 py-2.5 first:pt-0">
                <dt className="text-[var(--color-text-secondary)]">ประเภท Backup</dt>
                <dd className="font-medium text-[var(--color-text)]">
                  {payload.technical_details.backup_type}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-2.5">
                <dt className="text-[var(--color-text-secondary)]">ขนาดไฟล์ Archive</dt>
                <dd className="font-mono text-[var(--color-text)] tabular-nums">
                  {payload.technical_details.file_size_label || '—'}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-2.5">
                <dt className="text-[var(--color-text-secondary)]">SHA-256 Archive</dt>
                <dd className="flex items-center gap-1.5 font-mono text-[var(--color-text)]">
                  <span>{payload.technical_details.checksum_short || '—'}</span>
                  {payload.technical_details.checksum_sha256 && (
                    <CopyButton
                      getText={() => payload.technical_details?.checksum_sha256 || ''}
                      size="xs"
                      ariaLabel="คัดลอก SHA-256"
                    />
                  )}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-2.5">
                <dt className="text-[var(--color-text-secondary)]">เวลา Restore ใน Sandbox</dt>
                <dd className="font-mono text-[var(--color-text)] tabular-nums">
                  {payload.technical_details.restore_time_label || '—'}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-2.5">
                <dt className="text-[var(--color-text-secondary)]">ความสมบูรณ์เทียบ Manifest</dt>
                <dd className="font-mono text-[var(--color-text)] tabular-nums">
                  {payload.technical_details.data_integrity_label}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-2.5 last:pb-0">
                <dt className="text-[var(--color-text-secondary)]">สถานะ Service Health</dt>
                <dd
                  className={`font-mono font-semibold ${
                    payload.technical_details.service_status === 'OK'
                      ? 'text-[var(--color-success)]'
                      : 'text-[var(--color-danger)]'
                  }`}
                >
                  {payload.technical_details.service_status}
                </dd>
              </div>
            </dl>
          )}
        </section>
      </div>

      {/* Verification History Chart */}
      <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 className="text-sm font-semibold text-[var(--color-text)]">
              ประวัติผลการตรวจสอบย้อนหลัง (Verification History)
            </h4>
            <p className="text-xs text-[var(--color-text-secondary)]">
              เปรียบเทียบจำนวนรอบที่ผ่านและไม่ผ่านจริงตามวันที่ตรวจสอบ
            </p>
          </div>
          <span className="font-mono text-xs text-[var(--color-text-muted)] tabular-nums">
            {payload.history.length} วันที่มีบันทึก
          </span>
        </div>

        {payload.history.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-8 text-center text-xs text-[var(--color-text-muted)]">
            ยังไม่มีข้อมูลกราฟประวัติย้อนหลัง
          </div>
        ) : (
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={payload.history} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis
                  dataKey="label"
                  tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--color-surface)',
                    borderColor: 'var(--color-border)',
                    borderRadius: '12px',
                    fontSize: '12px',
                    color: 'var(--color-text)',
                  }}
                />
                <Bar
                  dataKey="passed_count"
                  name="ผ่านการตรวจ"
                  fill="var(--color-success)"
                  radius={[6, 6, 0, 0]}
                />
                <Bar
                  dataKey="failed_count"
                  name="ไม่ผ่านการตรวจ"
                  fill="var(--color-danger)"
                  radius={[6, 6, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}
