import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeftRight,
  CheckCircle2,
  Download,
  GitCompare,
  Layers,
  Minus,
  Search,
  TrendingDown,
  TrendingUp,
  X,
  AlertTriangle,
} from 'lucide-react';
import type {
  CheckpointItem,
  DatasetItem,
  EvaluationItem,
  ExperimentItem,
} from '../types';
import { CopyButton } from './CopyButton';
import { serializeTableToTsv } from '../lib/clipboard';

export type ModelRegistryModalTab = 'compare' | 'registry';

interface ModelRegistryModalProps {
  open: boolean;
  initialTab?: ModelRegistryModalTab;
  initialBaseVersion?: string;
  initialCandidateVersion?: string;
  checkpoints: CheckpointItem[];
  evaluations?: EvaluationItem[];
  experiments?: ExperimentItem[];
  datasets?: DatasetItem[];
  downloadingArtifact?: 'logs' | 'manifest' | null;
  artifactNotice?: { type: 'success' | 'error'; text: string } | null;
  onDownloadArtifact?: (kind: 'logs' | 'manifest', versionLabel: string) => void | Promise<void>;
  onClose: () => void;
}

type MetricDirection = 'lower' | 'higher';

interface MetricSpec {
  key: string;
  label: string;
  direction: MetricDirection;
  format: (val: number) => string;
  formatDelta: (delta: number) => string;
  extract: (ck: CheckpointItem, ev: EvaluationItem | null) => number | null;
}

type ComparisonOutcome = 'improved' | 'regressed' | 'unchanged' | 'missing';

interface ComparedMetricRow {
  spec: MetricSpec;
  valA: number | null;
  valB: number | null;
  delta: number | null;
  pctChange: number | null;
  outcome: ComparisonOutcome;
  barWidthA: number;
  barWidthB: number;
  divergingWidth: number;
}

function formatDateShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('th-TH', {
    year: '2-digit',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getStatusToneClass(status: string): string {
  const s = String(status || '').toUpperCase();
  if (s.includes('VERIFIED') || s === 'PASS' || s === 'APPROVED' || s === 'PRODUCTION') {
    return 'text-[var(--color-success)]';
  }
  if (s.includes('REJECT') || s.includes('FAIL') || s.includes('BLOCK')) {
    return 'text-[var(--color-danger)]';
  }
  if (s.includes('PENDING') || s.includes('STAG') || s.includes('WARN')) {
    return 'text-[var(--color-warning)]';
  }
  return 'text-[var(--color-accent)]';
}

const METRIC_SPECS: MetricSpec[] = [
  {
    key: 'val_loss',
    label: 'Validation Loss',
    direction: 'lower',
    format: (v) => v.toFixed(4),
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${d.toFixed(4)}`,
    extract: (ck) => (typeof ck.val_loss === 'number' && Number.isFinite(ck.val_loss) ? ck.val_loss : null),
  },
  {
    key: 'train_loss',
    label: 'Train Loss',
    direction: 'lower',
    format: (v) => v.toFixed(4),
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${d.toFixed(4)}`,
    extract: (ck) => (typeof ck.train_loss === 'number' && Number.isFinite(ck.train_loss) ? ck.train_loss : null),
  },
  {
    key: 'perplexity',
    label: 'Perplexity (PPL)',
    direction: 'lower',
    format: (v) => v.toFixed(2),
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${d.toFixed(2)}`,
    extract: (ck) => (typeof ck.perplexity === 'number' && Number.isFinite(ck.perplexity) ? ck.perplexity : null),
  },
  {
    key: 'eval_accuracy',
    label: 'Checkpoint Eval Accuracy',
    direction: 'higher',
    format: (v) => `${(v * 100).toFixed(1)}%`,
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pp`,
    extract: (ck) =>
      typeof ck.eval_accuracy === 'number' && Number.isFinite(ck.eval_accuracy) ? ck.eval_accuracy : null,
  },
  {
    key: 'math_score',
    label: 'Evaluation · Math AST Score',
    direction: 'higher',
    format: (v) => `${(v * 100).toFixed(1)}%`,
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pp`,
    extract: (_ck, ev) =>
      ev && typeof ev.math_score === 'number' && Number.isFinite(ev.math_score) ? ev.math_score : null,
  },
  {
    key: 'knowledge_score',
    label: 'Evaluation · Knowledge Graph Score',
    direction: 'higher',
    format: (v) => `${(v * 100).toFixed(1)}%`,
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pp`,
    extract: (_ck, ev) =>
      ev && typeof ev.knowledge_score === 'number' && Number.isFinite(ev.knowledge_score)
        ? ev.knowledge_score
        : null,
  },
  {
    key: 'planning_score',
    label: 'Evaluation · Planning DAG Score',
    direction: 'higher',
    format: (v) => `${(v * 100).toFixed(1)}%`,
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pp`,
    extract: (_ck, ev) =>
      ev && typeof ev.planning_score === 'number' && Number.isFinite(ev.planning_score)
        ? ev.planning_score
        : null,
  },
  {
    key: 'test_accuracy',
    label: 'Evaluation · Unseen Test Accuracy',
    direction: 'higher',
    format: (v) => `${(v * 100).toFixed(1)}%`,
    formatDelta: (d) => `${d >= 0 ? '+' : ''}${(d * 100).toFixed(1)} pp`,
    extract: (_ck, ev) =>
      ev && typeof ev.test_accuracy === 'number' && Number.isFinite(ev.test_accuracy)
        ? ev.test_accuracy
        : null,
  },
];

function computeMetricRow(
  spec: MetricSpec,
  ckptA: CheckpointItem,
  evalA: EvaluationItem | null,
  ckptB: CheckpointItem,
  evalB: EvaluationItem | null
): ComparedMetricRow {
  const valA = spec.extract(ckptA, evalA);
  const valB = spec.extract(ckptB, evalB);

  if (valA === null || valB === null) {
    const soloMax = valA ?? valB ?? 0;
    const isPercent = spec.direction === 'higher';
    const scaleMax = isPercent ? Math.max(1, soloMax) : Math.max(soloMax, 1e-6);
    return {
      spec,
      valA,
      valB,
      delta: null,
      pctChange: null,
      outcome: 'missing',
      barWidthA: valA === null ? 0 : Math.min(100, Math.max(4, (valA / scaleMax) * 100)),
      barWidthB: valB === null ? 0 : Math.min(100, Math.max(4, (valB / scaleMax) * 100)),
      divergingWidth: 0,
    };
  }

  const delta = valB - valA;
  const eps = 1e-9;
  let outcome: ComparisonOutcome = 'unchanged';
  if (Math.abs(delta) > eps) {
    if (spec.direction === 'lower') {
      outcome = delta < 0 ? 'improved' : 'regressed';
    } else {
      outcome = delta > 0 ? 'improved' : 'regressed';
    }
  }

  const pctChange = Math.abs(valA) > eps ? (delta / Math.abs(valA)) * 100 : null;
  const isPercent = spec.direction === 'higher';
  const maxVal = isPercent ? Math.max(1, valA, valB) : Math.max(valA, valB, 1e-6);

  const signedGainPct =
    pctChange !== null
      ? spec.direction === 'lower'
        ? -pctChange
        : pctChange
      : outcome === 'improved'
        ? 25
        : outcome === 'regressed'
          ? -25
          : 0;

  return {
    spec,
    valA,
    valB,
    delta,
    pctChange,
    outcome,
    barWidthA: valA === 0 ? 0 : Math.min(100, Math.max(4, (valA / maxVal) * 100)),
    barWidthB: valB === 0 ? 0 : Math.min(100, Math.max(4, (valB / maxVal) * 100)),
    divergingWidth: Math.min(100, Math.max(outcome === 'unchanged' ? 0 : 8, Math.abs(signedGainPct))),
  };
}

export function ModelRegistryModal(props: ModelRegistryModalProps) {
  if (!props.open) return null;
  const modalKey = `${props.initialTab ?? 'compare'}:${props.initialBaseVersion ?? ''}:${props.initialCandidateVersion ?? ''}`;
  return <ModelRegistryModalInner key={modalKey} {...props} />;
}

function ModelRegistryModalInner({
  open,
  initialTab = 'compare',
  initialBaseVersion,
  initialCandidateVersion,
  checkpoints,
  evaluations = [],
  experiments = [],
  datasets = [],
  downloadingArtifact = null,
  artifactNotice = null,
  onDownloadArtifact,
  onClose,
}: ModelRegistryModalProps) {
  const sortedCheckpoints = useMemo(
    () => [...checkpoints].sort((a, b) => b.version - a.version),
    [checkpoints]
  );

  const defaultCandidate = useMemo(() => {
    if (
      initialCandidateVersion &&
      sortedCheckpoints.some((c) => `v${c.version}` === initialCandidateVersion)
    ) {
      return initialCandidateVersion;
    }
    return sortedCheckpoints[0] ? `v${sortedCheckpoints[0].version}` : '';
  }, [initialCandidateVersion, sortedCheckpoints]);

  const defaultBase = useMemo(() => {
    if (
      initialBaseVersion &&
      sortedCheckpoints.some((c) => `v${c.version}` === initialBaseVersion)
    ) {
      return initialBaseVersion;
    }
    if (sortedCheckpoints.length >= 2) {
      const candidateItem = sortedCheckpoints.find((c) => `v${c.version}` === defaultCandidate);
      const fallback = sortedCheckpoints.find((c) => c.version !== candidateItem?.version);
      return fallback ? `v${fallback.version}` : `v${sortedCheckpoints[1].version}`;
    }
    return sortedCheckpoints[0] ? `v${sortedCheckpoints[0].version}` : '';
  }, [defaultCandidate, initialBaseVersion, sortedCheckpoints]);

  const [activeTab, setActiveTab] = useState<ModelRegistryModalTab>(initialTab);
  const [baseVersion, setBaseVersion] = useState<string>(defaultBase);
  const [candidateVersion, setCandidateVersion] = useState<string>(defaultCandidate);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'verified' | 'neural'>('all');

  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const prevFocused = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      prevFocused?.focus?.();
    };
  }, [open, onClose]);

  const datasetMap = useMemo(() => {
    const map = new Map<string, DatasetItem>();
    datasets.forEach((d) => map.set(d.id, d));
    return map;
  }, [datasets]);

  const evalByVersion = useMemo(() => {
    const map = new Map<number, EvaluationItem>();
    evaluations.forEach((ev) => {
      if (ev.checkpoint_version !== null && !map.has(ev.checkpoint_version)) {
        map.set(ev.checkpoint_version, ev);
      }
    });
    return map;
  }, [evaluations]);

  const experimentByCkptId = useMemo(() => {
    const map = new Map<string, ExperimentItem>();
    experiments.forEach((exp) => {
      if (exp.candidate_ckpt_id && !map.has(exp.candidate_ckpt_id)) {
        map.set(exp.candidate_ckpt_id, exp);
      }
    });
    return map;
  }, [experiments]);

  const ckptA = useMemo(
    () => sortedCheckpoints.find((c) => `v${c.version}` === baseVersion) || sortedCheckpoints[1] || sortedCheckpoints[0] || null,
    [baseVersion, sortedCheckpoints]
  );

  const ckptB = useMemo(
    () => sortedCheckpoints.find((c) => `v${c.version}` === candidateVersion) || sortedCheckpoints[0] || null,
    [candidateVersion, sortedCheckpoints]
  );

  const comparisonRows = useMemo(() => {
    if (!ckptA || !ckptB) return [];
    const evalA = evalByVersion.get(ckptA.version) || null;
    const evalB = evalByVersion.get(ckptB.version) || null;
    return METRIC_SPECS.map((spec) => computeMetricRow(spec, ckptA, evalA, ckptB, evalB)).filter(
      (row) => row.valA !== null || row.valB !== null
    );
  }, [ckptA, ckptB, evalByVersion]);

  const verdictSummary = useMemo(() => {
    const comparable = comparisonRows.filter((r) => r.outcome !== 'missing');
    const improved = comparable.filter((r) => r.outcome === 'improved').length;
    const regressed = comparable.filter((r) => r.outcome === 'regressed').length;
    const unchanged = comparable.filter((r) => r.outcome === 'unchanged').length;
    const missing = comparisonRows.length - comparable.length;
    const sameVersion = Boolean(ckptA && ckptB && ckptA.version === ckptB.version);
    return {
      totalComparable: comparable.length,
      improved,
      regressed,
      unchanged,
      missing,
      sameVersion,
    };
  }, [ckptA, ckptB, comparisonRows]);

  const filteredRegistry = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return sortedCheckpoints.filter((ck) => {
      const statusUpper = String(ck.eval_status || '').toUpperCase();
      if (
        statusFilter === 'verified' &&
        !statusUpper.includes('VERIFIED') &&
        statusUpper !== 'PASS'
      ) {
        return false;
      }
      if (statusFilter === 'neural' && ck.ngram_order !== 0 && !statusUpper.includes('NEURAL')) {
        return false;
      }
      if (!q) return true;
      const dsName = datasetMap.get(ck.dataset_id)?.name || '';
      return (
        `v${ck.version}`.toLowerCase().includes(q) ||
        ck.dataset_id.toLowerCase().includes(q) ||
        dsName.toLowerCase().includes(q) ||
        statusUpper.includes(q.toUpperCase())
      );
    });
  }, [datasetMap, searchQuery, sortedCheckpoints, statusFilter]);

  function handleSwapVersions() {
    const currentA = ckptA ? `v${ckptA.version}` : baseVersion;
    const currentB = ckptB ? `v${ckptB.version}` : candidateVersion;
    setBaseVersion(currentB);
    setCandidateVersion(currentA);
  }

  function renderVersionCard(
    roleLabel: string,
    accentClass: string,
    ck: CheckpointItem
  ) {
    const ds = datasetMap.get(ck.dataset_id);
    const ev = evalByVersion.get(ck.version) || null;
    const exp = experimentByCkptId.get(ck.id) || null;
    const versionLabel = `v${ck.version}`;

    return (
      <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className={`text-xs font-semibold ${accentClass}`}>{roleLabel}</p>
            <h4 className="mt-0.5 font-mono text-lg font-bold text-[var(--color-text)] tabular-nums">
              Checkpoint {versionLabel}
            </h4>
          </div>
          <span className={`font-mono text-xs font-semibold ${getStatusToneClass(ck.eval_status)}`}>
            {ck.eval_status}
          </span>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--color-text-secondary)] tabular-nums">
          <span>{ck.ngram_order === 0 ? 'Neural Transformer' : `N-Gram (order ${ck.ngram_order})`}</span>
          <span aria-hidden="true">·</span>
          <span>vocab {ck.vocab_size.toLocaleString()}</span>
          <span aria-hidden="true">·</span>
          <span>{formatDateShort(ck.created_at)}</span>
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-[var(--color-border)] pt-3 text-xs">
          <div>
            <dt className="text-[11px] text-[var(--color-text-muted)]">Dataset</dt>
            <dd className="truncate font-mono text-[var(--color-text)]" title={ds?.name || ck.dataset_id}>
              {ds?.name || ck.dataset_id}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-[var(--color-text-muted)]">Evaluation Suite</dt>
            <dd className="truncate font-mono text-[var(--color-text)]">
              {ev ? `${ev.suite_name} (${ev.overall_status})` : 'NOT RUN'}
            </dd>
          </div>
          {exp && (
            <div className="col-span-2">
              <dt className="text-[11px] text-[var(--color-text-muted)]">Experiment Hypothesis</dt>
              <dd className="truncate text-[var(--color-text-secondary)]" title={exp.hypothesis}>
                {exp.hypothesis}
              </dd>
            </div>
          )}
        </dl>

        {onDownloadArtifact && (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-3">
            <button
              type="button"
              disabled={downloadingArtifact !== null}
              onClick={() => void onDownloadArtifact('manifest', versionLabel)}
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2.5 text-[11px] font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap shrink-0"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Manifest {versionLabel}</span>
            </button>
            <button
              type="button"
              disabled={downloadingArtifact !== null}
              onClick={() => void onDownloadArtifact('logs', versionLabel)}
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2.5 text-[11px] font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap shrink-0"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Logs {versionLabel}</span>
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-3 backdrop-blur-sm sm:p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-registry-modal-title"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] shadow-2xl"
      >
        {/* Modal Header */}
        <div className="flex flex-col gap-3 border-b border-[var(--color-border)] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0">
            <h3
              id="model-registry-modal-title"
              className="text-lg font-bold tracking-tight text-[var(--color-text)]"
            >
              Model Registry &amp; Version Comparison
            </h3>
            <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] tabular-nums">
              {sortedCheckpoints.length} เวอร์ชันที่บันทึกไว้ · ข้อมูลจาก Checkpoint และ Evaluation จริง (ไม่จำลองค่า)
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <div
              role="tablist"
              aria-label="มุมมองใน Model Registry"
              className="inline-flex items-center gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'compare'}
                onClick={() => setActiveTab('compare')}
                className={`inline-flex min-h-[36px] items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                  activeTab === 'compare'
                    ? 'bg-[var(--color-primary)] text-white'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                }`}
              >
                <GitCompare className="h-3.5 w-3.5" aria-hidden="true" />
                <span>เปรียบเทียบสองเวอร์ชัน</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'registry'}
                onClick={() => setActiveTab('registry')}
                className={`inline-flex min-h-[36px] items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                  activeTab === 'registry'
                    ? 'bg-[var(--color-primary)] text-white'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                }`}
              >
                <Layers className="h-3.5 w-3.5" aria-hidden="true" />
                <span>รายการเวอร์ชัน ({sortedCheckpoints.length})</span>
              </button>
            </div>

            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              aria-label="ปิดหน้าต่าง Model Registry"
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-text)] focus-visible:outline-2 focus-visible:outline-[var(--color-focus)]"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5 sm:px-6">
          {artifactNotice && (
            <p
              role={artifactNotice.type === 'error' ? 'alert' : 'status'}
              className={`rounded-xl border px-3.5 py-2.5 text-xs ${
                artifactNotice.type === 'error'
                  ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                  : 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
              }`}
            >
              {artifactNotice.text}
            </p>
          )}

          {sortedCheckpoints.length === 0 ? (
            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center">
              <p className="text-sm font-semibold text-[var(--color-text)]">
                ยังไม่มีเวอร์ชันโมเดลใน Model Registry
              </p>
              <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                กรุณานำเข้าชุดข้อมูล ผ่าน Approval Gate และฝึกโมเดลจริงเพื่อบันทึก Checkpoint แรกก่อนเปรียบเทียบ
              </p>
            </div>
          ) : activeTab === 'compare' ? (
            <>
              {sortedCheckpoints.length < 2 && (
                <div className="flex items-start gap-2.5 rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-4 py-3 text-xs text-[var(--color-warning)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <div>
                    <p className="font-semibold">
                      มีเพียง 1 เวอร์ชันใน Registry (v{sortedCheckpoints[0].version})
                    </p>
                    <p className="mt-0.5 text-[var(--color-text-secondary)]">
                      ต้องมีอย่างน้อย 2 Checkpoint เพื่อวิเคราะห์ความแตกต่างแบบ Side-by-Side
                    </p>
                  </div>
                </div>
              )}

              {/* Version Selectors & Controls */}
              <div className="flex flex-col gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 lg:flex-row lg:items-end lg:justify-between">
                <div className="grid flex-1 gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
                  <div>
                    <label
                      htmlFor="registry-compare-base"
                      className="block text-xs font-medium text-[var(--color-text-secondary)]"
                    >
                      เวอร์ชันฐาน (Version A · Baseline)
                    </label>
                    <select
                      id="registry-compare-base"
                      aria-label="เลือกเวอร์ชันฐาน (Version A)"
                      value={ckptA ? `v${ckptA.version}` : ''}
                      onChange={(e) => setBaseVersion(e.target.value)}
                      className="mt-1.5 h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 font-mono text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      {sortedCheckpoints.map((ck) => {
                        const v = `v${ck.version}`;
                        return (
                          <option key={`base-${ck.id}`} value={v}>
                            {v} · {ck.eval_status} · val_loss {ck.val_loss.toFixed(4)}
                          </option>
                        );
                      })}
                    </select>
                  </div>

                  <button
                    type="button"
                    onClick={handleSwapVersions}
                    disabled={sortedCheckpoints.length < 2}
                    aria-label="สลับเวอร์ชัน A และ B"
                    title="สลับฝั่ง Version A และ Version B"
                    className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] disabled:opacity-40 whitespace-nowrap shrink-0"
                  >
                    <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>สลับ A ↔ B</span>
                  </button>

                  <div>
                    <label
                      htmlFor="registry-compare-candidate"
                      className="block text-xs font-medium text-[var(--color-text-secondary)]"
                    >
                      เวอร์ชันเปรียบเทียบ (Version B · Candidate)
                    </label>
                    <select
                      id="registry-compare-candidate"
                      aria-label="เลือกเวอร์ชันเปรียบเทียบ (Version B)"
                      value={ckptB ? `v${ckptB.version}` : ''}
                      onChange={(e) => setCandidateVersion(e.target.value)}
                      className="mt-1.5 h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 font-mono text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      {sortedCheckpoints.map((ck) => {
                        const v = `v${ck.version}`;
                        return (
                          <option key={`cand-${ck.id}`} value={v}>
                            {v} · {ck.eval_status} · val_loss {ck.val_loss.toFixed(4)}
                          </option>
                        );
                      })}
                    </select>
                  </div>
                </div>

                {ckptA && ckptB && (
                  <div className="flex items-center justify-end gap-2 shrink-0">
                    <CopyButton
                      getText={() =>
                        [
                          `ZYRQUEN Model Registry Comparison: v${ckptA.version} (Baseline A) vs v${ckptB.version} (Candidate B)`,
                          serializeTableToTsv(
                            ['Metric', 'Goal', `v${ckptA.version}`, `v${ckptB.version}`, 'Delta (B-A)', 'Outcome'],
                            comparisonRows.map((row) => [
                              row.spec.label,
                              row.spec.direction === 'lower' ? 'Lower is better' : 'Higher is better',
                              row.valA !== null ? row.spec.format(row.valA) : 'NOT RUN',
                              row.valB !== null ? row.spec.format(row.valB) : 'NOT RUN',
                              row.delta !== null ? row.spec.formatDelta(row.delta) : 'N/A',
                              row.outcome.toUpperCase(),
                            ])
                          ),
                        ].join('\n\n')
                      }
                      ariaLabel="คัดลอกตารางเปรียบเทียบเวอร์ชัน"
                      title="คัดลอกผลเปรียบเทียบเป็น TSV"
                      size="xs"
                    />
                  </div>
                )}
              </div>

              {/* Regression / Summary Verdict Strip */}
              {ckptA && ckptB && (
                <div
                  className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-xs ${
                    verdictSummary.sameVersion
                      ? 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)]'
                      : verdictSummary.regressed > 0
                        ? 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                        : verdictSummary.improved > 0
                          ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                          : 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text)]'
                  }`}
                >
                  <div className="flex items-center gap-2 font-semibold">
                    {verdictSummary.sameVersion ? (
                      <Minus className="h-4 w-4 shrink-0" aria-hidden="true" />
                    ) : verdictSummary.regressed > 0 ? (
                      <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
                    ) : verdictSummary.improved > 0 ? (
                      <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
                    ) : (
                      <Minus className="h-4 w-4 shrink-0" aria-hidden="true" />
                    )}
                    <span>
                      {verdictSummary.sameVersion
                        ? `SAME VERSION · กำลังเปรียบเทียบ v${ckptA.version} กับตัวเอง`
                        : verdictSummary.regressed > 0
                          ? `REGRESSION DETECTED · v${ckptB.version} ถดถอย ${verdictSummary.regressed} ตัวชี้วัดเทียบ v${ckptA.version}`
                          : verdictSummary.improved > 0
                            ? `ZERO REGRESSION · v${ckptB.version} ดีขึ้น ${verdictSummary.improved} ตัวชี้วัดเทียบ v${ckptA.version}`
                            : verdictSummary.totalComparable > 0
                              ? `UNCHANGED · ค่าตัวชี้วัดระหว่าง v${ckptA.version} และ v${ckptB.version} เท่ากัน`
                              : 'INSUFFICIENT METRICS · ไม่มีตัวชี้วัดที่เทียบกันได้'}
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                    <span>ดีขึ้น {verdictSummary.improved}</span>
                    <span aria-hidden="true">·</span>
                    <span>คงที่ {verdictSummary.unchanged}</span>
                    <span aria-hidden="true">·</span>
                    <span>ถดถอย {verdictSummary.regressed}</span>
                    {verdictSummary.missing > 0 && (
                      <>
                        <span aria-hidden="true">·</span>
                        <span>ยังไม่วัดผล {verdictSummary.missing}</span>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* Side-by-Side Version Profile Columns */}
              {ckptA && ckptB && (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {renderVersionCard(
                    'Version A · Baseline',
                    'text-[var(--color-primary)]',
                    ckptA
                  )}
                  {renderVersionCard(
                    'Version B · Candidate',
                    'text-[var(--color-accent)]',
                    ckptB
                  )}
                </div>
              )}

              {/* Side-by-Side Visual Performance Comparison */}
              {ckptA && ckptB && (
                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] px-4 py-3">
                    <div>
                      <h4 className="text-sm font-semibold text-[var(--color-text)]">
                        Performance Visualization (v{ckptA.version} vs v{ckptB.version})
                      </h4>
                      <p className="text-[11px] text-[var(--color-text-secondary)]">
                        แสดงกราฟแท่งเปรียบเทียบสัดส่วนจริงและค่าความต่าง Delta (B − A) แยกตามทิศทางที่ต้องการ
                      </p>
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-secondary)] font-mono tabular-nums">
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-xs bg-[var(--color-primary)]" aria-hidden="true" />
                        <span>A: v{ckptA.version}</span>
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-xs bg-[var(--color-accent)]" aria-hidden="true" />
                        <span>B: v{ckptB.version}</span>
                      </span>
                    </div>
                  </div>

                  <div className="divide-y divide-[var(--color-border)]">
                    {comparisonRows.map((row) => {
                      const outcomeLabel =
                        row.outcome === 'improved'
                          ? 'ดีขึ้น'
                          : row.outcome === 'regressed'
                            ? 'ถดถอย'
                            : row.outcome === 'unchanged'
                              ? 'คงที่'
                              : 'NOT RUN';

                      const outcomeColor =
                        row.outcome === 'improved'
                          ? 'text-[var(--color-success)]'
                          : row.outcome === 'regressed'
                            ? 'text-[var(--color-danger)]'
                            : 'text-[var(--color-text-muted)]';

                      const barBColor =
                        row.outcome === 'improved'
                          ? 'bg-[var(--color-success)]'
                          : row.outcome === 'regressed'
                            ? 'bg-[var(--color-danger)]'
                            : 'bg-[var(--color-accent)]';

                      return (
                        <div
                          key={row.spec.key}
                          className="grid grid-cols-1 gap-3 px-4 py-3.5 md:grid-cols-12 md:items-center"
                        >
                          {/* Metric Name + Direction */}
                          <div className="md:col-span-3">
                            <p className="text-xs font-semibold text-[var(--color-text)]">
                              {row.spec.label}
                            </p>
                            <p className="mt-0.5 text-[11px] text-[var(--color-text-muted)]">
                              {row.spec.direction === 'lower'
                                ? 'ต่ำกว่าดีกว่า (Lower is better)'
                                : 'สูงกว่าดีกว่า (Higher is better)'}
                            </p>
                          </div>

                          {/* Side-by-Side Proportional Bar Comparison */}
                          <div className="space-y-1.5 md:col-span-6">
                            <div className="flex items-center gap-2.5">
                              <span className="w-8 shrink-0 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                                A
                              </span>
                              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[var(--color-surface-raised)]">
                                <div
                                  aria-hidden="true"
                                  className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-200"
                                  style={{ width: `${row.barWidthA}%` }}
                                />
                              </div>
                              <span className="w-16 shrink-0 text-right font-mono text-xs text-[var(--color-text)] tabular-nums">
                                {row.valA !== null ? row.spec.format(row.valA) : '—'}
                              </span>
                            </div>

                            <div className="flex items-center gap-2.5">
                              <span className="w-8 shrink-0 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                                B
                              </span>
                              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[var(--color-surface-raised)]">
                                <div
                                  aria-hidden="true"
                                  className={`h-full rounded-full transition-[width] duration-200 ${barBColor}`}
                                  style={{ width: `${row.barWidthB}%` }}
                                />
                              </div>
                              <span className="w-16 shrink-0 text-right font-mono text-xs font-semibold text-[var(--color-text)] tabular-nums">
                                {row.valB !== null ? row.spec.format(row.valB) : '—'}
                              </span>
                            </div>
                          </div>

                          {/* Delta + Outcome */}
                          <div className="flex items-center justify-between gap-2 md:col-span-3 md:flex-col md:items-end md:justify-center">
                            <div className={`inline-flex items-center gap-1 font-mono text-xs font-semibold tabular-nums ${outcomeColor}`}>
                              {row.outcome === 'improved' ? (
                                <TrendingUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              ) : row.outcome === 'regressed' ? (
                                <TrendingDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              ) : (
                                <Minus className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                              )}
                              <span>
                                {row.delta !== null ? row.spec.formatDelta(row.delta) : 'ไม่มีข้อมูล'}
                              </span>
                            </div>

                            <div className="flex items-center gap-1.5 font-mono text-[11px] tabular-nums">
                              {row.pctChange !== null && (
                                <span className="text-[var(--color-text-secondary)]">
                                  ({row.pctChange >= 0 ? '+' : ''}
                                  {row.pctChange.toFixed(1)}%)
                                </span>
                              )}
                              <span className={`font-semibold ${outcomeColor}`}>{outcomeLabel}</span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            /* Registry Table View */
            <div className="space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="relative flex-1">
                  <Search
                    className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-muted)]"
                    aria-hidden="true"
                  />
                  <input
                    type="search"
                    aria-label="ค้นหาเวอร์ชันใน Model Registry"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="ค้นหาตามเวอร์ชัน (เช่น v2), dataset หรือสถานะ..."
                    className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] pl-9 pr-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                  />
                </div>

                <div className="inline-flex items-center gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1 shrink-0">
                  {(
                    [
                      ['all', 'ทั้งหมด'],
                      ['verified', 'VERIFIED / PASS'],
                      ['neural', 'Neural'],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setStatusFilter(id)}
                      className={`min-h-[34px] rounded-lg px-2.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                        statusFilter === id
                          ? 'bg-[var(--color-primary)] text-white'
                          : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {filteredRegistry.length === 0 ? (
                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 text-center text-xs text-[var(--color-text-secondary)]">
                  ไม่พบเวอร์ชันโมเดลที่ตรงกับเงื่อนไขการค้นหา
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]">
                  <table className="w-full min-w-[700px] border-collapse text-left text-xs">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] text-[11px] font-semibold text-[var(--color-text-secondary)]">
                        <th className="px-3.5 py-2.5">Version</th>
                        <th className="px-3.5 py-2.5">Status</th>
                        <th className="px-3.5 py-2.5">Dataset</th>
                        <th className="px-3.5 py-2.5 text-right">Train Loss</th>
                        <th className="px-3.5 py-2.5 text-right">Val Loss</th>
                        <th className="px-3.5 py-2.5 text-right">PPL</th>
                        <th className="px-3.5 py-2.5 text-right">Eval Acc</th>
                        <th className="px-3.5 py-2.5 text-right">เลือกเปรียบเทียบ</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-border)]">
                      {filteredRegistry.map((ck, idx) => {
                        const vLabel = `v${ck.version}`;
                        const dsName = datasetMap.get(ck.dataset_id)?.name || ck.dataset_id;
                        const isA = ckptA?.version === ck.version;
                        const isB = ckptB?.version === ck.version;
                        const prevCk = filteredRegistry[idx + 1] || sortedCheckpoints.find((c) => c.version < ck.version);

                        return (
                          <tr key={ck.id} className="hover:bg-[var(--color-surface-hover)]/60">
                            <td className="px-3.5 py-2.5 font-mono font-semibold text-[var(--color-text)] tabular-nums">
                              {vLabel}
                              <div className="text-[10px] font-normal text-[var(--color-text-muted)]">
                                {ck.ngram_order === 0 ? 'Neural' : `${ck.ngram_order}-gram`} · vocab {ck.vocab_size}
                              </div>
                            </td>
                            <td className={`px-3.5 py-2.5 font-mono font-semibold ${getStatusToneClass(ck.eval_status)}`}>
                              {ck.eval_status}
                            </td>
                            <td className="max-w-[160px] truncate px-3.5 py-2.5 text-[var(--color-text-secondary)]" title={dsName}>
                              {dsName}
                            </td>
                            <td className="px-3.5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
                              {ck.train_loss.toFixed(4)}
                            </td>
                            <td className="px-3.5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
                              {ck.val_loss.toFixed(4)}
                            </td>
                            <td className="px-3.5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
                              {ck.perplexity.toFixed(2)}
                            </td>
                            <td className="px-3.5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
                              {ck.eval_accuracy !== null ? `${(ck.eval_accuracy * 100).toFixed(1)}%` : '—'}
                            </td>
                            <td className="px-3.5 py-2.5 text-right">
                              <div className="inline-flex items-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => setBaseVersion(vLabel)}
                                  className={`min-h-[30px] rounded-lg border px-2 text-[11px] font-medium whitespace-nowrap ${
                                    isA
                                      ? 'border-[var(--color-primary)] bg-[var(--color-primary)] text-white'
                                      : 'border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-text)]'
                                  }`}
                                >
                                  {isA ? 'Base A' : 'ตั้งเป็น A'}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setCandidateVersion(vLabel)}
                                  className={`min-h-[30px] rounded-lg border px-2 text-[11px] font-medium whitespace-nowrap ${
                                    isB
                                      ? 'border-[var(--color-accent)] bg-[var(--color-accent)] text-[#090E1F]'
                                      : 'border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)]'
                                  }`}
                                >
                                  {isB ? 'Cand B' : 'ตั้งเป็น B'}
                                </button>
                                {prevCk && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setBaseVersion(`v${prevCk.version}`);
                                      setCandidateVersion(vLabel);
                                      setActiveTab('compare');
                                    }}
                                    className="min-h-[30px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 text-[11px] font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] whitespace-nowrap"
                                  >
                                    เทียบ v{prevCk.version}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] px-5 py-3.5 sm:px-6">
          <p className="text-[11px] text-[var(--color-text-muted)]">
            {ckptA && ckptB
              ? `กำลังเลือก A: v${ckptA.version} · B: v${ckptB.version}`
              : 'Model Registry (Non-Destructive Checkpoint Ledger)'}
          </p>
          <div className="flex items-center gap-2">
            {activeTab === 'registry' && sortedCheckpoints.length >= 2 && (
              <button
                type="button"
                onClick={() => setActiveTab('compare')}
                className="inline-flex min-h-[36px] items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] whitespace-nowrap shrink-0"
              >
                <GitCompare className="h-3.5 w-3.5" aria-hidden="true" />
                <span>เปิดมุมมองเปรียบเทียบ</span>
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="inline-flex min-h-[36px] items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] whitespace-nowrap shrink-0"
            >
              ปิด
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
