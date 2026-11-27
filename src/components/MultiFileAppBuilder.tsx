import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  FileCode2,
  FolderGit2,
  GitCompare,
  History,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  ShieldCheck,
  Trash2,
  Wrench,
  XCircle,
} from 'lucide-react';
import { CopyButton } from './CopyButton';

interface WorkspaceSummary {
  workspace: string;
  file_count: number;
  files: string[];
  snapshot_count: number;
  last_snapshot_id: string | null;
  last_verified_snapshot_id: string | null;
  updated_at: string | null;
}

interface SnapshotSummary {
  snapshot_id: string;
  index: number;
  created_at: string;
  action: string;
  label: string;
  verified: boolean;
  file_count: number;
  tests_run: number;
}

interface BuildStage {
  stage: string;
  status: string;
  detail?: string;
  root_cause?: string;
  repairable?: boolean;
  tests_run?: number;
  snapshot_id?: string;
}

interface BuildOutput {
  workspace: string;
  blueprint?: string;
  verified: boolean;
  build_passed: boolean;
  lint_passed: boolean;
  tests_passed: boolean;
  tests_run: number;
  files: string[];
  file_count?: number;
  changed_files?: string[];
  diffs?: Record<string, string>;
  repair_rounds_used?: number;
  rolled_back?: boolean;
  snapshot_id?: string | null;
  typescript_compile_status?: string;
  build_evidence?: {
    command?: string;
    executed?: boolean;
    passed?: boolean;
    returncode?: number | null;
    stderr?: string;
    stdout?: string;
    duration_ms?: number;
  };
  lint_evidence?: {
    passed?: boolean;
    files_checked?: number;
    issue_count?: number;
    issues?: Array<{ file?: string; rule?: string; detail?: string }>;
  };
  test_evidence?: {
    ok?: boolean;
    status?: string;
    tests_run?: number;
    returncode?: number | null;
    stdout?: string;
    stderr?: string;
  };
  stages?: BuildStage[];
  duration_ms?: number;
}

interface AppBuilderResponse {
  ok: boolean;
  status?: string;
  error?: string | null;
  summary?: string;
  output?: Record<string, unknown>;
}

interface MultiFileAppBuilderProps {
  token: string;
}

async function callAppBuilderApi(
  path: string,
  token: string,
  options: { method?: 'GET' | 'POST'; body?: Record<string, unknown> } = {}
): Promise<{ statusCode: number; data: AppBuilderResponse }> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  if (token && token !== '__cookie__') {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(path, {
    method: options.method || 'GET',
    headers,
    credentials: 'include',
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const data = (await res.json().catch(() => ({
    ok: false,
    error: `HTTP ${res.status}`,
  }))) as AppBuilderResponse;
  return { statusCode: res.status, data };
}

function renderPassFailBadge(passed: boolean | undefined, label: string, extra?: string) {
  return (
    <div
      className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${
        passed
          ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
          : 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
      }`}
    >
      <span className="inline-flex items-center gap-1.5 font-medium">
        {passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
        <span>{label}</span>
      </span>
      <span className="font-mono text-[11px] font-semibold tabular-nums">
        {passed ? 'PASS' : 'FAILED'}
        {extra ? ` (${extra})` : ''}
      </span>
    </div>
  );
}

export function MultiFileAppBuilder({ token }: MultiFileAppBuilderProps) {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceName, setWorkspaceName] = useState('my_native_app');
  const [newWorkspaceInput, setNewWorkspaceInput] = useState('');
  const [loadingWorkspaces, setLoadingWorkspaces] = useState(true);

  const [authorMode, setAuthorMode] = useState<'blueprint' | 'custom_files'>('blueprint');
  const [blueprint, setBlueprint] = useState<'auto' | 'python_cli_app' | 'python_service_app' | 'python_data_app'>('auto');
  const [goal, setGoal] = useState('Build task workflow manager CLI with real unit tests');
  const [appName, setAppName] = useState('task_manager');
  const [editMode, setEditMode] = useState<'upsert' | 'replace'>('upsert');
  const [autoRepair, setAutoRepair] = useState(true);
  const [maxRepairRounds, setMaxRepairRounds] = useState(2);
  const [rollbackOnFailure, setRollbackOnFailure] = useState(true);

  // Multi-file custom editor state
  const [workspaceFiles, setWorkspaceFiles] = useState<string[]>([]);
  const [draftFiles, setDraftFiles] = useState<Record<string, string>>({});
  const [deleteQueue, setDeleteQueue] = useState<string[]>([]);
  const [activeFilePath, setActiveFilePath] = useState<string>('');
  const [newFilePath, setNewFilePath] = useState('');
  const [loadingFile, setLoadingFile] = useState(false);

  // History, Diff, and Build/Verify output
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [selectedDiffSnap, setSelectedDiffSnap] = useState<string>('');
  const [diffResult, setDiffResult] = useState<{
    compared: string;
    changed_files: string[];
    diffs: Record<string, string>;
  } | null>(null);
  const [buildOutput, setBuildOutput] = useState<BuildOutput | null>(null);
  const [lastSummary, setLastSummary] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<'build' | 'verify' | 'snapshot' | 'rollback' | 'diff' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadWorkspaceDetail = useCallback(
    async (targetWs: string) => {
      const clean = targetWs.trim();
      if (!clean || !token) return;
      try {
        const { data } = await callAppBuilderApi('/api/app-builder/history', token, {
          method: 'POST',
          body: { workspace: clean, action: 'list' },
        });
        if (data.ok && data.output) {
          const out = data.output as {
            current_files?: string[];
            snapshots?: SnapshotSummary[];
          };
          const files = Array.isArray(out.current_files) ? out.current_files : [];
          const snaps = Array.isArray(out.snapshots) ? out.snapshots : [];
          setWorkspaceFiles(files);
          setSnapshots([...snaps].reverse());
          if (files.length > 0 && !files.includes(activeFilePath)) {
            setActiveFilePath(files[0]);
          }
          if (snaps.length > 0) {
            setSelectedDiffSnap(snaps[snaps.length - 1].snapshot_id);
          } else {
            setSelectedDiffSnap('');
            setDiffResult(null);
          }
        }
      } catch {
        // Non-fatal while browsing workspaces
      }
    },
    [token, activeFilePath]
  );

  const loadWorkspaces = useCallback(async () => {
    if (!token) {
      setLoadingWorkspaces(false);
      return;
    }
    setLoadingWorkspaces(true);
    try {
      const { statusCode, data } = await callAppBuilderApi('/api/app-builder/workspaces', token);
      if (statusCode === 401) {
        setError('กรุณาเข้าสู่ระบบเพื่อใช้งาน Multi-file Persistent App Builder');
        return;
      }
      if (data.ok && data.output) {
        const list = Array.isArray((data.output as { workspaces?: WorkspaceSummary[] }).workspaces)
          ? ((data.output as { workspaces?: WorkspaceSummary[] }).workspaces as WorkspaceSummary[])
          : [];
        setWorkspaces(list);
        if (list.length > 0 && !list.some((w) => w.workspace === workspaceName)) {
          setWorkspaceName(list[0].workspace);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ไม่สามารถโหลดรายการ workspace ได้');
    } finally {
      setLoadingWorkspaces(false);
    }
  }, [token, workspaceName]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void loadWorkspaces();
    });
    return () => { cancelled = true; };
  }, [loadWorkspaces]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled && workspaceName) void loadWorkspaceDetail(workspaceName);
    });
    return () => { cancelled = true; };
  }, [workspaceName, loadWorkspaceDetail]);

  const handleOpenWorkspaceFile = async (relPath: string) => {
    setActiveFilePath(relPath);
    if (Object.prototype.hasOwnProperty.call(draftFiles, relPath)) {
      return;
    }
    setLoadingFile(true);
    setError(null);
    try {
      const { data } = await callAppBuilderApi('/api/app-builder/history', token, {
        method: 'POST',
        body: { workspace: workspaceName, action: 'read_file', file_path: relPath },
      });
      if (data.ok && data.output && typeof data.output.content === 'string') {
        const content = data.output.content;
        setDraftFiles((prev) => ({ ...prev, [relPath]: content }));
      } else {
        setError(data.error || `ไม่สามารถเปิดไฟล์ ${relPath} ได้`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `ไม่สามารถอ่านไฟล์ ${relPath} ได้`);
    } finally {
      setLoadingFile(false);
    }
  };

  const handleAddCustomFile = () => {
    const clean = newFilePath.trim().replace(/^\/+/, '');
    if (!clean) return;
    if (clean.includes('..') || clean.includes('\\')) {
      setError('เส้นทางไฟล์ต้องเป็น relative path ภายใน workspace เท่านั้น');
      return;
    }
    setError(null);
    setWorkspaceFiles((prev) => (prev.includes(clean) ? prev : [...prev, clean].sort()));
    setDeleteQueue((prev) => prev.filter((p) => p !== clean));
    setDraftFiles((prev) => ({
      ...prev,
      [clean]:
        prev[clean] ??
        (clean.endsWith('.py')
          ? `"""Module ${clean}."""\n\n\ndef run() -> dict[str, bool]:\n    return {"ok": True}\n`
          : clean.endsWith('.json')
            ? '{\n  "name": "zyrquen_app"\n}\n'
            : `# ${clean}\n`),
    }));
    setActiveFilePath(clean);
    setNewFilePath('');
  };

  const handleToggleDeleteFile = (relPath: string) => {
    setDeleteQueue((prev) =>
      prev.includes(relPath) ? prev.filter((p) => p !== relPath) : [...prev, relPath]
    );
  };

  const handleCreateOrSwitchWorkspace = () => {
    const clean = newWorkspaceInput.trim();
    if (!clean) return;
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(clean) || clean.includes('..')) {
      setError('ชื่อ workspace ใช้ได้เฉพาะ A-Z, a-z, 0-9, ., _, - (ไม่เกิน 64 ตัวอักษร)');
      return;
    }
    setError(null);
    setWorkspaceName(clean);
    setDraftFiles({});
    setDeleteQueue([]);
    setBuildOutput(null);
    setDiffResult(null);
    setNewWorkspaceInput('');
  };

  const handleBuildAndVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspaceName.trim()) {
      setError('กรุณาระบุชื่อ workspace');
      return;
    }
    setRunningAction('build');
    setError(null);
    setLastSummary(null);

    try {
      const payload: Record<string, unknown> = {
        workspace: workspaceName.trim(),
        goal: goal.trim() || 'Multi-file app build and verification',
        appName: appName.trim() || workspaceName.trim(),
        blueprint: authorMode === 'blueprint' ? blueprint : 'auto',
        mode: editMode,
        autoRepair,
        maxRepairRounds,
        rollbackOnFailure,
      };

      if (authorMode === 'custom_files') {
        const filesToSend: Record<string, string> = {};
        for (const [path, content] of Object.entries(draftFiles)) {
          if (!deleteQueue.includes(path)) {
            filesToSend[path] = content;
          }
        }
        if (Object.keys(filesToSend).length === 0 && deleteQueue.length === 0) {
          setError('กรุณาแก้ไขหรือเพิ่มไฟล์อย่างน้อย 1 ไฟล์ก่อนสั่ง Build');
          setRunningAction(null);
          return;
        }
        if (Object.keys(filesToSend).length > 0) {
          payload.files = filesToSend;
        }
        if (deleteQueue.length > 0) {
          payload.deleteFiles = deleteQueue;
        }
      }

      const { data } = await callAppBuilderApi('/api/app-builder/build', token, {
        method: 'POST',
        body: payload,
      });

      if (data.output) {
        setBuildOutput(data.output as unknown as BuildOutput);
      }
      if (data.summary) {
        setLastSummary(data.summary);
      }
      if (!data.ok) {
        setError(data.error || 'Build, Lint หรือ Unit Tests ใน Sandbox ไม่ผ่าน');
      } else {
        setDeleteQueue([]);
      }
      await Promise.all([loadWorkspaces(), loadWorkspaceDetail(workspaceName.trim())]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'เรียกใช้ App Builder ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  };

  const handleVerifyOnly = async () => {
    setRunningAction('verify');
    setError(null);
    try {
      const { data } = await callAppBuilderApi('/api/app-builder/verify', token, {
        method: 'POST',
        body: { workspace: workspaceName.trim(), runLint: true, runTests: true },
      });
      if (data.output) {
        setBuildOutput(data.output as unknown as BuildOutput);
      }
      if (data.summary) setLastSummary(data.summary);
      if (!data.ok) {
        setError(data.error || 'การตรวจสอบ Build/Lint/Test ใน Sandbox ไม่ผ่าน');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ตรวจสอบ Sandbox ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  };

  const handleManualSnapshot = async () => {
    setRunningAction('snapshot');
    setError(null);
    try {
      const { data } = await callAppBuilderApi('/api/app-builder/history', token, {
        method: 'POST',
        body: {
          workspace: workspaceName.trim(),
          action: 'snapshot',
          label: goal.trim().slice(0, 80) || 'Manual checkpoint',
        },
      });
      if (!data.ok) {
        setError(data.error || 'บันทึก Snapshot ไม่สำเร็จ');
      } else {
        setLastSummary(data.summary || 'บันทึก Snapshot ลงพื้นที่ถาวรแล้ว');
        await loadWorkspaceDetail(workspaceName.trim());
        await loadWorkspaces();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'บันทึก Snapshot ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  };

  const handleViewDiff = async (snapId?: string) => {
    const targetSnap = snapId || selectedDiffSnap;
    if (!targetSnap) return;
    setRunningAction('diff');
    setError(null);
    try {
      const { data } = await callAppBuilderApi('/api/app-builder/history', token, {
        method: 'POST',
        body: { workspace: workspaceName.trim(), action: 'diff', snapshot_id: targetSnap },
      });
      if (!data.ok || !data.output) {
        setError(data.error || 'ไม่สามารถสร้าง Unified Diff ได้');
      } else {
        const out = data.output as {
          compared?: string;
          changed_files?: string[];
          diffs?: Record<string, string>;
        };
        setDiffResult({
          compared: out.compared || `${targetSnap} -> working_tree`,
          changed_files: Array.isArray(out.changed_files) ? out.changed_files : [],
          diffs: out.diffs && typeof out.diffs === 'object' ? out.diffs : {},
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'โหลด Diff ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  };

  const handleRollback = async (snapId: string) => {
    setRunningAction('rollback');
    setError(null);
    try {
      const { data } = await callAppBuilderApi('/api/app-builder/history', token, {
        method: 'POST',
        body: { workspace: workspaceName.trim(), action: 'rollback', snapshot_id: snapId },
      });
      if (!data.ok) {
        setError(data.error || 'ย้อนกลับ Snapshot ไม่สำเร็จ');
      } else {
        setLastSummary(data.summary || `ย้อนกลับไปยัง ${snapId} สำเร็จ`);
        setDraftFiles({});
        setDeleteQueue([]);
        if (data.output && typeof data.output.diffs === 'object') {
          setDiffResult({
            compared: `rollback -> ${snapId}`,
            changed_files: Object.keys(data.output.diffs as Record<string, string>),
            diffs: data.output.diffs as Record<string, string>,
          });
        }
        await Promise.all([loadWorkspaces(), loadWorkspaceDetail(workspaceName.trim())]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rollback ไม่สำเร็จ');
    } finally {
      setRunningAction(null);
    }
  };

  const allManagedFiles = Array.from(
    new Set([...workspaceFiles, ...Object.keys(draftFiles)])
  ).sort();

  return (
    <div className="space-y-6">
      {/* Persistent Workspace Selector */}
      <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <FolderGit2 className="h-4 w-4 text-[var(--color-accent)]" />
              <h3 className="text-sm font-semibold text-[var(--color-text)]">
                Persistent Sandbox Workspace
              </h3>
              <span className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                {workspaces.length} workspaces
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label="เลือก Persistent Workspace"
                value={workspaceName}
                onChange={(e) => {
                  setWorkspaceName(e.target.value);
                  setDraftFiles({});
                  setDeleteQueue([]);
                  setDiffResult(null);
                }}
                className="h-10 min-w-[220px] flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              >
                {!workspaces.some((w) => w.workspace === workspaceName) && (
                  <option value={workspaceName}>{workspaceName} (ใหม่ / ยังไม่บันทึก)</option>
                )}
                {workspaces.map((ws) => (
                  <option key={ws.workspace} value={ws.workspace}>
                    {ws.workspace} · {ws.file_count} ไฟล์ · {ws.snapshot_count} snapshots
                  </option>
                ))}
              </select>

              <button
                type="button"
                disabled={loadingWorkspaces}
                onClick={() => void loadWorkspaces()}
                className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] disabled:opacity-50"
              >
                <RotateCw className={`h-3.5 w-3.5 ${loadingWorkspaces ? 'animate-spin' : ''}`} />
                <span>รีเฟรช</span>
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              aria-label="ชื่อ Workspace ใหม่"
              value={newWorkspaceInput}
              onChange={(e) => setNewWorkspaceInput(e.target.value)}
              placeholder="ตั้งชื่อ workspace ใหม่..."
              className="h-10 w-48 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            <button
              type="button"
              onClick={handleCreateOrSwitchWorkspace}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] whitespace-nowrap"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>สลับ/สร้างใหม่</span>
            </button>
          </div>
        </div>
      </section>

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-xs text-[var(--color-danger)]"
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="break-words">{error}</span>
          </div>
          <CopyButton getText={() => error} ariaLabel="คัดลอกข้อผิดพลาด App Builder" size="xs" />
        </div>
      )}

      {lastSummary && !error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--color-success)]/40 bg-[var(--color-success-bg)] px-4 py-3 text-xs font-medium text-[var(--color-success)]">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{lastSummary}</span>
        </div>
      )}

      {/* Multi-file Authoring + Real Build/Repair Form */}
      <form
        onSubmit={handleBuildAndVerify}
        className="space-y-5 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] pb-4">
          <div
            role="group"
            aria-label="โหมดสร้างและแก้ไขไฟล์"
            className="inline-flex rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
          >
            <button
              type="button"
              aria-pressed={authorMode === 'blueprint'}
              onClick={() => setAuthorMode('blueprint')}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap ${
                authorMode === 'blueprint'
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              สังเคราะห์โครงสร้างหลายไฟล์ (Blueprint)
            </button>
            <button
              type="button"
              aria-pressed={authorMode === 'custom_files'}
              onClick={() => setAuthorMode('custom_files')}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap ${
                authorMode === 'custom_files'
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              แก้ไข/เพิ่มหลายไฟล์โดยตรง ({allManagedFiles.length})
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-text-secondary)]">
            <label className="inline-flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={autoRepair}
                onChange={(e) => setAutoRepair(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-primary)]"
              />
              <span>Auto-Repair Loop</span>
            </label>
            {autoRepair && (
              <label className="inline-flex items-center gap-1.5">
                <span>สูงสุด</span>
                <select
                  aria-label="จำนวนรอบ Repair Loop สูงสุด"
                  value={maxRepairRounds}
                  onChange={(e) => setMaxRepairRounds(Number(e.target.value))}
                  className="h-7 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 font-mono text-xs text-[var(--color-text)]"
                >
                  <option value={1}>1 รอบ</option>
                  <option value={2}>2 รอบ</option>
                  <option value={3}>3 รอบ</option>
                </select>
              </label>
            )}
            <label className="inline-flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={rollbackOnFailure}
                onChange={(e) => setRollbackOnFailure(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--color-primary)]"
              />
              <span>Rollback เมื่อเทสต์ไม่ผ่าน</span>
            </label>
          </div>
        </div>

        {authorMode === 'blueprint' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="ab-app-name" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                ชื่อแพ็กเกจ (App Name)
              </label>
              <input
                id="ab-app-name"
                type="text"
                value={appName}
                onChange={(e) => setAppName(e.target.value)}
                className="mt-1.5 h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="ab-blueprint" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                สถาปัตยกรรมต้นแบบ (Blueprint)
              </label>
              <select
                id="ab-blueprint"
                value={blueprint}
                onChange={(e) =>
                  setBlueprint(e.target.value as 'auto' | 'python_cli_app' | 'python_service_app' | 'python_data_app')
                }
                className="mt-1.5 h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
              >
                <option value="auto">Auto (เลือกตามเป้าหมาย)</option>
                <option value="python_cli_app">Python CLI App (models/engine/cli/main/tests)</option>
                <option value="python_service_app">Python Service App (router/schema/state/tests)</option>
                <option value="python_data_app">Python Data Pipeline (etl/stats/sha256/tests)</option>
              </select>
            </div>

            <div className="md:col-span-2">
              <label htmlFor="ab-goal" className="block text-xs font-medium text-[var(--color-text-secondary)]">
                เป้าหมายของโปรเจกต์ / รายการเปลี่ยนแปลง
              </label>
              <textarea
                id="ab-goal"
                rows={3}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="อธิบายฟังก์ชัน โครงสร้างโมดูล และเงื่อนไขที่ต้องทดสอบ..."
                className="mt-1.5 w-full rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  aria-label="เส้นทางไฟล์ใหม่"
                  value={newFilePath}
                  onChange={(e) => setNewFilePath(e.target.value)}
                  placeholder="เช่น pkg/validator.py หรือ tests/test_extra.py"
                  className="h-9 w-72 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
                <button
                  type="button"
                  onClick={handleAddCustomFile}
                  className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)]"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>เพิ่มไฟล์</span>
                </button>
              </div>

              <label className="inline-flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                <span>โหมดเขียนทับ:</span>
                <select
                  aria-label="โหมดการแก้ไขไฟล์"
                  value={editMode}
                  onChange={(e) => setEditMode(e.target.value as 'upsert' | 'replace')}
                  className="h-8 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 text-xs text-[var(--color-text)]"
                >
                  <option value="upsert">upsert (อัปเดตเฉพาะไฟล์ที่แก้)</option>
                  <option value="replace">replace (แทนที่ไฟล์ทั้งหมด)</option>
                </select>
              </label>
            </div>

            <div className="grid gap-4 lg:grid-cols-12">
              <div className="space-y-1.5 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 lg:col-span-4">
                <p className="text-[11px] font-semibold text-[var(--color-text-muted)]">
                  ไฟล์ใน Workspace ({allManagedFiles.length})
                </p>
                {allManagedFiles.length === 0 ? (
                  <p className="py-3 text-xs text-[var(--color-text-secondary)]">
                    ยังไม่มีไฟล์ใน workspace นี้ เพิ่มไฟล์ใหม่ด้านบนหรือสร้างจาก Blueprint
                  </p>
                ) : (
                  <div className="max-h-64 space-y-1 overflow-y-auto">
                    {allManagedFiles.map((rel) => {
                      const isActive = activeFilePath === rel;
                      const markedDelete = deleteQueue.includes(rel);
                      const isEdited = Object.prototype.hasOwnProperty.call(draftFiles, rel);
                      return (
                        <div
                          key={rel}
                          className={`flex items-center justify-between gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
                            isActive
                              ? 'border-[var(--color-accent)] bg-[var(--color-surface-hover)]'
                              : 'border-transparent hover:bg-[var(--color-surface-raised)]'
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => void handleOpenWorkspaceFile(rel)}
                            className={`flex min-w-0 flex-1 items-center gap-1.5 text-left font-mono text-[11px] ${
                              markedDelete
                                ? 'line-through text-[var(--color-danger)]'
                                : 'text-[var(--color-text)]'
                            }`}
                          >
                            <FileCode2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-accent)]" />
                            <span className="truncate">{rel}</span>
                            {isEdited && !markedDelete && (
                              <span className="text-[10px] text-[var(--color-warning)]">*</span>
                            )}
                          </button>
                          <button
                            type="button"
                            aria-label={`สลับการลบไฟล์ ${rel}`}
                            onClick={() => handleToggleDeleteFile(rel)}
                            className={`rounded p-1 ${
                              markedDelete
                                ? 'text-[var(--color-danger)]'
                                : 'text-[var(--color-text-muted)] hover:text-[var(--color-danger)]'
                            }`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 lg:col-span-8">
                {activeFilePath ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <code className="font-mono text-xs font-medium text-[var(--color-accent)]">
                        ไฟล์ที่เปิด: {activeFilePath}
                      </code>
                      {loadingFile && (
                        <span className="text-[11px] text-[var(--color-text-muted)]">กำลังโหลดเนื้อหา...</span>
                      )}
                    </div>
                    <textarea
                      aria-label={`แก้ไขเนื้อหา ${activeFilePath}`}
                      rows={12}
                      value={draftFiles[activeFilePath] ?? ''}
                      onChange={(e) =>
                        setDraftFiles((prev) => ({
                          ...prev,
                          [activeFilePath]: e.target.value,
                        }))
                      }
                      placeholder="เลือกหรือเพิ่มไฟล์เพื่อแก้ไขซอร์สโค้ดหลายไฟล์พร้อมกัน..."
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 font-mono text-xs leading-relaxed text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    />
                  </div>
                ) : (
                  <p className="py-10 text-center text-xs text-[var(--color-text-secondary)]">
                    เลือกไฟล์ทางด้านซ้ายหรือเพิ่มไฟล์ใหม่เพื่อดูและแก้ไขโค้ด
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={runningAction !== null}
              onClick={() => void handleVerifyOnly()}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] disabled:opacity-50 whitespace-nowrap"
            >
              <ShieldCheck className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              <span>{runningAction === 'verify' ? 'กำลังทดสอบ...' : 'รัน Build/Lint/Test ซ้ำใน Sandbox'}</span>
            </button>

            <button
              type="button"
              disabled={runningAction !== null || workspaceFiles.length === 0}
              onClick={() => void handleManualSnapshot()}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] disabled:opacity-50 whitespace-nowrap"
            >
              <History className="h-3.5 w-3.5" />
              <span>{runningAction === 'snapshot' ? 'กำลังบันทึก...' : 'บันทึก Snapshot'}</span>
            </button>
          </div>

          <button
            type="submit"
            disabled={runningAction !== null}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-xs font-semibold text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
          >
            <Play className="h-3.5 w-3.5" />
            <span>{runningAction === 'build' ? 'กำลัง Build + Lint + Test...' : 'สร้าง / อัปเดตและตรวจสอบจริง'}</span>
          </button>
        </div>
      </form>

      {/* Real Build / Lint / Test / Repair Loop Evidence */}
      {buildOutput && (
        <section
          aria-label="หลักฐานการตรวจสอบ Sandbox จริง"
          className="space-y-4 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <Wrench className="h-4 w-4 text-[var(--color-accent)]" />
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                หลักฐานการตรวจสอบจริง ({buildOutput.workspace})
              </h4>
              <span
                className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold ${
                  buildOutput.verified
                    ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                    : 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)]'
                }`}
              >
                {buildOutput.verified ? 'VERIFIED' : 'FAILED'}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
              {typeof buildOutput.repair_rounds_used === 'number' && (
                <span>Repair rounds: {buildOutput.repair_rounds_used}</span>
              )}
              {buildOutput.rolled_back && (
                <span className="text-[var(--color-warning)]">Rolled back</span>
              )}
              {typeof buildOutput.duration_ms === 'number' && (
                <span>{buildOutput.duration_ms} ms</span>
              )}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {renderPassFailBadge(
              buildOutput.build_passed,
              'Build (compileall)',
              buildOutput.build_evidence?.returncode !== undefined &&
                buildOutput.build_evidence?.returncode !== null
                ? `exit ${buildOutput.build_evidence.returncode}`
                : undefined
            )}
            {renderPassFailBadge(
              buildOutput.lint_passed,
              'Lint (AST + Policy)',
              `${buildOutput.lint_evidence?.issue_count ?? 0} issues`
            )}
            {renderPassFailBadge(
              buildOutput.tests_passed,
              'Unit Tests (unittest)',
              `${buildOutput.tests_run ?? 0} run`
            )}
          </div>

          {(buildOutput.build_evidence?.stderr ||
            (buildOutput.lint_evidence?.issues && buildOutput.lint_evidence.issues.length > 0) ||
            buildOutput.test_evidence?.stderr ||
            buildOutput.test_evidence?.stdout) && (
            <div className="space-y-2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 font-mono text-[11px] text-[var(--color-text-secondary)]">
              {buildOutput.build_evidence?.stderr && (
                <div>
                  <p className="font-semibold text-[var(--color-danger)]">Build stderr:</p>
                  <pre className="mt-1 whitespace-pre-wrap break-words">{buildOutput.build_evidence.stderr}</pre>
                </div>
              )}
              {buildOutput.lint_evidence?.issues && buildOutput.lint_evidence.issues.length > 0 && (
                <div>
                  <p className="font-semibold text-[var(--color-danger)]">Lint issues:</p>
                  <ul className="mt-1 space-y-1">
                    {buildOutput.lint_evidence.issues.map((iss, idx) => (
                      <li key={idx}>
                        [{iss.rule}] {iss.file}: {iss.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {buildOutput.test_evidence?.stderr && (
                <div>
                  <p className="font-semibold text-[var(--color-text)]">Test output:</p>
                  <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
                    {buildOutput.test_evidence.stderr}
                  </pre>
                </div>
              )}
            </div>
          )}

          {Array.isArray(buildOutput.stages) && buildOutput.stages.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold text-[var(--color-text)]">
                ขั้นตอนการทำงานและ Repair Loop ({buildOutput.stages.length} ขั้น)
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {buildOutput.stages.map((st, idx) => (
                  <div
                    key={`${st.stage}-${idx}`}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] font-medium text-[var(--color-text)]">
                        {st.stage}
                      </span>
                      <span
                        className={`font-mono text-[10px] font-semibold ${
                          st.status === 'PASS' || st.status === 'COMPLETED'
                            ? 'text-[var(--color-success)]'
                            : 'text-[var(--color-danger)]'
                        }`}
                      >
                        {st.status}
                      </span>
                    </div>
                    {(st.detail || st.root_cause) && (
                      <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">
                        {st.detail || st.root_cause}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Persistent History, Unified Diff & Rollback */}
      <section className="grid gap-6 lg:grid-cols-12">
        <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-[var(--color-accent)]" />
              <h4 className="text-sm font-semibold text-[var(--color-text)]">
                ประวัติ Snapshot ({snapshots.length})
              </h4>
            </div>
          </div>

          {snapshots.length === 0 ? (
            <p className="text-xs text-[var(--color-text-secondary)]">
              ยังไม่มี Snapshot ใน .zyrquen_history/ สำหรับ workspace นี้
            </p>
          ) : (
            <div className="max-h-72 divide-y divide-[var(--color-border)] overflow-y-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]">
              {snapshots.map((snap) => (
                <div key={snap.snapshot_id} className="space-y-2 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <code className="font-mono text-[11px] font-medium text-[var(--color-text)]">
                      {snap.snapshot_id}
                    </code>
                    <span
                      className={`font-mono text-[10px] font-semibold ${
                        snap.verified ? 'text-[var(--color-success)]' : 'text-[var(--color-text-muted)]'
                      }`}
                    >
                      {snap.verified ? 'สแนปช็อต VERIFIED' : snap.action}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--color-text-secondary)]">{snap.label || snap.action}</p>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--color-text-muted)] tabular-nums">
                    <span>
                      {snap.file_count} ไฟล์ · {snap.tests_run} tests
                    </span>
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedDiffSnap(snap.snapshot_id);
                          void handleViewDiff(snap.snapshot_id);
                        }}
                        className="inline-flex h-7 items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 text-[11px] font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)]"
                      >
                        <GitCompare className="h-3 w-3" />
                        <span>Diff</span>
                      </button>
                      <button
                        type="button"
                        disabled={runningAction !== null}
                        onClick={() => void handleRollback(snap.snapshot_id)}
                        className="inline-flex h-7 items-center gap-1 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-2 text-[11px] font-medium text-[var(--color-warning)] hover:opacity-90 disabled:opacity-50"
                      >
                        <RotateCcw className="h-3 w-3" />
                        <span>ย้อนกลับไปยังรุ่นนี้</span>
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 lg:col-span-7">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <GitCompare className="h-4 w-4 text-[var(--color-accent)]" />
              <h4 className="text-sm font-semibold text-[var(--color-text)]">Unified Diff Viewer</h4>
            </div>
            {diffResult && (
              <span className="font-mono text-[11px] text-[var(--color-text-muted)]">
                {diffResult.compared} · {diffResult.changed_files.length} changed
              </span>
            )}
          </div>

          {!diffResult ? (
            <p className="py-8 text-center text-xs text-[var(--color-text-secondary)]">
              กดปุ่ม Diff ที่ Snapshot ทางซ้ายเพื่อเปรียบเทียบการเปลี่ยนแปลงกับสถานะปัจจุบัน
            </p>
          ) : Object.keys(diffResult.diffs).length === 0 ? (
            <p className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-xs text-[var(--color-text-secondary)]">
              สถานะไฟล์ใน workspace ตรงกับ Snapshot ที่เลือกทุกประการ (ไม่มีความแตกต่าง)
            </p>
          ) : (
            <div className="max-h-72 space-y-3 overflow-y-auto">
              {Object.entries(diffResult.diffs).map(([filePath, patchText]) => (
                <div
                  key={filePath}
                  className="overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]"
                >
                  <div className="border-b border-[var(--color-border)] px-3 py-1.5 font-mono text-[11px] font-semibold text-[var(--color-accent)]">
                    {filePath}
                  </div>
                  <pre className="overflow-x-auto p-3 font-mono text-[11px] leading-relaxed">
                    {patchText.split('\n').map((line, i) => {
                      const cls = line.startsWith('+') && !line.startsWith('+++')
                        ? 'text-[var(--color-success)]'
                        : line.startsWith('-') && !line.startsWith('---')
                          ? 'text-[var(--color-danger)]'
                          : line.startsWith('@@')
                            ? 'text-[var(--color-accent)]'
                            : 'text-[var(--color-text-secondary)]';
                      return (
                        <div key={i} className={cls}>
                          {line || ' '}
                        </div>
                      );
                    })}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
