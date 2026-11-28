import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Fuse from 'fuse.js';
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Clock,
  Cpu,
  ExternalLink,
  GitBranch,
  Play,
  Plus,
  RotateCw,
  Search,
  ShieldCheck,
  Trash2,
  Workflow,
  X,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import {
  filterValidTraceSteps,
  isMalformedOrEmptyTraceText,
  sanitizeTraceDisplayText,
  serializeTableToTsv,
  validateTracePlan,
} from '../lib/clipboard';
import type {
  AutonomousMissionItem,
  KnowledgeTriple,
  MissionEvidenceItem,
  MissionNodeItem,
  NativeTrace,
  ReasoningTraceRecord,
  User,
  WorkflowGroup,
  WorkflowRun,
  WorkflowStageResult,
} from '../types';
import { CopyButton } from './CopyButton';
import { WorkflowLogsConsole } from './WorkflowLogsConsole';

interface MemoryWorkflowsViewProps {
  token: string;
  user: User;
}

function renderStatusLabel(status: string) {
  const normalized = String(status || 'UNKNOWN').trim().toUpperCase();
  switch (normalized) {
    case 'COMPLETED':
    case 'PASS':
    case 'VERIFIED':
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-success)]">
          <CheckCircle2 className="h-3.5 w-3.5" />
          <span>{normalized}</span>
        </span>
      );
    case 'PLANNED':
    case 'READY':
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-accent)]">
          <GitBranch className="h-3.5 w-3.5" />
          <span>{normalized}</span>
        </span>
      );
    case 'RUNNING':
    case 'EXECUTING':
    case 'PENDING_APPROVAL':
    case 'AWAITING_APPROVAL':
    case 'AWAITING_EVIDENCE':
    case 'RECOVERING':
    case 'NEEDS_CLARIFICATION':
    case 'WARN':
    case 'NOT_LEARNED':
    case 'UNCERTAIN':
    case 'UNABLE_TO_INFER':
    case 'UNKNOWN':
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-warning)]">
          <Clock className="h-3.5 w-3.5" />
          <span>{normalized}</span>
        </span>
      );
    case 'FAILED':
    case 'REJECTED':
    case 'BLOCKED':
    case 'CANCELLED':
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-danger)]">
          <XCircle className="h-3.5 w-3.5" />
          <span>{normalized}</span>
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-text-secondary)]">
          <span>{normalized}</span>
        </span>
      );
  }
}

function ReasoningTraceRow({ item }: { item: ReasoningTraceRecord }) {
  let enginePath: string[];
  try {
    const parsedPath = JSON.parse(item.engine_path_json);
    enginePath = Array.isArray(parsedPath) ? parsedPath.map(String) : [];
  } catch {
    enginePath = [];
  }

  let trace: NativeTrace;
  try {
    trace = JSON.parse(item.trace_json) as NativeTrace;
  } catch {
    trace = {};
  }

  const rawOrderedSteps: string[] = [];
  if (trace.math?.steps?.length) rawOrderedSteps.push(...trace.math.steps);
  if (trace.word_math?.steps?.length) rawOrderedSteps.push(...trace.word_math.steps);
  if (trace.algebra?.steps?.length) rawOrderedSteps.push(...trace.algebra.steps);
  if (trace.logic?.steps?.length) rawOrderedSteps.push(...trace.logic.steps);
  if (trace.causal_logic?.steps?.length) rawOrderedSteps.push(...trace.causal_logic.steps);
  if (trace.statistics) {
    rawOrderedSteps.push(
      `สถิติ ${trace.statistics.count} ค่า: mean=${trace.statistics.mean}, median=${trace.statistics.median}, stdev=${trace.statistics.stdev}`
    );
  }
  if (trace.graph_path?.path?.edges?.length) {
    trace.graph_path.path.edges.forEach((edge, i) => {
      rawOrderedSteps.push(`BFS Hop ${i + 1}: ${edge.from} -[${edge.relation}]-> ${edge.to} (${edge.source})`);
    });
  }
  const validatedPlan = validateTracePlan(trace.plan);
  if (validatedPlan.valid) {
    rawOrderedSteps.push(`เป้าหมายแผนงาน (${validatedPlan.planStatus}): ${validatedPlan.goal}`);
    validatedPlan.steps.forEach((s) => {
      const deps = s.depends_on.length > 0 ? ` · รอ ${s.depends_on.join(', ')}` : '';
      rawOrderedSteps.push(`${s.step_id} · ${s.title} [${s.status}${deps}]: ${s.detail}`);
    });
    validatedPlan.statusTransitions.forEach((tr) => {
      rawOrderedSteps.push(
        `สถานะ${tr.step_id ? ` ${tr.step_id}` : ''}: ${tr.from_status} → ${tr.to_status}${tr.reason ? ` (${tr.reason})` : ''}`
      );
    });
  } else if (trace.goal_validation?.status_transitions?.length) {
    trace.goal_validation.status_transitions.forEach((tr) => {
      if (tr.from_status && tr.to_status) {
        rawOrderedSteps.push(
          `Goal Gate: ${tr.from_status} → ${tr.to_status}${tr.reason ? ` (${sanitizeTraceDisplayText(tr.reason)})` : ''}`
        );
      }
    });
  }
  if (trace.autonomous_mission?.stages?.length) {
    trace.autonomous_mission.stages.forEach((s) => {
      const st = String(s.status || '').trim();
      const stage = String(s.stage || '').trim();
      if (stage && st) {
        const cleanDetail = s.detail ? sanitizeTraceDisplayText(s.detail) : '';
        rawOrderedSteps.push(`Mission ${stage}: ${st}${cleanDetail ? ` — ${cleanDetail}` : ''}`);
      }
    });
  }
  if (trace.checkpoint) {
    rawOrderedSteps.push(
      `Checkpoint v${trace.checkpoint.checkpoint_version} (${trace.checkpoint.engine || 'ngram'}) · ppl=${trace.checkpoint.perplexity.toFixed(2)}${
        trace.checkpoint.generated ? ` → "${trace.checkpoint.generated}"` : ''
      }`
    );
  }
  if (trace.external_tool) {
    rawOrderedSteps.push(
      `Tool ${trace.external_tool.tool_id} [${trace.external_tool.status}]${
        trace.external_tool.trust_grade ? ` · trust=${trace.external_tool.trust_grade}` : ''
      }${trace.external_tool.analysis_summary ? ` — ${sanitizeTraceDisplayText(trace.external_tool.analysis_summary)}` : ''}`
    );
  }
  if (trace.teach) {
    const t = trace.teach.triple;
    rawOrderedSteps.push(
      `บันทึกความรู้: ${t.subject} -> ${t.relation} -> ${t.object}${
        trace.teach.contradictions.length
          ? ` (พบข้อขัดแย้ง: ${trace.teach.contradictions.join(', ')})`
          : trace.teach.duplicate
            ? ' (มีอยู่เดิม)'
            : ''
      }`
    );
  }
  const orderedSteps = filterValidTraceSteps(rawOrderedSteps);
  if (enginePath.includes('unlearned_boundary') && orderedSteps.length === 0) {
    orderedSteps.push(
      'งดตอบเดาอัตโนมัติ (Honest Abstention): ไม่ตรงกับ AST คณิตศาสตร์, กราฟความรู้, หรือคำศัพท์ใน Checkpoint และไม่ส่งต่อ LLM ภายนอก'
    );
  }

  const cleanPrompt =
    sanitizeTraceDisplayText(item.prompt) || 'คำสั่งไม่สมบูรณ์หรือผิดรูปแบบ (ถูกคัดกรอง)';
  const cleanResponse = sanitizeTraceDisplayText(item.response_preview) || '—';

  const taskTimings = (Array.isArray(trace.task_timings) ? trace.task_timings : [])
    .filter(
      (t) =>
        Boolean(t?.task) &&
        !isMalformedOrEmptyTraceText(t.task) &&
        Boolean(t?.status) &&
        !isMalformedOrEmptyTraceText(t.status)
    )
    .map((t) => ({
      ...t,
      detail: t.detail ? sanitizeTraceDisplayText(t.detail) : '',
    }));
  const totalTaskMs = taskTimings.reduce((acc, t) => acc + (Number(t.duration_ms) || 0), 0);
  const rawBottleneck =
    trace.bottleneck_task ||
    (taskTimings.length > 0
      ? (() => {
          const slowest = taskTimings.reduce((best, cur) =>
            (cur.duration_ms || 0) > (best.duration_ms || 0) ? cur : best
          );
          return {
            task: slowest.task,
            duration_ms: slowest.duration_ms,
            share_pct:
              totalTaskMs > 0
                ? Math.round(((slowest.duration_ms || 0) / totalTaskMs) * 1000) / 10
                : 0,
          };
        })()
      : null);
  const bottleneck =
    rawBottleneck && rawBottleneck.task && !isMalformedOrEmptyTraceText(rawBottleneck.task)
      ? rawBottleneck
      : null;

  return (
    <details className="group border-b border-[var(--color-border)] last:border-b-0">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-[var(--color-surface-hover)] sm:px-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {renderStatusLabel(item.status)}
            <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 font-mono text-[11px] text-[var(--color-text)]">
              {item.model_version}
            </span>
            <span className="font-mono text-[11px] text-[var(--color-accent)]">
              {enginePath.length > 0 ? enginePath.join(' → ') : item.mode}
            </span>
            {bottleneck && (
              <span className="rounded-md border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-2 py-0.5 font-mono text-[11px] text-[var(--color-warning)] tabular-nums">
                Bottleneck: {bottleneck.task} ({bottleneck.duration_ms} ms)
              </span>
            )}
          </div>
          <p className="mt-1.5 line-clamp-1 text-sm font-medium text-[var(--color-text)]">
            {cleanPrompt}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3 pt-0.5 text-right">
          <div className="hidden sm:block">
            <p className="font-mono text-xs text-[var(--color-text)] tabular-nums">{item.latency_ms} ms</p>
            <p className="text-[11px] text-[var(--color-text-muted)] tabular-nums">
              {new Date(item.created_at).toLocaleString('th-TH')}
            </p>
          </div>
          <ChevronDown className="h-4 w-4 text-[var(--color-text-muted)] transition-transform group-open:rotate-180" />
        </div>
      </summary>

      <div className="space-y-3 border-t border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="inline-flex items-center gap-1.5 font-medium text-[var(--color-success)]">
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>
              {item.external_models_used === 0
                ? 'Native-Only Verified (ไม่ใช้ LLM ภายนอก)'
                : 'ตรวจพบการอ้างอิงภายนอก'}
            </span>
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
              mode: {item.mode} · {item.latency_ms} ms ·{' '}
              {new Date(item.created_at).toLocaleString('th-TH')}
            </span>
            <CopyButton
              getText={() => {
                const lines = [
                  `ZYRQUEN Reasoning Trace Report`,
                  `Status: ${item.status} | Model: ${item.model_version} | Mode: ${item.mode} | Latency: ${item.latency_ms} ms`,
                  `Engine Path: ${enginePath.join(' -> ') || item.mode}`,
                  `Prompt:\n${cleanPrompt}`,
                  `Response:\n${cleanResponse}`,
                ];
                if (orderedSteps.length > 0) {
                  lines.push(`Steps:\n${orderedSteps.map((s, i) => `${i + 1}. ${s}`).join('\n')}`);
                }
                if (taskTimings.length > 0) {
                  lines.push(
                    `Task Timings:\n${serializeTableToTsv(
                      ['Task', 'Status', 'Duration (ms)'],
                      taskTimings.map((t) => [t.task, t.status, t.duration_ms])
                    )}`
                  );
                }
                return lines.join('\n\n');
              }}
              ariaLabel="คัดลอกรายงาน Reasoning Trace"
              title="คัดลอกรายงาน Reasoning Trace ฉบับเต็ม"
              size="xs"
            />
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              คำถามตั้งต้น (Prompt)
            </p>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs text-[var(--color-text)]">
              {cleanPrompt}
            </p>
          </div>
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              คำตอบที่ได้ (Response Preview)
            </p>
            <p className="mt-1 whitespace-pre-wrap break-words text-xs text-[var(--color-text-secondary)]">
              {cleanResponse}
            </p>
          </div>
        </div>

        {taskTimings.length > 0 && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-warning)]">
                <Clock className="h-3.5 w-3.5" />
                <span>บันทึกเวลาทำงานแยกราย Task (Bottleneck Profiler · {taskTimings.length} งาน)</span>
              </p>
              {bottleneck && (
                <span className="font-mono text-[11px] text-[var(--color-warning)] tabular-nums">
                  ช้าที่สุด: {bottleneck.task} ({bottleneck.duration_ms} ms · {bottleneck.share_pct}%)
                </span>
              )}
            </div>
            <div className="space-y-1.5">
              {taskTimings.map((timing, idx) => {
                const isBottleneck =
                  bottleneck &&
                  timing.task === bottleneck.task &&
                  timing.duration_ms === bottleneck.duration_ms;
                const pct =
                  totalTaskMs > 0
                    ? Math.min(100, Math.max(4, Math.round(((timing.duration_ms || 0) / totalTaskMs) * 100)))
                    : 10;
                return (
                  <div
                    key={`${timing.task}-${idx}`}
                    className={`rounded-lg border px-2.5 py-2 text-xs ${
                      isBottleneck
                        ? 'border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)]'
                        : 'border-[var(--color-border)] bg-[var(--color-surface)]'
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="font-mono text-[10px] text-[var(--color-text-muted)] tabular-nums">
                          #{timing.order ?? idx + 1}
                        </span>
                        <span className="truncate font-mono text-[11px] font-medium text-[var(--color-text)]">
                          {timing.task}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                            timing.matched
                              ? 'bg-[var(--zyrquen-indigo)]/30 text-[var(--color-accent)]'
                              : 'bg-[var(--color-surface-hover)] text-[var(--color-text-secondary)]'
                          }`}
                        >
                          {timing.status}
                        </span>
                      </div>
                      <span
                        className={`font-mono text-[11px] font-semibold tabular-nums ${
                          isBottleneck ? 'text-[var(--color-warning)]' : 'text-[var(--color-text)]'
                        }`}
                      >
                        {timing.duration_ms} ms
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-hover)]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: isBottleneck
                            ? 'var(--color-warning)'
                            : timing.matched
                              ? 'var(--color-accent)'
                              : 'var(--color-text-muted)',
                        }}
                      />
                    </div>
                    {timing.detail && (
                      <p className="mt-1 font-mono text-[10px] text-[var(--color-text-secondary)]">{timing.detail}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {orderedSteps.length > 0 && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-accent)]">
              <GitBranch className="h-3.5 w-3.5" />
              <span>ลำดับขั้นตอนการตัดสินใจ ({orderedSteps.length} ขั้น)</span>
            </p>
            <ol className="list-decimal space-y-1.5 pl-4 text-xs text-[var(--color-text)]">
              {orderedSteps.map((step, idx) => (
                <li key={idx} className="leading-relaxed">
                  {step}
                </li>
              ))}
            </ol>
          </div>
        )}

        {trace.matched_triples && trace.matched_triples.length > 0 && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-accent)]">
              หลักฐานจากกราฟความรู้ที่ใช้อ้างอิง ({trace.matched_triples.length} รายการ)
            </p>
            <ul className="space-y-1 text-xs text-[var(--color-text)]">
              {trace.matched_triples.map((m) => (
                <li key={m.id} className="font-mono text-[11px]">
                  {m.inferred_chain
                    ? `[${m.hop || 2}-hop] ${m.inferred_chain}`
                    : `${m.subject} -[${m.relation}]-> ${m.object}`}{' '}
                  <span className="text-[var(--color-text-muted)]">({m.source})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

export function MemoryWorkflowsView({ token, user }: MemoryWorkflowsViewProps) {
  const [tab, setTab] = useState<'knowledge' | 'workflows' | 'missions'>('knowledge');
  const [triples, setTriples] = useState<KnowledgeTriple[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [subject, setSubject] = useState('');
  const [relation, setRelation] = useState('');
  const [objectVal, setObjectVal] = useState('');
  const [contradictionWarning, setContradictionWarning] = useState<string | null>(null);

  const [groups, setGroups] = useState<WorkflowGroup[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [reasoningTraces, setReasoningTraces] = useState<ReasoningTraceRecord[]>([]);
  const [traceStatusFilter, setTraceStatusFilter] = useState<string>('ALL');
  const [refreshingTraces, setRefreshingTraces] = useState(false);
  const [missions, setMissions] = useState<AutonomousMissionItem[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [selectedMissionDetail, setSelectedMissionDetail] = useState<{
    mission: AutonomousMissionItem;
    nodes: MissionNodeItem[];
    evidence: MissionEvidenceItem[];
  } | null>(null);
  const [loadingMissionDetail, setLoadingMissionDetail] = useState(false);
  const [missionActionId, setMissionActionId] = useState<string | null>(null);
  const [newMissionGoal, setNewMissionGoal] = useState('');
  const [launchingMission, setLaunchingMission] = useState(false);

  const [runningGroupId, setRunningGroupId] = useState<string | null>(null);
  const [decidingRunId, setDecidingRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tripleFuse = useMemo(
    () =>
      new Fuse(triples, {
        keys: ['subject', 'relation', 'object', 'source'],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [triples]
  );

  const groupFuse = useMemo(
    () =>
      new Fuse(groups, {
        keys: ['id', 'name', 'description', 'stages'],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [groups]
  );

  const runFuse = useMemo(
    () =>
      new Fuse(runs, {
        keys: ['group_id', 'status', 'summary'],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [runs]
  );

  const traceFuse = useMemo(
    () =>
      new Fuse(reasoningTraces, {
        keys: ['prompt', 'response_preview', 'status', 'model_version', 'engine_path_json', 'mode'],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [reasoningTraces]
  );

  const trimmedQuery = searchQuery.trim();

  const fuzzyTriples = useMemo(
    () => (trimmedQuery ? tripleFuse.search(trimmedQuery).map((r) => r.item) : triples),
    [trimmedQuery, tripleFuse, triples]
  );

  const fuzzyGroups = useMemo(
    () => (trimmedQuery ? groupFuse.search(trimmedQuery).map((r) => r.item) : groups),
    [trimmedQuery, groupFuse, groups]
  );

  const fuzzyRuns = useMemo(
    () => (trimmedQuery ? runFuse.search(trimmedQuery).map((r) => r.item) : runs),
    [trimmedQuery, runFuse, runs]
  );

  const fuzzyTraces = useMemo(() => {
    const base = trimmedQuery ? traceFuse.search(trimmedQuery).map((r) => r.item) : reasoningTraces;
    if (traceStatusFilter === 'ALL') return base;
    return base.filter((t) => t.status === traceStatusFilter);
  }, [trimmedQuery, traceFuse, reasoningTraces, traceStatusFilter]);

  const loadData = useCallback(async () => {
    await Promise.resolve();
    setLoading(true);
    setError(null);
    try {
      const [kRes, wRes, mRes] = await Promise.all([
        apiRequest<{ triples: KnowledgeTriple[] }>('/api/knowledge', { token }),
        apiRequest<{
          groups: WorkflowGroup[];
          runs: WorkflowRun[];
          reasoning_traces?: ReasoningTraceRecord[];
        }>('/api/workflows', {
          token,
        }),
        apiRequest<{ missions: AutonomousMissionItem[] }>('/api/autonomous/missions', {
          token,
        }).catch(() => ({ missions: [] as AutonomousMissionItem[] })),
      ]);
      setTriples(kRes.triples);
      setGroups(wRes.groups);
      setRuns(wRes.runs);
      setReasoningTraces(wRes.reasoning_traces || []);
      setMissions(mRes.missions || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดข้อมูลความจำและเวิร์กโฟลว์ได้');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) void loadData();
    });
    return () => {
      active = false;
    };
  }, [loadData]);

  async function handleAddTriple(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setContradictionWarning(null);
    try {
      const res = await apiRequest<{
        triple: KnowledgeTriple;
        contradictions: string[];
      }>('/api/knowledge', {
        method: 'POST',
        token,
        body: { subject, relation, object: objectVal },
      });
      setTriples((prev) => [res.triple, ...prev]);
      setSubject('');
      setRelation('');
      setObjectVal('');
      if (res.contradictions?.length) {
        setContradictionWarning(
          `ตรวจพบข้อมูลขัดแย้งกับค่าเดิม: ${res.contradictions.join(', ')}`
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'บันทึกความสัมพันธ์ไม่สำเร็จ');
    }
  }

  async function handleDeleteTriple(id: string) {
    try {
      await apiRequest(`/api/knowledge/${id}`, { method: 'DELETE', token });
      setTriples((prev) => prev.filter((t) => t.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ลบความสัมพันธ์ไม่สำเร็จ');
    }
  }

  async function handleRunWorkflow(groupId: string) {
    setRunningGroupId(groupId);
    setError(null);
    try {
      const res = await apiRequest<{ run: WorkflowRun }>(`/api/workflows/${groupId}/run`, {
        method: 'POST',
        token,
        body: {},
      });
      setRuns((prev) => [res.run, ...prev]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เรียกทำงานเวิร์กโฟลว์ไม่สำเร็จ');
    } finally {
      setRunningGroupId(null);
    }
  }

  async function handleWorkflowDecision(runId: string, decision: 'approve' | 'reject') {
    setDecidingRunId(runId);
    setError(null);
    try {
      const res = await apiRequest<{ run: WorkflowRun }>(`/api/workflows/runs/${runId}/decide`, {
        method: 'POST',
        token,
        body: { decision },
      });
      if (res.run) {
        setRuns((prev) => prev.map((item) => (item.id === runId ? res.run : item)));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถดำเนินการอนุมัติเวิร์กโฟลว์ได้');
    } finally {
      setDecidingRunId(null);
    }
  }

  async function handleRefreshTraces() {
    setRefreshingTraces(true);
    setError(null);
    try {
      const res = await apiRequest<{ reasoning_traces: ReasoningTraceRecord[] }>(
        '/api/workflows/reasoning-traces?limit=40',
        { token }
      );
      setReasoningTraces(res.reasoning_traces || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถอัปเดตบันทึกการตัดสินใจได้');
    } finally {
      setRefreshingTraces(false);
    }
  }

  async function handleSelectMission(missionId: string) {
    setSelectedMissionId(missionId);
    setLoadingMissionDetail(true);
    setError(null);
    try {
      const detail = await apiRequest<{
        mission: AutonomousMissionItem;
        nodes: MissionNodeItem[];
        evidence: MissionEvidenceItem[];
      }>(`/api/autonomous/missions/${missionId}`, { token });
      setSelectedMissionDetail(detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดรายละเอียดภารกิจได้');
    } finally {
      setLoadingMissionDetail(false);
    }
  }

  async function handleLaunchMission(e: React.FormEvent) {
    e.preventDefault();
    const goal = newMissionGoal.trim();
    if (!goal) return;
    setLaunchingMission(true);
    setError(null);
    try {
      const res = await apiRequest<{
        mission: AutonomousMissionItem;
        nodes?: MissionNodeItem[];
        evidence?: MissionEvidenceItem[];
      }>('/api/autonomous/missions', {
        method: 'POST',
        token,
        body: { goal },
      });
      setMissions((prev) => [res.mission, ...prev]);
      setNewMissionGoal('');
      setSelectedMissionId(res.mission.id);
      if (res.nodes) {
        setSelectedMissionDetail({
          mission: res.mission,
          nodes: res.nodes,
          evidence: res.evidence || [],
        });
      } else {
        await handleSelectMission(res.mission.id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เริ่มภารกิจอัตโนมัติไม่สำเร็จ');
    } finally {
      setLaunchingMission(false);
    }
  }

  async function handleMissionAction(missionId: string, action: 'resume' | 'cancel') {
    setMissionActionId(missionId);
    setError(null);
    try {
      const res = await apiRequest<{
        mission: AutonomousMissionItem;
        nodes?: MissionNodeItem[];
        evidence?: MissionEvidenceItem[];
      }>(`/api/autonomous/missions/${missionId}/${action}`, {
        method: 'POST',
        token,
        body: {},
      });
      setMissions((prev) => prev.map((m) => (m.id === missionId ? res.mission : m)));
      if (selectedMissionId === missionId) {
        if (res.nodes) {
          setSelectedMissionDetail({
            mission: res.mission,
            nodes: res.nodes,
            evidence: res.evidence || [],
          });
        } else {
          await handleSelectMission(missionId);
        }
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : action === 'resume'
            ? 'ดำเนินภารกิจต่อไม่สำเร็จ'
            : 'ยกเลิกภารกิจไม่สำเร็จ'
      );
    } finally {
      setMissionActionId(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">
            ความจำและระบบเวิร์กโฟลว์ภายใน
          </h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            จัดการกราฟความรู้ถาวร เวิร์กโฟลว์กลางทั้ง 8 กลุ่มงาน และภารกิจอัตโนมัติ (DAG Executor)
          </p>
        </div>

        <div className="grid grid-cols-3 gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1 sm:w-auto">
          <button
            type="button"
            onClick={() => setTab('knowledge')}
            className={`flex min-h-[40px] items-center justify-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              tab === 'knowledge'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            <BrainCircuit className="h-3.5 w-3.5" />
            <span>กราฟความรู้ ({fuzzyTriples.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('workflows')}
            className={`flex min-h-[40px] items-center justify-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              tab === 'workflows'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            <Workflow className="h-3.5 w-3.5" />
            <span>ระบบเวิร์กโฟลว์ ({fuzzyGroups.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('missions')}
            className={`flex min-h-[40px] items-center justify-center gap-2 rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              tab === 'missions'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            <Cpu className="h-3.5 w-3.5" />
            <span>ภารกิจอัตโนมัติ ({missions.length})</span>
          </button>
        </div>
      </div>

      {/* Unified Global Fuzzy Search Bar (queries Knowledge Fragments & Workflow Definitions) */}
      <div className="relative mb-6">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="ค้นหาแบบคลุมเครือ (Fuzzy Search) ทั้งกราฟความรู้และนิยามเวิร์กโฟลว์..."
          aria-label="ค้นหากราฟความรู้และเวิร์กโฟลว์"
          className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] pl-10 pr-10 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
        />
        {searchQuery && (
          <button
            type="button"
            onClick={() => setSearchQuery('')}
            aria-label="ล้างคำค้นหา"
            className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            <X className="h-4 w-4" />
          </button>
        )}
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

      {trimmedQuery ? (
        <div className="space-y-6" aria-label="ผลลัพธ์การค้นหาทั้งหมด">
          <section>
            <h3 className="mb-3 text-sm font-semibold text-[var(--color-accent)] tabular-nums">
              กราฟความรู้ที่ตรงกัน ({fuzzyTriples.length})
            </h3>
            <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
              {fuzzyTriples.length === 0 ? (
                <p className="p-4 text-sm text-[var(--color-text-secondary)]">
                  ไม่พบความจำในกราฟความรู้ที่ตรงกับ &ldquo;{trimmedQuery}&rdquo;
                </p>
              ) : (
                fuzzyTriples.map((t) => (
                  <div
                    key={t.id}
                    className="flex min-h-[56px] items-center justify-between gap-3 px-4 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[var(--color-text)]">
                        <span>{t.subject}</span>
                        <span className="mx-2 text-[var(--color-accent)]">→ {t.relation} →</span>
                        <span>{t.object}</span>
                      </p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] tabular-nums">{t.source}</p>
                    </div>
                    {(user.role === 'admin' || t.created_by === user.id) && (
                      <button
                        type="button"
                        onClick={() => void handleDeleteTriple(t.id)}
                        aria-label={`ลบความสัมพันธ์ ${t.subject}`}
                        className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl text-[var(--color-text-muted)] hover:bg-[var(--color-danger-bg)] hover:text-[var(--color-danger)]"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-semibold text-[var(--color-accent)] tabular-nums">
              นิยามเวิร์กโฟลว์ที่ตรงกัน ({fuzzyGroups.length})
            </h3>
            {fuzzyGroups.length === 0 ? (
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 text-sm text-[var(--color-text-secondary)]">
                ไม่พบนิยามเวิร์กโฟลว์ที่ตรงกับ &ldquo;{trimmedQuery}&rdquo;
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {fuzzyGroups.map((grp) => (
                  <div
                    key={grp.id}
                    className="flex flex-col justify-between rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                  >
                    <div>
                      <h4 className="text-sm font-semibold text-[var(--color-text)]">{grp.name}</h4>
                      <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">
                        {grp.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={runningGroupId === grp.id}
                      onClick={() => void handleRunWorkflow(grp.id)}
                      className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-50"
                    >
                      <Play className="h-3.5 w-3.5" />
                      <span>{runningGroupId === grp.id ? 'กำลังทำงาน...' : 'เริ่มรันเวิร์กโฟลว์'}</span>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {fuzzyRuns.length > 0 && (
            <section>
              <h3 className="mb-3 text-sm font-semibold text-[var(--color-accent)] tabular-nums">
                ประวัติการรันที่ตรงกัน ({fuzzyRuns.length})
              </h3>
              <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
                {fuzzyRuns.map((run) => (
                  <div key={run.id} className="p-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-[var(--color-text)]">{run.group_id}</span>
                      {renderStatusLabel(run.status)}
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{run.summary}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {fuzzyTraces.length > 0 && (
            <section>
              <h3 className="mb-3 text-sm font-semibold text-[var(--color-accent)] tabular-nums">
                บันทึกการตัดสินใจ (Reasoning Trace) ที่ตรงกัน ({fuzzyTraces.length})
              </h3>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
                {fuzzyTraces.map((item) => (
                  <ReasoningTraceRow key={item.id} item={item} />
                ))}
              </div>
            </section>
          )}
        </div>
      ) : tab === 'knowledge' ? (
        <div className="grid gap-6 lg:grid-cols-12">
          <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-5">
            <h3 className="text-base font-semibold text-[var(--color-text)]">บันทึกความสัมพันธ์ใหม่</h3>
            <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
              เพิ่มความรู้ลงในกราฟ SQLite ภายในพร้อมตรวจสอบข้อขัดแย้งกับความจำเดิมอัตโนมัติ
            </p>

            <form onSubmit={handleAddTriple} className="mt-4 space-y-3.5">
              <div>
                <label htmlFor="triple-subject" className="mb-1 block text-xs text-[var(--color-text-secondary)]">
                  ประธาน (Subject)
                </label>
                <input
                  id="triple-subject"
                  type="text"
                  required
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="ZYRQUEN"
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="triple-relation" className="mb-1 block text-xs text-[var(--color-text-secondary)]">
                  ความสัมพันธ์ (Relation)
                </label>
                <input
                  id="triple-relation"
                  type="text"
                  required
                  value={relation}
                  onChange={(e) => setRelation(e.target.value)}
                  placeholder="บังคับใช้"
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="triple-object" className="mb-1 block text-xs text-[var(--color-text-secondary)]">
                  กรรม (Object)
                </label>
                <input
                  id="triple-object"
                  type="text"
                  required
                  value={objectVal}
                  onChange={(e) => setObjectVal(e.target.value)}
                  placeholder="Approval Gate"
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>

              {contradictionWarning && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] p-3 text-xs text-[var(--color-warning)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{contradictionWarning}</span>
                </div>
              )}

              <button
                type="submit"
                className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] text-sm font-medium text-white hover:bg-[var(--color-primary-hover)]"
              >
                <Plus className="h-4 w-4" />
                <span>เพิ่มความจำ</span>
              </button>
            </form>
          </section>

          <section className="lg:col-span-7">
            <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
              {loading ? (
                <div className="p-6 text-sm text-[var(--color-text-secondary)]">กำลังโหลดกราฟความรู้...</div>
              ) : fuzzyTriples.length === 0 ? (
                <div className="p-6 text-sm text-[var(--color-text-secondary)]">
                  {searchQuery
                    ? `ไม่พบความสัมพันธ์ที่ตรงกับ "${searchQuery}"`
                    : 'ยังไม่มีข้อมูลในกราฟความรู้ คุณสามารถสอนในเวิร์กสเปซหรือเพิ่มจากแบบฟอร์มด้านซ้าย'}
                </div>
              ) : (
                fuzzyTriples.map((t) => (
                  <div
                    key={t.id}
                    className="flex min-h-[60px] items-center justify-between gap-3 px-4 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-[var(--color-text)]">
                        <span>{t.subject}</span>
                        <span className="mx-2 text-[var(--color-accent)]">→ {t.relation} →</span>
                        <span>{t.object}</span>
                      </p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] tabular-nums">
                        {t.source} · {new Date(t.created_at).toLocaleDateString('th-TH')}
                      </p>
                    </div>
                    {(user.role === 'admin' || t.created_by === user.id) && (
                      <button
                        type="button"
                        onClick={() => void handleDeleteTriple(t.id)}
                        aria-label={`ลบความสัมพันธ์ ${t.subject}`}
                        className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl text-[var(--color-text-muted)] hover:bg-[var(--color-danger-bg)] hover:text-[var(--color-danger)]"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      ) : tab === 'workflows' ? (
        <div className="space-y-8">
          {/* Filtered Workflow Groups */}
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {fuzzyGroups.map((grp) => (
              <div
                key={grp.id}
                className="flex flex-col justify-between rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-[var(--color-text)]">{grp.name}</h3>
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-[var(--color-text-secondary)]">
                    {grp.description}
                  </p>
                  <p className="mt-3 text-[11px] text-[var(--color-text-muted)]">
                    {grp.requires_approval ? 'ต้องผ่าน Approval Gate' : 'ทำงานอัตโนมัติได้ทันที'} ·{' '}
                    <span className="tabular-nums">{grp.stages.length} ขั้นตอน</span>
                  </p>
                </div>

                <button
                  type="button"
                  disabled={runningGroupId === grp.id}
                  onClick={() => void handleRunWorkflow(grp.id)}
                  className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" />
                  <span>{runningGroupId === grp.id ? 'กำลังทำงาน...' : 'เริ่มรันเวิร์กโฟลว์'}</span>
                </button>
              </div>
            ))}
          </section>

          {/* Real-time Orchestration Logs Console (/api/v1/workflows/logs) */}
          <WorkflowLogsConsole token={token} />

          {/* Recent Workflow Executions */}
          <section>
            <h3 className="mb-3 text-base font-semibold text-[var(--color-text)]">
              ประวัติการรันเวิร์กโฟลว์ล่าสุด
            </h3>
            <div className="divide-y divide-[var(--color-border)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
              {fuzzyRuns.length === 0 ? (
                <div className="p-6 text-sm text-[var(--color-text-secondary)]">
                  {searchQuery
                    ? `ไม่พบประวัติเวิร์กโฟลว์ที่ตรงกับ "${searchQuery}"`
                    : 'ยังไม่มีการรันเวิร์กโฟลว์ เลือกกลุ่มงานด้านบนเพื่อตรวจสอบสถานะจริงของระบบ'}
                </div>
              ) : (
                fuzzyRuns.map((run) => {
                  let stages: WorkflowStageResult[];
                  try {
                    stages = JSON.parse(run.stages_json) as WorkflowStageResult[];
                  } catch {
                    stages = [];
                  }
                  return (
                    <div key={run.id} className="p-4 sm:p-5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-semibold text-[var(--color-text)]">
                            {run.group_id}
                          </span>
                          {renderStatusLabel(run.status)}
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs text-[var(--color-text-muted)] tabular-nums">
                            {new Date(run.created_at).toLocaleString('th-TH')}
                          </span>
                          {run.status === 'PENDING_APPROVAL' && user.role === 'admin' && (
                            <>
                              <button
                                type="button"
                                disabled={decidingRunId === run.id}
                                onClick={() => void handleWorkflowDecision(run.id, 'approve')}
                                className="inline-flex h-7 items-center gap-1 rounded-lg bg-[var(--color-accent)] px-2.5 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                <span>{decidingRunId === run.id ? 'กำลังดำเนินการ...' : 'อนุมัติและทำต่อ'}</span>
                              </button>
                              <button
                                type="button"
                                disabled={decidingRunId === run.id}
                                onClick={() => void handleWorkflowDecision(run.id, 'reject')}
                                className="inline-flex h-7 items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-[11px] font-medium text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger-bg)] disabled:opacity-50"
                              >
                                <XCircle className="h-3 w-3" />
                                <span>ปฏิเสธ</span>
                              </button>
                            </>
                          )}
                          <CopyButton
                            getText={() => {
                              const lines = [
                                `Workflow: ${run.group_id} [${run.status}]`,
                                `Summary: ${run.summary}`,
                              ];
                              if (stages.length > 0) {
                                lines.push(
                                  serializeTableToTsv(
                                    ['Stage', 'Status', 'Detail'],
                                    stages.map((st) => [st.stage, st.status, st.detail || ''])
                                  )
                                );
                              }
                              return lines.join('\n\n');
                            }}
                            ariaLabel={`คัดลอกผลเวิร์กโฟลว์ ${run.group_id}`}
                            title="คัดลอกรายงานผลการทำงานเวิร์กโฟลว์"
                            size="xs"
                          />
                        </div>
                      </div>
                      <p className="mt-1.5 text-sm text-[var(--color-text-secondary)]">{run.summary}</p>
                      {stages.length > 0 && (
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                          {stages.map((st) => (
                            <div
                              key={st.stage}
                              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-mono text-[11px] text-[var(--color-text)]">
                                  {st.stage}
                                </span>
                                {renderStatusLabel(st.status)}
                              </div>
                              {st.detail && (
                                <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">{st.detail}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Persistent Reasoning Trace Audit Log */}
          <section aria-label="บันทึกการตัดสินใจย้อนหลังของแกนสมอง">
            <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  บันทึกการตัดสินใจย้อนหลัง (Reasoning Trace)
                </h3>
                <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
                  ตรวจสอบเส้นทางแกนสมอง ลำดับสมการ/ตรรกะ หลักฐานกราฟความรู้ และสถานะ Native-Only ย้อนหลังของแต่ละคำตอบ
                </p>
              </div>
              <div className="flex items-center gap-2">
                <select
                  aria-label="กรองสถานะ Reasoning Trace"
                  value={traceStatusFilter}
                  onChange={(e) => setTraceStatusFilter(e.target.value)}
                  className="h-9 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                >
                  <option value="ALL">ทุกสถานะ ({reasoningTraces.length})</option>
                  <option value="VERIFIED">VERIFIED</option>
                  <option value="PLANNED">PLANNED</option>
                  <option value="RUNNING">RUNNING</option>
                  <option value="EXECUTING">EXECUTING</option>
                  <option value="COMPLETED">COMPLETED</option>
                  <option value="NEEDS_CLARIFICATION">NEEDS_CLARIFICATION</option>
                  <option value="UNCERTAIN">UNCERTAIN</option>
                  <option value="NOT_LEARNED">NOT_LEARNED</option>
                  <option value="UNABLE_TO_INFER">UNABLE_TO_INFER</option>
                  <option value="UNKNOWN">UNKNOWN</option>
                  <option value="BLOCKED">BLOCKED</option>
                  <option value="FAILED">FAILED</option>
                  <option value="PENDING_APPROVAL">PENDING_APPROVAL</option>
                </select>
                <button
                  type="button"
                  disabled={refreshingTraces}
                  onClick={() => void handleRefreshTraces()}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-50"
                >
                  <RotateCw className={`h-3.5 w-3.5 ${refreshingTraces ? 'animate-spin' : ''}`} />
                  <span>รีเฟรช</span>
                </button>
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
              {fuzzyTraces.length === 0 ? (
                <div className="p-6 text-sm text-[var(--color-text-secondary)]">
                  {traceStatusFilter !== 'ALL'
                    ? `ไม่พบบันทึกการตัดสินใจที่มีสถานะ ${traceStatusFilter}`
                    : 'ยังไม่มีบันทึกการตัดสินใจในระบบ เมื่อสนทนากับ ZYRQUEN ในเวิร์กสเปซ ระบบจะบันทึก Trace การตัดสินใจไว้ตรวจสอบย้อนหลังที่นี่'}
                </div>
              ) : (
                fuzzyTraces.map((item) => <ReasoningTraceRow key={item.id} item={item} />)
              )}
            </div>
          </section>
        </div>
      ) : (
        <div className="space-y-6">
          <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              สั่งงานภารกิจอัตโนมัติ (DAG Cognitive-Action Loop)
            </h3>
            <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
              ระบบจะแตกงานเป็นกราฟ DAG ตรวจสอบ pre/postconditions และพักรอที่ P5 Approval Gate อัตโนมัติเมื่อต้องสืบค้นเว็บ
            </p>
            <form onSubmit={handleLaunchMission} className="mt-4 flex flex-col gap-2 sm:flex-row">
              <input
                type="text"
                required
                value={newMissionGoal}
                onChange={(e) => setNewMissionGoal(e.target.value)}
                placeholder="ระบุเป้าหมายภารกิจ (เช่น คำนวณ 3x + 7 = 22 หรือ ค้นคว้าเรื่อง SQLite)..."
                aria-label="เป้าหมายภารกิจอัตโนมัติ"
                className="h-11 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
              <button
                type="submit"
                disabled={launchingMission}
                className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
              >
                <Play className="h-4 w-4" />
                <span>{launchingMission ? 'กำลังเริ่มภารกิจ...' : 'เริ่มภารกิจอัตโนมัติ'}</span>
              </button>
            </form>
          </section>

          <div className="grid gap-6 lg:grid-cols-12">
            <section className="divide-y divide-[var(--color-border)] rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] lg:col-span-5">
              <div className="px-5 py-3.5">
                <h3 className="text-sm font-semibold text-[var(--color-text)]">
                  รายการภารกิจถาวร ({missions.length})
                </h3>
              </div>
              {missions.length === 0 ? (
                <p className="p-5 text-sm text-[var(--color-text-secondary)]">ยังไม่มีภารกิจอัตโนมัติในระบบ</p>
              ) : (
                missions.map((m) => {
                  const isSelected = selectedMissionId === m.id;
                  const canResume = !['COMPLETED', 'CANCELLED'].includes(m.status);
                  const canCancel = [
                    'AWAITING_APPROVAL',
                    'EXECUTING',
                    'PLAN_READY',
                    'RECOVERING',
                    'AWAITING_EVIDENCE',
                  ].includes(m.status);
                  return (
                    <div
                      key={m.id}
                      className={`p-4 transition-colors ${
                        isSelected ? 'bg-[var(--color-surface-hover)]' : 'hover:bg-[var(--color-surface-hover)]/60'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => void handleSelectMission(m.id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-center justify-between gap-2">
                          {renderStatusLabel(m.status)}
                          <span className="text-[11px] text-[var(--color-text-muted)] tabular-nums">
                            {new Date(m.created_at).toLocaleString('th-TH')}
                          </span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-sm font-medium text-[var(--color-text)]">
                          {m.goal}
                        </p>
                      </button>
                      {(canResume || canCancel) && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {canResume && (
                            <button
                              type="button"
                              disabled={missionActionId === m.id}
                              onClick={() => void handleMissionAction(m.id, 'resume')}
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-50"
                            >
                              <RotateCw className="h-3 w-3" />
                              <span>ดำเนินต่อ (Resume)</span>
                            </button>
                          )}
                          {canCancel && (
                            <button
                              type="button"
                              disabled={missionActionId === m.id}
                              onClick={() => void handleMissionAction(m.id, 'cancel')}
                              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3 text-xs font-medium text-[var(--color-danger)] hover:opacity-90 disabled:opacity-50"
                            >
                              <XCircle className="h-3 w-3" />
                              <span>ยกเลิกภารกิจ</span>
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </section>

            <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-7">
              {loadingMissionDetail ? (
                <p className="text-sm text-[var(--color-text-secondary)]">กำลังโหลดโครงสร้าง DAG และหลักฐาน...</p>
              ) : !selectedMissionDetail ? (
                <p className="text-sm text-[var(--color-text-secondary)]">
                  เลือกภารกิจทางด้านซ้ายเพื่อดูโหนด DAG, จำนวนรอบ Retry, และหลักฐานจากอินเทอร์เน็ต
                </p>
              ) : (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-3">
                    <div>
                      <p className="text-sm font-semibold text-[var(--color-text)]">
                        {selectedMissionDetail.mission.goal}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-[var(--color-text-muted)]">
                        ID: {selectedMissionDetail.mission.id}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {renderStatusLabel(selectedMissionDetail.mission.status)}
                      <CopyButton
                        getText={() => {
                          const m = selectedMissionDetail.mission;
                          const nodeTable = serializeTableToTsv(
                            ['Task ID', 'Status', 'Attempts', 'Last Error'],
                            selectedMissionDetail.nodes.map((nd) => [
                              nd.task_id,
                              nd.execution_status,
                              nd.attempt_count,
                              nd.last_error || '',
                            ])
                          );
                          const evLines = selectedMissionDetail.evidence.map(
                            (ev) => `- ${ev.provider} [${ev.trust_grade}]: ${ev.source_url}`
                          );
                          return [
                            `Mission: ${m.goal}`,
                            `ID: ${m.id} | Status: ${m.status}`,
                            `DAG Nodes:\n${nodeTable}`,
                            evLines.length > 0 ? `Evidence:\n${evLines.join('\n')}` : '',
                          ]
                            .filter(Boolean)
                            .join('\n\n');
                        }}
                        ariaLabel="คัดลอกรายงานภารกิจ"
                        title="คัดลอกรายงานภารกิจและตาราง DAG Nodes"
                        size="xs"
                      />
                    </div>
                  </div>

                  <div>
                    <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-[var(--color-accent)]">
                      DAG Nodes ({selectedMissionDetail.nodes.length})
                    </h4>
                    {selectedMissionDetail.nodes.length === 0 ? (
                      <p className="text-xs text-[var(--color-text-secondary)]">ไม่มีข้อมูลโหนดย่อยสำหรับภารกิจนี้</p>
                    ) : (
                      <div className="space-y-2">
                        {selectedMissionDetail.nodes.map((nd) => {
                          let parsedTitle = nd.task_id;
                          let deps: string[] = [];
                          try {
                            const obj = JSON.parse(nd.node_json) as { title?: string; dependencies?: string[] };
                            if (obj.title) parsedTitle = obj.title;
                            if (Array.isArray(obj.dependencies)) deps = obj.dependencies;
                          } catch {
                            /* keep task_id */
                          }
                          return (
                            <div
                              key={nd.id}
                              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="font-mono text-xs font-semibold text-[var(--color-text)]">
                                  {nd.task_id}
                                </span>
                                <div className="flex items-center gap-3">
                                  <span className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                                    attempts: {nd.attempt_count}
                                  </span>
                                  {renderStatusLabel(nd.execution_status)}
                                </div>
                              </div>
                              <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{parsedTitle}</p>
                              {deps.length > 0 && (
                                <p className="mt-1 font-mono text-[11px] text-[var(--color-text-muted)]">
                                  deps: {deps.join(', ')}
                                </p>
                              )}
                              {nd.last_error && (
                                <p className="mt-1.5 text-xs text-[var(--color-danger)]">
                                  last_error: {nd.last_error}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div>
                    <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-[var(--color-accent)]">
                      Mission Evidence ({selectedMissionDetail.evidence.length})
                    </h4>
                    {selectedMissionDetail.evidence.length === 0 ? (
                      <p className="text-xs text-[var(--color-text-secondary)]">
                        ยังไม่มีหลักฐานภายนอกที่บันทึกไว้ในภารกิจนี้
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {selectedMissionDetail.evidence.map((ev) => (
                          <div
                            key={ev.id}
                            className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="font-semibold text-[var(--color-text)]">{ev.provider}</span>
                              <span className="font-mono text-[11px] text-[var(--color-accent)]">
                                {ev.trust_grade}
                              </span>
                            </div>
                            <p className="mt-1 flex items-center gap-1 break-all font-mono text-[11px] text-[var(--color-text-secondary)]">
                              <ExternalLink className="h-3 w-3 shrink-0" />
                              <span>{ev.source_url}</span>
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
