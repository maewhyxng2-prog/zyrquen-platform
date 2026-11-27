import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Clock,
  Lock,
  Pause,
  Play,
  RotateCw,
  Search,
  Terminal,
  X,
} from 'lucide-react';
import { CopyButton } from './CopyButton';

export type WorkflowLogLevel = 'INFO' | 'WARN' | 'ERROR';

export interface WorkflowActiveRunItem {
  id: string;
  workflow_key: string;
  status: string;
  started_at?: string | null;
}

export interface WorkflowLogEntry {
  id: string;
  run_id: string;
  workflow_key: string;
  step_key: string | null;
  level: WorkflowLogLevel;
  event_type: string;
  status: string;
  actor_id?: string | null;
  message: string;
  details?: Record<string, unknown> | null;
  timestamp: string | null;
}

export interface WorkflowLogsPayload {
  items: WorkflowLogEntry[];
  active_runs: WorkflowActiveRunItem[];
  active_only: boolean;
  polled_at: string;
}

interface WorkflowLogsConsoleProps {
  token: string;
  onAuthError?: () => void;
}

const POLL_INTERVAL_MS = 2500;

function formatLogTimestamp(ts: string | null | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleTimeString('th-TH', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function levelStyles(level: WorkflowLogLevel): { text: string; bg: string; border: string } {
  switch (level) {
    case 'ERROR':
      return {
        text: 'text-[var(--color-danger)]',
        bg: 'bg-[var(--color-danger-bg)]',
        border: 'border-[var(--color-danger)]/40',
      };
    case 'WARN':
      return {
        text: 'text-[var(--color-warning)]',
        bg: 'bg-[var(--color-warning-bg)]',
        border: 'border-[var(--color-warning)]/40',
      };
    default:
      return {
        text: 'text-[var(--color-accent)]',
        bg: 'bg-[var(--color-surface)]',
        border: 'border-[var(--color-border)]',
      };
  }
}

export function WorkflowLogsConsole({ token, onAuthError }: WorkflowLogsConsoleProps) {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [logs, setLogs] = useState<WorkflowLogEntry[]>([]);
  const [activeRuns, setActiveRuns] = useState<WorkflowActiveRunItem[]>([]);
  const [knownRuns, setKnownRuns] = useState<WorkflowActiveRunItem[]>([]);
  const [polledAt, setPolledAt] = useState<string | null>(null);

  const [activeOnly, setActiveOnly] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [levelFilter, setLevelFilter] = useState<'ALL' | WorkflowLogLevel>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [livePolling, setLivePolling] = useState(true);
  const [pinLatest, setPinLatest] = useState(true);

  const feedRef = useRef<HTMLDivElement | null>(null);

  const fetchLogs = useCallback(
    async (options?: { silent?: boolean; isCancelled?: () => boolean }) => {
      const silent = Boolean(options?.silent);
      if (!token) {
        setUnauthorized(true);
        setLoading(false);
        setRefreshing(false);
        setLogs([]);
        setActiveRuns([]);
        setKnownRuns([]);
        setError(null);
        return;
      }

      if (!silent) {
        setRefreshing(true);
      }

      try {
        const params = new URLSearchParams();
        params.set('active_only', activeOnly ? 'true' : 'false');
        params.set('limit', '100');
        if (selectedRunId) {
          params.set('run_id', selectedRunId);
        }
        if (levelFilter !== 'ALL') {
          params.set('level', levelFilter);
        }
        if (searchQuery.trim()) {
          params.set('search', searchQuery.trim());
        }

        const headers: Record<string, string> = {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        };
        if (token !== '__cookie__') {
          headers.Authorization = `Bearer ${token}`;
        }

        const res = await fetch(`/api/v1/workflows/logs?${params.toString()}`, {
          method: 'GET',
          cache: 'no-store',
          credentials: 'include',
          headers,
        });

        if (options?.isCancelled?.()) return;

        if (res.status === 401) {
          setUnauthorized(true);
          setLogs([]);
          setActiveRuns([]);
          setError(null);
          onAuthError?.();
          return;
        }

        const payload = (await res.json().catch(() => null)) as
          | (Partial<WorkflowLogsPayload> & { error?: string; detail?: string })
          | null;

        if (res.status === 403) {
          setUnauthorized(false);
          setLogs([]);
          setError(payload?.error || payload?.detail || 'ไม่มีสิทธิ์เข้าถึง Execution Logs ของ Workflow ที่ระบุ');
          return;
        }

        if (!res.ok || !payload) {
          throw new Error(
            payload?.error ||
              payload?.detail ||
              `ไม่สามารถดึงข้อมูลจาก /api/v1/workflows/logs ได้ (HTTP ${res.status})`
          );
        }

        const nextItems = Array.isArray(payload.items) ? payload.items : [];
        const nextActiveRuns = Array.isArray(payload.active_runs) ? payload.active_runs : [];

        setUnauthorized(false);
        setError(null);
        setLogs(nextItems);
        setActiveRuns(nextActiveRuns);
        setPolledAt(payload.polled_at || new Date().toISOString());

        setKnownRuns((prev) => {
          const map = new Map<string, WorkflowActiveRunItem>();
          for (const run of nextActiveRuns) {
            if (run?.id) map.set(run.id, run);
          }
          for (const entry of nextItems) {
            if (entry?.run_id && !map.has(entry.run_id)) {
              map.set(entry.run_id, {
                id: entry.run_id,
                workflow_key: entry.workflow_key || 'workflow',
                status: entry.status || 'UNKNOWN',
                started_at: entry.timestamp || null,
              });
            }
          }
          for (const old of prev) {
            if (old?.id && !map.has(old.id)) {
              map.set(old.id, old);
            }
          }
          return Array.from(map.values()).slice(0, 40);
        });
      } catch (err) {
        if (options?.isCancelled?.()) return;
        setUnauthorized(false);
        setError(
          err instanceof Error
            ? err.message
            : 'ไม่สามารถเชื่อมต่อ /api/v1/workflows/logs ได้'
        );
      } finally {
        if (!options?.isCancelled?.()) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [token, activeOnly, selectedRunId, levelFilter, searchQuery, onAuthError]
  );

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) {
        void fetchLogs({ isCancelled: () => cancelled });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [fetchLogs]);

  useEffect(() => {
    if (!token || unauthorized || !livePolling) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void fetchLogs({ silent: true, isCancelled: () => cancelled });
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [token, unauthorized, livePolling, fetchLogs]);

  useEffect(() => {
    if (pinLatest && feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
  }, [logs, pinLatest]);

  const visibleLogs = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return logs.filter((entry) => {
      if (levelFilter !== 'ALL' && String(entry.level).toUpperCase() !== levelFilter) {
        return false;
      }
      if (q) {
        const hay = [
          entry.message,
          entry.workflow_key,
          entry.step_key,
          entry.event_type,
          entry.status,
          entry.run_id,
        ]
          .map((v) => String(v || '').toLowerCase())
          .join(' ');
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [logs, levelFilter, searchQuery]);

  const selectableRuns = activeOnly ? activeRuns : knownRuns;
  const hasFilters = levelFilter !== 'ALL' || searchQuery.trim() !== '' || selectedRunId !== '';

  if (unauthorized) {
    return (
      <section
        aria-label="Orchestration Logs Console"
        className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] pb-4">
          <div className="flex items-center gap-2.5">
            <Terminal className="h-4 w-4 text-[var(--color-accent)]" />
            <div>
              <h3 className="text-base font-semibold text-[var(--color-text)]">
                Orchestration Logs Console
              </h3>
              <p className="font-mono text-[11px] text-[var(--color-text-muted)]">
                GET /api/v1/workflows/logs
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-warning)]/40 bg-[var(--color-warning-bg)] px-2.5 py-1 text-xs font-medium text-[var(--color-warning)]">
            <Lock className="h-3.5 w-3.5" />
            <span>ต้องยืนยันตัวตน (401)</span>
          </span>
        </div>

        <div className="mt-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
          <p className="text-sm font-medium text-[var(--color-text)]">
            กรุณาเข้าสู่ระบบเพื่อดู Execution Logs จริงจาก Workflow Orchestrator
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            ระบบเชื่อมต่อโดยตรงกับ /api/v1/workflows/logs และจะไม่สร้างหรือจำลองบันทึกการทำงานเมื่อยังไม่ได้รับอนุญาต
          </p>
        </div>
      </section>
    );
  }

  return (
    <section
      aria-label="Orchestration Logs Console"
      className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5"
    >
      {/* Header */}
      <div className="flex flex-col gap-3 border-b border-[var(--color-border)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Terminal className="h-4 w-4 text-[var(--color-accent)]" />
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              Orchestration Logs Console
            </h3>
            <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
              {activeRuns.length} active
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] tabular-nums ${
                livePolling
                  ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                  : 'border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-muted)]'
              }`}
            >
              <Activity className="h-3 w-3" />
              <span>{livePolling ? 'Live 2.5s' : 'Paused'}</span>
            </span>
          </div>
          <p className="mt-1 font-mono text-[11px] text-[var(--color-text-muted)]">
            /api/v1/workflows/logs · ข้อมูลจริงจาก Workflow Orchestrator และ Audit Trail
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setLivePolling((prev) => !prev)}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] whitespace-nowrap shrink-0"
          >
            {livePolling ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            <span>{livePolling ? 'หยุดชั่วคราว' : 'ติดตามต่อเนื่อง'}</span>
          </button>

          <button
            type="button"
            disabled={refreshing}
            onClick={() => void fetchLogs()}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] disabled:opacity-50 whitespace-nowrap shrink-0"
          >
            <RotateCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            <span>{refreshing ? 'กำลังดึง...' : 'รีเฟรช'}</span>
          </button>
        </div>
      </div>

      {/* Toolbar */}
      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Active vs All Runs Toggle */}
          <div
            role="group"
            aria-label="ขอบเขตงาน Workflow"
            className="inline-flex rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
          >
            <button
              type="button"
              aria-pressed={activeOnly}
              onClick={() => {
                setActiveOnly(true);
                setSelectedRunId('');
              }}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                activeOnly
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              งานที่กำลังทำงาน ({activeRuns.length})
            </button>
            <button
              type="button"
              aria-pressed={!activeOnly}
              onClick={() => setActiveOnly(false)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                !activeOnly
                  ? 'bg-[var(--color-primary)] text-white'
                  : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
              }`}
            >
              ประวัติล่าสุดทั้งหมด
            </button>
          </div>

          {/* Active Workflow Selector */}
          <select
            aria-label="เลือก Workflow Run"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
            className="h-9 min-w-[220px] flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none sm:max-w-xs"
          >
            <option value="">
              {activeOnly
                ? activeRuns.length > 0
                  ? `ทุก Active Workflows (${activeRuns.length})`
                  : 'ทุก Active Workflows (ไม่มีงานค้าง)'
                : `ทุก Workflow ล่าสุด (${knownRuns.length})`}
            </option>
            {selectedRunId && !selectableRuns.some((r) => r.id === selectedRunId) && (
              <option value={selectedRunId}>Run {selectedRunId.slice(0, 8)} (เลือกอยู่)</option>
            )}
            {selectableRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {run.workflow_key} · {run.status} ({run.id.slice(0, 8)})
              </option>
            ))}
          </select>

          {/* Level Filter */}
          <div
            role="group"
            aria-label="กรองระดับ Log"
            className="inline-flex rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1"
          >
            {(['ALL', 'INFO', 'WARN', 'ERROR'] as const).map((lvl) => (
              <button
                key={lvl}
                type="button"
                aria-pressed={levelFilter === lvl}
                onClick={() => setLevelFilter(lvl)}
                className={`rounded-lg px-2.5 py-1 font-mono text-[11px] font-medium transition-colors whitespace-nowrap shrink-0 ${
                  levelFilter === lvl
                    ? 'bg-[var(--color-primary)] text-white'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                }`}
              >
                {lvl}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input
              type="search"
              aria-label="ค้นหาข้อความหรือ workflow ใน Logs"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="กรองตามข้อความ, workflow_key, step_key หรือ run_id..."
              className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] pl-9 pr-8 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="ล้างคำค้นหา Log"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-[var(--color-text-secondary)] select-none">
            <input
              type="checkbox"
              checked={pinLatest}
              onChange={(e) => setPinLatest(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--color-primary)]"
            />
            <span>ตรึงรายการล่าสุดด้านบน</span>
          </label>
        </div>
      </div>

      {/* Meta bar */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--color-text-muted)] tabular-nums">
        <span>
          แสดง {visibleLogs.length} / {logs.length} รายการ
          {activeOnly ? ' (เฉพาะงานที่กำลังดำเนินการ)' : ' (รวมประวัติล่าสุด)'}
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          <span>อัปเดตล่าสุด: {formatLogTimestamp(polledAt)}</span>
        </span>
      </div>

      {/* Error State */}
      {error && (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-xs text-[var(--color-danger)]"
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="break-words">{error}</span>
          </div>
          <CopyButton getText={() => error} ariaLabel="คัดลอกข้อผิดพลาด Log" size="xs" />
        </div>
      )}

      {/* Body States: Loading -> Empty -> Log Feed */}
      {loading && logs.length === 0 ? (
        <div
          role="status"
          className="mt-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center text-xs text-[var(--color-text-secondary)]"
        >
          กำลังเชื่อมต่อ /api/v1/workflows/logs และโหลดบันทึกการทำงานจริง...
        </div>
      ) : visibleLogs.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <p className="text-sm font-medium text-[var(--color-text)]">
            {activeOnly && activeRuns.length === 0 && !hasFilters
              ? 'ยังไม่มี Workflow ที่กำลังทำงานในขณะนี้'
              : 'ไม่พบ Orchestration Logs ที่ตรงกับเงื่อนไข'}
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            {activeOnly && activeRuns.length === 0 && !hasFilters
              ? 'เมื่อสั่งรัน Workflow ระบบจะแสดง Log ของแต่ละ Step และ Audit Event จริงที่นี่ทันที หรือสลับไปดูประวัติล่าสุดทั้งหมด'
              : 'ลองล้างตัวกรองระดับ Log คำค้นหา หรือเลือกดูประวัติล่าสุดทั้งหมด'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {activeOnly && (
              <button
                type="button"
                onClick={() => setActiveOnly(false)}
                className="inline-flex h-8 items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)]"
              >
                แสดงประวัติล่าสุดทั้งหมด
              </button>
            )}
            {hasFilters && (
              <button
                type="button"
                onClick={() => {
                  setLevelFilter('ALL');
                  setSearchQuery('');
                  setSelectedRunId('');
                }}
                className="inline-flex h-8 items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)]"
              >
                ล้างตัวกรอง
              </button>
            )}
          </div>
        </div>
      ) : (
        <div
          ref={feedRef}
          role="log"
          aria-live="polite"
          className="mt-4 max-h-[380px] divide-y divide-[var(--color-border)] overflow-y-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]"
        >
          {visibleLogs.map((entry) => {
            const st = levelStyles(entry.level);
            return (
              <div key={entry.id} className="space-y-1.5 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                      {formatLogTimestamp(entry.timestamp)}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold border ${st.border} ${st.bg} ${st.text}`}
                    >
                      {entry.level}
                    </span>
                    <code className="font-mono text-[11px] font-medium text-[var(--color-text)]">
                      {entry.workflow_key || entry.event_type}
                    </code>
                    {entry.step_key && (
                      <code className="font-mono text-[11px] text-[var(--color-accent)]">
                        #{entry.step_key}
                      </code>
                    )}
                    {entry.run_id && (
                      <span className="font-mono text-[11px] text-[var(--color-text-muted)] tabular-nums">
                        run:{entry.run_id.slice(0, 8)}
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
                    {entry.status}
                  </span>
                </div>

                <p className="break-words text-xs leading-relaxed text-[var(--color-text-secondary)]">
                  {entry.message}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
