import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  FolderKanban,
  ListTodo,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import { serializeTableToTsv } from '../lib/clipboard';
import type {
  ConversationSummary,
  ProjectPendingAction,
  ProjectStatusCode,
} from '../types';
import { CopyButton } from './CopyButton';

export type ProjectDashboardFilter = 'all' | 'active' | 'pending' | 'completed';

interface ProjectDashboardProps {
  projects: ConversationSummary[];
  variant: 'overview' | 'full';
  loading?: boolean;
  onOpenProject: (projectId: string) => void;
  onDeleteProject?: (projectId: string) => void | Promise<void>;
  onCreateNew?: () => void;
  onManageAll?: () => void;
  maxOverviewItems?: number;
}

export interface DerivedProjectTelemetry {
  status: ProjectStatusCode;
  statusLabel: string;
  completionPct: number;
  completedUnits: number;
  totalUnits: number;
  pendingActions: ProjectPendingAction[];
  lastSummary: string | null;
}

export function deriveProjectTelemetry(proj: ConversationSummary): DerivedProjectTelemetry {
  const hasBackendFields =
    typeof proj.completion_pct === 'number' &&
    typeof proj.project_status === 'string' &&
    Array.isArray(proj.pending_actions);

  if (hasBackendFields) {
    const pct = Math.max(0, Math.min(100, Math.round(proj.completion_pct ?? 0)));
    const status = proj.project_status as ProjectStatusCode;
    return {
      status,
      statusLabel: getProjectStatusLabel(status),
      completionPct: pct,
      completedUnits: proj.completed_units ?? 0,
      totalUnits: proj.total_units ?? 0,
      pendingActions: proj.pending_actions ?? [],
      lastSummary: proj.last_activity_summary ?? null,
    };
  }

  const msgCount = Math.max(0, proj.message_count || 0);
  if (msgCount === 0) {
    return {
      status: 'NEEDS_INPUT',
      statusLabel: getProjectStatusLabel('NEEDS_INPUT'),
      completionPct: 0,
      completedUnits: 0,
      totalUnits: 0,
      pendingActions: [
        {
          id: `${proj.id}-setup`,
          title: 'ส่งเป้าหมายหรือคำสั่งงานแรกของโปรเจกต์',
          status: 'PENDING',
          category: 'setup',
        },
      ],
      lastSummary: proj.last_activity_summary ?? null,
    };
  }

  const totalUnits = Math.max(1, Math.ceil(msgCount / 2));
  const completedUnits = Math.min(totalUnits, Math.floor(msgCount / 2));
  const completionPct = Math.round((completedUnits / totalUnits) * 100);
  const status: ProjectStatusCode = completionPct >= 100 ? 'ACTIVE' : 'NEEDS_INPUT';
  const pendingActions: ProjectPendingAction[] =
    completedUnits < totalUnits
      ? [
          {
            id: `${proj.id}-pending`,
            title: 'รอการประมวลผลคำสั่งล่าสุด',
            status: 'IN_PROGRESS',
            category: 'task',
          },
        ]
      : [];

  return {
    status,
    statusLabel: getProjectStatusLabel(status),
    completionPct,
    completedUnits,
    totalUnits,
    pendingActions,
    lastSummary: proj.last_activity_summary ?? null,
  };
}

function getProjectStatusLabel(status: ProjectStatusCode): string {
  switch (status) {
    case 'COMPLETED':
      return 'เสร็จสมบูรณ์';
    case 'AWAITING_APPROVAL':
      return 'รออนุมัติ';
    case 'BLOCKED':
      return 'ติดปัญหา';
    case 'NEEDS_INPUT':
      return 'รอเริ่มงาน / ข้อมูลเพิ่ม';
    default:
      return 'กำลังดำเนินการ';
  }
}

function formatDateCompact(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString('th-TH', {
    month: 'short',
    day: 'numeric',
  });
}

function renderStatusWithIcon(status: ProjectStatusCode, label: string) {
  switch (status) {
    case 'COMPLETED':
      return (
        <span className="inline-flex items-center gap-1 font-medium text-[var(--color-success)]">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
    case 'BLOCKED':
      return (
        <span className="inline-flex items-center gap-1 font-medium text-[var(--color-danger)]">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
    case 'AWAITING_APPROVAL':
    case 'NEEDS_INPUT':
      return (
        <span className="inline-flex items-center gap-1 font-medium text-[var(--color-warning)]">
          <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 font-medium text-[var(--color-accent)]">
          <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{label}</span>
        </span>
      );
  }
}

function getProgressBarColor(status: ProjectStatusCode): string {
  switch (status) {
    case 'COMPLETED':
      return 'bg-[var(--color-success)]';
    case 'BLOCKED':
      return 'bg-[var(--color-danger)]';
    case 'AWAITING_APPROVAL':
    case 'NEEDS_INPUT':
      return 'bg-[var(--color-warning)]';
    default:
      return 'bg-[var(--color-primary)]';
  }
}

function matchesFilter(telemetry: DerivedProjectTelemetry, filter: ProjectDashboardFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'completed') return telemetry.status === 'COMPLETED';
  if (filter === 'pending') {
    return (
      telemetry.status === 'AWAITING_APPROVAL' ||
      telemetry.status === 'BLOCKED' ||
      telemetry.status === 'NEEDS_INPUT' ||
      telemetry.pendingActions.length > 0
    );
  }
  return telemetry.status !== 'COMPLETED';
}

export function ProjectDashboard({
  projects,
  variant,
  loading = false,
  onOpenProject,
  onDeleteProject,
  onCreateNew,
  onManageAll,
  maxOverviewItems = 4,
}: ProjectDashboardProps) {
  const [filter, setFilter] = useState<ProjectDashboardFilter>('all');
  const [search, setSearch] = useState('');

  const enriched = useMemo(
    () =>
      projects.map((proj) => ({
        project: proj,
        telemetry: deriveProjectTelemetry(proj),
      })),
    [projects]
  );

  const counts = useMemo(() => {
    let active = 0;
    let pending = 0;
    let completed = 0;
    let totalPendingItems = 0;
    for (const item of enriched) {
      if (item.telemetry.status === 'COMPLETED') completed += 1;
      else active += 1;
      if (item.telemetry.pendingActions.length > 0 || item.telemetry.status !== 'COMPLETED') {
        if (
          item.telemetry.status === 'AWAITING_APPROVAL' ||
          item.telemetry.status === 'BLOCKED' ||
          item.telemetry.status === 'NEEDS_INPUT' ||
          item.telemetry.pendingActions.length > 0
        ) {
          pending += 1;
        }
      }
      totalPendingItems += item.telemetry.pendingActions.length;
    }
    return {
      all: enriched.length,
      active,
      pending,
      completed,
      totalPendingItems,
    };
  }, [enriched]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = enriched.filter((entry) => {
      if (!matchesFilter(entry.telemetry, filter)) return false;
      if (!q) return true;
      const inTitle = entry.project.title.toLowerCase().includes(q);
      const inPending = entry.telemetry.pendingActions.some((a) =>
        a.title.toLowerCase().includes(q)
      );
      return inTitle || inPending;
    });
    return variant === 'overview' ? list.slice(0, maxOverviewItems) : list;
  }, [enriched, filter, maxOverviewItems, search, variant]);

  const avgCompletion = useMemo(() => {
    if (enriched.length === 0) return 0;
    const sum = enriched.reduce((acc, item) => acc + item.telemetry.completionPct, 0);
    return Math.round(sum / enriched.length);
  }, [enriched]);

  const buildCopyText = () =>
    [
      'ZYRQUEN Project Dashboard Summary',
      serializeTableToTsv(
        ['Project', 'Status', 'Completion', 'Pending Items', 'Updated'],
        enriched.map(({ project, telemetry }) => [
          project.title,
          telemetry.statusLabel,
          `${telemetry.completionPct}% (${telemetry.completedUnits}/${telemetry.totalUnits})`,
          telemetry.pendingActions.length > 0
            ? telemetry.pendingActions.map((a) => a.title).join('; ')
            : 'None',
          project.updated_at,
        ])
      ),
    ].join('\n\n');

  const FILTER_TABS: Array<{ id: ProjectDashboardFilter; label: string; count: number }> = [
    { id: 'all', label: 'ทั้งหมด', count: counts.all },
    { id: 'active', label: 'กำลังดำเนินการ', count: counts.active },
    { id: 'pending', label: 'มีงานค้าง', count: counts.pending },
    { id: 'completed', label: 'เสร็จสมบูรณ์', count: counts.completed },
  ];

  return (
    <section aria-label="แดชบอร์ดโปรเจกต์" className="space-y-4">
      {/* Header Row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              {variant === 'overview' ? 'โปรเจกต์ล่าสุด' : `แดชบอร์ดโปรเจกต์ (${filtered.length})`}
            </h3>
            {enriched.length > 0 && (
              <span className="text-xs text-[var(--color-text-secondary)] tabular-nums">
                · เฉลี่ย {avgCompletion}% · ค้างดำเนินการ {counts.totalPendingItems} รายการ
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {enriched.length > 0 && (
            <CopyButton
              getText={buildCopyText}
              ariaLabel="คัดลอกสรุปแดชบอร์ดโปรเจกต์"
              title="คัดลอกตารางสรุปโปรเจกต์"
              size="xs"
            />
          )}
          {variant === 'overview' && onManageAll && (
            <button
              type="button"
              onClick={onManageAll}
              className="min-h-[36px] px-2 text-xs font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] whitespace-nowrap"
            >
              จัดการโปรเจกต์
            </button>
          )}
        </div>
      </div>

      {/* Filter & Search Bar */}
      {enriched.length > 0 && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div
            role="tablist"
            aria-label="กรองสถานะโปรเจกต์"
            className="inline-flex flex-wrap gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-1"
          >
            {FILTER_TABS.map((tab) => {
              const selected = filter === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setFilter(tab.id)}
                  className={`min-h-[34px] rounded-lg px-3 text-xs font-medium transition-colors whitespace-nowrap tabular-nums ${
                    selected
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  {tab.label} ({tab.count})
                </button>
              );
            })}
          </div>

          {variant === 'full' && (
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ค้นหาโปรเจกต์หรือรายการค้าง..."
                aria-label="ค้นหาโปรเจกต์"
                className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] pl-9 pr-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>
          )}
        </div>
      )}

      {/* Body */}
      {loading && enriched.length === 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1].map((idx) => (
            <div
              key={idx}
              className="h-44 animate-pulse rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5"
            />
          ))}
        </div>
      ) : enriched.length === 0 ? (
        <div className="flex flex-col items-start gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6">
          <p className="text-sm text-[var(--color-text-secondary)]">
            {variant === 'overview'
              ? 'ยังไม่มีโปรเจกต์ที่เปิดใช้งาน เริ่มสร้างงานใหม่หรือกำหนดเป้าหมายด้านบนเพื่อเริ่มทำงานทันที'
              : 'ยังไม่มีโปรเจกต์ เริ่มสร้างโปรเจกต์แรกจากแบบฟอร์มด้านซ้ายได้เลย'}
          </p>
          {onCreateNew && (
            <button
              type="button"
              onClick={onCreateNew}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-text)] hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)]"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>เริ่มงานใหม่</span>
            </button>
          )}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6 text-center text-sm text-[var(--color-text-secondary)]">
          ไม่พบโปรเจกต์ที่ตรงกับตัวกรองที่เลือก
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map(({ project, telemetry }) => {
            const visibleActions = telemetry.pendingActions.slice(0, 3);
            const extraActionsCount = Math.max(
              0,
              telemetry.pendingActions.length - visibleActions.length
            );

            return (
              <article
                key={project.id}
                aria-label={`การ์ดโปรเจกต์ ${project.title}`}
                className="flex flex-col justify-between rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 transition-colors hover:border-[var(--color-accent)]/60"
              >
                <div>
                  {/* Card Top: Title + Unboxed Status Metadata */}
                  <div className="flex items-start justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => onOpenProject(project.id)}
                      className="flex min-w-0 flex-1 items-start gap-3 text-left"
                    >
                      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-primary)]">
                        <FolderKanban className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4 className="truncate text-sm font-semibold text-[var(--color-text)]">
                          {project.title}
                        </h4>
                        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-[var(--color-text-secondary)] tabular-nums">
                          {renderStatusWithIcon(telemetry.status, telemetry.statusLabel)}
                          <span aria-hidden="true">·</span>
                          <span>{project.message_count} รายการ</span>
                          <span aria-hidden="true">·</span>
                          <span>อัปเดต {formatDateCompact(project.updated_at)}</span>
                        </p>
                      </div>
                    </button>
                  </div>

                  {/* Completion Percentage Bar */}
                  <div className="mt-4">
                    <div className="mb-1.5 flex items-center justify-between text-xs tabular-nums">
                      <span className="text-[var(--color-text-secondary)]">ความคืบหน้า</span>
                      <span className="font-mono font-semibold text-[var(--color-text)]">
                        {telemetry.completionPct}%
                        {telemetry.totalUnits > 0
                          ? ` (${telemetry.completedUnits}/${telemetry.totalUnits})`
                          : ''}
                      </span>
                    </div>
                    <div
                      role="progressbar"
                      aria-label={`ความคืบหน้า ${project.title}`}
                      aria-valuenow={telemetry.completionPct}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      className="h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface)]"
                    >
                      <div
                        className={`h-full rounded-full transition-all duration-200 ${getProgressBarColor(telemetry.status)}`}
                        style={{ width: `${telemetry.completionPct}%` }}
                      />
                    </div>
                  </div>

                  {/* Pending Action Items */}
                  <div className="mt-4 border-t border-[var(--color-border)] pt-3">
                    <div className="mb-2 flex items-center justify-between text-xs">
                      <span className="inline-flex items-center gap-1.5 font-medium text-[var(--color-text-secondary)]">
                        <ListTodo className="h-3.5 w-3.5 text-[var(--color-accent)]" aria-hidden="true" />
                        <span>รายการค้างดำเนินการ</span>
                      </span>
                      <span className="font-mono text-[var(--color-text-muted)] tabular-nums">
                        {telemetry.pendingActions.length}
                      </span>
                    </div>

                    {telemetry.pendingActions.length === 0 ? (
                      <p className="text-xs text-[var(--color-text-muted)]">
                        ไม่มีรายการค้างดำเนินการ
                      </p>
                    ) : (
                      <ul className="space-y-1.5">
                        {visibleActions.map((act) => (
                          <li
                            key={act.id}
                            className="flex items-start justify-between gap-2 text-xs text-[var(--color-text)]"
                          >
                            <span className="line-clamp-1 flex-1">{act.title}</span>
                            <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-muted)]">
                              {act.status}
                            </span>
                          </li>
                        ))}
                        {extraActionsCount > 0 && (
                          <li className="text-[11px] text-[var(--color-text-muted)] tabular-nums">
                            + อีก {extraActionsCount} รายการค้างดำเนินการ
                          </li>
                        )}
                      </ul>
                    )}
                  </div>
                </div>

                {/* Card Footer Actions */}
                <div className="mt-4 flex items-center justify-between gap-2 border-t border-[var(--color-border)] pt-3">
                  <button
                    type="button"
                    onClick={() => onOpenProject(project.id)}
                    className="inline-flex min-h-[36px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-accent)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] whitespace-nowrap"
                  >
                    <span>
                      {variant === 'overview' ? 'เปิดโปรเจกต์เพื่อทำงานต่อ' : 'เปิดโปรเจกต์'}
                    </span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>

                  {onDeleteProject && (
                    <button
                      type="button"
                      onClick={() => void onDeleteProject(project.id)}
                      aria-label={`ลบโปรเจกต์ ${project.title}`}
                      className="flex min-h-[36px] min-w-[36px] items-center justify-center rounded-xl text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-danger-bg)] hover:text-[var(--color-danger)]"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
