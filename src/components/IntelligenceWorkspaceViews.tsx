import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Archive,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  Calculator,
  CheckCircle2,
  ChevronRight,
  Clock,
  Code2,
  Download,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Globe,
  Layers,
  Paperclip,
  PenTool,
  Play,
  Plus,
  RefreshCw,
  RotateCw,
  Save,
  Search,
  Settings,
  ShieldCheck,
  Workflow,
  Wrench,
  X,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import { isMalformedOrEmptyTraceText, sanitizeTraceDisplayText } from '../lib/clipboard';
import { externalToolAdapter, type ToolId } from '../lib/tools';
import type {
  AppScreen,
  AutonomousMissionItem,
  ConversationSummary,
  KnowledgeTriple,
  MissionEvidenceItem,
  MissionNodeItem,
  NativeTrace,
  ReasoningMode,
  ReasoningTraceRecord,
  ToolsOverview,
  User,
  WorkflowGroup,
  WorkflowRun,
  WorkspaceFileItem,
} from '../types';
import { CopyButton } from './CopyButton';
import { ProjectDashboard } from './ProjectDashboard';
import { SafeMessageText, toPlainAssistantCopyText } from './SafeMessageText';

function formatDateThai(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('th-TH', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function downloadTextFile(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  if (typeof document === 'undefined' || typeof URL === 'undefined') return;
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderStatusInline(status: string) {
  switch (status) {
    case 'COMPLETED':
    case 'VERIFIED':
    case 'PASS':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-success)]">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{status}</span>
        </span>
      );
    case 'PLANNED':
    case 'READY':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-accent)]">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{status}</span>
        </span>
      );
    case 'RUNNING':
    case 'EXECUTING':
    case 'PENDING_APPROVAL':
    case 'AWAITING_APPROVAL':
    case 'AWAITING_EVIDENCE':
    case 'NEEDS_CLARIFICATION':
    case 'NOT_LEARNED':
    case 'UNKNOWN':
    case 'UNCERTAIN':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-warning)]">
          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{status}</span>
        </span>
      );
    case 'FAILED':
    case 'REJECTED':
    case 'BLOCKED':
    case 'CANCELLED':
      return (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-[var(--color-danger)]">
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{status}</span>
        </span>
      );
    default:
      return <span className="text-xs font-medium text-[var(--color-text-secondary)]">{status}</span>;
  }
}

/* ============================================================================
 * 1. ProjectsView (โปรเจกต์)
 * ========================================================================== */

interface ProjectsViewProps {
  token: string;
  conversations: ConversationSummary[];
  onOpenConversation: (cid: string) => void;
  onCreateProject: (title: string, initialPrompt?: string) => Promise<void>;
  onDeleteProject: (cid: string) => Promise<void>;
  onNavigate: (screen: AppScreen) => void;
}

export function ProjectsView({
  token,
  conversations,
  onOpenConversation,
  onCreateProject,
  onDeleteProject,
  onNavigate,
}: ProjectsViewProps) {
  const [projectTitle, setProjectTitle] = useState('');
  const [projectGoal, setProjectGoal] = useState('');
  const [saveSpecFile, setSaveSpecFile] = useState(true);
  const [creating, setCreating] = useState(false);
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFileItem[]>([]);
  const [missionsCount, setMissionsCount] = useState(0);
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaceMeta = useCallback(async () => {
    setLoadingMeta(true);
    try {
      const [toolsRes, missionsRes] = await Promise.all([
        apiRequest<ToolsOverview>('/api/developer/tools', { token }).catch(() => null),
        apiRequest<{ missions: AutonomousMissionItem[] }>('/api/autonomous/missions', { token }).catch(
          () => null
        ),
      ]);
      setWorkspaceFiles(toolsRes?.workspace_files || []);
      setMissionsCount(missionsRes?.missions?.length || 0);
    } finally {
      setLoadingMeta(false);
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) void loadWorkspaceMeta();
    });
    return () => {
      active = false;
    };
  }, [loadWorkspaceMeta]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const title = projectTitle.trim();
    const goal = projectGoal.trim();
    if (!title && !goal) return;
    setCreating(true);
    setError(null);
    try {
      const resolvedTitle = title || goal.slice(0, 48);
      if (saveSpecFile && goal) {
        const slug = resolvedTitle
          .toLowerCase()
          .replace(/[^a-z0-9ก-๙_-]+/g, '-')
          .replace(/^-+|-+$/g, '')
          .slice(0, 36);
        const safeFilename = `${slug || 'project'}-brief.md`;
        await apiRequest('/api/developer/workspace-files', {
          method: 'POST',
          token,
          body: {
            filename: safeFilename,
            content: `# ${resolvedTitle}\n\n## เป้าหมายโปรเจกต์\n${goal}\n`,
          },
        }).catch(() => {});
      }
      await onCreateProject(resolvedTitle, goal || undefined);
      setProjectTitle('');
      setProjectGoal('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'สร้างโปรเจกต์ไม่สำเร็จ');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">โปรเจกต์</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            สร้างโปรเจกต์ใหม่ เปิดพื้นที่ทำงานต่อเนื่อง และจัดการไฟล์โครงสร้างงานจริง
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)] tabular-nums">
          <span>{conversations.length} โปรเจกต์</span>
          <span aria-hidden="true">·</span>
          <span>{workspaceFiles.length} ไฟล์งาน</span>
          <span aria-hidden="true">·</span>
          <span>{missionsCount} ภารกิจ</span>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด" />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Create New Project Form */}
        <section className="lg:col-span-5">
          <form
            onSubmit={handleCreate}
            className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6"
          >
            <div className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-[var(--color-accent)]" />
              <h3 className="text-base font-semibold text-[var(--color-text)]">สร้างโปรเจกต์ใหม่</h3>
            </div>

            <div>
              <label htmlFor="new-project-title" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                ชื่อโปรเจกต์
              </label>
              <input
                id="new-project-title"
                type="text"
                value={projectTitle}
                onChange={(e) => setProjectTitle(e.target.value)}
                placeholder="เช่น ระบบวิเคราะห์ยอดขายรายไตรมาส"
                className="mt-1.5 h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="new-project-goal" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                เป้าหมายและขอบเขตงาน (ไม่บังคับ)
              </label>
              <textarea
                id="new-project-goal"
                rows={4}
                value={projectGoal}
                onChange={(e) => setProjectGoal(e.target.value)}
                placeholder="อธิบายสิ่งที่ต้องการสร้าง ปัญหาที่ต้องแก้ หรือผลลัพธ์ที่คาดหวัง..."
                className="mt-1.5 w-full resize-none rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 py-2.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <label className="flex cursor-pointer items-center gap-2 text-xs text-[var(--color-text-secondary)]">
              <input
                type="checkbox"
                checked={saveSpecFile}
                onChange={(e) => setSaveSpecFile(e.target.checked)}
                className="h-4 w-4 rounded border-[var(--color-border)]"
              />
              <span>บันทึกเอกสารขอบเขตโปรเจกต์ (.md) ลงคลังไฟล์อัตโนมัติ</span>
            </label>

            <button
              type="submit"
              disabled={creating || (!projectTitle.trim() && !projectGoal.trim())}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-45"
            >
              <Plus className="h-4 w-4" />
              <span>{creating ? 'กำลังสร้างโปรเจกต์...' : 'สร้างและเปิดโปรเจกต์'}</span>
            </button>
          </form>

          {/* Workspace Files Quick Overview */}
          <div className="mt-6 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">ไฟล์ในพื้นที่ทำงาน</h3>
              <button
                type="button"
                onClick={() => onNavigate('artifacts')}
                className="text-xs font-medium text-[var(--color-accent)] hover:underline"
              >
                เปิดคลังผลงาน
              </button>
            </div>
            {loadingMeta ? (
              <p className="text-xs text-[var(--color-text-secondary)]">กำลังโหลดรายการไฟล์...</p>
            ) : workspaceFiles.length === 0 ? (
              <p className="text-xs text-[var(--color-text-secondary)]">
                ยังไม่มีไฟล์โปรเจกต์ที่บันทึกไว้ สามารถสร้างไฟล์ใหม่ได้จากหน้าสร้างงาน
              </p>
            ) : (
              <div className="divide-y divide-[var(--color-border)]">
                {workspaceFiles.slice(0, 6).map((f) => (
                  <div key={f.name} className="flex items-center justify-between gap-2 py-2.5 text-xs">
                    <span className="truncate font-mono text-[var(--color-text)]">{f.name}</span>
                    <span className="shrink-0 text-[var(--color-text-muted)] tabular-nums">
                      {f.size_bytes} B
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Project Dashboard */}
        <div className="lg:col-span-7">
          <ProjectDashboard
            projects={conversations}
            variant="full"
            loading={loadingMeta}
            onOpenProject={onOpenConversation}
            onDeleteProject={onDeleteProject}
          />
        </div>
      </div>
    </div>
  );
}

/* ============================================================================
 * 2. MyTasksView (งานของฉัน)
 * ========================================================================== */

interface MyTasksViewProps {
  token: string;
  user: User;
  conversations: ConversationSummary[];
  onOpenConversation: (cid: string) => void;
  onNavigate: (screen: AppScreen) => void;
}

export function MyTasksView({
  token,
  conversations,
  onOpenConversation,
  onNavigate,
}: MyTasksViewProps) {
  const [subTab, setSubTab] = useState<'missions' | 'history' | 'workflows'>('missions');
  const [missions, setMissions] = useState<AutonomousMissionItem[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [selectedMissionDetail, setSelectedMissionDetail] = useState<{
    mission: AutonomousMissionItem;
    nodes: MissionNodeItem[];
    evidence: MissionEvidenceItem[];
  } | null>(null);
  const [traces, setTraces] = useState<ReasoningTraceRecord[]>([]);
  const [groups, setGroups] = useState<WorkflowGroup[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [newTaskGoal, setNewTaskGoal] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [actingId, setActingId] = useState<string | null>(null);
  const [runningGroupId, setRunningGroupId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadTasksData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [missionsRes, tracesRes, wfRes] = await Promise.all([
        apiRequest<{ missions: AutonomousMissionItem[] }>('/api/autonomous/missions', { token }),
        apiRequest<{ reasoning_traces: ReasoningTraceRecord[] }>(
          '/api/workflows/reasoning-traces?limit=40',
          { token }
        ),
        apiRequest<{ groups: WorkflowGroup[]; runs: WorkflowRun[] }>('/api/workflows', { token }),
      ]);
      const loadedMissions = missionsRes.missions || [];
      setMissions(loadedMissions);
      setTraces(tracesRes.reasoning_traces || []);
      setGroups(wfRes.groups || []);
      setRuns(wfRes.runs || []);
      if (loadedMissions.length > 0 && !selectedMissionId) {
        const firstId = loadedMissions[0].id;
        setSelectedMissionId(firstId);
        const detail = await apiRequest<{
          mission: AutonomousMissionItem;
          nodes: MissionNodeItem[];
          evidence: MissionEvidenceItem[];
        }>(`/api/autonomous/missions/${firstId}`, { token }).catch(() => null);
        if (detail) setSelectedMissionDetail(detail);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดรายการงานได้');
    } finally {
      setLoading(false);
    }
  }, [selectedMissionId, token]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) void loadTasksData();
    });
    return () => {
      active = false;
    };
  }, [loadTasksData]);

  async function handleSelectMission(missionId: string) {
    setSelectedMissionId(missionId);
    setError(null);
    try {
      const detail = await apiRequest<{
        mission: AutonomousMissionItem;
        nodes: MissionNodeItem[];
        evidence: MissionEvidenceItem[];
      }>(`/api/autonomous/missions/${missionId}`, { token });
      setSelectedMissionDetail(detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'โหลดรายละเอียดงานไม่สำเร็จ');
    }
  }

  async function handleCreateTask(e: React.FormEvent) {
    e.preventDefault();
    const goal = newTaskGoal.trim();
    if (!goal || isMalformedOrEmptyTraceText(goal)) {
      setError('กรุณาระบุเป้าหมายงานที่ชัดเจนและสมบูรณ์ก่อนสั่งดำเนินงาน');
      return;
    }
    setLaunching(true);
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
      setNewTaskGoal('');
      setSelectedMissionId(res.mission.id);
      setSelectedMissionDetail({
        mission: res.mission,
        nodes: res.nodes || [],
        evidence: res.evidence || [],
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'สร้างงานไม่สำเร็จ');
    } finally {
      setLaunching(false);
    }
  }

  async function handleMissionAction(missionId: string, action: 'resume' | 'cancel') {
    setActingId(missionId);
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
        setSelectedMissionDetail({
          mission: res.mission,
          nodes: res.nodes || [],
          evidence: res.evidence || [],
        });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'อัปเดตสถานะงานไม่สำเร็จ');
    } finally {
      setActingId(null);
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
      setError(err instanceof ApiError ? err.message : 'สั่งทำงานเวิร์กโฟลว์ไม่สำเร็จ');
    } finally {
      setRunningGroupId(null);
    }
  }

  const filteredTraces = useMemo(() => {
    const validTraces = traces.filter((t) => {
      const cleanPrompt = sanitizeTraceDisplayText(t.prompt);
      const cleanPreview = sanitizeTraceDisplayText(t.response_preview);
      if (!cleanPrompt && !cleanPreview) return false;
      if (isMalformedOrEmptyTraceText(t.prompt) && t.status === 'UNKNOWN') return false;
      return true;
    });
    const q = searchQuery.trim().toLowerCase();
    if (!q) return validTraces;
    return validTraces.filter(
      (t) =>
        sanitizeTraceDisplayText(t.prompt).toLowerCase().includes(q) ||
        sanitizeTraceDisplayText(t.response_preview || '').toLowerCase().includes(q) ||
        t.status.toLowerCase().includes(q)
    );
  }, [searchQuery, traces]);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">งานของฉัน</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            ติดตามสถานะงานที่กำลังดำเนินการ ประวัติการดำเนินงาน ผลลัพธ์ และหลักฐานตรวจสอบ
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onNavigate('memory')}
            className="flex min-h-[38px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
          >
            <BrainCircuit className="h-3.5 w-3.5" />
            <span>กราฟความรู้ภายใน</span>
          </button>
          <button
            type="button"
            onClick={() => void loadTasksData()}
            className="flex min-h-[38px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)] whitespace-nowrap"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>รีเฟรช</span>
          </button>
        </div>
      </div>

      {/* Segmented View Selector */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1">
          <button
            type="button"
            onClick={() => setSubTab('missions')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              subTab === 'missions'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            ภารกิจและขั้นตอนงาน ({missions.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab('history')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              subTab === 'history'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            ประวัติและผลลัพธ์ ({traces.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab('workflows')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              subTab === 'workflows'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            ระบบงานอัตโนมัติ ({runs.length})
          </button>
        </div>

        <span className="text-xs text-[var(--color-text-secondary)] tabular-nums">
          โปรเจกต์ที่เปิดอยู่ {conversations.length} รายการ
        </span>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด" />
        </div>
      )}

      {subTab === 'missions' && (
        <div className="space-y-6">
          <form
            onSubmit={handleCreateTask}
            className="flex flex-col gap-3 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 sm:flex-row sm:items-center sm:p-5"
          >
            <input
              type="text"
              value={newTaskGoal}
              onChange={(e) => setNewTaskGoal(e.target.value)}
              placeholder="กำหนดเป้าหมายงานใหม่เพื่อวางแผนและดำเนินงานเป็นขั้นตอน..."
              aria-label="เป้าหมายงานใหม่"
              className="h-11 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={launching || !newTaskGoal.trim()}
              className="flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-45 whitespace-nowrap"
            >
              <Play className="h-4 w-4" />
              <span>{launching ? 'กำลังเริ่มงาน...' : 'สั่งดำเนินงาน'}</span>
            </button>
          </form>

          <div className="grid gap-6 lg:grid-cols-12">
            <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] lg:col-span-5">
              {missions.length === 0 ? (
                <div className="p-6 text-sm text-[var(--color-text-secondary)]">
                  ยังไม่มีงานอัตโนมัติที่บันทึกไว้ พิมพ์เป้าหมายด้านบนเพื่อสร้างงานแรก
                </div>
              ) : (
                missions.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => void handleSelectMission(m.id)}
                    className={`flex w-full items-start justify-between gap-3 p-4 text-left transition-colors hover:bg-[var(--color-surface-hover)] ${
                      selectedMissionId === m.id ? 'bg-[var(--color-surface-hover)]' : ''
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm font-medium text-[var(--color-text)]">{m.goal}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)] tabular-nums">
                        {renderStatusInline(m.status)}
                        <span aria-hidden="true">·</span>
                        <span>{formatDateThai(m.updated_at)}</span>
                      </div>
                    </div>
                    <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
                  </button>
                ))
              )}
            </div>

            <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-7">
              {!selectedMissionDetail ? (
                <p className="text-sm text-[var(--color-text-secondary)]">
                  เลือกรายการงานด้านซ้ายเพื่อดูขั้นตอนการทำงาน หลักฐานตรวจสอบ และผลลัพธ์
                </p>
              ) : (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--color-border)] pb-4">
                    <div>
                      <h3 className="text-base font-semibold text-[var(--color-text)]">
                        {selectedMissionDetail.mission.goal}
                      </h3>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)] tabular-nums">
                        {renderStatusInline(selectedMissionDetail.mission.status)}
                        <span aria-hidden="true">·</span>
                        <span>{selectedMissionDetail.nodes.length} ขั้นตอน</span>
                        <span aria-hidden="true">·</span>
                        <span>{selectedMissionDetail.evidence.length} หลักฐาน</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <CopyButton
                        getText={() =>
                          selectedMissionDetail.mission.report_markdown ||
                          `${selectedMissionDetail.mission.goal}\nStatus: ${selectedMissionDetail.mission.status}`
                        }
                        ariaLabel="คัดลอกรายงานงาน"
                        size="xs"
                      />
                      {['PENDING_APPROVAL', 'AWAITING_EVIDENCE', 'RECOVERING', 'FAILED'].includes(
                        selectedMissionDetail.mission.status
                      ) && (
                        <button
                          type="button"
                          disabled={actingId === selectedMissionDetail.mission.id}
                          onClick={() =>
                            void handleMissionAction(selectedMissionDetail.mission.id, 'resume')
                          }
                          className="flex min-h-[34px] items-center gap-1 rounded-lg bg-[var(--color-primary)] px-3 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                        >
                          <RotateCw className="h-3.5 w-3.5" />
                          <span>ทำต่อ</span>
                        </button>
                      )}
                      {!['COMPLETED', 'VERIFIED', 'CANCELLED'].includes(
                        selectedMissionDetail.mission.status
                      ) && (
                        <button
                          type="button"
                          disabled={actingId === selectedMissionDetail.mission.id}
                          onClick={() =>
                            void handleMissionAction(selectedMissionDetail.mission.id, 'cancel')
                          }
                          className="flex min-h-[34px] items-center gap-1 rounded-lg border border-[var(--color-danger)]/40 px-3 text-xs font-medium text-[var(--color-danger)] hover:bg-[var(--color-danger-bg)]"
                        >
                          <X className="h-3.5 w-3.5" />
                          <span>ยกเลิก</span>
                        </button>
                      )}
                    </div>
                  </div>

                  {selectedMissionDetail.nodes.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        สถานะขั้นตอนย่อย (DAG Nodes)
                      </p>
                      <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]">
                        {selectedMissionDetail.nodes.map((node) => {
                          let title = node.task_id;
                          try {
                            const parsed = JSON.parse(node.node_json) as {
                              title?: string;
                              stage?: string;
                            };
                            title = parsed.title || parsed.stage || node.task_id;
                          } catch {
                            // keep task_id
                          }
                          return (
                            <div
                              key={node.id}
                              className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-xs"
                            >
                              <span className="truncate font-medium text-[var(--color-text)]">{title}</span>
                              {renderStatusInline(node.execution_status)}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {selectedMissionDetail.mission.report_markdown && (
                    <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                      <p className="mb-2 text-xs font-semibold text-[var(--color-accent)]">รายงานผลลัพธ์</p>
                      <SafeMessageText content={selectedMissionDetail.mission.report_markdown} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {subTab === 'history' && (
        <div className="space-y-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="ค้นหาประวัติงาน คำสั่ง หรือผลลัพธ์..."
              aria-label="ค้นหาประวัติงาน"
              className="h-11 w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] pl-10 pr-4 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
          </div>

          <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
            {filteredTraces.length === 0 ? (
              <p className="p-6 text-sm text-[var(--color-text-secondary)]">
                ยังไม่มีประวัติการดำเนินงานที่ตรงกับคำค้นหา
              </p>
            ) : (
              filteredTraces.map((tr) => {
                let parsed: NativeTrace;
                try {
                  parsed = JSON.parse(tr.trace_json) as NativeTrace;
                } catch {
                  parsed = {};
                }
                const cleanPrompt = sanitizeTraceDisplayText(tr.prompt) || 'คำสั่งไม่สมบูรณ์ (ถูกคัดกรอง)';
                const cleanPreview = sanitizeTraceDisplayText(tr.response_preview);
                return (
                  <div key={tr.id} className="space-y-2 p-4 sm:p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        {renderStatusInline(tr.status)}
                        <span aria-hidden="true">·</span>
                        <span className="font-mono text-[var(--color-text-secondary)] tabular-nums">
                          {tr.latency_ms} ms
                        </span>
                        <span aria-hidden="true">·</span>
                        <span className="text-[var(--color-text-muted)] tabular-nums">
                          {formatDateThai(tr.created_at)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <CopyButton
                          getText={() =>
                            [
                              `งาน: ${cleanPrompt}`,
                              `สถานะ: ${tr.status}`,
                              `ผลลัพธ์:\n${toPlainAssistantCopyText(cleanPreview)}`,
                            ].join('\n\n')
                          }
                          ariaLabel="คัดลอกผลลัพธ์งาน"
                          size="xs"
                        />
                        {tr.conversation_id && (
                          <button
                            type="button"
                            onClick={() => onOpenConversation(tr.conversation_id!)}
                            className="min-h-[32px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)]"
                          >
                            เปิดงาน
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="text-sm font-semibold text-[var(--color-text)]">{cleanPrompt}</p>
                    {cleanPreview && (
                      <p className="line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-[var(--color-text-secondary)]">
                        {toPlainAssistantCopyText(cleanPreview)}
                      </p>
                    )}
                    {parsed.bottleneck_task && !isMalformedOrEmptyTraceText(parsed.bottleneck_task.task) && (
                      <p className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                        ขั้นตอนที่ใช้เวลานานที่สุด: {parsed.bottleneck_task.task} ({parsed.bottleneck_task.duration_ms} ms)
                      </p>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {subTab === 'workflows' && (
        <div className="grid gap-6 lg:grid-cols-12">
          <div className="space-y-3 lg:col-span-7">
            {groups.map((grp) => (
              <div
                key={grp.id}
                className="flex flex-col gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Workflow className="h-4 w-4 text-[var(--color-accent)]" />
                    <p className="text-sm font-semibold text-[var(--color-text)]">{grp.name}</p>
                    {grp.requires_approval && (
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--color-warning)]">
                        <ShieldCheck className="h-3 w-3" />
                        ต้องรออนุมัติ
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{grp.description}</p>
                </div>
                <button
                  type="button"
                  disabled={runningGroupId === grp.id}
                  onClick={() => void handleRunWorkflow(grp.id)}
                  className="flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
                >
                  <Play className="h-3.5 w-3.5" />
                  <span>{runningGroupId === grp.id ? 'กำลังทำงาน...' : 'เริ่มรันงาน'}</span>
                </button>
              </div>
            ))}
          </div>

          <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--color-text)]">ประวัติการรันล่าสุด</h3>
              <button
                type="button"
                onClick={() => onNavigate('settings')}
                className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
              >
                <Settings className="h-3.5 w-3.5" />
                <span>Approval Gate</span>
              </button>
            </div>
            <div className="divide-y divide-[var(--color-border)]">
              {runs.length === 0 ? (
                <p className="py-4 text-xs text-[var(--color-text-secondary)]">ยังไม่มีประวัติการรันเวิร์กโฟลว์</p>
              ) : (
                runs.slice(0, 10).map((run) => (
                  <div key={run.id} className="space-y-1 py-3">
                    <div className="flex items-center justify-between gap-2">
                      {renderStatusInline(run.status)}
                      <CopyButton
                        getText={() => `${run.group_id} (${run.status})\n${run.summary}`}
                        size="xs"
                        ariaLabel="คัดลอกสรุปเวิร์กโฟลว์"
                      />
                    </div>
                    <p className="text-xs font-medium text-[var(--color-text)]">{run.summary}</p>
                    <p className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                      {run.group_id} · {formatDateThai(run.created_at)}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================================================================
 * 3. CreateArtifactView (สร้างงาน)
 * ========================================================================== */

export type CreatePresetKind = 'software' | 'document' | 'data' | 'direct_file';

interface CreateArtifactViewProps {
  token: string;
  initialKind?: CreatePresetKind;
  onStartTask: (prompt: string, mode: ReasoningMode, attachment?: string) => Promise<void>;
  onNavigate: (screen: AppScreen) => void;
}

export function CreateArtifactView({
  token,
  initialKind = 'software',
  onStartTask,
  onNavigate,
}: CreateArtifactViewProps) {
  const [kind, setKind] = useState<CreatePresetKind>(initialKind);
  const [prevInitialKind, setPrevInitialKind] = useState<CreatePresetKind>(initialKind);
  const [title, setTitle] = useState('');
  const [spec, setSpec] = useState('');
  const [attachment, setAttachment] = useState<{ name: string; content: string } | null>(null);
  const [filename, setFilename] = useState('artifact-output.md');
  const [fileBody, setFileBody] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  if (prevInitialKind !== initialKind) {
    setPrevInitialKind(initialKind);
    setKind(initialKind);
  }

  function handleAttach(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setAttachment({
        name: file.name,
        content: typeof reader.result === 'string' ? reader.result.slice(0, 8000) : '',
      });
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  async function handleExecuteCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStatusMsg(null);
    setSubmitting(true);
    try {
      if (kind === 'direct_file') {
        const cleanName = filename.trim();
        if (!cleanName || !fileBody.trim()) {
          setError('กรุณาระบุชื่อไฟล์และเนื้อหาที่ต้องการบันทึก');
          return;
        }
        await apiRequest('/api/developer/workspace-files', {
          method: 'POST',
          token,
          body: { filename: cleanName, content: fileBody },
        });
        setStatusMsg(`บันทึกไฟล์ "${cleanName}" ลงในคลังผลงานเรียบร้อยแล้ว`);
        return;
      }

      const cleanTitle = title.trim();
      const cleanSpec = spec.trim();
      if (!cleanTitle && !cleanSpec && !attachment) {
        setError('กรุณาระบุหัวข้อหรือรายละเอียดของงานที่ต้องการสร้าง');
        return;
      }
      if (
        (cleanTitle && isMalformedOrEmptyTraceText(cleanTitle)) ||
        (cleanSpec && isMalformedOrEmptyTraceText(cleanSpec))
      ) {
        setError('หัวข้อหรือรายละเอียดไม่สมบูรณ์หรือมีอักขระผิดรูปแบบ กรุณาระบุเป้าหมายให้ชัดเจนก่อนสร้างงาน');
        return;
      }

      const prefix =
        kind === 'software'
          ? 'วางแผนและพัฒนาซอร์สโค้ด'
          : kind === 'document'
            ? 'สร้างเอกสารและรายงานเชิงโครงสร้าง'
            : 'ออกแบบและสร้างโครงสร้างข้อมูล/ตาราง';
      const prompt = [
        `${prefix}${cleanTitle ? `: ${cleanTitle}` : ''}`,
        cleanSpec ? `รายละเอียดและข้อกำหนด:\n${cleanSpec}` : '',
        attachment ? `อ้างอิงไฟล์แนบ: ${attachment.name}` : '',
      ]
        .filter(Boolean)
        .join('\n\n');

      await onStartTask(prompt, kind === 'software' ? 'plan' : 'auto', attachment?.content);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถสร้างงานได้');
    } finally {
      setSubmitting(false);
    }
  }

  const KIND_OPTIONS: Array<{
    id: CreatePresetKind;
    label: string;
    desc: string;
    icon: React.ComponentType<{ className?: string }>;
  }> = [
    { id: 'software', label: 'ซอร์สโค้ดและระบบ', desc: 'ออกแบบโครงสร้าง วางแผน และสร้างโค้ด', icon: Code2 },
    { id: 'document', label: 'เอกสารและรายงาน', desc: 'ร่างสเปก สรุปรายงาน และคู่มือทำงาน', icon: FileText },
    { id: 'data', label: 'ข้อมูลและตาราง', desc: 'จัดโครงสร้าง JSON/CSV และชุดข้อมูล', icon: FileSpreadsheet },
    { id: 'direct_file', label: 'เขียนไฟล์ลงคลังตรง', desc: 'สร้างและบันทึกไฟล์จริงเข้า workspace', icon: FileCode2 },
  ];

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">สร้างงาน</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            เลือกประเภทผลลัพธ์ที่ต้องการสร้าง กำหนดขอบเขต หรือเขียนไฟล์ลงพื้นที่ทำงานโดยตรง
          </p>
        </div>
        <button
          type="button"
          onClick={() => onNavigate('artifacts')}
          className="flex min-h-[38px] items-center gap-2 self-start rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3.5 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] whitespace-nowrap"
        >
          <Archive className="h-4 w-4" />
          <span>เปิดคลังผลงาน</span>
        </button>
      </div>

      {/* Creation Type Selector */}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {KIND_OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = kind === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => {
                setKind(opt.id);
                setError(null);
                setStatusMsg(null);
              }}
              className={`flex flex-col items-start gap-2 rounded-2xl border p-4 text-left transition-colors ${
                active
                  ? 'border-[var(--color-accent)] bg-[var(--color-surface-hover)]'
                  : 'border-[var(--color-border)] bg-[var(--color-surface-raised)] hover:border-[var(--color-primary)]'
              }`}
            >
              <Icon
                className={`h-4 w-4 ${active ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-secondary)]'}`}
              />
              <div>
                <p className="text-sm font-semibold text-[var(--color-text)]">{opt.label}</p>
                <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">{opt.desc}</p>
              </div>
            </button>
          );
        })}
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด" />
        </div>
      )}

      {statusMsg && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-success)]/40 bg-[var(--color-success-bg)] px-4 py-3 text-sm text-[var(--color-success)]">
          <span>{statusMsg}</span>
          <button
            type="button"
            onClick={() => onNavigate('artifacts')}
            className="text-xs font-semibold underline"
          >
            ดูไฟล์ในคลังผลงาน
          </button>
        </div>
      )}

      <form
        onSubmit={handleExecuteCreate}
        className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-7"
      >
        {kind === 'direct_file' ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  ตัวแก้ไขไฟล์ในพื้นที่ทำงาน
                </h3>
                <p className="text-xs text-[var(--color-text-secondary)]">
                  รองรับไฟล์ข้อความ โค้ด Markdown JSON และ CSV เพื่อบันทึกเข้าคลังผลงานทันที
                </p>
              </div>
              {fileBody.trim() && (
                <div className="flex items-center gap-2">
                  <CopyButton getText={() => fileBody} size="xs" ariaLabel="คัดลอกเนื้อหาไฟล์" />
                  <button
                    type="button"
                    onClick={() => downloadTextFile(filename.trim() || 'artifact.txt', fileBody)}
                    className="flex min-h-[32px] items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>ดาวน์โหลด</span>
                  </button>
                </div>
              )}
            </div>

            <div>
              <label htmlFor="create-file-name" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                ชื่อไฟล์ (เช่น report.md, schema.json, module.py)
              </label>
              <input
                id="create-file-name"
                type="text"
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                className="mt-1.5 h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 font-mono text-sm text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="create-file-body" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                เนื้อหาไฟล์
              </label>
              <textarea
                id="create-file-body"
                rows={10}
                value={fileBody}
                onChange={(e) => setFileBody(e.target.value)}
                placeholder="พิมพ์โค้ด เอกสาร Markdown หรือข้อมูล CSV/JSON ที่ต้องการบันทึก..."
                className="mt-1.5 w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-xs leading-relaxed text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-6 text-sm font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              <span>{submitting ? 'กำลังบันทึก...' : 'บันทึกไฟล์ลงคลังผลงาน'}</span>
            </button>
          </>
        ) : (
          <>
            <div>
              <label htmlFor="create-title" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                ชื่อชิ้นงาน / หัวข้อหลัก
              </label>
              <input
                id="create-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={
                  kind === 'software'
                    ? 'เช่น บริการตรวจสอบความถูกต้องของชุดข้อมูล CSV'
                    : kind === 'document'
                      ? 'เช่น รายงานสรุปผลการประเมินเสถียรภาพระบบ'
                      : 'เช่น ตารางเปรียบเทียบตัวชี้วัดรายสัปดาห์'
                }
                className="mt-1.5 h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="create-spec" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                ข้อกำหนดและรายละเอียดที่ต้องการ
              </label>
              <textarea
                id="create-spec"
                rows={6}
                value={spec}
                onChange={(e) => setSpec(e.target.value)}
                placeholder="อธิบายโครงสร้าง ข้อจำกัด รูปแบบผลลัพธ์ และเงื่อนไขการตรวจสอบ..."
                className="mt-1.5 w-full resize-none rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".txt,.md,.json,.csv,.py,.ts,.tsx,.js"
                  onChange={handleAttach}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="flex min-h-[40px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                >
                  <Paperclip className="h-4 w-4" />
                  <span>แนบไฟล์อ้างอิง</span>
                </button>
                {attachment && (
                  <span className="inline-flex items-center gap-1.5 text-xs text-[var(--color-accent)]">
                    <span>{attachment.name}</span>
                    <button
                      type="button"
                      onClick={() => setAttachment(null)}
                      aria-label="ลบไฟล์แนบ"
                      className="text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                )}
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-6 text-sm font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
              >
                <PenTool className="h-4 w-4" />
                <span>{submitting ? 'กำลังเริ่มสร้างงาน...' : 'เริ่มสร้างงาน'}</span>
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

/* ============================================================================
 * 4. AnalysisView (วิเคราะห์)
 * ========================================================================== */

interface AnalysisViewProps {
  token: string;
  user: User;
  onStartTask: (prompt: string, mode: ReasoningMode, attachment?: string) => Promise<void>;
  onNavigate: (screen: AppScreen) => void;
}

export function AnalysisView({ token, user, onStartTask, onNavigate }: AnalysisViewProps) {
  const [activeTool, setActiveTool] = useState<'data' | 'math' | 'knowledge'>('data');
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFileItem[]>([]);
  const [selectedFile, setSelectedFile] = useState('');
  const [fileQuestion, setFileQuestion] = useState('');
  const [uploadedFile, setUploadedFile] = useState<{ name: string; content: string } | null>(null);
  const [fileInspectionOutput, setFileInspectionOutput] = useState<string | null>(null);
  const [inspectingFile, setInspectingFile] = useState(false);

  const [mathExpr, setMathExpr] = useState('');
  const [mathResult, setMathResult] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);

  const [triples, setTriples] = useState<KnowledgeTriple[]>([]);
  const [kgSearch, setKgSearch] = useState('');
  const [webToolId, setWebToolId] = useState<ToolId>('web_search');
  const [webToolParam, setWebToolParam] = useState('');
  const [webToolOutput, setWebToolOutput] = useState<string | null>(null);
  const [runningWebTool, setRunningWebTool] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(async () => {
      const [toolsRes, kgRes] = await Promise.all([
        apiRequest<ToolsOverview>('/api/developer/tools', { token }).catch(() => null),
        apiRequest<{ triples: KnowledgeTriple[] }>('/api/knowledge', { token }).catch(() => null),
      ]);
      if (!active) return;
      setWorkspaceFiles(toolsRes?.workspace_files || []);
      setTriples(kgRes?.triples || []);
    });
    return () => {
      active = false;
    };
  }, [token]);

  function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setUploadedFile({
        name: file.name,
        content: typeof reader.result === 'string' ? reader.result.slice(0, 8000) : '',
      });
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  async function handleAnalyzeAttachmentOrFile(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (uploadedFile) {
      const prompt =
        fileQuestion.trim() || `วิเคราะห์ข้อมูลและสรุปประเด็นสำคัญจากไฟล์ ${uploadedFile.name}`;
      await onStartTask(prompt, 'auto', uploadedFile.content);
      return;
    }
    if (!selectedFile) {
      setError('กรุณาอัปโหลดไฟล์หรือเลือกไฟล์จากพื้นที่ทำงานก่อนเริ่มวิเคราะห์');
      return;
    }
    setInspectingFile(true);
    try {
      const res = await apiRequest<{
        ok: boolean;
        status: string;
        output?: { content?: string; preview?: string };
        analysis?: { summary?: string };
        error?: string;
      }>('/api/developer/tools/workspace_file_read/invoke', {
        method: 'POST',
        token,
        body: { action: 'read', filename: selectedFile },
      });
      if (!res.ok) {
        setError(res.error || 'ไม่สามารถอ่านไฟล์เพื่อวิเคราะห์ได้');
        return;
      }
      const text = res.output?.content || res.output?.preview || '';
      if (fileQuestion.trim() && text) {
        await onStartTask(`${fileQuestion.trim()} (${selectedFile})`, 'auto', text);
      } else {
        setFileInspectionOutput(text || res.analysis?.summary || 'อ่านไฟล์สำเร็จ (ไม่มีเนื้อหา)');
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'วิเคราะห์ไฟล์ไม่สำเร็จ');
    } finally {
      setInspectingFile(false);
    }
  }

  async function handleRunCalc(e: React.FormEvent) {
    e.preventDefault();
    const expr = mathExpr.trim();
    if (!expr) return;
    setCalculating(true);
    setError(null);
    try {
      const res = await externalToolAdapter.run('calc_ast', { expression: expr }, token, {
        userRole: user.role,
      });
      if (!res.ok) {
        setError(res.error || 'คำนวณไม่สำเร็จ');
        return;
      }
      setMathResult(
        res.analysis?.summary ||
          res.invocation?.analysis_summary ||
          res.invocation?.output_json ||
          JSON.stringify(res.invocation || {}, null, 2)
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'คำนวณเชิงสัญลักษณ์ไม่สำเร็จ');
    } finally {
      setCalculating(false);
    }
  }

  async function handleRunGovernedLookup(e: React.FormEvent) {
    e.preventDefault();
    if (!webToolParam.trim()) return;
    setRunningWebTool(true);
    setError(null);
    try {
      const payload =
        webToolId === 'doc_fetch' ? { url: webToolParam.trim() } : { query: webToolParam.trim() };
      const res = await externalToolAdapter.run(webToolId, payload, token, {
        userRole: user.role,
      });
      if (!res.ok) {
        setError(res.error || 'คำขอไม่ผ่านนโยบายเครื่องมือ');
        return;
      }
      setWebToolOutput(
        res.analysis?.summary ||
          res.invocation?.analysis_summary ||
          `สถานะคำขอ: ${res.status} (หากรออนุมัติ สามารถอนุมัติได้ในหน้าตั้งค่าผู้ดูแลระบบ)`
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เรียกเครื่องมือสืบค้นไม่สำเร็จ');
    } finally {
      setRunningWebTool(false);
    }
  }

  const filteredTriples = useMemo(() => {
    const q = kgSearch.trim().toLowerCase();
    if (!q) return triples;
    return triples.filter((t) =>
      `${t.subject} ${t.relation} ${t.object} ${t.source}`.toLowerCase().includes(q)
    );
  }, [kgSearch, triples]);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">วิเคราะห์</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            เครื่องมือวิเคราะห์ข้อมูล ไฟล์งาน สมการเชิงสัญลักษณ์ และการตรวจสอบข้อเท็จจริงจริงจากระบบ
          </p>
        </div>

        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1">
          <button
            type="button"
            onClick={() => setActiveTool('data')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              activeTool === 'data'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            วิเคราะห์ไฟล์และข้อมูล
          </button>
          <button
            type="button"
            onClick={() => setActiveTool('math')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              activeTool === 'math'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            คำนวณและแก้สมการ
          </button>
          <button
            type="button"
            onClick={() => setActiveTool('knowledge')}
            className={`min-h-[38px] rounded-lg px-3.5 text-xs font-medium transition-colors whitespace-nowrap ${
              activeTool === 'knowledge'
                ? 'bg-[var(--color-primary)] text-white'
                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
            }`}
          >
            ตรวจสอบฐานความรู้ ({triples.length})
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด" />
        </div>
      )}

      {activeTool === 'data' && (
        <div className="space-y-6">
          <form
            onSubmit={handleAnalyzeAttachmentOrFile}
            className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6"
          >
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-[var(--color-accent)]" />
              <h3 className="text-base font-semibold text-[var(--color-text)]">
                วิเคราะห์ไฟล์ CSV / JSON / ซอร์สโค้ด / เอกสาร
              </h3>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-1.5 text-xs font-medium text-[var(--color-text-secondary)]">
                  อัปโหลดไฟล์ใหม่เพื่อวิเคราะห์
                </p>
                <input
                  ref={uploadRef}
                  type="file"
                  accept=".csv,.json,.txt,.md,.py,.ts,.tsx,.js"
                  onChange={handleUpload}
                  className="hidden"
                />
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => uploadRef.current?.click()}
                    className="flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
                  >
                    <Paperclip className="h-4 w-4 text-[var(--color-accent)]" />
                    <span>{uploadedFile ? uploadedFile.name : 'เลือกไฟล์จากเครื่อง...'}</span>
                  </button>
                  {uploadedFile && (
                    <button
                      type="button"
                      onClick={() => setUploadedFile(null)}
                      aria-label="ล้างไฟล์ที่อัปโหลด"
                      className="flex h-10 w-10 items-center justify-center rounded-xl text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>

              <div>
                <label
                  htmlFor="analysis-workspace-file"
                  className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  หรือเลือกไฟล์ที่มีอยู่ในพื้นที่ทำงาน
                </label>
                <select
                  id="analysis-workspace-file"
                  value={selectedFile}
                  onChange={(e) => setSelectedFile(e.target.value)}
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                >
                  <option value="">-- เลือกไฟล์ใน workspace ({workspaceFiles.length}) --</option>
                  {workspaceFiles.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name} ({f.size_bytes} B)
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label
                htmlFor="analysis-question"
                className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
              >
                คำถามหรือประเด็นที่ต้องการวิเคราะห์
              </label>
              <input
                id="analysis-question"
                type="text"
                value={fileQuestion}
                onChange={(e) => setFileQuestion(e.target.value)}
                placeholder="เช่น วิเคราะห์ค่าผิดปกติ สรุปสถิติ หรือตรวจสอบโครงสร้างไฟล์นี้"
                className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={inspectingFile}
              className="flex h-11 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
            >
              <BarChart3 className="h-4 w-4" />
              <span>{inspectingFile ? 'กำลังตรวจสอบไฟล์...' : 'เริ่มวิเคราะห์ข้อมูล'}</span>
            </button>
          </form>

          {fileInspectionOutput && (
            <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-[var(--color-accent)]">
                  เนื้อหาและผลตรวจไฟล์: {selectedFile}
                </h4>
                <CopyButton getText={() => fileInspectionOutput} size="xs" ariaLabel="คัดลอกผลตรวจไฟล์" />
              </div>
              <pre className="max-h-80 overflow-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-xs text-[var(--color-text)]">
                {fileInspectionOutput}
              </pre>
            </div>
          )}
        </div>
      )}

      {activeTool === 'math' && (
        <div className="space-y-5 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
          <div className="flex items-center gap-2">
            <Calculator className="h-4 w-4 text-[var(--color-accent)]" />
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              คำนวณเชิงสัญลักษณ์ แก้สมการ และสถิติ
            </h3>
          </div>
          <p className="text-xs text-[var(--color-text-secondary)]">
            ประมวลผลผ่านตัวคำนวณเชิงกำหนด (Deterministic AST / Linear &amp; Quadratic Solver) เพื่อป้องกันการคำนวณผิดพลาด
          </p>

          <form onSubmit={handleRunCalc} className="flex flex-col gap-3 sm:flex-row">
            <input
              type="text"
              value={mathExpr}
              onChange={(e) => setMathExpr(e.target.value)}
              placeholder="เช่น (2^12 - 96) / 16 หรือ แก้สมการ: 3x + 7 = 22"
              aria-label="นิพจน์หรือสมการที่ต้องการคำนวณ"
              className="h-11 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 font-mono text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={calculating || !mathExpr.trim()}
              className="flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-45"
            >
              <Calculator className="h-4 w-4" />
              <span>{calculating ? 'กำลังคำนวณ...' : 'คำนวณผลลัพธ์'}</span>
            </button>
          </form>

          <div className="flex flex-wrap gap-2">
            {[
              '(2^12 - 96) / 16',
              'แก้สมการ: 3x + 7 = 22',
              'สถิติ: 12, 18, 22, 27, 31',
            ].map((sample) => (
              <button
                key={sample}
                type="button"
                onClick={() => setMathExpr(sample)}
                className="min-h-[34px] rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)]"
              >
                {sample}
              </button>
            ))}
          </div>

          {mathResult && (
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-[var(--color-success)]">ผลลัพธ์ที่ยืนยันแล้ว</span>
                <CopyButton getText={() => mathResult} size="xs" ariaLabel="คัดลอกผลคำนวณ" />
              </div>
              <SafeMessageText content={mathResult} />
            </div>
          )}
        </div>
      )}

      {activeTool === 'knowledge' && (
        <div className="grid gap-6 lg:grid-cols-12">
          <div className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-7">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-semibold text-[var(--color-text)]">
                ข้อเท็จจริงในกราฟความรู้ ({filteredTriples.length})
              </h3>
              <button
                type="button"
                onClick={() => onNavigate('memory')}
                className="text-xs font-medium text-[var(--color-accent)] hover:underline"
              >
                จัดการฐานความรู้เต็มรูปแบบ
              </button>
            </div>
            <input
              type="search"
              value={kgSearch}
              onChange={(e) => setKgSearch(e.target.value)}
              placeholder="ค้นหาข้อเท็จจริงหรือความสัมพันธ์..."
              aria-label="ค้นหาข้อเท็จจริง"
              className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            <div className="divide-y divide-[var(--color-border)]">
              {filteredTriples.length === 0 ? (
                <p className="py-4 text-xs text-[var(--color-text-secondary)]">
                  ยังไม่มีข้อมูลในกราฟความรู้ที่ตรงกับคำค้นหา
                </p>
              ) : (
                filteredTriples.slice(0, 12).map((t) => (
                  <div key={t.id} className="flex items-center justify-between gap-3 py-2.5 text-xs">
                    <span className="text-[var(--color-text)]">
                      {t.subject} → <span className="text-[var(--color-accent)]">{t.relation}</span> →{' '}
                      {t.object}
                    </span>
                    <span className="shrink-0 text-[var(--color-text-muted)]">{t.source}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-5">
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-[var(--color-accent)]" />
              <h3 className="text-base font-semibold text-[var(--color-text)]">
                สืบค้นเอกสาร/แหล่งภายนอก (ภายใต้ Gate)
              </h3>
            </div>
            <form onSubmit={handleRunGovernedLookup} className="space-y-3">
              <select
                value={webToolId}
                onChange={(e) => setWebToolId(e.target.value as ToolId)}
                aria-label="เลือกเครื่องมือสืบค้น"
                className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
              >
                <option value="web_search">web_search (สืบค้นเว็บสาธารณะ)</option>
                <option value="doc_fetch">doc_fetch (อ่านเอกสาร HTTPS)</option>
              </select>
              <input
                type="text"
                value={webToolParam}
                onChange={(e) => setWebToolParam(e.target.value)}
                placeholder={webToolId === 'doc_fetch' ? 'https://en.wikipedia.org/wiki/SQLite' : 'คำค้นหา...'}
                className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)]"
              />
              <button
                type="submit"
                disabled={runningWebTool || !webToolParam.trim()}
                className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-45"
              >
                <Wrench className="h-3.5 w-3.5" />
                <span>{runningWebTool ? 'กำลังตรวจสอบสิทธิ์และเรียกใช้...' : 'ส่งคำขอสืบค้น'}</span>
              </button>
            </form>
            {webToolOutput && (
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-text)]">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="font-semibold text-[var(--color-accent)]">ผลคำขอเครื่องมือ</span>
                  <CopyButton getText={() => webToolOutput} size="xs" ariaLabel="คัดลอกผลคำขอ" />
                </div>
                <p>{webToolOutput}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================================================================
 * 5. ArtifactsView (คลังผลงาน)
 * ========================================================================== */

interface ArtifactsViewProps {
  token: string;
  onOpenConversation: (cid: string) => void;
  onNavigate: (screen: AppScreen) => void;
}

type ArtifactSelection =
  | { kind: 'file'; title: string; subtitle: string; content: string; filename: string }
  | { kind: 'mission'; title: string; subtitle: string; content: string; filename: string }
  | {
      kind: 'output';
      title: string;
      subtitle: string;
      content: string;
      filename: string;
      conversationId: string | null;
    };

export function ArtifactsView({ token, onOpenConversation, onNavigate }: ArtifactsViewProps) {
  const [filter, setFilter] = useState<'all' | 'files' | 'reports' | 'outputs'>('all');
  const [search, setSearch] = useState('');
  const [files, setFiles] = useState<WorkspaceFileItem[]>([]);
  const [missions, setMissions] = useState<AutonomousMissionItem[]>([]);
  const [traces, setTraces] = useState<ReasoningTraceRecord[]>([]);
  const [selected, setSelected] = useState<ArtifactSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadArtifacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [toolsRes, missionsRes, tracesRes] = await Promise.all([
        apiRequest<ToolsOverview>('/api/developer/tools', { token }).catch(() => null),
        apiRequest<{ missions: AutonomousMissionItem[] }>('/api/autonomous/missions', { token }).catch(
          () => null
        ),
        apiRequest<{ reasoning_traces: ReasoningTraceRecord[] }>(
          '/api/workflows/reasoning-traces?limit=30',
          { token }
        ).catch(() => null),
      ]);
      setFiles(toolsRes?.workspace_files || []);
      setMissions((missionsRes?.missions || []).filter((m) => Boolean(m.report_markdown?.trim())));
      setTraces(
        (tracesRes?.reasoning_traces || []).filter((t) => {
          const cleanPreview = sanitizeTraceDisplayText(t.response_preview);
          const cleanPrompt = sanitizeTraceDisplayText(t.prompt);
          if (!cleanPreview || !cleanPrompt) return false;
          if (t.status === 'NEEDS_CLARIFICATION' || t.status === 'UNKNOWN') return false;
          return !isMalformedOrEmptyTraceText(t.prompt);
        })
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดคลังผลงานได้');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    let active = true;
    Promise.resolve().then(() => {
      if (active) void loadArtifacts();
    });
    return () => {
      active = false;
    };
  }, [loadArtifacts]);

  async function handleOpenFile(file: WorkspaceFileItem) {
    setLoadingContent(true);
    setError(null);
    try {
      const res = await apiRequest<{
        ok: boolean;
        output?: { content?: string; preview?: string };
        error?: string;
      }>('/api/developer/tools/workspace_file_read/invoke', {
        method: 'POST',
        token,
        body: { action: 'read', filename: file.name },
      });
      const content = res.output?.content || res.output?.preview || res.error || '(ไฟล์ว่าง)';
      setSelected({
        kind: 'file',
        title: file.name,
        subtitle: `${file.size_bytes} bytes · ${formatDateThai(file.modified_at)}`,
        content,
        filename: file.name,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'เปิดอ่านไฟล์ไม่สำเร็จ');
    } finally {
      setLoadingContent(false);
    }
  }

  const q = search.trim().toLowerCase();
  const visibleFiles =
    filter === 'all' || filter === 'files'
      ? files.filter((f) => !q || f.name.toLowerCase().includes(q))
      : [];
  const visibleMissions =
    filter === 'all' || filter === 'reports'
      ? missions.filter(
          (m) =>
            !q ||
            m.goal.toLowerCase().includes(q) ||
            m.report_markdown.toLowerCase().includes(q)
        )
      : [];
  const visibleTraces =
    filter === 'all' || filter === 'outputs'
      ? traces.filter((t) => {
          const cleanPrompt = sanitizeTraceDisplayText(t.prompt);
          const cleanPreview = sanitizeTraceDisplayText(t.response_preview);
          return (
            !q ||
            cleanPrompt.toLowerCase().includes(q) ||
            cleanPreview.toLowerCase().includes(q)
          );
        })
      : [];

  const totalCount = files.length + missions.length + traces.length;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-[var(--color-text)]">คลังผลงาน</h2>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            เปิดดู คัดลอก และดาวน์โหลดไฟล์งาน รายงานภารกิจ และผลลัพธ์จริงทั้งหมดที่สร้างขึ้น
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onNavigate('create')}
            className="flex min-h-[38px] items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] whitespace-nowrap"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>สร้างไฟล์ใหม่</span>
          </button>
          <button
            type="button"
            onClick={() => void loadArtifacts()}
            className="flex min-h-[38px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>รีเฟรช</span>
          </button>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1">
          {(
            [
              { id: 'all', label: `ทั้งหมด (${totalCount})` },
              { id: 'files', label: `ไฟล์งาน (${files.length})` },
              { id: 'reports', label: `รายงานภารกิจ (${missions.length})` },
              { id: 'outputs', label: `ผลลัพธ์งาน (${traces.length})` },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setFilter(item.id)}
              className={`min-h-[36px] rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap ${
                filter === item.id
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ค้นหาในคลังผลงาน..."
            aria-label="ค้นหาในคลังผลงาน"
            className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] pl-9 pr-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
          />
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span>{error}</span>
          <CopyButton getText={() => error} size="xs" ariaLabel="คัดลอกข้อผิดพลาด" />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Artifact List */}
        <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] lg:col-span-5">
          {visibleFiles.length === 0 && visibleMissions.length === 0 && visibleTraces.length === 0 ? (
            <div className="p-8 text-center">
              <p className="text-sm text-[var(--color-text-secondary)]">
                {totalCount === 0
                  ? 'คลังผลงานยังว่างอยู่ เริ่มสร้างเอกสาร โค้ด หรือสั่งงานเพื่อบันทึกผลลัพธ์แรก'
                  : 'ไม่พบผลงานที่ตรงกับเงื่อนไขการค้นหา'}
              </p>
            </div>
          ) : (
            <>
              {visibleFiles.map((f) => (
                <button
                  key={`file-${f.name}`}
                  type="button"
                  onClick={() => void handleOpenFile(f)}
                  className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-[var(--color-surface-hover)]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <FileCode2 className="h-4 w-4 shrink-0 text-[var(--color-accent)]" />
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs font-semibold text-[var(--color-text)]">
                        {f.name}
                      </p>
                      <p className="mt-0.5 text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                        ไฟล์งาน · {f.size_bytes} B · {formatDateThai(f.modified_at)}
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
                </button>
              ))}

              {visibleMissions.map((m) => (
                <button
                  key={`mission-${m.id}`}
                  type="button"
                  onClick={() =>
                    setSelected({
                      kind: 'mission',
                      title: m.goal,
                      subtitle: `รายงานภารกิจ · ${m.status} · ${formatDateThai(m.updated_at)}`,
                      content: m.report_markdown,
                      filename: `mission-${m.id.slice(0, 8)}.md`,
                    })
                  }
                  className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-[var(--color-surface-hover)]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <Layers className="h-4 w-4 shrink-0 text-[var(--zyrquen-violet)]" />
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-[var(--color-text)]">{m.goal}</p>
                      <p className="mt-0.5 text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                        รายงานภารกิจ · {m.status} · {formatDateThai(m.updated_at)}
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
                </button>
              ))}

              {visibleTraces.map((tr) => {
                const cleanPrompt = sanitizeTraceDisplayText(tr.prompt) || 'ผลลัพธ์งาน';
                const cleanPreview = sanitizeTraceDisplayText(tr.response_preview);
                return (
                  <button
                    key={`trace-${tr.id}`}
                    type="button"
                    onClick={() =>
                      setSelected({
                        kind: 'output',
                        title: cleanPrompt,
                        subtitle: `ผลลัพธ์งาน · ${tr.status} · ${formatDateThai(tr.created_at)}`,
                        content: toPlainAssistantCopyText(cleanPreview),
                        filename: `output-${tr.id.slice(0, 8)}.md`,
                        conversationId: tr.conversation_id,
                      })
                    }
                    className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-[var(--color-surface-hover)]"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <FileText className="h-4 w-4 shrink-0 text-[var(--color-primary)]" />
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-[var(--color-text)]">{cleanPrompt}</p>
                        <p className="mt-0.5 text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                          ผลลัพธ์งาน · {tr.status} · {formatDateThai(tr.created_at)}
                        </p>
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
                  </button>
                );
              })}
            </>
          )}
        </div>

        {/* Artifact Preview & Export */}
        <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6 lg:col-span-7">
          {loadingContent ? (
            <p className="text-sm text-[var(--color-text-secondary)]">กำลังเปิดอ่านเนื้อหาผลงาน...</p>
          ) : !selected ? (
            <div className="flex min-h-[260px] flex-col items-center justify-center text-center">
              <Archive className="h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-3 text-sm font-medium text-[var(--color-text)]">
                เลือกผลงานจากรายการด้านซ้ายเพื่อตรวจสอบและส่งออก
              </p>
              <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                รองรับการคัดลอกข้อความและการดาวน์โหลดเป็นไฟล์
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--color-border)] pb-4">
                <div className="min-w-0 flex-1">
                  <h3 className="break-words text-base font-semibold text-[var(--color-text)]">
                    {selected.title}
                  </h3>
                  <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] tabular-nums">
                    {selected.subtitle}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <CopyButton
                    getText={() => selected.content}
                    ariaLabel="คัดลอกเนื้อหาผลงาน"
                    size="xs"
                  />
                  <button
                    type="button"
                    onClick={() => downloadTextFile(selected.filename, selected.content)}
                    className="flex min-h-[32px] items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>ดาวน์โหลด</span>
                  </button>
                  {selected.kind === 'output' && selected.conversationId && (
                    <button
                      type="button"
                      onClick={() => onOpenConversation(selected.conversationId!)}
                      className="flex min-h-[32px] items-center gap-1 rounded-lg bg-[var(--color-primary)] px-3 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                    >
                      <span>ทำงานต่อ</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>

              {selected.kind === 'file' ? (
                <pre className="max-h-[55dvh] overflow-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-xs leading-relaxed text-[var(--color-text)]">
                  {selected.content}
                </pre>
              ) : (
                <div className="max-h-[55dvh] overflow-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                  <SafeMessageText content={selected.content} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
