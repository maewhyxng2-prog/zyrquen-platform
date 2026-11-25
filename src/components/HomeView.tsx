import React, { useRef, useState } from 'react';
import {
  Archive,
  ArrowRight,
  BarChart3,
  ChevronRight,
  Code2,
  FileText,
  FolderKanban,
  Paperclip,
  Plus,
  Wrench,
  X,
} from 'lucide-react';
import { serializeTableToTsv } from '../lib/clipboard';
import type {
  AppScreen,
  AutonomousMissionItem,
  ConversationSummary,
  HomeSummary,
  ReasoningMode,
  User,
} from '../types';
import { CopyButton } from './CopyButton';
import { ProjectDashboard } from './ProjectDashboard';
import { SpacetimeFabric } from './SpacetimeFabric';
import { TemporalIntelligenceCore } from './TemporalIntelligenceCore';

interface HomeViewProps {
  user: User;
  homeSummary: HomeSummary | null;
  nativeReady: boolean;
  loading: boolean;
  error: string | null;
  onStartPrompt: (prompt: string, mode: ReasoningMode, attachment?: string) => void;
  onOpenConversation: (conversationId: string) => void;
  onNavigate: (screen: AppScreen, options?: { preset?: string }) => void;
  onRetry: () => void;
}

const WORKSPACE_ACTIONS: Array<{
  id: 'software' | 'document' | 'data' | 'troubleshoot';
  title: string;
  description: string;
  targetScreen: AppScreen;
  preset: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  {
    id: 'software',
    title: 'พัฒนาซอฟต์แวร์',
    description: 'สร้างโมดูล วางโครงสร้างระบบ เขียนและตรวจสอบโค้ด',
    targetScreen: 'create',
    preset: 'software',
    icon: Code2,
  },
  {
    id: 'document',
    title: 'สร้างเอกสาร',
    description: 'จัดทำรายงาน สเปกงาน ตารางข้อมูล และเอกสารโปรเจกต์',
    targetScreen: 'create',
    preset: 'document',
    icon: FileText,
  },
  {
    id: 'data',
    title: 'วิเคราะห์ข้อมูล',
    description: 'ตรวจสอบไฟล์ CSV/JSON คำนวณสถิติ และตรวจหาความผิดปกติ',
    targetScreen: 'analysis',
    preset: 'data',
    icon: BarChart3,
  },
  {
    id: 'troubleshoot',
    title: 'แก้ปัญหา',
    description: 'วิเคราะห์ข้อผิดพลาด หาสาเหตุหลัก และคำนวณเชิงเทคนิค',
    targetScreen: 'analysis',
    preset: 'solve',
    icon: Wrench,
  },
];

function formatRelativeTime(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString('th-TH', { month: 'short', day: 'numeric' });
}

function formatMissionStatusThai(status: string): string {
  switch (status) {
    case 'COMPLETED':
    case 'VERIFIED':
      return 'เสร็จสมบูรณ์';
    case 'PENDING_APPROVAL':
    case 'AWAITING_APPROVAL':
      return 'รออนุมัติ';
    case 'FAILED':
    case 'BLOCKED':
    case 'CANCELLED':
      return 'หยุดชะงัก';
    default:
      return 'กำลังดำเนินการ';
  }
}

export function HomeView({
  user,
  homeSummary,
  nativeReady: _nativeReady,
  loading,
  error,
  onStartPrompt,
  onOpenConversation,
  onNavigate,
  onRetry,
}: HomeViewProps) {
  const [goal, setGoal] = useState('');
  const [attachment, setAttachment] = useState<{ name: string; content: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed && !attachment) {
      onNavigate('workspace');
      return;
    }
    const effectiveGoal = trimmed || `วิเคราะห์และสรุปไฟล์ ${attachment?.name || 'ที่แนบมา'}`;
    onStartPrompt(effectiveGoal, 'auto', attachment?.content);
    setGoal('');
    setAttachment(null);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === 'string' ? reader.result : '';
      setAttachment({ name: file.name, content: text.slice(0, 8000) });
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  const recentProjects: ConversationSummary[] = (homeSummary?.recent_conversations || []).slice(0, 5);
  const recentMissions: AutonomousMissionItem[] = (homeSummary?.recent_missions || []).slice(0, 3);
  const counts = homeSummary?.counts;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8">
      {/* Workspace Hero Header */}
      <section className="zyrq-glow relative mb-6 overflow-hidden rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-7">
        <SpacetimeFabric density="expansive" className="pointer-events-none absolute inset-0" />
        <div
          className="zyrq-brand-gradient-line absolute inset-x-0 top-0 h-[2px] opacity-85"
          aria-hidden="true"
        />

        <div className="relative z-10 flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
            <div className="shrink-0 self-center sm:self-auto">
              <TemporalIntelligenceCore variant="compact" size={112} active={loading} />
            </div>
            <div className="min-w-0">
              <p className="font-mono text-[11px] font-semibold tracking-[0.16em] text-[var(--color-accent)] uppercase">
                ZYRQUEN · Workspace
              </p>
              <h2 className="mt-1 text-2xl font-bold tracking-tight text-[var(--color-text)] sm:text-3xl text-balance">
                คุณต้องการสร้างอะไรวันนี้?
              </h2>
              <p className="mt-1.5 text-sm font-medium text-[var(--color-text-secondary)]">
                เริ่มต้นงานใหม่ หรือทำงานต่อจากโปรเจกต์เดิม
              </p>
              <p className="mt-2 text-xs text-[var(--color-text-muted)]">
                ผู้ใช้งาน: {user.display_name} · Web Workspace Client เชื่อมต่อ Python Core (แยกจากแอป Native Android/Desktop)
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 lg:shrink-0">
            <button
              type="button"
              onClick={() => onNavigate('projects')}
              className="flex min-h-[42px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] whitespace-nowrap"
            >
              <FolderKanban className="h-4 w-4 text-[var(--color-accent)]" />
              <span>โปรเจกต์ทั้งหมด</span>
            </button>
            <button
              type="button"
              onClick={() => onNavigate('create')}
              className="flex min-h-[42px] items-center gap-2 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] whitespace-nowrap"
            >
              <Plus className="h-4 w-4" />
              <span>เริ่มงานใหม่</span>
            </button>
          </div>
        </div>
      </section>

      {/* Four Real Task Workflows */}
      <section aria-label="ประเภทงานหลัก" className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {WORKSPACE_ACTIONS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onNavigate(item.targetScreen, { preset: item.preset })}
              className="group flex flex-col items-start justify-between gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 text-left transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)]"
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-accent)]">
                  <Icon className="h-4 w-4" />
                </span>
                <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--color-accent)]" />
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--color-text)]">{item.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-[var(--color-text-secondary)]">
                  {item.description}
                </p>
              </div>
            </button>
          );
        })}
      </section>

      {/* New Task / Goal Launcher */}
      <section className="mb-8 rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 sm:p-6">
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-text)]">เริ่มงานใหม่</h3>
              <label htmlFor="home-ai-input" className="text-xs text-[var(--color-text-secondary)]">
                อธิบายเป้าหมายหรือแนบไฟล์เพื่อให้ ZYRQUEN เริ่มดำเนินงาน
              </label>
            </div>
            {attachment && (
              <div className="flex min-w-0 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1 text-xs text-[var(--color-accent)]">
                <span className="max-w-[180px] truncate">{attachment.name}</span>
                <button
                  type="button"
                  onClick={() => setAttachment(null)}
                  aria-label="ลบไฟล์แนบ"
                  className="text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>

          <textarea
            id="home-ai-input"
            rows={2}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder="บอกงานที่ต้องการให้ดำเนินการ..."
            className="w-full resize-none rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[15px] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
          />

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.md,.json,.csv,.py,.ts,.tsx,.js"
                onChange={handleFileChange}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex min-h-[38px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
              >
                <Paperclip className="h-3.5 w-3.5" />
                <span>แนบไฟล์งาน</span>
              </button>
              <button
                type="button"
                onClick={() => onNavigate('artifacts')}
                className="flex min-h-[38px] items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] whitespace-nowrap"
              >
                <Archive className="h-3.5 w-3.5" />
                <span>เปิดคลังผลงาน</span>
              </button>
            </div>

            <button
              type="submit"
              className="flex h-10 items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] whitespace-nowrap"
            >
              <span>{goal.trim() || attachment ? 'เริ่มดำเนินงาน' : 'เปิดพื้นที่ดำเนินงาน'}</span>
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </form>
      </section>

      {error && (
        <div
          role="alert"
          className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 py-3 text-sm text-[var(--color-danger)]"
        >
          <span className="min-w-0 flex-1 break-words">{error}</span>
          <div className="flex flex-wrap items-center gap-2">
            <CopyButton
              getText={() => error}
              ariaLabel="คัดลอกข้อความข้อผิดพลาด"
              size="xs"
            />
            <button
              type="button"
              onClick={onRetry}
              className="min-h-[40px] rounded-lg border border-[var(--color-danger)]/35 bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-danger)] hover:bg-[var(--color-surface-hover)]"
            >
              ลองใหม่
            </button>
          </div>
        </div>
      )}

      {/* Two-Column Workspace Overview: Recent Projects & Execution Status */}
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="space-y-6 lg:col-span-7">
          <ProjectDashboard
            projects={recentProjects}
            variant="overview"
            loading={loading && !homeSummary}
            onOpenProject={onOpenConversation}
            onCreateNew={() => onNavigate('create')}
            onManageAll={() => onNavigate('projects')}
          />

          {recentMissions.length > 0 && (
            <section>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  งานที่ดำเนินการล่าสุด
                </h3>
                <button
                  type="button"
                  onClick={() => onNavigate('tasks')}
                  className="min-h-[36px] px-2 text-xs font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] whitespace-nowrap"
                >
                  ดูงานทั้งหมด
                </button>
              </div>
              <div className="divide-y divide-[var(--color-border)] overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]">
                {recentMissions.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => onNavigate('tasks')}
                    className="flex min-h-[54px] w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--color-surface-hover)]"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-[var(--color-text)]">{m.goal}</p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-secondary)] tabular-nums">
                        <span>{formatMissionStatusThai(m.status)}</span>
                        <span aria-hidden="true"> · </span>
                        <span>{formatRelativeTime(m.created_at)}</span>
                      </p>
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <section className="lg:col-span-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              สรุปพื้นที่ทำงานจริง
            </h3>
            <CopyButton
              getText={() =>
                [
                  'ZYRQUEN Workspace Status Summary',
                  serializeTableToTsv(
                    ['Metric', 'Value'],
                    [
                      ['Active Projects', homeSummary?.recent_conversations?.length ?? 0],
                      ['Autonomous Tasks', counts?.missions ?? recentMissions.length],
                      ['Datasets', counts?.datasets ?? 0],
                      ['Pending Gate Approvals', counts?.pending_approvals ?? 0],
                    ]
                  ),
                ].join('\n\n')
              }
              ariaLabel="คัดลอกสรุปสถานะระบบ"
              title="คัดลอกสรุปสถานะพื้นที่ทำงาน"
              size="xs"
            />
          </div>

          <div className="space-y-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5">
            <div className="grid grid-cols-2 gap-3 tabular-nums">
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                <p className="text-[11px] text-[var(--color-text-secondary)]">โปรเจกต์ล่าสุด</p>
                <p className="mt-1 text-lg font-semibold text-[var(--color-text)]">
                  {homeSummary?.recent_conversations?.length ?? 0}{' '}
                  <span className="text-xs font-normal text-[var(--color-text-muted)]">รายการ</span>
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                <p className="text-[11px] text-[var(--color-text-secondary)]">งานของฉัน</p>
                <p className="mt-1 text-lg font-semibold text-[var(--color-text)]">
                  {counts?.missions ?? recentMissions.length}{' '}
                  <span className="text-xs font-normal text-[var(--color-text-muted)]">ภารกิจ</span>
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                <p className="text-[11px] text-[var(--color-text-secondary)]">ชุดข้อมูลในระบบ</p>
                <p className="mt-1 text-lg font-semibold text-[var(--color-text)]">
                  {counts?.datasets ?? 0}{' '}
                  <span className="text-xs font-normal text-[var(--color-text-muted)]">ชุด</span>
                </p>
              </div>
              <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
                <p className="text-[11px] text-[var(--color-text-secondary)]">รออนุมัติ (Gate)</p>
                <p className="mt-1 text-lg font-semibold text-[var(--zyrquen-violet)]">
                  {counts?.pending_approvals ?? 0}{' '}
                  <span className="text-xs font-normal text-[var(--color-text-muted)]">รายการ</span>
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 py-2.5 text-xs text-[var(--color-text-secondary)]">
              สถานะทั้งหมดอ่านจากฐานข้อมูลและพื้นที่ทำงานจริง พร้อมระบบอนุมัติก่อนดำเนินการที่ส่งผลกระทบสูง
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
