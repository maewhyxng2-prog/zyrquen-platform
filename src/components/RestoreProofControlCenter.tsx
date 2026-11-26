import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  Download,
  FileText,
  FolderArchive,
  GitCompare,
  HardDrive,
  Layers,
  Lock,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Server,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Square,
  Terminal,
  Trash2,
  WifiOff,
  XCircle,
} from 'lucide-react';
import { jsPDF } from 'jspdf';
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
  RpAssistantResponse,
  RpBackupSource,
  RpCompareResult,
  RpControlOverview,
  RpRestoreTarget,
  RpRunDetail,
  RpRunStatus,
  RpSecurityPolicies,
  User,
} from '../types';
import { CopyButton } from './CopyButton';
import { RestoreProofPanel } from './RestoreProofPanel';

export type RpTabId =
  | 'home'
  | 'assistant'
  | 'backups'
  | 'restore'
  | 'jobs'
  | 'evidence'
  | 'analytics'
  | 'system'
  | 'settings';

const RP_TABS: Array<{
  id: RpTabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { id: 'home', label: 'หน้าหลัก', icon: Activity },
  { id: 'assistant', label: 'สั่งงาน', icon: Bot },
  { id: 'backups', label: 'Backup', icon: FolderArchive },
  { id: 'restore', label: 'Restore', icon: Database },
  { id: 'jobs', label: 'งานทั้งหมด', icon: Layers },
  { id: 'evidence', label: 'หลักฐาน', icon: FileText },
  { id: 'analytics', label: 'วิเคราะห์', icon: GitCompare },
  { id: 'system', label: 'ระบบ', icon: Server },
  { id: 'settings', label: 'ตั้งค่า', icon: Settings },
];

interface RestoreProofControlCenterProps {
  token: string;
  user: User;
  initialTab?: RpTabId;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('th-TH', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function shortSha(sha: string | null | undefined): string {
  if (!sha) return '-';
  return sha.length > 16 ? `${sha.slice(0, 12)}…${sha.slice(-4)}` : sha;
}

function statusTextClass(status: string): string {
  switch (status) {
    case 'PASS':
    case 'PASSED':
    case 'READY':
    case 'ONLINE':
      return 'text-[var(--color-success)]';
    case 'FAIL':
    case 'FAILED':
    case 'ERROR':
      return 'text-[var(--color-danger)]';
    case 'BLOCKED':
    case 'CANCELLED':
    case 'WARNING':
      return 'text-[var(--color-warning)]';
    case 'RUNNING':
    case 'QUEUED':
      return 'text-[var(--color-accent)]';
    default:
      return 'text-[var(--color-text-secondary)]';
  }
}

function statusBorderClass(status: string): string {
  switch (status) {
    case 'PASS':
    case 'READY':
      return 'border-[var(--color-success)]/40 bg-[var(--color-success)]/8 text-[var(--color-success)]';
    case 'FAIL':
      return 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]';
    case 'BLOCKED':
    case 'CANCELLED':
      return 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]';
    case 'RUNNING':
    case 'QUEUED':
      return 'border-[var(--color-accent)]/40 bg-[var(--color-surface)] text-[var(--color-accent)]';
    default:
      return 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)]';
  }
}

function StatusIcon({ status, className = 'h-4 w-4' }: { status: string; className?: string }) {
  switch (status) {
    case 'PASS':
    case 'PASSED':
    case 'READY':
      return <CheckCircle2 className={`${className} text-[var(--color-success)]`} />;
    case 'FAIL':
    case 'FAILED':
      return <XCircle className={`${className} text-[var(--color-danger)]`} />;
    case 'BLOCKED':
    case 'CANCELLED':
      return <AlertTriangle className={`${className} text-[var(--color-warning)]`} />;
    case 'RUNNING':
    case 'QUEUED':
      return <Clock className={`${className} text-[var(--color-accent)]`} />;
    default:
      return <Clock className={`${className} text-[var(--color-text-muted)]`} />;
  }
}

export function RestoreProofControlCenter({
  token,
  user,
  initialTab = 'home',
}: RestoreProofControlCenterProps) {
  const [activeTab, setActiveTab] = useState<RpTabId>(initialTab);
  const [overview, setOverview] = useState<RpControlOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  // Assistant state
  const [assistantInput, setAssistantInput] = useState('');
  const [pendingProposal, setPendingProposal] = useState<RpAssistantResponse | null>(null);
  const [lastAssistantResp, setLastAssistantResp] = useState<RpAssistantResponse | null>(null);

  // Backup creation form
  const [newBackupName, setNewBackupName] = useState('');
  const [registerName, setRegisterName] = useState('');
  const [registerUri, setRegisterUri] = useState('');
  const [registerFmt, setRegisterFmt] = useState('sqlite_dump');
  const [selectedBackupId, setSelectedBackupId] = useState<string>('');

  // Restore verification form & new target form
  const [selectedTargetId, setSelectedTargetId] = useState<string>('');
  const [verifyMinRows, setVerifyMinRows] = useState(1);
  const [verifyReqTables, setVerifyReqTables] = useState('accounts');
  const [verifyPriority, setVerifyPriority] = useState<'high' | 'normal' | 'low'>('normal');
  const [verifyTimeoutSec, setVerifyTimeoutSec] = useState(120);
  const [targetName, setTargetName] = useState('');
  const [targetEngine, setTargetEngine] = useState('sqlite');
  const [targetIsoMode, setTargetIsoMode] = useState('sqlite_sandbox');
  const [targetDbName, setTargetDbName] = useState('rp_verify_sandbox');
  const [targetHost, setTargetHost] = useState('127.0.0.1');
  const [targetPort, setTargetPort] = useState(5432);

  // Jobs filter & selected run
  const [jobFilter, setJobFilter] = useState<'ALL' | RpRunStatus>('ALL');
  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [evidenceSearch, setEvidenceSearch] = useState('');

  // Run comparison
  const [compareRunA, setCompareRunA] = useState('');
  const [compareRunB, setCompareRunB] = useState('');
  const [compareResult, setCompareResult] = useState<RpCompareResult | null>(null);

  // Worker form & policy draft (admin)
  const [workerName, setWorkerName] = useState('');
  const [workerEndpoint, setWorkerEndpoint] = useState('http://127.0.0.1:8787');
  const [workerMaxConc, setWorkerMaxConc] = useState(2);
  const [policyDraft, setPolicyDraft] = useState<RpSecurityPolicies | null>(null);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const data = await apiRequest<RpControlOverview>('/api/restoreproof/control/overview', {
        token,
      });
      setOverview(data);
      setConnectionLost(false);
      setPolicyDraft(data.policies);
      setSelectedBackupId((prev) =>
        prev && data.backups.some((b) => b.id === prev) ? prev : data.backups[0]?.id || ''
      );
      setSelectedTargetId((prev) =>
        prev && data.targets.some((t) => t.id === prev) ? prev : data.targets[0]?.id || ''
      );
      setSelectedRunId((prev) =>
        prev && data.runs.some((r) => r.run_id === prev) ? prev : data.runs[0]?.run_id || ''
      );
      if (data.runs.length >= 2) {
        setCompareRunA((prev) => prev || data.runs[0].run_id);
        setCompareRunB((prev) => prev || data.runs[1].run_id);
      }
      if (!lastAssistantResp && data.assistant_history?.length) {
        setLastAssistantResp(data.assistant_history[0]);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        setConnectionLost(true);
      }
      setErrorMsg(
        err instanceof ApiError
          ? err.message
          : 'ไม่สามารถเชื่อมต่อ Backend ได้ — สถานะถูกตั้งเป็น UNVERIFIED (Fail-Closed)'
      );
    } finally {
      setLoading(false);
    }
  }, [lastAssistantResp, token]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const runs = useMemo(() => overview?.runs || [], [overview]);
  const backups = useMemo(() => overview?.backups || [], [overview]);
  const targets = useMemo(() => overview?.targets || [], [overview]);
  const workers = useMemo(() => overview?.workers || [], [overview]);
  const audit = useMemo(() => overview?.audit || [], [overview]);
  const monitor = overview?.monitor;

  const selectedRun: RpRunDetail | null = useMemo(
    () => runs.find((r) => r.run_id === selectedRunId) || runs[0] || null,
    [runs, selectedRunId]
  );

  const selectedTarget: RpRestoreTarget | null = useMemo(
    () => targets.find((t) => t.id === selectedTargetId) || targets[0] || null,
    [targets, selectedTargetId]
  );

  const filteredJobs = useMemo(() => {
    if (jobFilter === 'ALL') return runs;
    return runs.filter((r) => r.status === jobFilter);
  }, [jobFilter, runs]);

  const filteredEvidenceRuns = useMemo(() => {
    const q = evidenceSearch.trim().toLowerCase();
    if (!q) return runs;
    return runs.filter(
      (r) =>
        r.run_id.toLowerCase().includes(q) ||
        r.source_name.toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q) ||
        r.target_dbname.toLowerCase().includes(q)
    );
  }, [evidenceSearch, runs]);

  const analyticsSeries = useMemo(() => {
    if (!monitor) return [];
    return [
      { label: 'PASS', count: monitor.run_counts.passed },
      { label: 'FAIL', count: monitor.run_counts.failed },
      { label: 'BLOCKED', count: monitor.run_counts.blocked },
      { label: 'CANCELLED', count: monitor.run_counts.cancelled },
    ];
  }, [monitor]);

  async function handleCreatePresetBackup(
    preset: 'valid_sqlite' | 'low_rows_sqlite' | 'tampered_manifest_archive' | 'corrupt_archive' | 'pg_custom_sample',
    defaultLabel: string
  ) {
    setBusyAction(`preset-${preset}`);
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      const res = await apiRequest<{ ok: boolean; backup: RpBackupSource }>(
        '/api/restoreproof/control/backups',
        {
          method: 'POST',
          token,
          body: {
            preset,
            name: newBackupName.trim() || defaultLabel,
          },
        }
      );
      setNewBackupName('');
      setSelectedBackupId(res.backup.id);
      setActionFeedback(`สร้าง Backup '${res.backup.name}' (${res.backup.id}) สำเร็จ`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'สร้าง Backup ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRegisterBackup(e: React.FormEvent) {
    e.preventDefault();
    if (!registerUri.trim()) return;
    setBusyAction('register-backup');
    setErrorMsg(null);
    try {
      const res = await apiRequest<{ ok: boolean; backup: RpBackupSource }>(
        '/api/restoreproof/control/backups',
        {
          method: 'POST',
          token,
          body: {
            name: registerName.trim() || 'Registered Backup',
            backup_format: registerFmt,
            uri: registerUri.trim(),
          },
        }
      );
      setRegisterName('');
      setRegisterUri('');
      setSelectedBackupId(res.backup.id);
      setActionFeedback(`ลงทะเบียน Backup ${res.backup.id} เรียบร้อย`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ลงทะเบียน Backup ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCheckBackup(backupId: string) {
    setBusyAction(`chk-${backupId}`);
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      const res = await apiRequest<{ ok: boolean; status: string; backup: RpBackupSource }>(
        `/api/restoreproof/control/backups/${encodeURIComponent(backupId)}/check`,
        { method: 'POST', token }
      );
      setActionFeedback(`ตรวจความสมบูรณ์ ${res.backup.name}: ${res.status}`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ตรวจ Backup ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDeleteBackup(backupId: string) {
    setBusyAction(`del-bkp-${backupId}`);
    setErrorMsg(null);
    try {
      await apiRequest(`/api/restoreproof/control/backups/${encodeURIComponent(backupId)}`, {
        method: 'DELETE',
        token,
      });
      setActionFeedback(`ลบรายการ Backup ${backupId} แล้ว`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ลบ Backup ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCreateTarget(e: React.FormEvent) {
    e.preventDefault();
    if (!targetDbName.trim()) return;
    setBusyAction('create-target');
    setErrorMsg(null);
    try {
      const res = await apiRequest<{ ok: boolean; target: RpRestoreTarget }>(
        '/api/restoreproof/control/targets',
        {
          method: 'POST',
          token,
          body: {
            name: targetName.trim() || `${targetEngine} Target`,
            engine: targetEngine,
            isolation_mode: targetIsoMode,
            target_dbname: targetDbName.trim(),
            host: targetHost.trim() || '127.0.0.1',
            port: Number(targetPort) || 5432,
            drop_after_verify: true,
          },
        }
      );
      setTargetName('');
      setSelectedTargetId(res.target.id);
      setActionFeedback(
        `เพิ่ม Target '${res.target.name}' (${res.target.readiness?.status || 'CREATED'})`
      );
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'สร้าง Target ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDeleteTarget(targetId: string) {
    setBusyAction(`del-tgt-${targetId}`);
    setErrorMsg(null);
    try {
      await apiRequest(`/api/restoreproof/control/targets/${encodeURIComponent(targetId)}`, {
        method: 'DELETE',
        token,
      });
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ลบ Target ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleStartVerification(overrideBackupId?: string) {
    const bid = overrideBackupId || selectedBackupId;
    if (!bid) {
      setErrorMsg('กรุณาสร้างหรือเลือก Backup Source ก่อนสั่งทดสอบกู้คืน');
      return;
    }
    setBusyAction('start-verify');
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      const tables = verifyReqTables
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const res = await apiRequest<{ ok: boolean; run: RpRunDetail }>(
        '/api/restoreproof/control/verifications',
        {
          method: 'POST',
          token,
          body: {
            backup_source_id: bid,
            target_id: selectedTargetId || undefined,
            min_total_rows: Number(verifyMinRows) || 0,
            required_tables: tables,
            priority: verifyPriority,
            timeout_sec: Number(verifyTimeoutSec) || 120,
          },
        }
      );
      setSelectedRunId(res.run.run_id);
      setActionFeedback(`ผลลัพธ์ ${res.run.run_id}: ${res.run.status}`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'สั่ง Verification ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleQuickSqliteVerify() {
    setBusyAction('quick-sqlite');
    setErrorMsg(null);
    setActionFeedback(null);
    try {
      let targetBackup = backups.find((b) => b.backup_format === 'sqlite_dump');
      if (!targetBackup) {
        const created = await apiRequest<{ ok: boolean; backup: RpBackupSource }>(
          '/api/restoreproof/control/backups',
          {
            method: 'POST',
            token,
            body: { preset: 'valid_sqlite', name: 'SQLite Quick Verify Dump' },
          }
        );
        targetBackup = created.backup;
      }
      const sqliteTarget = targets.find((t) => t.isolation_mode === 'sqlite_sandbox');
      const res = await apiRequest<{ ok: boolean; run: RpRunDetail }>(
        '/api/restoreproof/control/verifications',
        {
          method: 'POST',
          token,
          body: {
            backup_source_id: targetBackup.id,
            target_id: sqliteTarget?.id,
            min_total_rows: 1,
            required_tables: ['accounts'],
            priority: 'high',
          },
        }
      );
      setSelectedRunId(res.run.run_id);
      setActionFeedback(`SQLite Isolated Restore (${res.run.run_id}): ${res.run.status}`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ทดสอบ SQLite ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCheckAllBackups() {
    if (!backups.length) {
      setErrorMsg('ยังไม่มี Backup Source ในรายการ');
      return;
    }
    setBusyAction('check-all-backups');
    setErrorMsg(null);
    try {
      for (const b of backups) {
        await apiRequest(`/api/restoreproof/control/backups/${encodeURIComponent(b.id)}/check`, {
          method: 'POST',
          token,
        });
      }
      setActionFeedback(`ตรวจ SHA-256 และความสมบูรณ์ครบ ${backups.length} รายการแล้ว`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ตรวจ Backup ทั้งหมดไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCancelRun(runId: string) {
    setBusyAction(`cancel-${runId}`);
    setErrorMsg(null);
    try {
      await apiRequest(`/api/restoreproof/control/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        token,
      });
      setActionFeedback(`ยกเลิกงาน ${runId} แล้ว`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ยกเลิกงานไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRetryRun(runId: string) {
    setBusyAction(`retry-${runId}`);
    setErrorMsg(null);
    try {
      const res = await apiRequest<{ ok: boolean; run: RpRunDetail }>(
        `/api/restoreproof/control/runs/${encodeURIComponent(runId)}/retry`,
        {
          method: 'POST',
          token,
          body: { force: true },
        }
      );
      setSelectedRunId(res.run.run_id);
      setActionFeedback(`รันซ้ำสำเร็จ -> ${res.run.run_id} (${res.run.status})`);
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'รันซ้ำไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCompareRuns() {
    if (!compareRunA || !compareRunB) return;
    setBusyAction('compare-runs');
    setErrorMsg(null);
    try {
      const res = await apiRequest<{ ok: boolean; comparison: RpCompareResult }>(
        `/api/restoreproof/control/compare?a=${encodeURIComponent(compareRunA)}&b=${encodeURIComponent(compareRunB)}`,
        { token }
      );
      setCompareResult(res.comparison);
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'เปรียบเทียบผลไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleAssistantSubmit(messageOverride?: string, confirmExecution = false) {
    const cmdText = (messageOverride ?? assistantInput).trim();
    if (!cmdText) return;
    setBusyAction('assistant');
    setErrorMsg(null);
    try {
      const res = await apiRequest<{ ok: boolean } & RpAssistantResponse>(
        '/api/restoreproof/control/assistant/command',
        {
          method: 'POST',
          token,
          body: {
            message: cmdText,
            confirm_execution: confirmExecution,
            context_run_id: selectedRun?.run_id,
            context_backup_id: selectedBackupId || undefined,
          },
        }
      );
      setLastAssistantResp(res);
      if (res.requires_approval && !res.executed) {
        setPendingProposal(res);
      } else {
        setPendingProposal(null);
        if (!messageOverride) setAssistantInput('');
        await loadOverview();
      }
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'ส่งคำสั่งให้ AI Operations Assistant ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSaveWorker(e: React.FormEvent) {
    e.preventDefault();
    if (!workerName.trim()) return;
    setBusyAction('save-worker');
    setErrorMsg(null);
    try {
      await apiRequest('/api/restoreproof/control/workers', {
        method: 'POST',
        token,
        body: {
          name: workerName.trim(),
          endpoint: workerEndpoint.trim(),
          max_concurrent: Number(workerMaxConc) || 2,
          isolation_modes: ['sqlite_sandbox', 'archive_sandbox', 'isolated_db'],
          status: 'ONLINE',
        },
      });
      setWorkerName('');
      setActionFeedback('บันทึก Worker Node สำเร็จ');
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'บันทึก Worker ไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSavePolicies() {
    if (!policyDraft) return;
    setBusyAction('save-policies');
    setErrorMsg(null);
    try {
      await apiRequest('/api/restoreproof/control/policies', {
        method: 'PUT',
        token,
        body: policyDraft,
      });
      setActionFeedback('อัปเดตนโยบายความปลอดภัยและ Audit Policy แล้ว');
      await loadOverview();
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : 'อัปเดตนโยบายไม่สำเร็จ');
    } finally {
      setBusyAction(null);
    }
  }

  function handleExportJson(run: RpRunDetail) {
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `restoreproof_${run.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleExportPdf(run: RpRunDetail) {
    const doc = new jsPDF({ unit: 'pt', format: 'a4' });
    let y = 48;
    const writeLine = (text: string, size = 10, bold = false) => {
      doc.setFont('helvetica', bold ? 'bold' : 'normal');
      doc.setFontSize(size);
      const wrapped = doc.splitTextToSize(text, 500);
      for (const line of wrapped) {
        if (y > 780) {
          doc.addPage();
          y = 48;
        }
        doc.text(String(line), 46, y);
        y += size + 5;
      }
    };

    writeLine('RealityCheck - RestoreProof Verification Evidence Report', 15, true);
    y += 4;
    writeLine(`Run ID: ${run.run_id}   Verdict: ${run.status}`, 11, true);
    writeLine(`Source: ${run.source_name} (${run.backup_format})`);
    writeLine(`Target DB: ${run.target_dbname} (${run.isolation_mode})`);
    writeLine(`Operator: ${run.operator} | Worker: ${run.worker_id}`);
    writeLine(`Started: ${run.started_at} | Finished: ${run.finished_at || '-'}`);
    writeLine(`Expected SHA-256: ${run.expected_sha256 || '-'}`);
    writeLine(
      `Report SHA-256: ${String((run.report as Record<string, unknown> | null)?.report_sha256 || '-')}`
    );
    y += 6;
    writeLine('Verification Steps:', 12, true);
    for (const s of run.steps) {
      writeLine(`- [${s.status}] ${s.step_key} (${s.duration_sec ?? '-'}s): ${s.detail}`);
    }
    if (run.discrepancies.length) {
      y += 6;
      writeLine('Discrepancies:', 12, true);
      for (const d of run.discrepancies) {
        writeLine(`* ${d}`);
      }
    }
    doc.save(`restoreproof_${run.run_id}.pdf`);
  }

  const totalRuns = monitor?.run_counts.total ?? 0;
  const passCount = monitor?.run_counts.passed ?? 0;
  const failCount = monitor?.run_counts.failed ?? 0;
  const blockedCount = monitor?.run_counts.blocked ?? 0;
  const runningCount = (monitor?.run_counts.running ?? 0) + (monitor?.run_counts.queued ?? 0);

  return (
    <div className="mx-auto w-full max-w-6xl px-3 py-4 sm:px-6 sm:py-6">
      {/* Header & Honest Connection Banner */}
      <header className="mb-4 flex flex-col gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-semibold tracking-[0.14em] text-[var(--color-accent)] uppercase">
            RealityCheck · RestoreProof Control Center
          </p>
          <h2 className="mt-0.5 text-lg font-bold tracking-tight text-[var(--color-text)] sm:text-xl">
            ศูนย์ควบคุมและพิสูจน์การกู้คืนระบบจริง
          </h2>
          <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
            {connectionLost
              ? 'UNREACHABLE · ห้ามเชื่อว่าสำเร็จ'
              : `Backend: ${monitor?.service || 'กำลังตรวจ'} · SQLite Sandbox: ${monitor?.isolated_sqlite_ready ? 'READY' : 'UNCHECKED'} · PG Worker: ${monitor?.isolated_pg_ready ? 'READY' : 'BLOCKED (ขาด pg_restore)'}`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void loadOverview()}
            disabled={loading}
            className="flex min-h-[44px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            <span>รีเฟรชสถานะจริง</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('assistant')}
            className="flex min-h-[44px] items-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)]"
          >
            <Bot className="h-4 w-4" />
            <span>สั่งงาน AI Ops</span>
          </button>
        </div>
      </header>

      {/* Mobile-First 9-Tab Navigation Strip */}
      <nav
        aria-label="แท็บควบคุม RealityCheck RestoreProof"
        className="mb-5 flex gap-1.5 overflow-x-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1.5"
      >
        {RP_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              aria-current={active ? 'page' : undefined}
              className={`flex min-h-[44px] shrink-0 items-center gap-2 rounded-xl px-3.5 text-xs font-semibold transition-colors whitespace-nowrap ${
                active
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]'
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Live Connection / Error / Feedback Banners */}
      {connectionLost && (
        <div
          role="alert"
          className="mb-4 flex items-center gap-3 rounded-2xl border border-[var(--color-danger)]/50 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <WifiOff className="h-5 w-5 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">UNREACHABLE — ขาดการเชื่อมต่อ Backend</p>
            <p className="text-xs opacity-90">
              ตามกฎ Fail-Closed ระบบจะไม่แสดงผล PASS เมื่อไม่สามารถตรวจสอบ Backend จริงได้
            </p>
          </div>
        </div>
      )}

      {errorMsg && (
        <div
          role="alert"
          className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-xs text-[var(--color-danger)]"
        >
          <span>{errorMsg}</span>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            className="min-h-[32px] px-2 font-semibold underline"
          >
            ปิด
          </button>
        </div>
      )}

      {actionFeedback && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[var(--color-accent)]/40 bg-[var(--color-surface-raised)] px-4 py-2.5 text-xs text-[var(--color-text)]"
        >
          <span>{actionFeedback}</span>
          <button
            type="button"
            onClick={() => setActionFeedback(null)}
            className="min-h-[32px] px-2 text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
          >
            ปิด
          </button>
        </div>
      )}

      {/* TAB 1: หน้าหลัก (Command Center) */}
      {activeTab === 'home' && (
        <div className="space-y-5">
          {/* KPI Strip */}
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-4 tabular-nums">
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <p className="text-xs text-[var(--color-text-secondary)]">กู้คืนผ่านจริง (PASS)</p>
              <p className="mt-1 font-mono text-2xl font-bold text-[var(--color-success)]">
                {passCount}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                จากทั้งหมด {totalRuns} รอบ
              </p>
            </div>
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <p className="text-xs text-[var(--color-text-secondary)]">ล้มเหลว (FAIL)</p>
              <p className="mt-1 font-mono text-2xl font-bold text-[var(--color-danger)]">
                {failCount}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                ห้ามนำ Backup ไปกู้จริง
              </p>
            </div>
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <p className="text-xs text-[var(--color-text-secondary)]">ติดเงื่อนไข (BLOCKED)</p>
              <p className="mt-1 font-mono text-2xl font-bold text-[var(--color-warning)]">
                {blockedCount}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                Fail-Closed Guard
              </p>
            </div>
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <p className="text-xs text-[var(--color-text-secondary)]">กำลังทำงาน (RUNNING)</p>
              <p className="mt-1 font-mono text-2xl font-bold text-[var(--color-accent)]">
                {runningCount}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                Workers: {workers.length} โหนด
              </p>
            </div>
          </section>

          {/* Quick Remote Control Actions */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">คำสั่งควบคุมด่วน</h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
              ทุกปุ่มยิง API จริงเข้า Worker แยกส่วน ไม่จำลองผลลัพธ์
            </p>
            <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() =>
                  void handleCreatePresetBackup('valid_sqlite', 'SQLite Production Snapshot')
                }
                className="flex min-h-[46px] items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-semibold text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50"
              >
                <Plus className="h-4 w-4 text-[var(--color-accent)]" />
                <span>สร้าง Backup ทดสอบ (SQLite)</span>
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void handleCheckAllBackups()}
                className="flex min-h-[46px] items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-semibold text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50"
              >
                <ShieldCheck className="h-4 w-4 text-[var(--color-accent)]" />
                <span>ตรวจ SHA-256 Backup ทั้งหมด</span>
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void handleQuickSqliteVerify()}
                className="flex min-h-[46px] items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                <span>สั่ง SQLite Restore Verify ทันที</span>
              </button>
            </div>
          </section>

          {/* Quick AI Command Bar */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                สั่งงานด้วย AI Operations Assistant (Native Deterministic)
              </h3>
              <span className="font-mono text-[11px] text-[var(--color-text-muted)]">
                external_ai_used=false · Approval Gate Active
              </span>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setActiveTab('assistant');
                void handleAssistantSubmit();
              }}
              className="mt-3 flex flex-col gap-2 sm:flex-row"
            >
              <input
                type="text"
                value={assistantInput}
                onChange={(e) => setAssistantInput(e.target.value)}
                placeholder="เช่น ตรวจสอบ Backup ล่าสุดทั้งหมด หรือ วิเคราะห์สาเหตุที่ run ล่าสุดพัง"
                className="min-h-[44px] flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
              <button
                type="submit"
                disabled={busyAction !== null || !assistantInput.trim()}
                className="min-h-[44px] rounded-xl bg-[var(--color-primary)] px-5 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
              >
                ส่งคำสั่ง
              </button>
            </form>
          </section>

          {/* Alerts + Recent Runs */}
          <div className="grid gap-4 lg:grid-cols-12">
            <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 lg:col-span-5">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                การแจ้งเตือนจากหลักฐานจริง
              </h3>
              <div className="mt-3 space-y-2">
                {monitor?.alerts?.length ? (
                  monitor.alerts.map((al, idx) => (
                    <div
                      key={`${al.code}-${idx}`}
                      className={`rounded-xl border px-3 py-2.5 text-xs ${
                        al.severity === 'error'
                          ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                          : 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]'
                      }`}
                    >
                      <p className="font-mono text-[11px] font-semibold">{al.code}</p>
                      <p className="mt-0.5 leading-relaxed">{al.message}</p>
                    </div>
                  ))
                ) : (
                  <p className="py-4 text-xs text-[var(--color-text-secondary)]">
                    ยังไม่มีการแจ้งเตือนความผิดปกติ หรือยังไม่ได้เริ่มทดสอบ
                  </p>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 lg:col-span-7">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[var(--color-text)]">งานล่าสุด</h3>
                <button
                  type="button"
                  onClick={() => setActiveTab('jobs')}
                  className="text-xs font-medium text-[var(--color-accent)] hover:underline"
                >
                  ดูงานทั้งหมด
                </button>
              </div>
              {runs.length === 0 ? (
                <div className="rounded-xl border border-dashed border-[var(--color-border)] p-6 text-center text-xs text-[var(--color-text-secondary)]">
                  ยังไม่มีประวัติการทดสอบ (Fail-Closed: ไม่มีผล PASS จนกว่าจะสั่งทดสอบจริง)
                </div>
              ) : (
                <div className="divide-y divide-[var(--color-border)]">
                  {runs.slice(0, 6).map((r) => (
                    <div key={r.run_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <StatusIcon status={r.status} />
                          <span className="truncate text-sm font-medium text-[var(--color-text)]">
                            {r.source_name}
                          </span>
                        </div>
                        <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          {r.run_id} · {r.status} · {r.duration_sec ?? '-'}s · {formatDateTime(r.started_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedRunId(r.run_id);
                            setActiveTab('evidence');
                          }}
                          className="min-h-[36px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] hover:border-[var(--color-accent)]"
                        >
                          หลักฐาน
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleRetryRun(r.run_id)}
                          disabled={busyAction !== null}
                          className="min-h-[36px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] hover:border-[var(--color-accent)]"
                        >
                          Retry
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      )}

      {/* TAB 2: สั่งงาน (AI Operations Assistant + Approval Gate) */}
      {activeTab === 'assistant' && (
        <div className="space-y-4">
          {/* Role Boundary */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              ขอบเขตบทบาทของระบบ (ห้าม AI ประกาศ PASS เอง)
            </h3>
            <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
              AI Assistant ใช้กลไก Native Deterministic Rule + Evidence Grounding ภายในระบบเท่านั้น (ไม่ส่งข้อมูลออก External AI)
            </p>
            <div className="mt-3 grid gap-2 text-xs sm:grid-cols-5">
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
                <p className="font-semibold text-[var(--color-accent)]">1. AI Assistant</p>
                <p className="mt-0.5 text-[var(--color-text-secondary)]">ตีความคำสั่ง วางแผน ตรวจความเสี่ยง</p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
                <p className="font-semibold text-[var(--color-text)]">2. Backend</p>
                <p className="mt-0.5 text-[var(--color-text-secondary)]">ตรวจสิทธิ์ Approval Gate & คิว</p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
                <p className="font-semibold text-[var(--color-text)]">3. Verification Engine</p>
                <p className="mt-0.5 text-[var(--color-text-secondary)]">ตัดสิน PASS/FAIL/BLOCKED</p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
                <p className="font-semibold text-[var(--color-text)]">4. Restore Worker</p>
                <p className="mt-0.5 text-[var(--color-text-secondary)]">กู้คืนจริงในพื้นที่แยก</p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
                <p className="font-semibold text-[var(--color-text)]">5. Evidence Engine</p>
                <p className="mt-0.5 text-[var(--color-text-secondary)]">บันทึก SHA-256 และ Audit</p>
              </div>
            </div>
          </section>

          {/* Command Prompt + Presets */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void handleAssistantSubmit();
              }}
              className="space-y-3"
            >
              <label htmlFor="rp-assistant-input" className="block text-sm font-semibold text-[var(--color-text)]">
                ป้อนคำสั่งปฏิบัติการ (ภาษาไทยหรืออังกฤษ)
              </label>
              <textarea
                id="rp-assistant-input"
                rows={2}
                value={assistantInput}
                onChange={(e) => setAssistantInput(e.target.value)}
                placeholder="ตัวอย่าง: ตรวจสอบ Backup ล่าสุดทั้งหมด / ทดสอบกู้คืน SQLite ล่าสุด / วิเคราะห์สาเหตุที่การทดสอบล่าสุดล้มเหลว"
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1.5">
                  {[
                    'สรุปสถานะระบบและความเสี่ยง',
                    'ตรวจสอบ Backup ล่าสุดทั้งหมด',
                    'ทดสอบกู้คืน SQLite ใน Sandbox',
                    'วิเคราะห์สาเหตุที่งานล่าสุดล้มเหลว',
                    'เปรียบเทียบ 2 รันล่าสุด',
                  ].map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => {
                        setAssistantInput(preset);
                        void handleAssistantSubmit(preset, false);
                      }}
                      className="min-h-[36px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)]"
                    >
                      {preset}
                    </button>
                  ))}
                </div>
                <button
                  type="submit"
                  disabled={busyAction !== null || !assistantInput.trim()}
                  className="min-h-[44px] rounded-xl bg-[var(--color-primary)] px-5 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
                >
                  {busyAction === 'assistant' ? 'กำลังวิเคราะห์...' : 'วิเคราะห์และวางแผน'}
                </button>
              </div>
            </form>
          </section>

          {/* Approval Gate Banner */}
          {pendingProposal && pendingProposal.requires_approval && !pendingProposal.executed && (
            <section
              role="region"
              aria-label="Approval Gate"
              className="rounded-2xl border border-[var(--color-warning)]/60 bg-[var(--color-warning-bg)] p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-semibold text-[var(--color-warning)]">
                    <Lock className="h-4 w-4" />
                    <span>Approval Gate: ต้องได้รับการยืนยันจากผู้ปฏิบัติงานก่อนสั่งทำงาน</span>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text)]">{pendingProposal.answer}</p>
                  <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)]">
                    intent={pendingProposal.intent} · risk={pendingProposal.risk_level}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPendingProposal(null)}
                    className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-text)]"
                  >
                    ไม่อนุมัติ
                  </button>
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void handleAssistantSubmit(pendingProposal.input, true)}
                    className="flex min-h-[44px] items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
                  >
                    <Check className="h-4 w-4" />
                    <span>อนุมัติให้ดำเนินการจริง</span>
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* Latest Assistant Plan & Response */}
          {lastAssistantResp && (
            <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-3">
                <div>
                  <p className="font-mono text-[11px] text-[var(--color-accent)]">
                    intent: {lastAssistantResp.intent} · risk: {lastAssistantResp.risk_level} · executed:{' '}
                    {String(lastAssistantResp.executed)}
                  </p>
                  <h4 className="mt-0.5 text-sm font-semibold text-[var(--color-text)]">
                    คำตอบและแผนปฏิบัติการจากหลักฐานจริง
                  </h4>
                </div>
                <CopyButton
                  getText={() => JSON.stringify(lastAssistantResp, null, 2)}
                  ariaLabel="คัดลอกผลวิเคราะห์ของ Assistant"
                  size="xs"
                />
              </div>

              <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-text)]">
                {lastAssistantResp.answer}
              </p>

              {lastAssistantResp.plan_steps?.length > 0 && (
                <div className="mt-4 space-y-2">
                  <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                    ขั้นตอนการวางแผน (Plan Trace)
                  </p>
                  {lastAssistantResp.plan_steps.map((st, i) => (
                    <div
                      key={`${st.step}-${i}`}
                      className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs"
                    >
                      <span className="text-[var(--color-text)]">
                        {i + 1}. {st.step}
                        {st.detail ? ` — ${st.detail}` : ''}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-[var(--color-accent)]">
                        {st.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {lastAssistantResp.referenced_run_ids && lastAssistantResp.referenced_run_ids.length > 0 && (
                <p className="mt-3 font-mono text-[11px] text-[var(--color-text-muted)]">
                  อ้างอิง Run IDs: {lastAssistantResp.referenced_run_ids.join(', ')}
                </p>
              )}
            </section>
          )}
        </div>
      )}

      {/* TAB 3: Backup Manager */}
      {activeTab === 'backups' && (
        <div className="space-y-5">
          {/* Create Managed Real Test Artifacts */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              สร้าง Backup Bundle จริงเข้าคลังตรวจสอบ (Vault)
            </h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
              สร้างไฟล์ SQLite Dump, Archive หรือ PostgreSQL sample จริงพร้อมคำนวณ SHA-256 Baseline
            </p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <input
                type="text"
                value={newBackupName}
                onChange={(e) => setNewBackupName(e.target.value)}
                placeholder="ตั้งชื่อ Backup (เว้นว่างเพื่อใช้ชื่อมาตรฐาน)"
                className="min-h-[44px] flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)]"
              />
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void handleCreatePresetBackup('valid_sqlite', 'Valid SQLite Dump')}
                className="min-h-[44px] rounded-xl bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
              >
                + SQLite ปกติ (3 แถว)
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void handleCreatePresetBackup('low_rows_sqlite', 'Low-Rows SQLite Dump')}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
              >
                + SQLite แถวน้อย (1 แถว)
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() =>
                  void handleCreatePresetBackup('tampered_manifest_archive', 'Tampered Config Archive')
                }
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
              >
                + Archive ถูกแก้ไข Hash
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() => void handleCreatePresetBackup('corrupt_archive', 'Corrupt Zip Artifact')}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
              >
                + Archive เสียหาย
              </button>
              <button
                type="button"
                disabled={busyAction !== null}
                onClick={() =>
                  void handleCreatePresetBackup('pg_custom_sample', 'PostgreSQL Custom Sample')
                }
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
              >
                + PG Custom (.dump)
              </button>
            </div>
          </section>

          {/* Register Workspace Path */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              ลงทะเบียนไฟล์ Backup ใน Workspace
            </h3>
            <form onSubmit={(e) => void handleRegisterBackup(e)} className="mt-3 grid gap-2 sm:grid-cols-4">
              <input
                type="text"
                value={registerName}
                onChange={(e) => setRegisterName(e.target.value)}
                placeholder="ชื่อแหล่งสำรองข้อมูล"
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
              />
              <select
                value={registerFmt}
                onChange={(e) => setRegisterFmt(e.target.value)}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
              >
                <option value="sqlite_dump">sqlite_dump</option>
                <option value="archive_zip">archive_zip</option>
                <option value="postgresql_custom">postgresql_custom</option>
                <option value="postgresql_sql">postgresql_sql</option>
              </select>
              <input
                type="text"
                value={registerUri}
                onChange={(e) => setRegisterUri(e.target.value)}
                placeholder="พาธไฟล์ภายใน Data Dir (Path Confined)"
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
              />
              <button
                type="submit"
                disabled={busyAction !== null || !registerUri.trim()}
                className="min-h-[44px] rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
              >
                ลงทะเบียน
              </button>
            </form>
          </section>

          {/* Backup List */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                คลัง Backup ที่ลงทะเบียน ({backups.length})
              </h3>
              <button
                type="button"
                disabled={busyAction !== null || backups.length === 0}
                onClick={() => void handleCheckAllBackups()}
                className="min-h-[38px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] disabled:opacity-50"
              >
                ตรวจ SHA-256 ทั้งหมด
              </button>
            </div>
            {backups.length === 0 ? (
              <p className="py-6 text-center text-xs text-[var(--color-text-secondary)]">
                ยังไม่มี Backup Source ในระบบ กดปุ่มด้านบนเพื่อสร้างชุดทดสอบจริง
              </p>
            ) : (
              <div className="space-y-3">
                {backups.map((b) => (
                  <div
                    key={b.id}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3.5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <StatusIcon status={b.last_check_status} />
                          <p className="font-semibold text-sm text-[var(--color-text)]">{b.name}</p>
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          {b.id} · {b.backup_format} · {formatBytes(b.size_bytes)} · SHA-256:{' '}
                          {shortSha(b.sha256)} · สถานะตรวจ: {b.last_check_status}
                        </p>
                        {b.notes && (
                          <p className="mt-1 text-xs text-[var(--color-text-muted)]">{b.notes}</p>
                        )}
                        {b.last_discrepancies?.length > 0 && (
                          <p className="mt-1.5 text-xs text-[var(--color-danger)]">
                            ความผิดปกติ: {b.last_discrepancies.join(' | ')}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <button
                          type="button"
                          disabled={busyAction !== null}
                          onClick={() => void handleCheckBackup(b.id)}
                          className="min-h-[40px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
                        >
                          ตรวจ Hash
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedBackupId(b.id);
                            setActiveTab('restore');
                          }}
                          className="min-h-[40px] rounded-xl bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
                        >
                          กู้คืนทดสอบ
                        </button>
                        <button
                          type="button"
                          aria-label={`ลบ Backup ${b.name}`}
                          disabled={busyAction !== null}
                          onClick={() => void handleDeleteBackup(b.id)}
                          className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-danger)] hover:text-[var(--color-danger)]"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {/* TAB 4: Restore Manager */}
      {activeTab === 'restore' && (
        <div className="grid gap-5 lg:grid-cols-12">
          {/* Execute Isolated Restore */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 lg:col-span-6">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              สั่ง Restore Verification ในพื้นที่แยก (Isolated)
            </h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
              ระบบป้องกันชื่อฐานข้อมูล Production อัตโนมัติ และลบพื้นที่ชั่วคราวหลังตรวจเสร็จ
            </p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
                  เลือก Backup Source
                </label>
                <select
                  value={selectedBackupId}
                  onChange={(e) => setSelectedBackupId(e.target.value)}
                  className="min-h-[44px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                >
                  {backups.length === 0 && <option value="">-- ยังไม่มี Backup --</option>}
                  {backups.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name} ({b.backup_format})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
                  เลือก Restore Target (แยกจาก Production)
                </label>
                <select
                  value={selectedTargetId}
                  onChange={(e) => setSelectedTargetId(e.target.value)}
                  className="min-h-[44px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                >
                  {targets.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} [{t.isolation_mode}] ({t.readiness?.status || 'UNKNOWN'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
                    จำนวนแถวขั้นต่ำ (min_total_rows)
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={verifyMinRows}
                    onChange={(e) => setVerifyMinRows(Number(e.target.value))}
                    className="min-h-[44px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
                    Priority / Timeout (sec)
                  </label>
                  <div className="flex gap-2">
                    <select
                      value={verifyPriority}
                      onChange={(e) =>
                        setVerifyPriority(e.target.value as 'high' | 'normal' | 'low')
                      }
                      className="min-h-[44px] flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs text-[var(--color-text)]"
                    >
                      <option value="high">high</option>
                      <option value="normal">normal</option>
                      <option value="low">low</option>
                    </select>
                    <input
                      type="number"
                      min={10}
                      value={verifyTimeoutSec}
                      onChange={(e) => setVerifyTimeoutSec(Number(e.target.value))}
                      className="min-h-[44px] w-20 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-2 font-mono text-xs text-[var(--color-text)]"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
                  ตารางที่ต้องพบหลัง Restore (คั่นด้วยจุลภาค)
                </label>
                <input
                  type="text"
                  value={verifyReqTables}
                  onChange={(e) => setVerifyReqTables(e.target.value)}
                  placeholder="accounts"
                  className="min-h-[44px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                />
              </div>

              {selectedTarget?.readiness && (
                <div className={`rounded-xl border p-3 text-xs ${statusBorderClass(selectedTarget.readiness.status)}`}>
                  <p className="font-semibold">
                    Target Readiness: {selectedTarget.readiness.status}
                  </p>
                  {selectedTarget.readiness.block_reason && (
                    <p className="mt-0.5">{selectedTarget.readiness.block_reason}</p>
                  )}
                  <ul className="mt-1.5 space-y-0.5 text-[11px]">
                    {selectedTarget.readiness.checks.map((c) => (
                      <li key={c.key}>
                        {c.passed ? '[OK]' : '[BLOCK]'} {c.label}: {c.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <button
                type="button"
                disabled={busyAction !== null || !selectedBackupId}
                onClick={() => void handleStartVerification()}
                className="flex min-h-[46px] w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                <span>เริ่มทดสอบการกู้คืนและตรวจสอบข้อมูล</span>
              </button>
            </div>
          </section>

          {/* Manage Isolated Targets */}
          <section className="space-y-4 lg:col-span-6">
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                เพิ่ม Isolated Restore Target
              </h3>
              <form onSubmit={(e) => void handleCreateTarget(e)} className="mt-3 grid gap-2 sm:grid-cols-2">
                <input
                  type="text"
                  value={targetName}
                  onChange={(e) => setTargetName(e.target.value)}
                  placeholder="ชื่อ Target (เช่น Ephemeral PG)"
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                />
                <input
                  type="text"
                  value={targetDbName}
                  onChange={(e) => setTargetDbName(e.target.value)}
                  placeholder="target_dbname (เช่น rp_verify_stage)"
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                />
                <select
                  value={targetEngine}
                  onChange={(e) => setTargetEngine(e.target.value)}
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                >
                  <option value="sqlite">sqlite</option>
                  <option value="postgresql">postgresql</option>
                  <option value="archive">archive</option>
                </select>
                <select
                  value={targetIsoMode}
                  onChange={(e) => setTargetIsoMode(e.target.value)}
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                >
                  <option value="sqlite_sandbox">sqlite_sandbox</option>
                  <option value="isolated_db">isolated_db</option>
                  <option value="docker_ephemeral">docker_ephemeral</option>
                  <option value="archive_sandbox">archive_sandbox</option>
                </select>
                <input
                  type="text"
                  value={targetHost}
                  onChange={(e) => setTargetHost(e.target.value)}
                  placeholder="Host"
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                />
                <div className="flex gap-2">
                  <input
                    type="number"
                    value={targetPort}
                    onChange={(e) => setTargetPort(Number(e.target.value))}
                    placeholder="Port"
                    className="min-h-[42px] w-24 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                  />
                  <button
                    type="submit"
                    disabled={busyAction !== null}
                    className="min-h-[42px] flex-1 rounded-xl bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
                  >
                    + เพิ่ม Target
                  </button>
                </div>
              </form>
            </div>

            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <h3 className="mb-3 text-sm font-semibold text-[var(--color-text)]">
                รายการ Restore Targets ({targets.length})
              </h3>
              <div className="space-y-2">
                {targets.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs"
                  >
                    <div className="min-w-0">
                      <p className="font-semibold text-[var(--color-text)]">{t.name}</p>
                      <p className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                        {t.engine} · {t.isolation_mode} · db={t.target_dbname} ·{' '}
                        <span className={statusTextClass(t.readiness?.status || '')}>
                          {t.readiness?.status || 'UNKNOWN'}
                        </span>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleDeleteTarget(t.id)}
                      aria-label={`ลบ Target ${t.name}`}
                      className="flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg border border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>
      )}

      {/* TAB 5: Job Queue & Runs */}
      {activeTab === 'jobs' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <div className="flex flex-wrap gap-1.5">
              {(['ALL', 'PASS', 'FAIL', 'BLOCKED', 'RUNNING', 'CANCELLED'] as const).map((st) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setJobFilter(st)}
                  className={`min-h-[38px] rounded-xl px-3 font-mono text-xs font-semibold ${
                    jobFilter === st
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)]'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
            <span className="font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
              แสดง {filteredJobs.length} จาก {runs.length} งาน
            </span>
          </div>

          {filteredJobs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--color-border)] p-8 text-center text-xs text-[var(--color-text-secondary)]">
              ไม่พบงานในสถานะ {jobFilter}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredJobs.map((r) => (
                <div
                  key={r.run_id}
                  className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <StatusIcon status={r.status} />
                        <span className="font-semibold text-sm text-[var(--color-text)]">
                          {r.source_name}
                        </span>
                        <span className={`font-mono text-xs font-bold ${statusTextClass(r.status)}`}>
                          {r.status}
                        </span>
                      </div>
                      <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                        {r.run_id} · priority={r.priority} · worker={r.worker_id} · attempt={r.attempt}/{r.max_retries} · {r.duration_sec ?? '-'}s · operator={r.operator}
                      </p>
                      {r.discrepancies.length > 0 && (
                        <p className="mt-1.5 text-xs text-[var(--color-danger)]">
                          {r.discrepancies.join(' | ')}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {(r.status === 'RUNNING' || r.status === 'QUEUED') && (
                        <button
                          type="button"
                          onClick={() => void handleCancelRun(r.run_id)}
                          disabled={busyAction !== null}
                          className="flex min-h-[38px] items-center gap-1 rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-3 text-xs font-semibold text-[var(--color-warning)]"
                        >
                          <Square className="h-3.5 w-3.5" />
                          <span>Cancel</span>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void handleRetryRun(r.run_id)}
                        disabled={busyAction !== null}
                        className="flex min-h-[38px] items-center gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>Retry</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedRunId(r.run_id);
                          setActiveTab('evidence');
                        }}
                        className="flex min-h-[38px] items-center gap-1 rounded-xl bg-[var(--color-primary)] px-3 text-xs font-semibold text-white"
                      >
                        <span>ดูหลักฐาน</span>
                        <ChevronRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                  {r.logs_tail?.length > 0 && (
                    <pre className="mt-2.5 overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5 font-mono text-[11px] text-[var(--color-text-secondary)]">
                      {r.logs_tail.slice(-4).join('\n')}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* TAB 6: หลักฐาน (Evidence, Timeline, Compare, JSON/PDF Export) */}
      {activeTab === 'evidence' && (
        <div className="space-y-5">
          {/* Search & Selector */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
                <input
                  type="text"
                  value={evidenceSearch}
                  onChange={(e) => setEvidenceSearch(e.target.value)}
                  placeholder="ค้นหาด้วย Run ID, ชื่อ Backup หรือสถานะ..."
                  className="min-h-[44px] w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] pr-3 pl-9 text-xs text-[var(--color-text)]"
                />
              </div>
              <select
                value={selectedRun?.run_id || ''}
                onChange={(e) => setSelectedRunId(e.target.value)}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
              >
                {filteredEvidenceRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} [{r.status}] — {r.source_name}
                  </option>
                ))}
              </select>
            </div>
          </section>

          {selectedRun ? (
            <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--color-border)] pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <StatusIcon status={selectedRun.status} className="h-5 w-5" />
                    <h3 className="font-mono text-base font-bold text-[var(--color-text)]">
                      {selectedRun.run_id}
                    </h3>
                    <span className={`font-mono text-xs font-bold ${statusTextClass(selectedRun.status)}`}>
                      {selectedRun.status}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)]">
                    {selectedRun.source_name} · {selectedRun.backup_format} · {selectedRun.target_dbname} · sha256={shortSha(selectedRun.expected_sha256)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleExportJson(selectedRun)}
                    className="flex min-h-[40px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Export JSON</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportPdf(selectedRun)}
                    className="flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Export PDF</span>
                  </button>
                </div>
              </div>

              {/* Step Timeline */}
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                  Verification Timeline
                </p>
                {selectedRun.steps.map((s) => (
                  <div
                    key={s.step_key}
                    className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs"
                  >
                    <div className="flex items-start gap-2">
                      <StatusIcon status={s.status} />
                      <div>
                        <p className="font-mono font-semibold text-[var(--color-text)]">
                          {s.step_key}
                        </p>
                        <p className="text-[var(--color-text-secondary)]">{s.detail}</p>
                      </div>
                    </div>
                    <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                      {s.duration_sec !== null ? `${s.duration_sec}s` : '-'}
                    </span>
                  </div>
                ))}
              </div>

              {/* Full Evidence JSON */}
              <div className="mt-4">
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                    Immutable Evidence Payload (JSON)
                  </p>
                  <CopyButton
                    getText={() => JSON.stringify(selectedRun, null, 2)}
                    ariaLabel="คัดลอก Evidence JSON"
                    size="xs"
                  />
                </div>
                <pre className="max-h-72 overflow-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-[11px] text-[var(--color-text-secondary)]">
                  {JSON.stringify(selectedRun, null, 2)}
                </pre>
              </div>
            </section>
          ) : (
            <div className="rounded-2xl border border-dashed border-[var(--color-border)] p-8 text-center text-xs text-[var(--color-text-secondary)]">
              ยังไม่มีหลักฐานให้แสดง — สั่งทดสอบ Backup หรือ Restore เพื่อสร้างหลักฐาน
            </div>
          )}

          {/* Run Comparison */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              เปรียบเทียบผลระหว่าง 2 รอบ (Run Comparison)
            </h3>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <select
                value={compareRunA}
                onChange={(e) => setCompareRunA(e.target.value)}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
              >
                <option value="">-- เลือก Run A --</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} [{r.status}]
                  </option>
                ))}
              </select>
              <select
                value={compareRunB}
                onChange={(e) => setCompareRunB(e.target.value)}
                className="min-h-[44px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
              >
                <option value="">-- เลือก Run B --</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} [{r.status}]
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busyAction !== null || !compareRunA || !compareRunB}
                onClick={() => void handleCompareRuns()}
                className="min-h-[44px] rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white disabled:opacity-50"
              >
                เปรียบเทียบหลักฐาน
              </button>
            </div>
            {compareResult && (
              <div className="mt-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-xs text-[var(--color-text)]">
                <p>
                  Transition: {compareResult.diff.verdict_transition} · Rows Delta:{' '}
                  {compareResult.diff.rows_delta} · Duration Delta:{' '}
                  {compareResult.diff.duration_delta_sec}s · SHA Changed:{' '}
                  {String(compareResult.diff.sha256_changed)}
                </p>
                {compareResult.diff.new_discrepancies.length > 0 && (
                  <p className="mt-1 text-[var(--color-danger)]">
                    New Discrepancies: {compareResult.diff.new_discrepancies.join(' | ')}
                  </p>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {/* TAB 7: วิเคราะห์ (Analytics & Sandbox Scenarios Lab) */}
      {activeTab === 'analytics' && (
        <div className="space-y-5">
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              สถิติผลการพิสูจน์จริง (PASS vs FAIL vs BLOCKED)
            </h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
              นับจากหลักฐานการรันจริงในระบบเท่านั้น
            </p>
            <div className="mt-4 h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analyticsSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" stroke="var(--color-text-secondary)" fontSize={12} />
                  <YAxis allowDecimals={false} stroke="var(--color-text-secondary)" fontSize={12} />
                  <Tooltip />
                  <Bar dataKey="count" fill="var(--color-primary)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Embedded RestoreProof Sandbox Lab for 5 Scenarios + Custom Bundle */}
          <RestoreProofPanel token={token} />
        </div>
      )}

      {/* TAB 8: ระบบ (System Monitor & Worker Registry) */}
      {activeTab === 'system' && (
        <div className="space-y-5">
          {monitor && (
            <section className="grid gap-3 sm:grid-cols-4 tabular-nums">
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                  <Cpu className="h-4 w-4 text-[var(--color-accent)]" />
                  <span>CPU & Load</span>
                </div>
                <p className="mt-1.5 font-mono text-lg font-bold text-[var(--color-text)]">
                  {monitor.host.cpu_count} Cores
                </p>
                <p className="font-mono text-[11px] text-[var(--color-text-muted)]">
                  load1m={monitor.host.load_avg[0]}
                </p>
              </div>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                <p className="text-xs text-[var(--color-text-secondary)]">RAM Usage</p>
                <p className="mt-1.5 font-mono text-lg font-bold text-[var(--color-text)]">
                  {monitor.host.ram.used_pct !== null ? `${monitor.host.ram.used_pct}%` : '-'}
                </p>
                <p className="font-mono text-[11px] text-[var(--color-text-muted)]">
                  avail {monitor.host.ram.available_mb ?? '-'} / {monitor.host.ram.total_mb ?? '-'} MB
                </p>
              </div>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                  <HardDrive className="h-4 w-4 text-[var(--color-accent)]" />
                  <span>Disk Space</span>
                </div>
                <p className="mt-1.5 font-mono text-lg font-bold text-[var(--color-text)]">
                  {monitor.host.disk.free_gb} GB free
                </p>
                <p className="font-mono text-[11px] text-[var(--color-text-muted)]">
                  used {monitor.host.disk.used_pct}% of {monitor.host.disk.total_gb} GB
                </p>
              </div>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                  <Terminal className="h-4 w-4 text-[var(--color-accent)]" />
                  <span>Worker Binaries</span>
                </div>
                <p className="mt-1.5 font-mono text-xs text-[var(--color-text)]">
                  sqlite3: {monitor.binaries.sqlite3?.available ? 'READY' : 'NO'} · pg_restore:{' '}
                  {monitor.binaries.pg_restore?.available ? 'READY' : 'MISSING'}
                </p>
                <p className="mt-1 font-mono text-[11px] text-[var(--color-text-muted)]">
                  docker: {monitor.binaries.docker?.available ? 'READY' : 'MISSING'}
                </p>
              </div>
            </section>
          )}

          {/* Worker Nodes */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="mb-3 text-sm font-semibold text-[var(--color-text)]">
              Restore Worker Nodes ({workers.length})
            </h3>
            <div className="space-y-2">
              {workers.map((w) => (
                <div
                  key={w.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs"
                >
                  <div>
                    <p className="font-semibold text-[var(--color-text)]">
                      {w.name} <span className="font-mono text-[11px] text-[var(--color-text-muted)]">({w.id})</span>
                    </p>
                    <p className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                      {w.endpoint} · modes={w.isolation_modes.join(',')} · active={w.active_jobs ?? 0}/{w.max_concurrent}
                    </p>
                  </div>
                  <span className={`font-mono font-semibold ${statusTextClass(w.status)}`}>
                    {w.status}
                  </span>
                </div>
              ))}
            </div>

            {user.role === 'admin' && (
              <form onSubmit={(e) => void handleSaveWorker(e)} className="mt-4 grid gap-2 sm:grid-cols-4">
                <input
                  type="text"
                  value={workerName}
                  onChange={(e) => setWorkerName(e.target.value)}
                  placeholder="ชื่อ Worker ใหม่ (เช่น PG Worker Node)"
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
                />
                <input
                  type="text"
                  value={workerEndpoint}
                  onChange={(e) => setWorkerEndpoint(e.target.value)}
                  placeholder="Endpoint URI"
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                />
                <input
                  type="number"
                  min={1}
                  value={workerMaxConc}
                  onChange={(e) => setWorkerMaxConc(Number(e.target.value))}
                  className="min-h-[42px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)]"
                />
                <button
                  type="submit"
                  disabled={busyAction !== null || !workerName.trim()}
                  className="min-h-[42px] rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white"
                >
                  + เพิ่ม Worker (Admin)
                </button>
              </form>
            )}
          </section>
        </div>
      )}

      {/* TAB 9: ตั้งค่า (Security Policies, Audit Trail, Android APK Status) */}
      {activeTab === 'settings' && (
        <div className="space-y-5">
          {/* Security Policies */}
          {policyDraft && (
            <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-text)]">
                    นโยบายความปลอดภัย Fail-Closed & Approval Gate
                  </h3>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    บทบาทปัจจุบัน: {user.email} ({user.role})
                  </p>
                </div>
                {user.role === 'admin' && (
                  <button
                    type="button"
                    disabled={busyAction !== null}
                    onClick={() => void handleSavePolicies()}
                    className="min-h-[42px] rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)]"
                  >
                    บันทึกนโยบาย
                  </button>
                )}
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {(
                  [
                    ['require_sha256_match', 'บังคับตรวจ SHA-256 ก่อนกู้คืน'],
                    ['auto_cleanup_ephemeral', 'ลบพื้นที่ทดสอบอัตโนมัติหลังจบงาน'],
                    ['require_approval_for_assistant_mutations', 'บังคับ Approval Gate เมื่อ AI Assistant สั่งเปลี่ยนระบบ'],
                    ['alert_on_fail', 'แจ้งเตือนทันทีเมื่อ Restore FAIL'],
                  ] as const
                ).map(([key, label]) => (
                  <label
                    key={key}
                    className="flex min-h-[44px] items-center justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs text-[var(--color-text)]"
                  >
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      disabled={user.role !== 'admin'}
                      checked={Boolean(policyDraft[key])}
                      onChange={(e) =>
                        setPolicyDraft((prev) =>
                          prev ? { ...prev, [key]: e.target.checked } : prev
                        )
                      }
                      className="h-4 w-4 accent-[var(--color-primary)]"
                    />
                  </label>
                ))}
              </div>
              <p className="mt-3 font-mono text-[11px] text-[var(--color-text-muted)]">
                Reserved DB Blocklist: {policyDraft.reserved_db_blocklist.join(', ')}
              </p>
            </section>
          )}

          {/* Honest Android APK Phased Delivery Disclosure */}
          <section className="rounded-2xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] p-4 text-xs">
            <div className="flex items-center gap-2 font-semibold text-[var(--color-warning)]">
              <ShieldAlert className="h-4 w-4" />
              <span>สถานะ Android APK Client (Phased Delivery — Fail-Closed Disclosure)</span>
            </div>
            <p className="mt-1 text-[var(--color-text)]">
              Phase 1 (Backend Control API v1 + Isolated Verification Worker + Mobile-First 9-Tab Web Control Center) พร้อมรันและทดสอบจริงแล้ว
              ส่วนการคอมไพล์ไฟล์ Android APK (.apk) ในคอนเทนเนอร์นี้มีสถานะ <strong className="font-mono">BLOCKED</strong> เนื่องจากไม่มี Android SDK / Java / Gradle ในเครื่องรัน
              (ดูโครงสร้างโมดูล Kotlin/Compose ที่พร้อมสร้าง APK ใน docs/products/realitycheck/ANDROID_MODULAR_ROADMAP.md)
            </p>
          </section>

          {/* Immutable Audit Log */}
          <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
            <h3 className="mb-3 text-sm font-semibold text-[var(--color-text)]">
              Audit Trail (บันทึกย้อนหลัง {audit.length} รายการล่าสุด)
            </h3>
            {audit.length === 0 ? (
              <p className="text-xs text-[var(--color-text-secondary)]">ยังไม่มีประวัติ Audit</p>
            ) : (
              <div className="max-h-72 space-y-1.5 overflow-y-auto font-mono text-[11px]">
                {audit.map((entry) => (
                  <div
                    key={entry.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
                  >
                    <span className="text-[var(--color-text)]">
                      {entry.action} · {entry.target} · {entry.actor}
                    </span>
                    <span className="text-[var(--color-text-secondary)]">
                      {entry.outcome} · {formatDateTime(entry.timestamp)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
