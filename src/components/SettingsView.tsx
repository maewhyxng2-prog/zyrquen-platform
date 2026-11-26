import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  Database,
  Download,
  KeyRound,
  LogOut,
  Moon,
  Play,
  Shield,
  ShieldCheck,
  Sun,
  Terminal,
  Trash2,
  User as UserIcon,
  X,
} from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import { downloadText, isPiiAuditEvent, redactAuditRow, toSafeAuditCsv, toSafeAuditJson } from '../lib/auditExport';
import type { AuditEvent } from '../lib/auditExport';
import { runNativeCapabilityBenchmark } from '../lib/benchmark';
import { serializeTableToTsv } from '../lib/clipboard';
import { useZyrquenTheme } from '../lib/theme';
import { MODEL_VARIANTS } from '../types';
import { CopyButton } from './CopyButton';
import { ToolRegistry } from './ToolRegistry';

const AdminStabilityPanel = lazy(() =>
  import('./AdminStabilityPanel').then((m) => ({ default: m.AdminStabilityPanel }))
);
import type {
  AdminOverview,
  ClientLatencySample,
  DatasetVerifyResult,
  DeveloperOverview,
  MemorySnapshot,
  ModelVariantId,
  NativeBenchmarkEvaluation,
  ReasoningMode,
  SettingsTab,
  ThreadCleanupVerification,
  ToolsOverview,
  User,
} from '../types';

interface SettingsViewProps {
  token: string;
  user: User;
  activeTab: SettingsTab;
  autoExpandTrace: boolean;
  defaultMode: ReasoningMode;
  selectedModelVariant?: ModelVariantId;
  perfSamples?: MemorySnapshot[];
  clientLatencies?: ClientLatencySample[];
  cleanupVerification?: ThreadCleanupVerification | null;
  onCapturePerfSample?: () => void;
  onChangeTab: (tab: SettingsTab) => void;
  onOpenMemory?: () => void;
  onUpdatePreferences: (prefs: {
    autoExpandTrace?: boolean;
    defaultMode?: ReasoningMode;
    modelVariant?: ModelVariantId;
  }) => void;
  onLogout: () => void;
}

export function SettingsView({
  token,
  user,
  activeTab,
  autoExpandTrace,
  defaultMode,
  selectedModelVariant = 'zyrquen-omega-v1',
  perfSamples = [],
  clientLatencies = [],
  cleanupVerification = null,
  onCapturePerfSample,
  onChangeTab,
  onOpenMemory,
  onUpdatePreferences,
  onLogout,
}: SettingsViewProps) {
  const { theme, setTheme } = useZyrquenTheme();
  const [devData, setDevData] = useState<DeveloperOverview | null>(null);
  const [toolsData, setToolsData] = useState<ToolsOverview | null>(null);
  const [adminData, setAdminData] = useState<AdminOverview | null>(null);
  const [adminSubTab, setAdminSubTab] = useState<'governance' | 'stability'>('governance');
  const [auditEventFilter, setAuditEventFilter] = useState('ALL');
  const [auditSearch, setAuditSearch] = useState('');
  const [auditFrom, setAuditFrom] = useState('');
  const [auditTo, setAuditTo] = useState('');
  const [auditFormat, setAuditFormat] = useState<'csv' | 'json'>('csv');
  const [auditPiiOnly, setAuditPiiOnly] = useState(true);
  const [exportingAudit, setExportingAudit] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [keyName, setKeyName] = useState('');
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);

  const [dsName, setDsName] = useState('');
  const [dsContent, setDsContent] = useState('');
  const [dsProvenance, setDsProvenance] = useState('developer_manual_corpus');
  const [dsSourceName, setDsSourceName] = useState('');
  const [dsLicense, setDsLicense] = useState('INTERNAL_VERIFIED');
  const [dsFormat, setDsFormat] = useState<'auto' | 'text' | 'jsonl' | 'json' | 'csv'>('auto');
  const [dsExtractKg, setDsExtractKg] = useState(true);
  const [dsMessage, setDsMessage] = useState<string | null>(null);
  const [dsVerifyMap, setDsVerifyMap] = useState<Record<string, DatasetVerifyResult>>({});
  const [verifyingDsId, setVerifyingDsId] = useState<string | null>(null);
  const [runningEval, setRunningEval] = useState(false);
  const [requestingTrainId, setRequestingTrainId] = useState<string | null>(null);
  const [benchmarkModel, setBenchmarkModel] = useState<ModelVariantId>('zyrquen-omega-v1');
  const [runningBenchmark, setRunningBenchmark] = useState(false);
  const [benchmarkEval, setBenchmarkEval] = useState<NativeBenchmarkEvaluation | null>(null);
  const [curatingCorpus, setCuratingCorpus] = useState(false);
  const [runningExperiment, setRunningExperiment] = useState(false);
  const [experimentMsg, setExperimentMsg] = useState<string | null>(null);

  const loadDeveloper = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [res, toolsRes] = await Promise.all([
        apiRequest<DeveloperOverview>('/api/developer/overview', { token }),
        apiRequest<ToolsOverview>('/api/developer/tools', { token }).catch(() => null),
      ]);
      setDevData(res);
      if (toolsRes) setToolsData(toolsRes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดเครื่องมือนักพัฒนาได้');
    } finally {
      setLoading(false);
    }
  }, [token]);

  const loadAdmin = useCallback(async () => {
    if (user.role !== 'admin') return;
    setLoading(true);
    setError(null);
    try {
      const [res, auditLogs] = await Promise.all([
        apiRequest<AdminOverview>('/api/admin/overview', { token }),
        apiRequest<AuditEvent[]>('/api/admin/audit-logs?limit=500', { token }).catch(() => null),
      ]);
      setAdminData({
        ...res,
        audit_logs: (auditLogs ?? res.audit_logs ?? []).map((log) => ({
          ...log,
          actor_id: log.actor_id ?? '',
          actor_email: log.actor_email ?? '',
          target: log.target ?? '',
          outcome: log.outcome ?? '',
        })),
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดส่วนผู้ดูแลระบบได้');
    } finally {
      setLoading(false);
    }
  }, [token, user.role]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (!active) return;
      if (activeTab === 'developer') {
        void loadDeveloper();
      } else if (activeTab === 'admin' && user.role === 'admin') {
        void loadAdmin();
      }
    });
    return () => {
      active = false;
    };
  }, [activeTab, loadAdmin, loadDeveloper, user.role]);

  async function handleCreateKey(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await apiRequest<{ plaintextKey: string }>('/api/developer/keys', {
        method: 'POST',
        token,
        body: { name: keyName, scopes: ['infer:read', 'knowledge:write'] },
      });
      setCreatedSecret(res.plaintextKey);
      setKeyName('');
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'สร้าง API Key ไม่สำเร็จ');
    }
  }

  async function handleRevokeKey(id: string) {
    try {
      await apiRequest(`/api/developer/keys/${id}`, { method: 'DELETE', token });
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เพิกถอน API Key ไม่สำเร็จ');
    }
  }

  async function handleDatasetFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setDsContent(text);
      if (!dsName.trim()) {
        const baseName = file.name.replace(/\.[^.]+$/, '').slice(0, 80);
        if (baseName) setDsName(baseName);
      }
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (ext === 'jsonl' || ext === 'json' || ext === 'csv') {
        setDsFormat(ext);
      } else if (ext === 'txt') {
        setDsFormat('text');
      }
      if (!dsSourceName.trim()) {
        setDsSourceName(file.name.slice(0, 120));
      }
    } catch {
      setError('ไม่สามารถอ่านไฟล์ชุดข้อมูลที่เลือกได้');
    }
  }

  async function handleIngestDataset(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setDsMessage(null);
    try {
      const res = await apiRequest<{
        dataset: {
          id: string;
          name: string;
          train_count: number;
          val_count: number;
          test_count: number;
          manifest_hash: string;
          source_format?: string;
        };
        kg_proposal?: { id: string; triple_count: number; status: string } | null;
        deduplicated_removed: number;
      }>('/api/developer/datasets', {
        method: 'POST',
        token,
        body: {
          name: dsName,
          content: dsContent,
          provenance: dsProvenance.trim() || 'developer_manual_corpus',
          sourceName: dsSourceName.trim() || dsProvenance.trim() || 'developer_manual_corpus',
          license: dsLicense.trim() || 'INTERNAL_VERIFIED',
          format: dsFormat,
          extractKg: dsExtractKg,
        },
      });
      const kgNote = res.kg_proposal
        ? ` · เสนอเข้า KG Gate ${res.kg_proposal.triple_count} triples (${res.kg_proposal.status})`
        : '';
      setDsMessage(
        `นำเข้า "${res.dataset.name}" (${res.dataset.source_format || dsFormat}) แล้ว: Train ${res.dataset.train_count} / Val ${res.dataset.val_count} / Test ${res.dataset.test_count} · SHA-256 ${res.dataset.manifest_hash.slice(0, 12)}… (คัดกรองซ้ำ ${res.deduplicated_removed} รายการ)${kgNote}`
      );
      setDsName('');
      setDsContent('');
      if (activeTab === 'admin' && user.role === 'admin') {
        await loadAdmin();
      } else {
        await loadDeveloper();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'นำเข้าชุดข้อมูลไม่สำเร็จ');
    }
  }

  async function handleVerifyDatasetChecksum(datasetId: string) {
    setVerifyingDsId(datasetId);
    setError(null);
    try {
      const res = await apiRequest<DatasetVerifyResult>(`/api/developer/datasets/${datasetId}/verify`, {
        token,
      });
      setDsVerifyMap((prev) => ({ ...prev, [datasetId]: res }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ตรวจสอบ Checksum ชุดข้อมูลไม่สำเร็จ');
    } finally {
      setVerifyingDsId(null);
    }
  }

  async function handleKgProposalDecision(proposalId: string, decision: 'approve' | 'reject') {
    setError(null);
    try {
      await apiRequest(`/api/admin/kg-proposals/${proposalId}/decide`, {
        method: 'POST',
        token,
        body: { decision },
      });
      await loadAdmin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ดำเนินการ KG Approval Gate ไม่สำเร็จ');
    }
  }

  async function handleRunEvaluation() {
    setRunningEval(true);
    setError(null);
    try {
      await apiRequest('/api/developer/evaluate', {
        method: 'POST',
        token,
        body: { suiteName: 'ZYRQUEN Scientific Benchmark v1' },
      });
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'รันการประเมินผลไม่สำเร็จ');
    } finally {
      setRunningEval(false);
    }
  }

  async function handleRunCapabilityBenchmark() {
    setRunningBenchmark(true);
    setError(null);
    try {
      const evaluation = await runNativeCapabilityBenchmark(token, {
        modelVersion: benchmarkModel,
        logToConsole: true,
      });
      setBenchmarkEval(evaluation);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'รัน Capability Benchmark จริงไม่สำเร็จ'
      );
    } finally {
      setRunningBenchmark(false);
    }
  }

  async function handleRequestTrainingGate(datasetId: string, datasetName: string) {
    setRequestingTrainId(datasetId);
    setError(null);
    setDsMessage(null);
    try {
      const res = await apiRequest<{
        run: { status: string; summary: string };
      }>('/api/workflows/native_training/run', {
        method: 'POST',
        token,
        body: { datasetId },
      });
      setDsMessage(
        res.run.status === 'PENDING_APPROVAL'
          ? `ส่งคำขอฝึกชุดข้อมูล "${datasetName}" เข้า Approval Gate แล้ว (รอผู้ดูแลระบบอนุมัติ)`
          : res.run.summary
      );
      if (activeTab === 'admin' && user.role === 'admin') {
        await loadAdmin();
      } else {
        await loadDeveloper();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ส่งคำขอฝึกโมเดลไม่สำเร็จ');
    } finally {
      setRequestingTrainId(null);
    }
  }

  async function handleApprovalDecision(runId: string, decision: 'approve' | 'reject') {
    setError(null);
    try {
      await apiRequest(`/api/workflows/runs/${runId}/decide`, {
        method: 'POST',
        token,
        body: { decision },
      });
      await loadAdmin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ดำเนินการ Approval Gate ไม่สำเร็จ');
    }
  }

  async function handleCurateCorpus() {
    setCuratingCorpus(true);
    setError(null);
    setExperimentMsg(null);
    try {
      const res = await apiRequest<{
        dataset: { name: string; total_records: number };
      }>('/api/developer/curate-corpus', {
        method: 'POST',
        token,
        body: { name: 'verified-knowledge-corpus' },
      });
      setExperimentMsg(
        `คัดกรองชุดข้อมูล "${res.dataset.name}" จากความจำที่ยืนยันแล้ว (${res.dataset.total_records} รายการ)`
      );
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'คัดกรองชุดข้อมูลจากความจำไม่สำเร็จ');
    } finally {
      setCuratingCorpus(false);
    }
  }

  async function handleRunNeuralExperiment() {
    setRunningExperiment(true);
    setError(null);
    setExperimentMsg(null);
    try {
      const cleanDs =
        (activeTab === 'admin'
          ? (adminData?.training_readiness?.datasets || []).find((d) => !d.leakage_detected)
          : (devData?.datasets || []).find((d) => !d.leakage_detected)) || null;
      const res = await apiRequest<{
        improved: boolean;
        experiment: { approval_status: string };
      }>('/api/developer/experiments', {
        method: 'POST',
        token,
        body: { datasetId: cleanDs?.id || null, epochs: 8 },
      });
      setExperimentMsg(
        res.improved
          ? 'การทดลอง Neural Transformer ลด Val Loss สำเร็จ — ส่งเข้าคิวอนุมัติผู้ดูแลระบบแล้ว'
          : `การทดลองเสร็จสิ้น (สถานะ: ${res.experiment.approval_status})`
      );
      if (activeTab === 'admin' && user.role === 'admin') {
        await loadAdmin();
      } else {
        await loadDeveloper();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'รันการทดลอง Neural Transformer ไม่สำเร็จ');
    } finally {
      setRunningExperiment(false);
    }
  }

  async function handleExperimentDecision(expId: string, decision: 'approve' | 'reject') {
    setError(null);
    try {
      await apiRequest(`/api/admin/experiments/${expId}/decide`, {
        method: 'POST',
        token,
        body: { decision },
      });
      await loadAdmin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ดำเนินการอนุมัติการทดลองไม่สำเร็จ');
    }
  }

  const filteredAuditLogs = (adminData?.audit_logs || []).filter((log) => {
    const event = log.action.toUpperCase();
    if (auditEventFilter !== 'ALL' && !event.includes(auditEventFilter)) return false;
    if (auditPiiOnly && !isPiiAuditEvent(log as AuditEvent)) return false;
    const created = new Date(log.created_at).getTime();
    if (auditFrom && created < new Date(`${auditFrom}T00:00:00`).getTime()) return false;
    if (auditTo && created > new Date(`${auditTo}T23:59:59.999`).getTime()) return false;
    const haystack = [log.action, log.actor_email, log.target, log.outcome].join(' ').toLowerCase();
    return haystack.includes(auditSearch.trim().toLowerCase());
  });

  async function handleExportAudit() {
    setExportingAudit(true);
    setError(null);
    try {
      const rows = filteredAuditLogs as AuditEvent[];
      const date = new Date().toISOString().slice(0, 10);
      const content = auditFormat === 'csv'
        ? toSafeAuditCsv(rows, auditPiiOnly)
        : toSafeAuditJson(rows, auditPiiOnly);
      await apiRequest('/api/admin/audit-logs/export', {
        method: 'POST',
        token,
        body: { format: auditFormat, exported_count: rows.length },
      });
      downloadText(
        `zyrquen-audit-${auditPiiOnly ? 'pii' : 'all'}-${date}.${auditFormat}`,
        content,
        auditFormat === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8'
      );
      await loadAdmin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ส่งออก Audit Logs ไม่สำเร็จ');
    } finally {
      setExportingAudit(false);
    }
  }

  async function handleRoleChange(targetUserId: string, role: 'admin' | 'user') {
    setError(null);
    try {
      await apiRequest(`/api/admin/users/${targetUserId}/role`, {
        method: 'PATCH',
        token,
        body: { role },
      });
      await loadAdmin();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เปลี่ยนสิทธิ์ผู้ใช้ไม่สำเร็จ');
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">ตั้งค่า</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            แยกการตั้งค่าบัญชีผู้ใช้ออกจากเครื่องมือนักพัฒนาและส่วนผู้ดูแลระบบอย่างชัดเจน
          </p>
        </div>

        <div className="flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1">
          <button
            type="button"
            onClick={() => onChangeTab('account')}
            className={`flex min-h-[40px] items-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              activeTab === 'account'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            <UserIcon className="h-3.5 w-3.5" />
            <span>บัญชีผู้ใช้</span>
          </button>

          <button
            type="button"
            onClick={() => onChangeTab('developer')}
            className={`flex min-h-[40px] items-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              activeTab === 'developer'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>นักพัฒนา</span>
          </button>

          {user.role === 'admin' && (
            <button
              type="button"
              onClick={() => onChangeTab('admin')}
              className={`flex min-h-[40px] items-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
                activeTab === 'admin'
                  ? 'bg-[var(--zyrquen-violet)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              <Shield className="h-3.5 w-3.5" />
              <span>ผู้ดูแลระบบ</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span className="min-w-0 flex-1 break-words">{error}</span>
          <CopyButton
            getText={() => error}
            ariaLabel="คัดลอกข้อความข้อผิดพลาด"
            size="xs"
          />
        </div>
      )}

      {/* TAB 1: บัญชีผู้ใช้ */}
      {activeTab === 'account' && (
        <div className="space-y-6">
          <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
            <h3 className="text-base font-semibold text-[var(--color-text)]">โปรไฟล์และเซสชัน</h3>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">ชื่อที่แสดง</p>
                <p className="mt-1 text-sm font-medium text-[var(--color-text)]">{user.display_name}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">อีเมล</p>
                <p className="mt-1 text-sm font-medium text-[var(--color-text)]">{user.email}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--color-text-secondary)]">สิทธิ์การเข้าถึง</p>
                <p className="mt-1 text-sm font-medium text-[var(--color-accent)]">
                  {user.role === 'admin' ? 'ผู้ดูแลระบบ (admin)' : 'ผู้ใช้งานทั่วไป (user)'}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
            <h3 className="text-base font-semibold text-[var(--color-text)]">การตั้งค่าเวิร์กสเปซและธีม Neural Aurora</h3>
            <div className="mt-4 space-y-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-[var(--color-text)]">โหมดสีและภาพลักษณ์ (Neural Aurora)</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    เลือกธีม Dark (Deep Navy) หรือ Light (WCAG AA Contrast) สำหรับทุกหน้าในระบบ
                  </p>
                </div>
                <div
                  role="group"
                  aria-label="เลือกโหมดสี Dark หรือ Light"
                  className="inline-flex gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
                >
                  <button
                    type="button"
                    aria-pressed={theme === 'dark'}
                    onClick={() => setTheme('dark')}
                    className={`flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap ${
                      theme === 'dark'
                        ? 'bg-[var(--color-primary)] text-white'
                        : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                    }`}
                  >
                    <Moon className="h-3.5 w-3.5" />
                    <span>โหมดมืด (Dark)</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={theme === 'light'}
                    onClick={() => setTheme('light')}
                    className={`flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap ${
                      theme === 'light'
                        ? 'bg-[var(--color-primary)] text-white'
                        : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                    }`}
                  >
                    <Sun className="h-3.5 w-3.5" />
                    <span>โหมดสว่าง (Light)</span>
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-2 border-t border-[var(--color-border)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-[var(--color-text)]">โหมดการประมวลผลเริ่มต้น</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    กำหนดแกนประมวลผลหลักเมื่อเปิดเซสชันใหม่ในเวิร์กสเปซ
                  </p>
                </div>
                <select
                  value={defaultMode}
                  onChange={(e) =>
                    onUpdatePreferences({ defaultMode: e.target.value as ReasoningMode })
                  }
                  className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                >
                  <option value="auto">อัตโนมัติภายใน (Auto)</option>
                  <option value="math">คณิตศาสตร์ AST</option>
                  <option value="knowledge">กราฟความรู้</option>
                  <option value="plan">วางแผนงาน DAG</option>
                  <option value="model">Checkpoint N-Gram</option>
                </select>
              </div>

              <div className="flex flex-col gap-2 border-t border-[var(--color-border)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-[var(--color-text)]">รุ่นโมเดลและแกนประมวลผลภายใน (Model Variant)</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    เลือกสถาปัตยกรรมภายในสำหรับประมวลผลคำสั่งในพื้นที่ดำเนินงาน
                  </p>
                </div>
                <select
                  aria-label="เลือกรุ่นโมเดล (Model Variant)"
                  value={selectedModelVariant}
                  onChange={(e) =>
                    onUpdatePreferences({ modelVariant: e.target.value as ModelVariantId })
                  }
                  className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                >
                  {MODEL_VARIANTS.map((variant) => (
                    <option key={variant.id} value={variant.id}>
                      {variant.label}
                    </option>
                  ))}
                </select>
              </div>

              {onOpenMemory && (
                <div className="flex flex-col gap-2 border-t border-[var(--color-border)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-[var(--color-text)]">
                      ความจำ กราฟความรู้ และเวิร์กโฟลว์ภายใน
                    </p>
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      จัดการข้อเท็จจริงถาวร สถานะเวิร์กโฟลว์กลางทั้ง 8 กลุ่ม และร่องรอยเหตุผลย้อนหลัง
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={onOpenMemory}
                    className="flex h-10 shrink-0 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] whitespace-nowrap"
                  >
                    เปิดหน้าความจำและเวิร์กโฟลว์
                  </button>
                </div>
              )}

              <div className="flex items-center justify-between gap-4 border-t border-[var(--color-border)] pt-4">
                <div>
                  <p className="text-sm font-medium text-[var(--color-text)]">
                    แสดงร่องรอยการประมวลผลอัตโนมัติ
                  </p>
                  <p className="text-xs text-[var(--color-text-secondary)]">
                    กางลำดับขั้น AST, แหล่งอ้างอิงความรู้ และเวลาทำงานใต้คำตอบโดยอัตโนมัติ
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={autoExpandTrace}
                  onClick={() => onUpdatePreferences({ autoExpandTrace: !autoExpandTrace })}
                  className={`flex h-8 w-14 shrink-0 items-center rounded-full p-1 transition-colors ${
                    autoExpandTrace
                      ? 'justify-end bg-[var(--color-primary)]'
                      : 'justify-start border border-[var(--color-border)] bg-[var(--color-surface)]'
                  }`}
                >
                  <span className="h-6 w-6 rounded-full bg-white shadow-sm" />
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">ออกจากระบบ</h3>
                <p className="text-xs text-[var(--color-text-secondary)]">
                  ยกเลิกโทเคนเซสชันบนเซิร์ฟเวอร์และล้างหน่วยความจำทันที
                </p>
              </div>
              <button
                type="button"
                onClick={onLogout}
                className="flex h-11 items-center justify-center gap-2 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-5 text-sm font-medium text-[var(--color-danger)] hover:opacity-90"
              >
                <LogOut className="h-4 w-4" />
                <span>ออกจากระบบ</span>
              </button>
            </div>
          </section>
        </div>
      )}

      {/* TAB 2: เครื่องมือนักพัฒนา */}
      {activeTab === 'developer' && (
        <div className="space-y-6">
          {loading && !devData ? (
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6 text-sm text-[var(--color-text-secondary)]">
              กำลังโหลดข้อมูลนักพัฒนา...
            </div>
          ) : (
            <>
              <section className="grid gap-4 sm:grid-cols-3">
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                  <p className="text-xs text-[var(--color-text-secondary)]">จำนวนคำขอ API ทั้งหมด</p>
                  <p className="mt-1 text-2xl font-bold text-[var(--color-text)] tabular-nums">
                    {devData?.usage.total_requests ?? 0}
                  </p>
                </div>
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                  <p className="text-xs text-[var(--color-text-secondary)]">โควตารายวัน</p>
                  <p className="mt-1 text-2xl font-bold text-[var(--color-accent)] tabular-nums">
                    {devData?.usage.daily_quota ?? 1000}
                  </p>
                </div>
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
                  <p className="text-xs text-[var(--color-text-secondary)]">ความหน่วง API เฉลี่ย</p>
                  <p className="mt-1 text-2xl font-bold text-[var(--color-text)] tabular-nums">
                    {devData?.usage.avg_latency_ms ?? 0} ms
                  </p>
                </div>
              </section>

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex items-center gap-2">
                  <KeyRound className="h-4 w-4 text-[var(--color-accent)]" />
                  <h3 className="text-base font-semibold text-[var(--color-text)]">จัดการ API Keys</h3>
                </div>
                <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                  คีย์ถูกแฮชด้วย SHA-256 บนเซิร์ฟเวอร์ และแสดงคีย์เต็มเพียงครั้งเดียวตอนสร้าง
                </p>

                <form onSubmit={handleCreateKey} className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <input
                    type="text"
                    required
                    minLength={2}
                    value={keyName}
                    onChange={(e) => setKeyName(e.target.value)}
                    placeholder="ชื่อคีย์ (เช่น CLI วิจัย)"
                    className="h-11 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                  />
                  <button
                    type="submit"
                    className="h-11 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-medium text-white hover:bg-[var(--color-primary-hover)] whitespace-nowrap"
                  >
                    สร้าง API Key
                  </button>
                </form>

                {createdSecret && (
                  <div className="mt-4 rounded-xl border border-[var(--color-accent)]/45 bg-[var(--color-surface)] p-3.5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="min-w-0 flex-1 break-all font-mono text-xs text-[var(--color-accent)]">{createdSecret}</p>
                      <CopyButton
                        text={createdSecret}
                        ariaLabel="คัดลอก API Key"
                        title="คัดลอก API Key"
                        size="xs"
                      />
                    </div>
                  </div>
                )}

                <div className="mt-4 divide-y divide-[var(--color-border)]">
                  {(devData?.keys || []).length === 0 ? (
                    <p className="py-3 text-sm text-[var(--color-text-secondary)]">ยังไม่มี API Key ที่สร้างไว้</p>
                  ) : (
                    devData!.keys.map((k) => (
                      <div
                        key={k.id}
                        className="flex min-h-[56px] items-center justify-between gap-3 py-3"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-[var(--color-text)]">{k.name}</p>
                          <p className="font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
                            {k.key_prefix}… · โควตา {k.quota_daily}/วัน ·{' '}
                            {k.revoked ? 'เพิกถอนแล้ว' : 'ใช้งานได้'}
                          </p>
                        </div>
                        {!k.revoked && (
                          <button
                            type="button"
                            onClick={() => void handleRevokeKey(k.id)}
                            aria-label={`เพิกถอน ${k.name}`}
                            className="flex min-h-[40px] items-center gap-1.5 rounded-xl px-3 text-xs text-[var(--color-danger)] hover:bg-[var(--color-danger-bg)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            <span>เพิกถอน</span>
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </section>

              <div className="grid gap-6 lg:grid-cols-2">
                <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-[var(--color-accent)]" />
                    <h3 className="text-base font-semibold text-[var(--color-text)]">
                      นำเข้าชุดข้อมูล (Train/Val/Test)
                    </h3>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    คัดกรองข้อมูลซ้ำ ตรวจ Data Leakage และสร้างแฮช SHA-256 (อย่างน้อย 5 บรรทัด)
                  </p>
                  <form onSubmit={handleIngestDataset} className="mt-4 space-y-3">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <input
                        type="text"
                        required
                        aria-label="ชื่อชุดข้อมูลนักพัฒนา"
                        value={dsName}
                        onChange={(e) => setDsName(e.target.value)}
                        placeholder="ชื่อชุดข้อมูล (เช่น zyrquen-thai-v1)"
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                      />
                      <select
                        aria-label="รูปแบบไฟล์ชุดข้อมูล"
                        value={dsFormat}
                        onChange={(e) => setDsFormat(e.target.value as 'auto' | 'text' | 'jsonl' | 'json' | 'csv')}
                        className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                      >
                        <option value="auto">ตรวจจับรูปแบบอัตโนมัติ (Auto)</option>
                        <option value="text">ข้อความทีละบรรทัด (TXT)</option>
                        <option value="jsonl">JSON Lines (.jsonl)</option>
                        <option value="json">JSON Array / Pre-split (.json)</option>
                        <option value="csv">CSV พร้อมหัวคอลัมน์ (.csv)</option>
                      </select>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <input
                        type="text"
                        aria-label="ที่มาของข้อมูล (Provenance)"
                        value={dsProvenance}
                        onChange={(e) => setDsProvenance(e.target.value)}
                        placeholder="ที่มาข้อมูล (เช่น internal_docs_2026)"
                        className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                      />
                      <input
                        type="text"
                        aria-label="สัญญาอนุญาต (License)"
                        value={dsLicense}
                        onChange={(e) => setDsLicense(e.target.value)}
                        placeholder="License (เช่น INTERNAL_VERIFIED, CC-BY-4.0)"
                        className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--color-text-secondary)]">
                      <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 hover:border-[var(--color-accent)]">
                        <span>โหลดไฟล์ (.txt, .jsonl, .json, .csv)</span>
                        <input
                          type="file"
                          accept=".txt,.jsonl,.json,.csv"
                          onChange={(e) => void handleDatasetFileSelect(e)}
                          className="hidden"
                        />
                      </label>
                      <label className="inline-flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={dsExtractKg}
                          onChange={(e) => setDsExtractKg(e.target.checked)}
                          className="h-4 w-4 accent-[var(--color-primary)]"
                        />
                        <span>สกัดข้อเท็จจริงเข้าคิวรออนุมัติ KG Gate</span>
                      </label>
                    </div>
                    <textarea
                      rows={4}
                      required
                      aria-label="เนื้อหาชุดข้อมูลนักพัฒนา"
                      value={dsContent}
                      onChange={(e) => setDsContent(e.target.value)}
                      placeholder="วางข้อมูลจริง (TXT / JSONL / JSON / CSV) อย่างน้อย 5 รายการที่ไม่ซ้ำกัน..."
                      className="w-full resize-none rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                    />
                    {dsMessage && <p className="text-xs text-[var(--color-accent)]">{dsMessage}</p>}
                    <button
                      type="submit"
                      className="h-11 w-full rounded-xl bg-[var(--color-primary)] text-sm font-medium text-white hover:bg-[var(--color-primary-hover)]"
                    >
                      นำเข้าและแบ่งชุดข้อมูล
                    </button>
                  </form>

                  {(devData?.datasets || []).length > 0 && (
                    <div className="mt-5 border-t border-[var(--color-border)] pt-4">
                      <p className="text-xs font-medium text-[var(--color-text)]">
                        ชุดข้อมูลที่ลงทะเบียน ({devData!.datasets.length} ชุด)
                      </p>
                      <div className="mt-2 divide-y divide-[var(--color-border)]">
                        {devData!.datasets.map((ds) => {
                          const verifyRes = dsVerifyMap[ds.id];
                          return (
                            <div
                              key={ds.id}
                              className="flex flex-wrap items-center justify-between gap-2 py-2.5"
                            >
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-xs font-semibold text-[var(--color-text)]">
                                  {ds.name}
                                </p>
                                <p className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                                  T:{ds.train_count}/V:{ds.val_count}/T:{ds.test_count} ·{' '}
                                  {ds.source_format || 'text'} · {ds.license || 'INTERNAL_VERIFIED'} ·{' '}
                                  {ds.leakage_detected ? 'พบ Leakage' : 'Leakage ผ่าน'} ·{' '}
                                  {ds.manifest_hash.slice(0, 10)}
                                </p>
                                {ds.provenance && (
                                  <p className="truncate text-[11px] text-[var(--color-text-muted)]">
                                    ที่มา: {ds.provenance}
                                  </p>
                                )}
                                {verifyRes && (
                                  <p
                                    className={`mt-0.5 font-mono text-[11px] ${
                                      verifyRes.verified ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'
                                    }`}
                                  >
                                    {verifyRes.verified
                                      ? `Checksum VERIFIED (${verifyRes.disk_verified ? 'Disk+DB' : 'DB'})`
                                      : `Checksum FAILED: ${(verifyRes.errors || [verifyRes.error || 'Mismatch']).join(', ')}`}
                                  </p>
                                )}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                <button
                                  type="button"
                                  disabled={verifyingDsId === ds.id}
                                  onClick={() => void handleVerifyDatasetChecksum(ds.id)}
                                  className="min-h-[34px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-[11px] font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)] disabled:opacity-40 whitespace-nowrap"
                                >
                                  {verifyingDsId === ds.id ? 'กำลังตรวจ...' : 'ตรวจ Checksum'}
                                </button>
                                <button
                                  type="button"
                                  disabled={Boolean(ds.leakage_detected) || requestingTrainId === ds.id}
                                  onClick={() => void handleRequestTrainingGate(ds.id, ds.name)}
                                  className="min-h-[34px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap"
                                >
                                  {requestingTrainId === ds.id ? 'กำลังส่ง...' : 'ส่งคำขอฝึก (Gate)'}
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </section>

                <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-base font-semibold text-[var(--color-text)]">
                      Checkpoint โมเดลแบบไม่เขียนทับ
                    </h3>
                    <button
                      type="button"
                      disabled={runningEval}
                      onClick={() => void handleRunEvaluation()}
                      className="min-h-[36px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50 whitespace-nowrap"
                    >
                      {runningEval ? 'กำลังประเมิน...' : 'ประเมินผลเทียบ Baseline'}
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    สร้างหลังผ่าน Approval Gate ในหน้า ความจำ → ระบบเวิร์กโฟลว์ → ฝึกโมเดลภายใน
                  </p>

                  {devData?.evaluations?.[0] && (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5 text-xs text-[var(--color-text)] tabular-nums">
                      <div>
                        <span className="font-semibold text-[var(--color-accent)]">
                          ผลประเมินล่าสุด ({devData.evaluations[0].overall_status})
                        </span>
                        {' · '}คณิต {Math.round(devData.evaluations[0].math_score * 100)}%
                        {' · '}ความจำ {Math.round(devData.evaluations[0].knowledge_score * 100)}%
                        {' · '}แผน DAG {Math.round(devData.evaluations[0].planning_score * 100)}%
                        {devData.evaluations[0].test_accuracy !== null && (
                          <span>
                            {' · '}Test {(devData.evaluations[0].test_accuracy * 100).toFixed(1)}%
                          </span>
                        )}
                      </div>
                      <CopyButton
                        getText={() => {
                          const ev = devData.evaluations?.[0];
                          if (!ev) return '';
                          return serializeTableToTsv(
                            ['Status', 'Math %', 'Knowledge %', 'Planning %', 'Test Accuracy %'],
                            [
                              [
                                ev.overall_status,
                                Math.round(ev.math_score * 100),
                                Math.round(ev.knowledge_score * 100),
                                Math.round(ev.planning_score * 100),
                                ev.test_accuracy !== null ? (ev.test_accuracy * 100).toFixed(1) : '-',
                              ],
                            ]
                          );
                        }}
                        ariaLabel="คัดลอกผลการประเมิน"
                        title="คัดลอกผลการประเมินเทียบ Baseline"
                        size="xs"
                      />
                    </div>
                  )}

                  <div className="mt-4 divide-y divide-[var(--color-border)]">
                    {(devData?.checkpoints || []).length === 0 ? (
                      <p className="py-4 text-sm text-[var(--color-text-secondary)]">
                        ยังไม่มี Checkpoint ที่ฝึกไว้
                      </p>
                    ) : (
                      devData!.checkpoints.map((ck) => (
                        <div key={ck.id} className="py-3">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-[var(--color-text)]">
                              Checkpoint v{ck.version}
                            </span>
                            <span className="text-xs font-medium text-[var(--color-accent)]">
                              {ck.eval_status}
                            </span>
                          </div>
                          <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
                            vocab {ck.vocab_size} · train_loss {ck.train_loss} · val_loss{' '}
                            {ck.val_loss} · ppl {ck.perplexity}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Activity className="h-4 w-4 text-[var(--color-accent)]" />
                      <h3 className="text-base font-semibold text-[var(--color-text)]">
                        Capability Benchmark (Zero-Mock Native Probe)
                      </h3>
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                      ทดสอบ Python Native AI Core จริงบนฐานข้อมูลแยกชั่วคราว ตรวจ Source Verification และ Abstention Accuracy พร้อมรายงานผลเข้า DevTools Console
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label="เลือกรุ่นโมเดลสำหรับ Benchmark"
                      value={benchmarkModel}
                      onChange={(e) => setBenchmarkModel(e.target.value as ModelVariantId)}
                      className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      {MODEL_VARIANTS.map((variant) => (
                        <option key={variant.id} value={variant.id}>
                          {variant.shortLabel}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      disabled={runningBenchmark}
                      onClick={() => void handleRunCapabilityBenchmark()}
                      className="flex h-10 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-medium text-white transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
                    >
                      <Play className="h-3.5 w-3.5" />
                      <span>{runningBenchmark ? 'กำลังรัน Benchmark...' : 'รัน Benchmark จริง'}</span>
                    </button>
                  </div>
                </div>

                {!benchmarkEval ? (
                  <p className="mt-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-xs text-[var(--color-text-secondary)]">
                    ยังไม่มีผลทดสอบในเซสชันนี้ — กด &ldquo;รัน Benchmark จริง&rdquo; เพื่อวัดความสามารถจริงโดยไม่จำลองคะแนน
                  </p>
                ) : (
                  <div className="mt-4 space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-xs">
                      <div className="flex flex-wrap items-center gap-2 text-[var(--color-text)] tabular-nums">
                        <span className="font-semibold text-[var(--color-accent)]">
                          {benchmarkEval.report.benchmark_version}
                        </span>
                        <span>·</span>
                        <span>
                          คะแนนรวม {benchmarkEval.report.summary.passed}/{benchmarkEval.report.summary.total_cases} (
                          {(benchmarkEval.report.summary.overall_score * 100).toFixed(1)}%)
                        </span>
                        {benchmarkEval.report.summary.failed > 0 && (
                          <>
                            <span>·</span>
                            <span className="font-semibold text-[var(--color-warning)]">
                              {benchmarkEval.report.summary.failed} FAILED
                            </span>
                          </>
                        )}
                        <span>·</span>
                        <span className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                          Python {benchmarkEval.report.environment.python_version} · {benchmarkEval.report.environment.model_version}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-accent)]/35 bg-[var(--color-surface-raised)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-accent)]">
                          <ShieldCheck className="h-3.5 w-3.5" />
                          <span>Zero External LLMs</span>
                        </span>
                        <CopyButton
                          getText={() => {
                            const rep = benchmarkEval.report;
                            const parts = [
                              `ZYRQUEN Native Capability Benchmark (${rep.benchmark_version})`,
                              `Model: ${rep.environment.model_version} | Python: ${rep.environment.python_version}`,
                              `Score: ${rep.summary.passed}/${rep.summary.total_cases} (${(rep.summary.overall_score * 100).toFixed(1)}%) | Failed: ${rep.summary.failed}`,
                              `Source Verification: ${benchmarkEval.sourceVerification.status} (${benchmarkEval.sourceVerification.passed}/${benchmarkEval.sourceVerification.total})`,
                              `Abstention Accuracy: ${(benchmarkEval.abstentionAccuracy.overallAbstentionAccuracy * 100).toFixed(1)}% | False Positives: ${benchmarkEval.abstentionAccuracy.falsePositives}`,
                            ];
                            if (rep.capability_ledger) {
                              parts.push(
                                `Capability Ledger:\n${serializeTableToTsv(
                                  ['Domain', 'Status', 'Passed', 'Total', 'Score %', 'FP', 'Evidence Hash'],
                                  Object.values(rep.capability_ledger.domains).map((d) => [
                                    d.domain,
                                    d.status,
                                    d.passed,
                                    d.total,
                                    (d.score * 100).toFixed(1),
                                    d.false_positives,
                                    d.evidence_hash,
                                  ])
                                )}`
                              );
                            }
                            if (rep.failures.length > 0) {
                              parts.push(
                                `Failures:\n${rep.failures
                                  .map((f) => `- [${f.id}] (${f.failure_type}) ${f.input} | expected=${f.expected} actual=${f.actual}`)
                                  .join('\n')}`
                              );
                            }
                            return parts.join('\n\n');
                          }}
                          ariaLabel="คัดลอกรายงาน Benchmark"
                          title="คัดลอกรายงาน Capability Benchmark ฉบับเต็ม"
                          size="xs"
                        />
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-[var(--color-text)]">
                            Source Verification (Anti-Fabrication)
                          </span>
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-semibold ${
                              benchmarkEval.sourceVerification.status === 'VERIFIED'
                                ? 'text-[var(--color-success)]'
                                : 'text-[var(--color-danger)]'
                            }`}
                          >
                            {benchmarkEval.sourceVerification.status === 'VERIFIED' ? (
                              <CheckCircle2 className="h-3.5 w-3.5" />
                            ) : (
                              <AlertTriangle className="h-3.5 w-3.5" />
                            )}
                            <span>
                              {benchmarkEval.sourceVerification.status} ({benchmarkEval.sourceVerification.passed}/
                              {benchmarkEval.sourceVerification.total})
                            </span>
                          </span>
                        </div>
                        <ul className="mt-3 space-y-1.5 text-[11px] text-[var(--color-text-secondary)]">
                          <li className="flex items-center justify-between">
                            <span>AFB-01 คัดกรองแหล่งปลอม/LLM ภายนอก</span>
                            <span className={benchmarkEval.sourceVerification.checks.fabricatedSourceRejected ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.sourceVerification.checks.fabricatedSourceRejected ? 'PASS' : 'FAIL'}
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>AFB-02 บล็อก URL ไม่ปลอดภัย / นอก Allowlist</span>
                            <span className={benchmarkEval.sourceVerification.checks.invalidUrlRejected ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.sourceVerification.checks.invalidUrlRejected ? 'PASS' : 'FAIL'}
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>AFB-04 ตรวจจับหลักฐานเก่า (STALE)</span>
                            <span className={benchmarkEval.sourceVerification.checks.staleEvidenceFlagged ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.sourceVerification.checks.staleEvidenceFlagged ? 'PASS' : 'FAIL'}
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>AFB-07 ป้องกันรายงานสำเร็จเท็จ</span>
                            <span className={benchmarkEval.sourceVerification.checks.falseSuccessPrevented ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.sourceVerification.checks.falseSuccessPrevented ? 'PASS' : 'FAIL'}
                            </span>
                          </li>
                        </ul>
                      </div>

                      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-[var(--color-text)]">
                            Abstention Accuracy & Leakage Guard
                          </span>
                          <span
                            className={`inline-flex items-center gap-1 text-xs font-semibold tabular-nums ${
                              benchmarkEval.abstentionAccuracy.status === 'VERIFIED'
                                ? 'text-[var(--color-success)]'
                                : 'text-[var(--color-danger)]'
                            }`}
                          >
                            {benchmarkEval.abstentionAccuracy.status === 'VERIFIED' ? (
                              <CheckCircle2 className="h-3.5 w-3.5" />
                            ) : (
                              <AlertTriangle className="h-3.5 w-3.5" />
                            )}
                            <span>
                              {(benchmarkEval.abstentionAccuracy.overallAbstentionAccuracy * 100).toFixed(1)}%
                            </span>
                          </span>
                        </div>
                        <ul className="mt-3 space-y-1.5 text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          <li className="flex items-center justify-between">
                            <span>งดตอบเมื่อไม่รู้จริง (Negative Cases)</span>
                            <span>
                              {benchmarkEval.abstentionAccuracy.negativeCasesPassed}/
                              {benchmarkEval.abstentionAccuracy.negativeCasesTotal}
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>False Positives (ตอบมั่ว / ข้ามขอบเขต)</span>
                            <span className={benchmarkEval.abstentionAccuracy.falsePositives === 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.abstentionAccuracy.falsePositives} (FPR {(benchmarkEval.abstentionAccuracy.falsePositiveRate * 100).toFixed(1)}%)
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>Negative Abstention Suite (NEG-01..07)</span>
                            <span>
                              {benchmarkEval.abstentionAccuracy.negativeAbstentionCategory.passed}/
                              {benchmarkEval.abstentionAccuracy.negativeAbstentionCategory.total}
                            </span>
                          </li>
                          <li className="flex items-center justify-between">
                            <span>Leakage Isolation / Near-Dup Guard</span>
                            <span className={benchmarkEval.report.leakage_detection.near_dup_leakage_caught ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}>
                              {benchmarkEval.report.leakage_detection.fixture_isolation.isolated &&
                              benchmarkEval.report.leakage_detection.near_dup_leakage_caught
                                ? 'VERIFIED'
                                : 'FAILED'}
                            </span>
                          </li>
                        </ul>
                      </div>
                    </div>

                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      {Object.entries(benchmarkEval.report.category_scores).map(([cat, stats]) => (
                        <div
                          key={cat}
                          className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs tabular-nums"
                        >
                          <p className="truncate font-mono text-[11px] text-[var(--color-text-secondary)]">{cat}</p>
                          <p className="mt-0.5 font-semibold text-[var(--color-text)]">
                            {stats.passed}/{stats.total} ({(stats.score * 100).toFixed(1)}%)
                          </p>
                        </div>
                      ))}
                    </div>

                    {benchmarkEval.report.capability_ledger && (
                      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-[var(--color-text)]">
                            Real Capability Ledger — Measured, Not Declared (6 Subsystems)
                          </p>
                          <span className="font-mono text-[11px] text-[var(--color-accent)]">
                            VERIFIED: {benchmarkEval.report.capability_ledger.summary.verified} · PARTIAL:{' '}
                            {benchmarkEval.report.capability_ledger.summary.partial} · BLOCKED:{' '}
                            {benchmarkEval.report.capability_ledger.summary.blocked} · REGRESSION:{' '}
                            {benchmarkEval.report.capability_ledger.summary.regression_failed}
                          </span>
                        </div>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                          {Object.values(benchmarkEval.report.capability_ledger.domains).map((dom) => {
                            const statusStyle =
                              dom.status === 'VERIFIED'
                                ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                                : dom.status === 'PARTIAL' || dom.status === 'TESTED'
                                ? 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]'
                                : dom.status === 'REGRESSION_FAILED' || dom.status === 'BLOCKED'
                                ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                                : 'border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)]';
                            return (
                              <div
                                key={dom.domain}
                                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 text-xs"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-mono text-[11px] font-semibold text-[var(--color-text)]">
                                    {dom.domain}
                                  </span>
                                  <span
                                    className={`rounded-md border px-2 py-0.5 font-mono text-[10px] font-semibold ${statusStyle}`}
                                  >
                                    {dom.status}
                                  </span>
                                </div>
                                <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">{dom.label}</p>
                                <p className="mt-1.5 font-mono text-[11px] text-[var(--color-text)] tabular-nums">
                                  {dom.passed}/{dom.total} ({(dom.score * 100).toFixed(1)}%) · FP {dom.false_positives} · sha{' '}
                                  {dom.evidence_hash.slice(0, 8)}
                                </p>
                                <p className="mt-1 text-[10px] text-[var(--color-text-muted)]">
                                  Unseen:{dom.criteria.has_unseen_dataset ? '✓' : '✗'} · E2E:{dom.criteria.has_e2e_probe ? '✓' : '✗'} · Post:{dom.criteria.has_postcondition_check ? '✓' : '✗'}
                                </p>
                                {dom.disclosed_gaps.length > 0 && (
                                  <p className="mt-1.5 text-[10px] text-[var(--color-warning)]">
                                    {dom.disclosed_gaps[0]}
                                  </p>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {benchmarkEval.report.failures.length > 0 && (
                      <div className="rounded-2xl border border-[var(--color-warning)]/35 bg-[var(--color-warning-bg)] p-4">
                        <p className="text-xs font-semibold text-[var(--color-warning)]">
                          ข้อจำกัดและรายการที่ยังไม่ผ่าน ({benchmarkEval.report.failures.length} รายการ — แสดงผลตามจริงไม่ปกปิด)
                        </p>
                        <div className="mt-2 max-h-48 space-y-1.5 overflow-y-auto pr-1">
                          {benchmarkEval.report.failures.map((f) => (
                            <div
                              key={f.id}
                              className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2 text-[11px] text-[var(--color-text)]"
                            >
                              <span className="font-mono font-semibold text-[var(--color-warning)]">[{f.id}]</span>{' '}
                              <span className="font-mono text-[var(--color-text-muted)]">({f.failure_type})</span>{' '}
                              <span>{f.input}</span>
                              <p className="mt-0.5 font-mono text-[10px] text-[var(--color-text-secondary)]">
                                expected: {f.expected} | actual: {f.actual}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {benchmarkEval.report.unmeasurable_limitations.length > 0 && (
                      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                        <p className="text-xs font-semibold text-[var(--color-text)]">
                          ขอบเขตที่ยังไม่สามารถวัดผลได้ในชุดทดสอบนี้ (Unmeasurable Limitations)
                        </p>
                        <ul className="mt-2 space-y-1 text-[11px] text-[var(--color-text-secondary)]">
                          {benchmarkEval.report.unmeasurable_limitations.map((item, idx) => (
                            <li key={idx}>• {item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </section>

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-[var(--color-text)]">
                      การเรียนรู้จากความจำ &amp; Neural Transformer (P2)
                    </h3>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                      คัดกรองข้อมูลจากความจำที่ยืนยันแล้ว และทดลองฝึก Native Transformer (Random Init + BPE) เพื่อขออนุมัติโปรโมต Checkpoint
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={curatingCorpus}
                      onClick={() => void handleCurateCorpus()}
                      className="min-h-[38px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-50"
                    >
                      {curatingCorpus ? 'กำลังคัดกรอง...' : 'สร้างชุดข้อมูลจากความจำที่ยืนยันแล้ว'}
                    </button>
                    <button
                      type="button"
                      disabled={runningExperiment}
                      onClick={() => void handleRunNeuralExperiment()}
                      className="min-h-[38px] rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
                    >
                      {runningExperiment ? 'กำลังฝึกทดลอง...' : 'รันการทดลอง Neural Transformer'}
                    </button>
                  </div>
                </div>

                {experimentMsg && (
                  <p className="mt-3 text-xs text-[var(--color-accent)]">{experimentMsg}</p>
                )}

                <div className="mt-4 divide-y divide-[var(--color-border)]">
                  {(devData?.experiments || []).length === 0 ? (
                    <p className="py-3 text-xs text-[var(--color-text-secondary)]">
                      ยังไม่มีประวัติการทดลอง Neural Transformer
                    </p>
                  ) : (
                    devData!.experiments!.map((exp) => {
                      let baseVal = '-';
                      let candVal = '-';
                      let params = '-';
                      try {
                        const b = JSON.parse(exp.baseline_metrics_json) as { initial_val_loss?: number };
                        const c = JSON.parse(exp.candidate_metrics_json) as {
                          final_val_loss?: number;
                          param_count?: number;
                        };
                        if (b.initial_val_loss !== undefined) baseVal = b.initial_val_loss.toFixed(4);
                        if (c.final_val_loss !== undefined) candVal = c.final_val_loss.toFixed(4);
                        if (c.param_count !== undefined) params = c.param_count.toLocaleString();
                      } catch {
                        /* ignore */
                      }
                      return (
                        <div key={exp.id} className="py-3 text-xs">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-semibold text-[var(--color-text)]">{exp.hypothesis}</span>
                            <span className="font-mono text-[var(--color-accent)]">{exp.approval_status}</span>
                          </div>
                          <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                            val_loss: {baseVal} → {candVal} · params: {params}
                          </p>
                        </div>
                      );
                    })
                  )}
                </div>
              </section>

              <ToolRegistry
                token={token}
                userRole={user.role}
                mode="developer"
                toolsData={toolsData}
                onRefresh={loadDeveloper}
                onError={setError}
              />
            </>
          )}
        </div>
      )}

      {/* TAB 3: ผู้ดูแลระบบ */}
      {activeTab === 'admin' && user.role === 'admin' && (
        <div className="space-y-6">
          <div
            role="tablist"
            aria-label="หมวดหมู่ผู้ดูแลระบบ"
            className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1"
          >
            <button
              type="button"
              role="tab"
              aria-selected={adminSubTab === 'governance'}
              onClick={() => setAdminSubTab('governance')}
              className={`flex min-h-[38px] items-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
                adminSubTab === 'governance'
                  ? 'bg-[var(--zyrquen-violet)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              <Shield className="h-3.5 w-3.5" />
              <span>ธรรมาภิบาล &amp; Approval Gate</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={adminSubTab === 'stability'}
              onClick={() => setAdminSubTab('stability')}
              className={`flex min-h-[38px] items-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
                adminSubTab === 'stability'
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              <Activity className="h-3.5 w-3.5" />
              <span>ความเสถียรเนทีฟ (PerformanceMonitor)</span>
            </button>
          </div>

          {loading && !adminData ? (
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6 text-sm text-[var(--color-text-secondary)]">
              กำลังโหลดระบบธรรมาภิบาล...
            </div>
          ) : adminSubTab === 'stability' ? (
            <Suspense
              fallback={
                <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6 text-sm text-[var(--color-text-secondary)]">
                  กำลังโหลดแผงเสถียรภาพระบบ...
                </div>
              }
            >
              <AdminStabilityPanel
                adminData={adminData}
                perfSamples={perfSamples}
                clientLatencies={clientLatencies}
                cleanupVerification={cleanupVerification}
                loading={loading}
                onCapturePerfSample={onCapturePerfSample}
                onRefreshAdmin={() => void loadAdmin()}
              />
            </Suspense>
          ) : (
            <>
              {(() => {
                const tr = adminData?.training_readiness;
                const cleanDatasets = tr?.clean_datasets ?? 0;
                const datasetsTotal = tr?.datasets_total ?? 0;
                const verifiedTriples = tr?.verified_triples ?? 0;
                const experimentsTotal = tr?.experiments_total ?? 0;
                const pendingApprovals =
                  (tr?.pending_experiments ?? adminData?.pending_experiments?.length ?? 0) +
                  (tr?.pending_training_runs ??
                    (adminData?.pending_runs || []).filter((r) => r.group_id === 'native_training')
                      .length);
                const checkpointsTotal = tr?.checkpoints_total ?? 0;
                const neuralCheckpoints = tr?.neural_checkpoints ?? 0;
                const gateStatus = tr?.gate_status || (cleanDatasets === 0 ? 'BLOCKED' : 'READY_FOR_TRAINING_GATE');
                const sys = adminData?.system;

                return (
                  <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-semibold text-[var(--color-text)]">
                            ความพร้อมก่อนเริ่มฝึก Native Model (Training Readiness Gate)
                          </h3>
                          <span
                            className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold ${
                              gateStatus === 'VERIFIED'
                                ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                                : gateStatus.startsWith('BLOCKED')
                                  ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                                  : 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] text-[var(--color-warning)]'
                            }`}
                          >
                            {gateStatus}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                          ZYRQUEN — ปัญญาประดิษฐ์พื้นฐานแบบอัตโนมัติ (Autonomous Foundational Intelligence) · แยกสถานะทรัพยากรเครื่องออกจากความพร้อมในการฝึกจริง
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <CopyButton
                          getText={() =>
                            [
                              `ZYRQUEN Training Readiness Gate: ${gateStatus}`,
                              serializeTableToTsv(
                                ['Check', 'Value'],
                                [
                                  ['Clean Datasets', `${cleanDatasets}/${datasetsTotal}`],
                                  ['Verified Triples', `${verifiedTriples}/${tr?.triples_total ?? 0}`],
                                  ['Experiments', experimentsTotal],
                                  ['Pending Approvals', pendingApprovals],
                                  ['Checkpoints', `${checkpointsTotal} (Neural ${neuralCheckpoints})`],
                                ]
                              ),
                            ].join('\n\n')
                          }
                          ariaLabel="คัดลอกสรุปความพร้อมการฝึก"
                          title="คัดลอกรายงานความพร้อมก่อนเริ่มฝึก Native Model"
                          size="xs"
                        />
                        <button
                          type="button"
                          onClick={() => onChangeTab('developer')}
                          className="min-h-[36px] shrink-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] whitespace-nowrap"
                        >
                          เปิดหน้านักพัฒนา
                        </button>
                      </div>
                    </div>

                    {sys && (
                      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-3 tabular-nums">
                        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2">
                          <p className="text-[11px] text-[var(--color-text-secondary)]">CPU ภายใน (ไม่ถือว่าพร้อมฝึก)</p>
                          <p className="mt-0.5 font-mono text-[var(--color-text)]">{sys.cpu_count} คอร์ · load {sys.load_1m}</p>
                        </div>
                        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2">
                          <p className="text-[11px] text-[var(--color-text-secondary)]">RAM ว่าง / ทั้งหมด</p>
                          <p className="mt-0.5 font-mono text-[var(--color-text)]">
                            {Math.round(sys.mem_available_mb).toLocaleString()} / {Math.round(sys.mem_total_mb).toLocaleString()} MB
                          </p>
                        </div>
                        <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2">
                          <p className="text-[11px] text-[var(--color-text-secondary)]">พื้นที่จัดเก็บว่าง</p>
                          <p className="mt-0.5 font-mono text-[var(--color-text)]">
                            {sys.disk_free_gb} / {sys.disk_total_gb} GB
                          </p>
                        </div>
                      </div>
                    )}

                    <div className="mt-4 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
                      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[var(--color-text)]">1. ชุดข้อมูลจริง (≥5 รายการ, ไร้ Leakage)</span>
                          <span className={`font-mono font-semibold ${cleanDatasets > 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-danger)]'}`}>
                            {cleanDatasets > 0 ? 'PASS' : 'BLOCKED'}
                          </span>
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          ผ่านเกณฑ์ {cleanDatasets} / {datasetsTotal} ชุด
                        </p>
                      </div>
                      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[var(--color-text)]">2. ความรู้ที่ยืนยันแล้ว (KG ≥ 5)</span>
                          <span className={`font-mono font-semibold ${verifiedTriples >= 5 ? 'text-[var(--color-success)]' : 'text-[var(--color-warning)]'}`}>
                            {verifiedTriples >= 5 ? 'PASS' : 'PARTIAL'}
                          </span>
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          ยืนยันแล้ว {verifiedTriples} / {tr?.triples_total ?? 0} รายการ
                        </p>
                      </div>
                      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[var(--color-text)]">3. Random-Init + Approval Gate</span>
                          <span className={`font-mono font-semibold ${checkpointsTotal > 0 ? 'text-[var(--color-success)]' : pendingApprovals > 0 ? 'text-[var(--color-warning)]' : 'text-[var(--color-text-muted)]'}`}>
                            {checkpointsTotal > 0 ? 'VERIFIED' : pendingApprovals > 0 ? 'PENDING' : 'NOT_RUN'}
                          </span>
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          ทดลอง {experimentsTotal} · รออนุมัติ {pendingApprovals} · Ckpt {checkpointsTotal} (Neural {neuralCheckpoints})
                        </p>
                      </div>
                    </div>

                    <div className="mt-5 grid gap-5 border-t border-[var(--color-border)] pt-5 lg:grid-cols-2">
                      <form onSubmit={handleIngestDataset} className="space-y-3">
                        <p className="text-xs font-semibold text-[var(--color-text)]">
                          ขั้นตอนที่ 1: นำเข้าชุดข้อมูลจริง (อย่างน้อย 5 รายการ ไม่ซ้ำกัน)
                        </p>
                        <input
                          type="text"
                          required
                          aria-label="ชื่อชุดข้อมูล Admin"
                          value={dsName}
                          onChange={(e) => setDsName(e.target.value)}
                          placeholder="ชื่อชุดข้อมูล (เช่น zyrquen-corpus-v1)"
                          className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                        />
                        <div className="grid gap-2 sm:grid-cols-2">
                          <input
                            type="text"
                            aria-label="ที่มาข้อมูล Admin"
                            value={dsProvenance}
                            onChange={(e) => setDsProvenance(e.target.value)}
                            placeholder="ที่มาข้อมูล (Provenance)"
                            className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                          />
                          <select
                            aria-label="รูปแบบชุดข้อมูล Admin"
                            value={dsFormat}
                            onChange={(e) => setDsFormat(e.target.value as 'auto' | 'text' | 'jsonl' | 'json' | 'csv')}
                            className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                          >
                            <option value="auto">Auto (TXT/JSONL/JSON/CSV)</option>
                            <option value="text">Text</option>
                            <option value="jsonl">JSONL</option>
                            <option value="json">JSON</option>
                            <option value="csv">CSV</option>
                          </select>
                        </div>
                        <textarea
                          rows={4}
                          required
                          aria-label="เนื้อหาชุดข้อมูล Admin"
                          value={dsContent}
                          onChange={(e) => setDsContent(e.target.value)}
                          placeholder="วางข้อมูลจริงบรรทัดละ 1 รายการ (อย่างน้อย 5 บรรทัดเพื่อแบ่ง Train / Val / Test)..."
                          className="w-full resize-none rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                        />
                        {dsMessage && <p className="text-xs text-[var(--color-accent)]">{dsMessage}</p>}
                        <button
                          type="submit"
                          className="h-10 w-full rounded-xl bg-[var(--color-primary)] text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                        >
                          นำเข้าชุดข้อมูลและตรวจ Data Leakage
                        </button>
                      </form>

                      <div className="space-y-3">
                        <p className="text-xs font-semibold text-[var(--color-text)]">
                          ขั้นตอนถัดไป: ทดลอง Random-Init Neural Transformer &amp; ส่ง Gate
                        </p>
                        {(tr?.datasets || []).length === 0 ? (
                          <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-xs text-[var(--color-text-secondary)]">
                            ยังไม่มีชุดข้อมูลจริงในระบบ — นำเข้าชุดข้อมูลอย่างน้อย 5 บรรทัดทางด้านซ้ายก่อน จึงจะรันการทดลองและส่งคำขอ Approval Gate ได้
                          </div>
                        ) : (
                          <div className="space-y-2">
                            {tr!.datasets.slice(0, 4).map((ds) => (
                              <div
                                key={ds.id}
                                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs"
                              >
                                <div className="min-w-0">
                                  <p className="truncate font-semibold text-[var(--color-text)]">{ds.name}</p>
                                  <p className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                                    T:{ds.train_count}/V:{ds.val_count}/T:{ds.test_count} ·{' '}
                                    {ds.leakage_detected ? 'พบ Leakage' : 'Leakage ผ่าน'}
                                  </p>
                                </div>
                                <button
                                  type="button"
                                  disabled={Boolean(ds.leakage_detected) || requestingTrainId === ds.id}
                                  onClick={() => void handleRequestTrainingGate(ds.id, ds.name)}
                                  className="min-h-[34px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2.5 text-[11px] font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-40"
                                >
                                  {requestingTrainId === ds.id ? 'กำลังส่ง...' : 'ส่ง Training Gate'}
                                </button>
                              </div>
                            ))}
                            <button
                              type="button"
                              disabled={cleanDatasets === 0 || runningExperiment}
                              onClick={() => void handleRunNeuralExperiment()}
                              className="h-10 w-full rounded-xl border border-[var(--zyrquen-indigo)] bg-[var(--zyrquen-indigo)]/20 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-40"
                            >
                              {runningExperiment
                                ? 'กำลังทดลอง Random-Init Neural Transformer...'
                                : 'ทดลอง Neural Transformer (Random Init + BPE)'}
                            </button>
                            {experimentMsg && (
                              <p className="text-xs text-[var(--color-accent)]">{experimentMsg}</p>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </section>
                );
              })()}

              <div className="grid gap-5 lg:grid-cols-2">
                <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                  <h3 className="text-base font-semibold text-[var(--color-text)]">
                    คิวรออนุมัติเวิร์กโฟลว์ (Approval Gate)
                  </h3>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    อนุมัติหรือปฏิเสธงานที่มีผลต่อการฝึกโมเดลหรือการปรับแต่งระบบ
                  </p>
                  <div className="mt-4 divide-y divide-[var(--color-border)]">
                    {(adminData?.pending_runs || []).length === 0 ? (
                      <p className="py-3 text-sm text-[var(--color-text-secondary)]">
                        ไม่มีรายการเวิร์กโฟลว์ที่รออนุมัติในขณะนี้
                      </p>
                    ) : (
                      adminData!.pending_runs.map((run) => (
                        <div
                          key={run.id}
                          className="flex flex-col gap-3 py-3"
                        >
                          <div>
                            <p className="text-sm font-semibold text-[var(--color-text)]">{run.group_id}</p>
                            <p className="text-xs text-[var(--color-text-secondary)]">{run.summary}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => void handleApprovalDecision(run.id, 'approve')}
                              className="flex h-9 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                            >
                              <Check className="h-3.5 w-3.5" />
                              <span>อนุมัติ</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleApprovalDecision(run.id, 'reject')}
                              className="flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-medium text-[var(--color-danger)] hover:opacity-90"
                            >
                              <X className="h-3.5 w-3.5" />
                              <span>ปฏิเสธ</span>
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>

                <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                  <h3 className="text-base font-semibold text-[var(--color-text)]">
                    คิวอนุมัติ Neural Experiment (Self-Improvement Gate)
                  </h3>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    อนุมัติเพื่อโปรโมต Candidate Neural Checkpoint ที่ผ่านเกณฑ์ลด Val Loss
                  </p>
                  <div className="mt-4 divide-y divide-[var(--color-border)]">
                    {(adminData?.pending_experiments || []).length === 0 ? (
                      <p className="py-3 text-sm text-[var(--color-text-secondary)]">
                        ไม่มีการทดลองที่รอการอนุมัติในขณะนี้
                      </p>
                    ) : (
                      adminData!.pending_experiments!.map((exp) => {
                        let metricsInfo = '';
                        try {
                          const b = JSON.parse(exp.baseline_metrics_json) as { initial_val_loss?: number };
                          const c = JSON.parse(exp.candidate_metrics_json) as {
                            final_val_loss?: number;
                            val_perplexity?: number;
                          };
                          metricsInfo = `val_loss: ${b.initial_val_loss?.toFixed(4) ?? '-'} → ${c.final_val_loss?.toFixed(4) ?? '-'} (ppl ${c.val_perplexity?.toFixed(2) ?? '-'})`;
                        } catch {
                          // ignore malformed metrics JSON
                        }
                        return (
                          <div
                            key={exp.id}
                            className="flex flex-col gap-3 py-3"
                          >
                            <div>
                              <p className="text-sm font-semibold text-[var(--color-text)]">{exp.hypothesis}</p>
                              {metricsInfo && (
                                <p className="mt-0.5 font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
                                  {metricsInfo}
                                </p>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void handleExperimentDecision(exp.id, 'approve')}
                                className="flex h-9 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                              >
                                <Check className="h-3.5 w-3.5" />
                                <span>อนุมัติโปรโมต Checkpoint</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleExperimentDecision(exp.id, 'reject')}
                                className="flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-medium text-[var(--color-danger)] hover:opacity-90"
                              >
                                <X className="h-3.5 w-3.5" />
                                <span>ปฏิเสธ</span>
                              </button>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </section>
              </div>

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-base font-semibold text-[var(--color-text)]">
                      คิวอนุมัติจัดเก็บ Knowledge Graph จากชุดข้อมูล (KG Ingestion Gate)
                    </h3>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                      ชุดข้อมูลที่นำเข้าจะถูกตรวจ Provenance, SHA-256 และความขัดแย้งก่อนจัดเก็บเข้า Knowledge Graph โดยไม่ข้าม Approval Gate
                    </p>
                  </div>
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                    รออนุมัติ {adminData?.pending_kg_proposals?.length ?? 0} รายการ
                  </span>
                </div>
                <div className="mt-4 divide-y divide-[var(--color-border)]">
                  {(adminData?.pending_kg_proposals || []).length === 0 ? (
                    <p className="py-3 text-sm text-[var(--color-text-secondary)]">
                      ไม่มีข้อเสนอ Knowledge Graph จากชุดข้อมูลที่รอการอนุมัติในขณะนี้
                    </p>
                  ) : (
                    adminData!.pending_kg_proposals!.map((prop) => {
                      let previewTriples: Array<{ subject: string; relation: string; object: string; has_contradiction?: boolean }> = [];
                      let contradictionsCount = 0;
                      try {
                        previewTriples = JSON.parse(prop.triples_json || '[]') as typeof previewTriples;
                        const cArr = JSON.parse(prop.contradictions_json || '[]') as unknown[];
                        contradictionsCount = Array.isArray(cArr) ? cArr.length : 0;
                      } catch {
                        // ignore malformed preview JSON
                      }
                      return (
                        <div key={prop.id} className="flex flex-col gap-3 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <p className="text-sm font-semibold text-[var(--color-text)]">
                                {prop.dataset_name} ({prop.triple_count} triples)
                              </p>
                              <p className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                                ที่มา: {prop.provenance} · License: {prop.license} · SHA-256: {prop.manifest_hash.slice(0, 12)}…
                              </p>
                            </div>
                            {contradictionsCount > 0 && (
                              <span className="rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-warning)]">
                                พบความขัดแย้ง {contradictionsCount} จุด
                              </span>
                            )}
                          </div>
                          {previewTriples.length > 0 && (
                            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5 font-mono text-[11px] text-[var(--color-text-secondary)]">
                              {previewTriples.slice(0, 3).map((t, i) => (
                                <div key={`${prop.id}-${i}`} className="truncate">
                                  {t.subject} → {t.relation} → {t.object}
                                </div>
                              ))}
                              {previewTriples.length > 3 && (
                                <div className="mt-0.5 text-[var(--color-text-muted)]">
                                  …และอีก {previewTriples.length - 3} triples
                                </div>
                              )}
                            </div>
                          )}
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => void handleKgProposalDecision(prop.id, 'approve')}
                              className="flex h-9 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                            >
                              <Check className="h-3.5 w-3.5" />
                              <span>อนุมัติจัดเก็บลง Knowledge Graph</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleKgProposalDecision(prop.id, 'reject')}
                              className="flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 text-xs font-medium text-[var(--color-danger)] hover:opacity-90"
                            >
                              <X className="h-3.5 w-3.5" />
                              <span>ปฏิเสธ</span>
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </section>

              <details
                open={(adminData?.pending_tool_invocations || []).length > 0}
                className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-[var(--color-text)]">
                  <span>ควบคุมเครื่องมือภายนอก (Tool Registry Gate)</span>
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                    รออนุมัติ {adminData?.pending_tool_invocations?.length ?? 0} · ทั้งหมด {adminData?.tools?.length ?? 0}
                  </span>
                </summary>
                <div className="mt-4">
                  <ToolRegistry
                    token={token}
                    userRole={user.role}
                    mode="admin"
                    pendingInvocations={adminData?.pending_tool_invocations || []}
                    adminTools={adminData?.tools || []}
                    onRefresh={loadAdmin}
                    onError={setError}
                  />
                </div>
              </details>

              <details className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-[var(--color-text)]">
                  <span>จัดการสิทธิ์ผู้ใช้งาน</span>
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                    {adminData?.users?.length ?? 0} บัญชี
                  </span>
                </summary>
                <div className="mt-4 divide-y divide-[var(--color-border)]">
                  {(adminData?.users || []).map((u) => (
                    <div
                      key={u.id}
                      className="flex min-h-[52px] items-center justify-between gap-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-[var(--color-text)]">
                          {u.display_name}
                        </p>
                        <p className="truncate text-xs text-[var(--color-text-secondary)]">
                          {u.email} · {u.role}
                        </p>
                      </div>
                      {u.id !== user.id && (
                        <button
                          type="button"
                          onClick={() =>
                            void handleRoleChange(u.id, u.role === 'admin' ? 'user' : 'admin')
                          }
                          className="min-h-[38px] shrink-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
                        >
                          {u.role === 'admin' ? 'ลดสิทธิ์เป็น User' : 'ตั้งเป็นผู้ดูแล'}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </details>

              <details className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 text-sm font-semibold text-[var(--color-text)]">
                  <span>บันทึกการตรวจสอบความปลอดภัย (Audit Logs)</span>
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                    {adminData?.audit_logs?.length ?? 0} รายการ · แสดง {filteredAuditLogs.length}
                  </span>
                </summary>
                <div className="mt-4 space-y-3">
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    <select aria-label="ตัวกรองเหตุการณ์ Audit" value={auditEventFilter} onChange={(e) => setAuditEventFilter(e.target.value)} className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]">
                      <option value="ALL">เหตุการณ์ทั้งหมด</option>
                      <option value="PII_REDACTED">PII_REDACTED</option>
                      <option value="PII_DETECTED">PII_DETECTED</option>
                      <option value="EXPORT">EXPORT</option>
                      <option value="LOGIN">LOGIN</option>
                      <option value="APPROVAL">APPROVAL</option>
                    </select>
                    <input aria-label="ค้นหา Audit Logs" value={auditSearch} onChange={(e) => setAuditSearch(e.target.value)} placeholder="ค้นหาเหตุการณ์ / ผู้ใช้ / เป้าหมาย" className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]" />
                    <input aria-label="Audit Logs ตั้งแต่วันที่" type="date" value={auditFrom} onChange={(e) => setAuditFrom(e.target.value)} className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]" />
                    <input aria-label="Audit Logs ถึงวันที่" type="date" value={auditTo} onChange={(e) => setAuditTo(e.target.value)} className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]" />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                    <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                      <label className="inline-flex items-center gap-2">
                        <input type="checkbox" checked={auditPiiOnly} onChange={(e) => setAuditPiiOnly(e.target.checked)} className="h-4 w-4 accent-[var(--color-primary)]" />
                        เฉพาะเหตุการณ์ PII
                      </label>
                      <label className="inline-flex items-center gap-2">
                        รูปแบบ
                        <select aria-label="รูปแบบไฟล์ส่งออก" value={auditFormat} onChange={(e) => setAuditFormat(e.target.value as 'csv' | 'json')} className="h-8 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 text-xs text-[var(--color-text)]">
                          <option value="csv">CSV</option>
                          <option value="json">JSON (Redacted)</option>
                        </select>
                      </label>
                      <span>ปกปิด PII ทุกแถว · ไม่รวม IP / User-Agent</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <CopyButton
                        stopPropagation
                        getText={() => serializeTableToTsv(
                          ['เวลา', 'ผู้ดำเนินการ', 'การกระทำ', 'ผลลัพธ์'],
                          filteredAuditLogs.map((log) => [
                            new Date(log.created_at).toLocaleString('th-TH'),
                            log.actor_email.replace(/^(.).+(@.*)$/, '**$2'),
                            log.action,
                            log.outcome,
                          ])
                        )}
                        label="คัดลอกตาราง"
                        ariaLabel="คัดลอกตาราง Audit Logs"
                        size="xs"
                      />
                      <button type="button" disabled={exportingAudit || filteredAuditLogs.length === 0} onClick={() => void handleExportAudit()} className="inline-flex min-h-[36px] items-center gap-2 rounded-lg bg-[var(--color-primary)] px-3 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-40">
                        <Download className="h-3.5 w-3.5" />
                        {exportingAudit ? 'กำลังส่งออก...' : 'ส่งออกบันทึก PII'}
                      </button>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-[var(--color-border)] text-[var(--color-text-secondary)]">
                          <th className="py-2 pr-4 font-medium">เวลา</th>
                          <th className="py-2 pr-4 font-medium">ผู้ดำเนินการ</th>
                          <th className="py-2 pr-4 font-medium">การกระทำ</th>
                          <th className="py-2 pr-4 font-medium">เป้าหมาย</th>
                          <th className="py-2 font-medium">ผลลัพธ์</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[var(--color-border)] tabular-nums">
                        {filteredAuditLogs.map((log) => {
                          const safe = redactAuditRow(log as AuditEvent);
                          return (
                            <tr key={log.id}>
                              <td className="py-2.5 pr-4 font-mono text-[var(--color-text-muted)]">{new Date(log.created_at).toLocaleString('th-TH')}</td>
                              <td className="py-2.5 pr-4 text-[var(--color-text)]">{String(safe.actor_email ?? '')}</td>
                              <td className="py-2.5 pr-4 font-mono text-[var(--color-accent)]">{String(safe.action ?? '')}</td>
                              <td className="py-2.5 pr-4 text-[var(--color-text-secondary)]">{String(safe.target ?? '')}</td>
                              <td className="py-2.5 text-[var(--color-text-secondary)]">{String(safe.outcome ?? '')}</td>
                            </tr>
                          );
                        })}
                        {filteredAuditLogs.length === 0 && (
                          <tr><td colSpan={5} className="py-5 text-center text-[var(--color-text-muted)]">ไม่พบเหตุการณ์ตามตัวกรอง</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </details>
            </>
          )}
        </div>
      )}
    </div>
  );
}
