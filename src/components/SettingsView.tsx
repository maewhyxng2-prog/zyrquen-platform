import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  Code2,
  Database,
  Download,
  GitCompare,
  KeyRound,
  Layers,
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
import { runNativeCapabilityBenchmark } from '../lib/benchmark';
import { serializeTableToTsv } from '../lib/clipboard';
import { useZyrquenTheme } from '../lib/theme';
import { MODEL_VARIANTS } from '../types';
import { CopyButton } from './CopyButton';
import { ModelRegistryModal, type ModelRegistryModalTab } from './ModelRegistryModal';
import { ToolRegistry } from './ToolRegistry';

const AdminStabilityPanel = lazy(() =>
  import('./AdminStabilityPanel').then((m) => ({ default: m.AdminStabilityPanel }))
);
import type {
  AdminOverview,
  AuditLogItem,
  ClientLatencySample,
  CodeCorpusCurateResult,
  CodeModelEvaluationResult,
  CodeTrainingExperimentResult,
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
  const [curatingCodeCorpus, setCuratingCodeCorpus] = useState(false);
  const [runningCodeExperiment, setRunningCodeExperiment] = useState(false);
  const [evaluatingCodeModel, setEvaluatingCodeModel] = useState(false);
  const [codeCorpusRes, setCodeCorpusRes] = useState<CodeCorpusCurateResult | null>(null);
  const [codeExpRes, setCodeExpRes] = useState<CodeTrainingExperimentResult | null>(null);
  const [codeEvalRes, setCodeEvalRes] = useState<CodeModelEvaluationResult | null>(null);
  const [codeTrainMsg, setCodeTrainMsg] = useState<string | null>(null);
  const [exportingAudit, setExportingAudit] = useState(false);
  const [auditExportFormat, setAuditExportFormat] = useState<'json' | 'csv'>('json');
  const [auditExportFocus, setAuditExportFocus] = useState<'pii_redaction' | 'all'>('pii_redaction');
  const [auditExportNotice, setAuditExportNotice] = useState<{
    filename: string;
    count: number;
    piiCount: number;
    sha256: string;
    focus: 'pii_redaction' | 'all';
    format: 'json' | 'csv';
  } | null>(null);
  const [selectedArtifactVersion, setSelectedArtifactVersion] = useState<string>('');
  const [downloadingArtifact, setDownloadingArtifact] = useState<'logs' | 'manifest' | null>(null);
  const [artifactNotice, setArtifactNotice] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [registryModalOpen, setRegistryModalOpen] = useState(false);
  const [registryModalTab, setRegistryModalTab] = useState<ModelRegistryModalTab>('compare');
  const [registryBaseVersion, setRegistryBaseVersion] = useState<string | undefined>(undefined);
  const [registryCandidateVersion, setRegistryCandidateVersion] = useState<string | undefined>(
    undefined
  );

  const loadDeveloper = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [res, toolsRes] = await Promise.all([
        apiRequest<DeveloperOverview>('/api/developer/overview', { token }),
        apiRequest<ToolsOverview>('/api/developer/tools', { token }).catch(() => null),
      ]);
      setDevData(res);
      const checkpoints = res.checkpoints || [];
      if (checkpoints.length > 0) {
        setSelectedArtifactVersion((prev) => {
          if (prev && checkpoints.some((ck) => `v${ck.version}` === prev)) {
            return prev;
          }
          return `v${checkpoints[0].version}`;
        });
      }
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
      const res = await apiRequest<AdminOverview>('/api/admin/overview', { token });
      setAdminData(res);
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

  async function handleCurateCodeCorpus() {
    setCuratingCodeCorpus(true);
    setError(null);
    setCodeTrainMsg(null);
    try {
      const res = await apiRequest<CodeCorpusCurateResult>('/api/developer/code-training/curate', {
        method: 'POST',
        token,
        body: { name: 'code-problem-solving-corpus' },
      });
      setCodeCorpusRes(res);
      const verified = res.code_verification?.verified_tasks ?? 0;
      const total = res.code_verification?.total_tasks ?? 0;
      const astCount = res.code_verification?.ast_records_added ?? 0;
      setCodeTrainMsg(
        `เตรียมชุดข้อมูลโค้ด "${res.dataset?.name || 'code-problem-solving-corpus'}" สำเร็จ (Sandbox Verified ${verified}/${total} งาน + AST ${astCount} รายการ)`
      );
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เตรียมชุดข้อมูลโค้ดและแก้ปัญหาไม่สำเร็จ');
    } finally {
      setCuratingCodeCorpus(false);
    }
  }

  async function handleRunCodeExperiment() {
    setRunningCodeExperiment(true);
    setError(null);
    setCodeTrainMsg(null);
    try {
      const targetDsId =
        codeCorpusRes?.dataset?.id ||
        (devData?.datasets || []).find(
          (d) =>
            !d.leakage_detected &&
            (d.provenance === 'native_ast_and_sandbox_verified' || d.name.includes('code'))
        )?.id ||
        null;
      const res = await apiRequest<CodeTrainingExperimentResult>(
        '/api/developer/code-training/experiment',
        {
          method: 'POST',
          token,
          body: { datasetId: targetDsId, epochs: 3, seed: 42 },
        }
      );
      setCodeExpRes(res);
      setCodeTrainMsg(
        res.improved
          ? `ฝึก Native Transformer ด้านโค้ดและแก้ปัญหาสำเร็จ (สถานะ: ${res.experiment.approval_status}) — ส่งเข้า Approval Gate แล้ว`
          : `การฝึกทดลองด้านโค้ดเสร็จสิ้น (สถานะ: ${res.experiment.approval_status})`
      );
      await loadDeveloper();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ฝึกทดลองโมเดลด้านโค้ดไม่สำเร็จ');
    } finally {
      setRunningCodeExperiment(false);
    }
  }

  async function handleEvaluateCodeModel() {
    setEvaluatingCodeModel(true);
    setError(null);
    try {
      const res = await apiRequest<CodeModelEvaluationResult>(
        '/api/developer/code-training/evaluate',
        {
          method: 'POST',
          token,
          body: {},
        }
      );
      setCodeEvalRes(res);
      if (res.status === 'NOT_RUN' && res.reason) {
        setCodeTrainMsg(res.reason);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ประเมินผลโมเดลด้านโค้ดไม่สำเร็จ');
    } finally {
      setEvaluatingCodeModel(false);
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

  function isPiiRedactionAuditLog(log: AuditLogItem): boolean {
    const actionUp = (log.action || '').toUpperCase();
    const outcomeUp = (log.outcome || '').toUpperCase();
    if (
      actionUp.includes('PII') ||
      actionUp.includes('REDACT') ||
      outcomeUp.includes('PII') ||
      outcomeUp.includes('REDACT')
    ) {
      return true;
    }
    if (!log.details_json) return false;
    try {
      const parsed = JSON.parse(log.details_json) as Record<string, unknown>;
      if (parsed.event_category === 'pii_redaction' || parsed.pii_redacted === true) {
        return true;
      }
      if (Number(parsed.total_redacted || parsed.redacted_count || 0) > 0) {
        return true;
      }
      const summary = parsed.pii_redaction_summary as Record<string, unknown> | undefined;
      if (summary && Number(summary.total_redacted || 0) > 0) {
        return true;
      }
    } catch {
      return false;
    }
    return false;
  }

  async function handleExportAuditLogs() {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      setError('ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อส่งออก Audit Logs');
      return;
    }
    setExportingAudit(true);
    setError(null);
    try {
      const headers: Record<string, string> = {
        'X-Requested-With': 'XMLHttpRequest',
      };
      if (token && token !== '__cookie__') {
        headers.Authorization = `Bearer ${token}`;
      }
      const res = await fetch(
        `/api/admin/audit-logs/export?focus=${encodeURIComponent(auditExportFocus)}&format=${encodeURIComponent(auditExportFormat)}`,
        {
          method: 'GET',
          headers,
          credentials: 'include',
        }
      );
      if (!res.ok) {
        const errPayload = (await res.json().catch(() => ({}))) as { error?: string };
        throw new ApiError(errPayload.error || `ส่งออก Audit Log ไม่สำเร็จ (${res.status})`, res.status);
      }

      const disposition = res.headers.get('content-disposition') || '';
      const filenameMatch = disposition.match(/filename="?([^";\n]+)"?/i);
      const filename =
        filenameMatch?.[1] || `zyrquen-audit-${auditExportFocus}.${auditExportFormat}`;
      const sha256Header = res.headers.get('x-zyrquen-export-sha256') || '';
      const countHeader = Number(res.headers.get('x-zyrquen-export-count') || '0');
      const piiCountHeader = Number(res.headers.get('x-zyrquen-pii-events') || '0');

      const rawText = await res.text();
      let resolvedCount = countHeader;
      let resolvedPiiCount = piiCountHeader;
      let resolvedSha256 = sha256Header;

      if (auditExportFormat === 'json') {
        try {
          const parsed = JSON.parse(rawText) as {
            exported_count?: number;
            pii_redaction_event_count?: number;
            integrity_sha256?: string;
          };
          if (typeof parsed.exported_count === 'number') resolvedCount = parsed.exported_count;
          if (typeof parsed.pii_redaction_event_count === 'number') {
            resolvedPiiCount = parsed.pii_redaction_event_count;
          }
          if (typeof parsed.integrity_sha256 === 'string' && !resolvedSha256) {
            resolvedSha256 = parsed.integrity_sha256;
          }
        } catch {
          // keep header metadata if body is custom JSON
        }
      }

      const mimeType =
        auditExportFormat === 'csv'
          ? 'text/csv;charset=utf-8'
          : 'application/json;charset=utf-8';
      const blob = new Blob([rawText], { type: mimeType });
      if (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function') {
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
      }

      setAuditExportNotice({
        filename,
        count: Number.isFinite(resolvedCount) ? resolvedCount : 0,
        piiCount: Number.isFinite(resolvedPiiCount) ? resolvedPiiCount : 0,
        sha256: resolvedSha256,
        focus: auditExportFocus,
        format: auditExportFormat,
      });

      await loadAdmin().catch(() => null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ส่งออก Audit Log ไม่สำเร็จ');
    } finally {
      setExportingAudit(false);
    }
  }

  function openModelRegistryModal(
    tab: ModelRegistryModalTab = 'compare',
    baseVersion?: string,
    candidateVersion?: string
  ) {
    setRegistryModalTab(tab);
    setRegistryBaseVersion(baseVersion);
    setRegistryCandidateVersion(candidateVersion);
    setRegistryModalOpen(true);
    if (!devData) {
      void loadDeveloper();
    }
  }

  async function handleDownloadTrainingArtifact(
    kind: 'logs' | 'manifest',
    versionOverride?: string
  ) {
    const targetVersion =
      versionOverride ||
      selectedArtifactVersion ||
      (devData?.checkpoints?.[0] ? `v${devData.checkpoints[0].version}` : '');
    if (!targetVersion) {
      setArtifactNotice({
        type: 'error',
        text: 'กรุณาเลือกรุ่นโมเดล (Checkpoint) ก่อนดาวน์โหลด',
      });
      return;
    }

    setDownloadingArtifact(kind);
    setArtifactNotice(null);
    try {
      const headers: Record<string, string> = {};
      if (token && token !== 'cookie-session') {
        headers.Authorization = `Bearer ${token}`;
      }
      const res = await fetch(
        `/api/developer/artifacts/${encodeURIComponent(targetVersion)}/download?kind=${encodeURIComponent(kind)}`,
        {
          method: 'GET',
          headers,
          credentials: 'include',
        }
      );
      if (!res.ok) {
        const errPayload = (await res.json().catch(() => ({}))) as { error?: string };
        throw new ApiError(
          errPayload.error || `ไม่สามารถดาวน์โหลด ${kind} สำหรับ ${targetVersion} ได้ (${res.status})`,
          res.status
        );
      }
      const disposition = res.headers.get('content-disposition') || '';
      const filenameMatch = disposition.match(/filename="?([^";\n]+)"?/i);
      const fallbackName =
        kind === 'logs'
          ? `zyrquen-${targetVersion}-training-logs.jsonl`
          : `zyrquen-${targetVersion}-manifest.json`;
      const filename = filenameMatch?.[1] || fallbackName;
      const rawText = await res.text();
      const mimeType =
        kind === 'logs' ? 'application/x-ndjson;charset=utf-8' : 'application/json;charset=utf-8';
      const blob = new Blob([rawText], { type: mimeType });
      if (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function') {
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
      }
      setArtifactNotice({
        type: 'success',
        text: `ดาวน์โหลด ${filename} สำหรับ ${targetVersion} เรียบร้อยแล้ว`,
      });
    } catch (err) {
      setArtifactNotice({
        type: 'error',
        text: err instanceof ApiError ? err.message : 'ไม่สามารถดาวน์โหลดไฟล์ Training Artifact ได้',
      });
    } finally {
      setDownloadingArtifact(null);
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
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => openModelRegistryModal('registry')}
                        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
                      >
                        <Layers className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>เปิด Model Registry</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => openModelRegistryModal('compare')}
                        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] whitespace-nowrap"
                      >
                        <GitCompare className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>เปรียบเทียบเวอร์ชัน</span>
                      </button>
                      <button
                        type="button"
                        disabled={runningEval}
                        onClick={() => void handleRunEvaluation()}
                        className="min-h-[36px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50 whitespace-nowrap"
                      >
                        {runningEval ? 'กำลังประเมิน...' : 'ประเมินผลเทียบ Baseline'}
                      </button>
                    </div>
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
                      devData!.checkpoints.map((ck, idx) => {
                        const ckVersionLabel = `v${ck.version}`;
                        const isSelected = selectedArtifactVersion === ckVersionLabel;
                        const prevCk = devData!.checkpoints[idx + 1] || devData!.checkpoints[0];
                        return (
                          <div
                            key={ck.id}
                            className={`py-3 transition-colors ${
                              isSelected ? 'rounded-xl bg-[var(--color-surface)] px-3 -mx-3' : ''
                            }`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedArtifactVersion(ckVersionLabel);
                                  setArtifactNotice(null);
                                }}
                                className="text-left text-sm font-semibold text-[var(--color-text)] hover:text-[var(--color-accent)]"
                              >
                                Checkpoint {ckVersionLabel}
                                {isSelected ? ' (Selected)' : ''}
                              </button>
                              <div className="flex items-center gap-2">
                                {devData!.checkpoints.length >= 2 && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      openModelRegistryModal(
                                        'compare',
                                        prevCk && prevCk.version !== ck.version
                                          ? `v${prevCk.version}`
                                          : undefined,
                                        ckVersionLabel
                                      )
                                    }
                                    className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
                                  >
                                    เทียบใน Registry
                                  </button>
                                )}
                                <span className="text-xs font-medium text-[var(--color-accent)]">
                                  {ck.eval_status}
                                </span>
                              </div>
                            </div>
                            <p className="mt-1 font-mono text-xs text-[var(--color-text-secondary)] tabular-nums">
                              vocab {ck.vocab_size} · train_loss {ck.train_loss} · val_loss{' '}
                              {ck.val_loss} · ppl {ck.perplexity}
                            </p>
                          </div>
                        );
                      })
                    )}
                  </div>

                  <div className="mt-5 border-t border-[var(--color-border)] pt-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <h4 className="text-sm font-semibold text-[var(--color-text)]">
                          Training Artifact History
                        </h4>
                        <p className="text-xs text-[var(--color-text-secondary)]">
                          เลือกเวอร์ชันโมเดลเพื่อดาวน์โหลดไฟล์ Raw Training Logs หรือ Manifest JSON จริง
                        </p>
                      </div>
                      {(devData?.checkpoints || []).length > 0 && (
                        <select
                          aria-label="เลือกรุ่นโมเดลใน Training Artifact History"
                          value={selectedArtifactVersion}
                          onChange={(e) => {
                            setSelectedArtifactVersion(e.target.value);
                            setArtifactNotice(null);
                          }}
                          className="h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                        >
                          {devData!.checkpoints.map((ck) => {
                            const ckVer = `v${ck.version}`;
                            return (
                              <option key={`art-${ck.id}`} value={ckVer}>
                                Checkpoint {ckVer} ({ck.eval_status})
                              </option>
                            );
                          })}
                        </select>
                      )}
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        disabled={!selectedArtifactVersion || downloadingArtifact !== null}
                        onClick={() => void handleDownloadTrainingArtifact('logs')}
                        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap"
                      >
                        <Download className="h-3.5 w-3.5" />
                        <span>
                          {downloadingArtifact === 'logs'
                            ? 'กำลังดาวน์โหลด Logs...'
                            : 'Download Raw Training Logs'}
                        </span>
                      </button>

                      <button
                        type="button"
                        disabled={!selectedArtifactVersion || downloadingArtifact !== null}
                        onClick={() => void handleDownloadTrainingArtifact('manifest')}
                        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap"
                      >
                        <Download className="h-3.5 w-3.5" />
                        <span>
                          {downloadingArtifact === 'manifest'
                            ? 'กำลังดาวน์โหลด Manifest...'
                            : 'Download Manifest JSON'}
                        </span>
                      </button>
                    </div>

                    {artifactNotice && (
                      <p
                        role={artifactNotice.type === 'error' ? 'alert' : 'status'}
                        className={`mt-2.5 rounded-lg border px-3 py-2 text-xs ${
                          artifactNotice.type === 'error'
                            ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 text-[var(--color-danger)]'
                            : 'border-[var(--color-success)]/40 bg-[var(--color-success)]/10 text-[var(--color-success)]'
                        }`}
                      >
                        {artifactNotice.text}
                      </p>
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

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Code2 className="h-4 w-4 text-[var(--color-accent)]" />
                      <h3 className="text-base font-semibold text-[var(--color-text)]">
                        ฝึกโมเดลให้เข้าใจโค้ดและแก้ปัญหา (Code &amp; Debugging Training)
                      </h3>
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                      สร้างชุดข้อมูลโค้ดที่ตรวจผ่าน Python AST และ Sandbox Test แยก Train/Val/Test ไม่ปนกัน แล้วฝึก NativeTransformerLM พร้อมวัดผล Pre/Post บนโจทย์ Unseen (ไม่ใช้โมเดลภายนอก)
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={curatingCodeCorpus}
                      onClick={() => void handleCurateCodeCorpus()}
                      className="min-h-[38px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-50"
                    >
                      {curatingCodeCorpus ? 'กำลังตรวจ AST & Sandbox...' : 'เตรียมชุดข้อมูลโค้ด & แก้บั๊ก'}
                    </button>
                    <button
                      type="button"
                      disabled={runningCodeExperiment}
                      onClick={() => void handleRunCodeExperiment()}
                      className="min-h-[38px] rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
                    >
                      {runningCodeExperiment ? 'กำลังฝึกโมเดลโค้ด...' : 'ฝึกทดลอง Native Model ด้านโค้ด'}
                    </button>
                    <button
                      type="button"
                      disabled={evaluatingCodeModel}
                      onClick={() => void handleEvaluateCodeModel()}
                      className="min-h-[38px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] disabled:opacity-50"
                    >
                      {evaluatingCodeModel ? 'กำลังประเมิน Unseen...' : 'ทดสอบบนโจทย์โค้ด Unseen'}
                    </button>
                  </div>
                </div>

                {codeTrainMsg && (
                  <p className="mt-3 text-xs text-[var(--color-accent)]">{codeTrainMsg}</p>
                )}

                {codeCorpusRes?.code_verification && (
                  <div className="mt-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3.5 text-xs">
                    <p className="font-semibold text-[var(--color-text)]">
                      ผลการตรวจ AST &amp; Sandbox ก่อนฝึก ({codeCorpusRes.code_verification.verified_tasks}/{codeCorpusRes.code_verification.total_tasks} งานผ่านเงื่อนไข)
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)]">
                      Train: {codeCorpusRes.code_verification.splits_counts.train ?? 0} · Val:{' '}
                      {codeCorpusRes.code_verification.splits_counts.val ?? 0} · Test (Unseen):{' '}
                      {codeCorpusRes.code_verification.splits_counts.test ?? 0} · AST:{' '}
                      {codeCorpusRes.code_verification.ast_records_added}
                    </p>
                  </div>
                )}

                {codeExpRes && (
                  <div className="mt-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-[var(--color-text)]">
                        {codeExpRes.experiment.hypothesis}
                      </span>
                      <span className="font-mono text-[var(--color-accent)]">
                        {codeExpRes.experiment.approval_status} · external_models={String(codeExpRes.external_models_used)}
                      </span>
                    </div>
                    <div className="mt-2 grid gap-2 sm:grid-cols-4 font-mono text-[11px] tabular-nums">
                      <div className="rounded-xl border border-[var(--color-border)] p-2.5">
                        <span className="block text-[var(--color-text-muted)]">Train Loss</span>
                        <span className="font-semibold text-[var(--color-text)]">
                          {codeExpRes.metrics.initial_train_loss.toFixed(4)} → {codeExpRes.metrics.final_train_loss.toFixed(4)}
                        </span>
                      </div>
                      <div className="rounded-xl border border-[var(--color-border)] p-2.5">
                        <span className="block text-[var(--color-text-muted)]">Val Loss</span>
                        <span className="font-semibold text-[var(--color-text)]">
                          {codeExpRes.metrics.initial_val_loss.toFixed(4)} → {codeExpRes.metrics.final_val_loss.toFixed(4)}
                        </span>
                      </div>
                      <div className="rounded-xl border border-[var(--color-border)] p-2.5">
                        <span className="block text-[var(--color-text-muted)]">Unseen Test PPL</span>
                        <span className="font-semibold text-[var(--color-text)]">
                          {codeExpRes.metrics.test_perplexity.toFixed(2)} (acc {(codeExpRes.metrics.test_accuracy * 100).toFixed(1)}%)
                        </span>
                      </div>
                      <div className="rounded-xl border border-[var(--color-border)] p-2.5">
                        <span className="block text-[var(--color-text-muted)]">Fix-vs-Bug Probe</span>
                        <span className="font-semibold text-[var(--color-text)]">
                          {(codeExpRes.metrics.pre_contrastive_accuracy * 100).toFixed(0)}% → {(codeExpRes.metrics.post_contrastive_accuracy * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                    {(codeExpRes.metrics.honest_limitations || []).length > 0 && (
                      <p className="mt-2 text-[11px] text-[var(--color-text-secondary)]">
                        ข้อจำกัดจริง: {codeExpRes.metrics.honest_limitations![0]}
                      </p>
                    )}
                  </div>
                )}

                {codeEvalRes && (
                  <div className="mt-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3.5 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-[var(--color-text)]">
                        ผลประเมิน Checkpoint บนชุด Unseen Code
                      </span>
                      <span className="font-mono text-[var(--color-accent)]">
                        {codeEvalRes.status}
                        {codeEvalRes.checkpoint_version ? ` · v${codeEvalRes.checkpoint_version}` : ''}
                      </span>
                    </div>
                    {codeEvalRes.status === 'NOT_RUN' ? (
                      <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">
                        {codeEvalRes.reason}
                      </p>
                    ) : (
                      <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                        test_loss: {codeEvalRes.unseen_test_loss?.toFixed(4) ?? '-'} · ppl:{' '}
                        {codeEvalRes.unseen_test_perplexity?.toFixed(2) ?? '-'} · contrastive:{' '}
                        {codeEvalRes.contrastive_probe
                          ? `${codeEvalRes.contrastive_probe.passed}/${codeEvalRes.contrastive_probe.total} (${(codeEvalRes.contrastive_probe.accuracy * 100).toFixed(0)}%)`
                          : '-'}
                      </p>
                    )}
                  </div>
                )}
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
                          onClick={() => openModelRegistryModal('compare')}
                          className="inline-flex min-h-[36px] shrink-0 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
                        >
                          <GitCompare className="h-3.5 w-3.5" aria-hidden="true" />
                          <span>Model Registry</span>
                        </button>
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

              <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-[var(--color-text)]">
                        บันทึกการตรวจสอบความปลอดภัย (Audit Logs)
                      </h3>
                      <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                        {adminData?.audit_logs?.length ?? 0} รายการ
                      </span>
                      <span className="rounded-md border border-[var(--color-accent)]/30 bg-[var(--color-surface)] px-2 py-0.5 font-mono text-[11px] text-[var(--color-accent)]">
                        PII Redaction:{' '}
                        {(adminData?.audit_logs || []).filter(isPiiRedactionAuditLog).length}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                      ส่งออกบันทึกเหตุการณ์ในรูปแบบไฟล์ที่คัดกรองข้อมูลส่วนบุคคล/ความลับและแนบ SHA-256 ตรวจสอบความถูกต้อง
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label="ขอบเขตการส่งออก Audit Log"
                      value={auditExportFocus}
                      onChange={(e) =>
                        setAuditExportFocus(e.target.value === 'all' ? 'all' : 'pii_redaction')
                      }
                      className="h-9 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      <option value="pii_redaction">เฉพาะ PII Redaction</option>
                      <option value="all">Audit Logs ทั้งหมด</option>
                    </select>
                    <select
                      aria-label="รูปแบบไฟล์ส่งออก Audit Log"
                      value={auditExportFormat}
                      onChange={(e) =>
                        setAuditExportFormat(e.target.value === 'csv' ? 'csv' : 'json')
                      }
                      className="h-9 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      <option value="json">JSON (SHA-256)</option>
                      <option value="csv">CSV (Sanitized)</option>
                    </select>
                    <button
                      type="button"
                      disabled={exportingAudit}
                      onClick={() => void handleExportAuditLogs()}
                      className="flex h-9 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
                    >
                      <Download className="h-3.5 w-3.5" />
                      <span>
                        {exportingAudit
                          ? 'กำลังส่งออก...'
                          : auditExportFocus === 'pii_redaction'
                            ? 'ส่งออก Audit Log (PII Redaction)'
                            : 'ส่งออก Audit Log (ทั้งหมด)'}
                      </span>
                    </button>
                    {(adminData?.audit_logs?.length ?? 0) > 0 && (
                      <CopyButton
                        getText={() =>
                          serializeTableToTsv(
                            ['เวลา', 'ผู้ดำเนินการ', 'การกระทำ', 'ผลลัพธ์'],
                            (adminData?.audit_logs || []).map((log) => [
                              new Date(log.created_at).toLocaleString('th-TH'),
                              log.actor_email,
                              log.action,
                              log.outcome,
                            ])
                          )
                        }
                        label="คัดลอกตาราง"
                        ariaLabel="คัดลอกตาราง Audit Logs"
                        title="คัดลอกตาราง Audit Logs เป็นรูปแบบคั่นด้วยแท็บ (TSV)"
                        size="xs"
                      />
                    )}
                  </div>
                </div>

                {auditExportNotice && (
                  <div
                    role="status"
                    className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-success)]/40 bg-[var(--color-success-bg)] px-3.5 py-2.5 text-xs text-[var(--color-success)]"
                  >
                    <span>
                      ส่งออกไฟล์ <strong className="font-mono">{auditExportNotice.filename}</strong>{' '}
                      สำเร็จ ({auditExportNotice.count} รายการ · PII Redaction{' '}
                      {auditExportNotice.piiCount} รายการ · {auditExportNotice.format.toUpperCase()})
                    </span>
                    {auditExportNotice.sha256 && (
                      <span className="font-mono text-[11px]">
                        SHA-256: {auditExportNotice.sha256.slice(0, 16)}…
                      </span>
                    )}
                  </div>
                )}

                <div className="mt-4 overflow-x-auto">
                  {(adminData?.audit_logs || []).length === 0 ? (
                    <p className="py-3 text-xs text-[var(--color-text-secondary)]">
                      ยังไม่มีบันทึก Audit Logs ในระบบ
                    </p>
                  ) : (
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-[var(--color-border)] text-[var(--color-text-secondary)]">
                          <th className="py-2 pr-4 font-medium">เวลา</th>
                          <th className="py-2 pr-4 font-medium">ผู้ดำเนินการ</th>
                          <th className="py-2 pr-4 font-medium">การกระทำ</th>
                          <th className="py-2 font-medium">ผลลัพธ์</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[var(--color-border)] tabular-nums">
                        {(adminData?.audit_logs || []).map((log) => {
                          const isPii = isPiiRedactionAuditLog(log);
                          return (
                            <tr key={log.id}>
                              <td className="py-2.5 pr-4 font-mono text-[var(--color-text-muted)]">
                                {new Date(log.created_at).toLocaleString('th-TH')}
                              </td>
                              <td className="py-2.5 pr-4 text-[var(--color-text)]">{log.actor_email}</td>
                              <td className="py-2.5 pr-4 font-mono text-[var(--color-accent)]">
                                <span className="inline-flex items-center gap-1.5">
                                  <span>{log.action}</span>
                                  {isPii && (
                                    <span className="rounded border border-[var(--color-accent)]/40 bg-[var(--color-surface)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-accent)]">
                                      PII
                                    </span>
                                  )}
                                </span>
                              </td>
                              <td className="py-2.5 text-[var(--color-text-secondary)]">{log.outcome}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              </section>
            </>
          )}
        </div>
      )}
      <ModelRegistryModal
        open={registryModalOpen}
        initialTab={registryModalTab}
        initialBaseVersion={registryBaseVersion}
        initialCandidateVersion={registryCandidateVersion}
        checkpoints={devData?.checkpoints ?? adminData?.training_readiness?.checkpoints ?? []}
        evaluations={devData?.evaluations ?? []}
        experiments={devData?.experiments ?? adminData?.training_readiness?.experiments ?? []}
        datasets={devData?.datasets ?? adminData?.training_readiness?.datasets ?? []}
        downloadingArtifact={downloadingArtifact}
        artifactNotice={artifactNotice}
        onDownloadArtifact={(kind, ver) => handleDownloadTrainingArtifact(kind, ver)}
        onClose={() => setRegistryModalOpen(false)}
      />
    </div>
  );
}
