import React, { useEffect, useState } from 'react';
import {
  Archive,
  ArrowLeft,
  BarChart3,
  BrainCircuit,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Cpu,
  FolderKanban,
  LayoutDashboard,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
  Shield,
  Sun,
  User as UserIcon,
  X,
} from 'lucide-react';
import { useZyrquenTheme } from '../lib/theme';
import type { AppScreen, SettingsTab, User } from '../types';
import { ZyrquenEmblem } from './ZyrquenEmblem';

interface AppShellProps {
  activeScreen: AppScreen;
  activeSettingsTab?: SettingsTab;
  screenTitle: string;
  user: User;
  showBackOnMobile?: boolean;
  hideBottomBarOnMobile?: boolean;
  isProcessing?: boolean;
  onNavigate: (screen: AppScreen, settingsTab?: SettingsTab) => void;
  onBack: () => void;
  onOpenProfile: () => void;
  onOpenCommandPalette?: () => void;
  children: React.ReactNode;
}

interface NavItemConfig {
  id: string;
  screen: AppScreen;
  settingsTab?: SettingsTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  prominent?: boolean;
}

const PRIMARY_NAV_ITEMS: NavItemConfig[] = [
  { id: 'overview', screen: 'overview', label: 'ภาพรวม', icon: LayoutDashboard },
  { id: 'projects', screen: 'projects', label: 'โปรเจกต์', icon: FolderKanban },
  { id: 'create', screen: 'create', label: 'สร้างงาน', icon: Plus, prominent: true },
  { id: 'tasks', screen: 'tasks', label: 'งานของฉัน', icon: CheckSquare },
  { id: 'artifacts', screen: 'artifacts', label: 'คลังผลงาน', icon: Archive },
];

const SYSTEM_NAV_ITEMS: NavItemConfig[] = [
  { id: 'analysis', screen: 'analysis', label: 'วิเคราะห์', icon: BarChart3 },
  { id: 'memory', screen: 'memory', label: 'ความรู้และ Workflow', icon: BrainCircuit },
  {
    id: 'model-training',
    screen: 'settings',
    settingsTab: 'developer',
    label: 'โมเดลและการฝึก',
    icon: Cpu,
  },
  {
    id: 'security-permissions',
    screen: 'settings',
    settingsTab: 'admin',
    label: 'สิทธิ์และความปลอดภัย',
    icon: Shield,
  },
  {
    id: 'settings',
    screen: 'settings',
    settingsTab: 'account',
    label: 'ตั้งค่า',
    icon: Settings,
  },
];

function isItemActive(
  item: NavItemConfig,
  activeScreen: AppScreen,
  activeSettingsTab: SettingsTab,
  userRole: User['role']
): boolean {
  if (item.screen === 'projects') {
    return activeScreen === 'projects' || activeScreen === 'workspace';
  }
  if (item.screen === 'settings') {
    if (activeScreen !== 'settings') return false;
    if (item.id === 'security-permissions') {
      return userRole === 'admin' && activeSettingsTab === 'admin';
    }
    return activeSettingsTab === (item.settingsTab || 'account');
  }
  return activeScreen === item.screen;
}

export function AppShell({
  activeScreen,
  activeSettingsTab = 'account',
  screenTitle,
  user,
  showBackOnMobile = false,
  hideBottomBarOnMobile = false,
  isProcessing = false,
  onNavigate,
  onBack,
  onOpenProfile,
  onOpenCommandPalette,
  children,
}: AppShellProps) {
  const { theme, toggleTheme } = useZyrquenTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [systemMenuExpanded, setSystemMenuExpanded] = useState(true);
  // The drawer belongs to the screen/tab it was opened on, so it closes automatically when navigating.
  const routeKey = `${activeScreen}:${activeSettingsTab}`;
  const [drawerOpenAt, setDrawerOpenAt] = useState<string | null>(null);
  const drawerOpen = drawerOpenAt === routeKey;

  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpenAt(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  const navigateItem = (item: NavItemConfig) => {
    if (item.screen === 'settings') {
      const targetTab: SettingsTab =
        item.settingsTab === 'admin' && user.role !== 'admin'
          ? 'account'
          : item.settingsTab || 'account';
      onNavigate('settings', targetTab);
      return;
    }
    onNavigate(item.screen);
  };

  const isSystemScreen =
    activeScreen === 'analysis' || activeScreen === 'memory' || activeScreen === 'settings';

  return (
    <div className="flex min-h-[100dvh] bg-[var(--color-bg)] text-[var(--color-text)]">
      {/* Desktop Left Sidebar (Expanded / Collapsed) */}
      <aside
        aria-label="แถบนำทางด้านข้าง"
        className={`sticky top-0 hidden h-[100dvh] shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]/95 transition-[width] duration-200 md:flex ${
          sidebarCollapsed ? 'w-[72px]' : 'w-64'
        }`}
      >
        {/* Sidebar Brand + Collapse Toggle */}
        <div
          className={`flex h-[60px] items-center border-b border-[var(--color-border)] px-3 ${
            sidebarCollapsed ? 'justify-center' : 'justify-between'
          }`}
        >
          {!sidebarCollapsed && (
            <button
              type="button"
              onClick={() => onNavigate('overview')}
              className="flex min-w-0 items-center gap-2.5 rounded-lg px-1.5 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)]"
            >
              <ZyrquenEmblem size={26} active={isProcessing} />
              <span className="truncate font-display text-base font-bold tracking-tight text-[var(--color-text)]">
                ZYRQUEN
              </span>
            </button>
          )}
          <button
            type="button"
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            aria-label={sidebarCollapsed ? 'ขยายแถบด้านข้าง' : 'ย่อแถบด้านข้าง'}
            aria-expanded={!sidebarCollapsed}
            title={sidebarCollapsed ? 'ขยายแถบด้านข้าง' : 'ย่อแถบด้านข้าง'}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)]"
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* Sidebar Navigation Scroll Area */}
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-2.5 py-4">
          <nav aria-label="เมนูหลัก" className="space-y-1.5">
            {PRIMARY_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = isItemActive(item, activeScreen, activeSettingsTab, user.role);

              if (item.prominent) {
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => navigateItem(item)}
                    aria-label={item.label}
                    aria-current={active ? 'page' : undefined}
                    title={sidebarCollapsed ? item.label : undefined}
                    className={`my-1.5 flex min-h-[42px] w-full items-center gap-2.5 rounded-xl px-3 text-sm font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)] ${
                      sidebarCollapsed ? 'justify-center px-0' : ''
                    } ${
                      active
                        ? 'bg-[var(--color-primary)] text-white ring-2 ring-[var(--color-accent)]/60 shadow-md'
                        : 'bg-[var(--color-primary)] text-white shadow-sm hover:bg-[var(--color-primary-hover)]'
                    }`}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                  </button>
                );
              }

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigateItem(item)}
                  aria-label={item.label}
                  aria-current={active ? 'page' : undefined}
                  title={sidebarCollapsed ? item.label : undefined}
                  className={`flex min-h-[40px] w-full items-center gap-2.5 rounded-xl px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)] ${
                    sidebarCollapsed ? 'justify-center px-0' : ''
                  } ${
                    active
                      ? 'border border-[var(--color-accent)]/35 bg-[var(--color-surface-raised)] text-[var(--color-accent)]'
                      : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]'
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </nav>

          {/* Additional / System Section */}
          <div className="border-t border-[var(--color-border)] pt-4">
            {!sidebarCollapsed && (
              <button
                type="button"
                onClick={() => setSystemMenuExpanded((prev) => !prev)}
                aria-expanded={systemMenuExpanded}
                className="mb-2 flex w-full items-center justify-between px-2 text-[11px] font-semibold tracking-wider text-[var(--color-text-muted)] uppercase hover:text-[var(--color-text-secondary)]"
              >
                <span>เพิ่มเติมและระบบ</span>
                {systemMenuExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </button>
            )}

            {(sidebarCollapsed || systemMenuExpanded) && (
              <nav aria-label="เมนูระบบเพิ่มเติม" className="space-y-1">
                {SYSTEM_NAV_ITEMS.map((item) => {
                  const Icon = item.icon;
                  const active = isItemActive(item, activeScreen, activeSettingsTab, user.role);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => navigateItem(item)}
                      aria-label={item.label}
                      aria-current={active ? 'page' : undefined}
                      title={sidebarCollapsed ? item.label : undefined}
                      className={`flex min-h-[38px] w-full items-center gap-2.5 rounded-xl px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)] ${
                        sidebarCollapsed ? 'justify-center px-0' : ''
                      } ${
                        active
                          ? 'border border-[var(--color-accent)]/35 bg-[var(--color-surface-raised)] text-[var(--color-accent)]'
                          : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]'
                      }`}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
                    </button>
                  );
                })}
              </nav>
            )}
          </div>
        </div>

        {/* Sidebar Footer */}
        <div className="border-t border-[var(--color-border)] p-2.5">
          <button
            type="button"
            onClick={onOpenProfile}
            aria-label="โปรไฟล์ผู้ใช้และการตั้งค่า"
            title={sidebarCollapsed ? user.display_name : undefined}
            className={`flex min-h-[42px] w-full items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2.5 text-left transition-colors hover:bg-[var(--color-surface-hover)] ${
              sidebarCollapsed ? 'justify-center px-0' : ''
            }`}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-semibold text-[var(--color-accent)]">
              {user.display_name.slice(0, 1).toUpperCase()}
            </div>
            {!sidebarCollapsed && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-[var(--color-text)]">
                  {user.display_name}
                </p>
                <p className="truncate font-mono text-[10px] text-[var(--color-text-muted)]">
                  {user.role === 'admin' ? 'ผู้ดูแลระบบ' : 'ผู้ใช้งาน'}
                </p>
              </div>
            )}
          </button>
        </div>
      </aside>

      {/* Main Column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top Bar: Mobile App Bar + Desktop Breadcrumb & Global Search */}
        <header className="sticky top-0 z-30 border-b border-[var(--color-border)] bg-[var(--color-surface)]/92 backdrop-blur-md">
          {/* Mobile Header (52px) */}
          <div className="flex h-[52px] items-center justify-between gap-2 px-3 md:hidden">
            <div className="flex min-w-[44px] items-center gap-1">
              {showBackOnMobile && (
                <button
                  type="button"
                  onClick={onBack}
                  aria-label="ย้อนกลับ"
                  className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
                >
                  <ArrowLeft className="h-5 w-5" />
                </button>
              )}
              <button
                type="button"
                onClick={() => setDrawerOpenAt(drawerOpen ? null : routeKey)}
                aria-label="เพิ่มเติม"
                aria-expanded={drawerOpen}
                aria-haspopup="dialog"
                className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
              >
                <Menu className="h-5 w-5" />
              </button>
            </div>

            <button
              type="button"
              onClick={() => onNavigate('overview')}
              className="flex min-w-0 items-center justify-center gap-2"
            >
              <ZyrquenEmblem size={22} active={isProcessing} />
              <h1 className="max-w-[160px] truncate text-center text-sm font-semibold tracking-tight text-[var(--color-text)]">
                {screenTitle}
              </h1>
            </button>

            <div className="flex items-center gap-1">
              {onOpenCommandPalette && (
                <button
                  type="button"
                  onClick={onOpenCommandPalette}
                  aria-label="ค้นหาและคำสั่งด่วน"
                  className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-accent)]"
                >
                  <Search className="h-4 w-4" />
                </button>
              )}
              <button
                type="button"
                onClick={toggleTheme}
                aria-label={theme === 'dark' ? 'เปลี่ยนเป็นโหมดสว่าง' : 'เปลี่ยนเป็นโหมดมืด'}
                className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
              >
                {theme === 'dark' ? (
                  <Sun className="h-4 w-4 text-[var(--color-accent)]" />
                ) : (
                  <Moon className="h-4 w-4 text-[var(--color-primary)]" />
                )}
              </button>
              <button
                type="button"
                onClick={onOpenProfile}
                aria-label="โปรไฟล์และตั้งค่าบัญชี"
                className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)]"
              >
                <div className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-xs font-semibold text-[var(--color-accent)]">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </div>
              </button>
            </div>
          </div>

          {/* Desktop Top Bar (60px): Breadcrumb + Global Search + Utilities */}
          <div className="hidden h-[60px] items-center justify-between gap-4 px-6 md:flex">
            <nav aria-label="เส้นทางตำแหน่ง" className="flex min-w-0 items-center gap-1.5 text-sm">
              <button
                type="button"
                onClick={() => onNavigate('overview')}
                className="rounded-md px-1.5 py-0.5 font-medium text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text)]"
              >
                ZYRQUEN
              </button>
              {activeScreen === 'workspace' && (
                <>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-muted)]" />
                  <button
                    type="button"
                    onClick={() => onNavigate('projects')}
                    className="rounded-md px-1.5 py-0.5 font-medium text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text)]"
                  >
                    โปรเจกต์
                  </button>
                </>
              )}
              {isSystemScreen && (
                <>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-muted)]" />
                  <span className="px-1 text-xs font-medium text-[var(--color-text-muted)]">
                    ระบบ
                  </span>
                </>
              )}
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-muted)]" />
              <span className="truncate font-semibold text-[var(--color-text)]">{screenTitle}</span>
            </nav>

            <div className="flex shrink-0 items-center gap-2.5">
              {onOpenCommandPalette && (
                <button
                  type="button"
                  onClick={onOpenCommandPalette}
                  aria-label="เปิดแผงคำสั่งด่วน (Ctrl+K)"
                  className="flex h-9 min-w-[220px] items-center justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)]/50 hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
                >
                  <span className="flex items-center gap-2 truncate">
                    <Search className="h-3.5 w-3.5 shrink-0 text-[var(--color-accent)]" />
                    <span className="truncate">ค้นหาโปรเจกต์ งาน คำสั่ง...</span>
                  </span>
                  <kbd className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-muted)]">
                    ⌘K
                  </kbd>
                </button>
              )}

              <button
                type="button"
                onClick={toggleTheme}
                aria-label={
                  theme === 'dark'
                    ? 'เปลี่ยนเป็นโหมดสว่าง (Light Mode)'
                    : 'เปลี่ยนเป็นโหมดมืด (Dark Mode)'
                }
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
              >
                {theme === 'dark' ? (
                  <Sun className="h-4 w-4 text-[var(--color-accent)]" />
                ) : (
                  <Moon className="h-4 w-4 text-[var(--color-primary)]" />
                )}
              </button>

              <button
                type="button"
                onClick={onOpenProfile}
                aria-label="บัญชีผู้ใช้งาน"
                className="flex h-9 shrink-0 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text)] transition-colors hover:bg-[var(--color-surface-hover)] whitespace-nowrap"
              >
                <UserIcon className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                <span className="max-w-[120px] truncate">{user.display_name}</span>
              </button>
            </div>
          </div>
        </header>

        {/* Main Content Area */}
        <main
          className={`flex min-h-0 flex-1 flex-col ${
            hideBottomBarOnMobile ? 'pb-0' : 'pb-[76px] md:pb-8'
          }`}
        >
          {children}
        </main>
      </div>

      {/* Mobile Side Drawer (เพิ่มเติม: วิเคราะห์, ความรู้และ Workflow, โมเดลและการฝึก, สิทธิ์และความปลอดภัย, ตั้งค่า) */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="ปิดเมนูเพิ่มเติม"
            onClick={() => setDrawerOpenAt(null)}
            className="fixed inset-0 bg-black/55 backdrop-blur-[1px]"
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="เมนูเพิ่มเติม"
            className="fixed inset-y-0 left-0 z-50 flex w-[280px] max-w-[85vw] flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl pb-safe"
          >
            <div className="flex h-[56px] items-center justify-between border-b border-[var(--color-border)] px-4">
              <div className="flex items-center gap-2.5">
                <ZyrquenEmblem size={24} active={isProcessing} />
                <span className="font-display text-sm font-bold tracking-tight text-[var(--color-text)]">
                  ZYRQUEN · เพิ่มเติม
                </span>
              </div>
              <button
                type="button"
                onClick={() => setDrawerOpenAt(null)}
                aria-label="ปิดแถบเมนู"
                className="flex h-9 w-9 items-center justify-center rounded-xl text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <nav aria-label="เมนูเพิ่มเติมในแถบข้าง" className="flex-1 space-y-1 overflow-y-auto p-3">
              {SYSTEM_NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                const active = isItemActive(item, activeScreen, activeSettingsTab, user.role);
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      setDrawerOpenAt(null);
                      navigateItem(item);
                    }}
                    aria-current={active ? 'page' : undefined}
                    className={`flex min-h-[46px] w-full items-center gap-3 rounded-xl px-3.5 text-sm font-medium transition-colors ${
                      active
                        ? 'border border-[var(--color-accent)]/35 bg-[var(--color-surface-raised)] text-[var(--color-accent)]'
                        : 'text-[var(--color-text)] hover:bg-[var(--color-surface-hover)]'
                    }`}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{item.label}</span>
                  </button>
                );
              })}
            </nav>

            <div className="border-t border-[var(--color-border)] p-3">
              <div className="flex items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2.5">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-semibold text-[var(--color-accent)]">
                  {user.display_name.slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-[var(--color-text)]">
                    {user.display_name}
                  </p>
                  <p className="truncate font-mono text-[10px] text-[var(--color-text-muted)]">
                    {user.role === 'admin' ? 'ผู้ดูแลระบบ (admin)' : 'ผู้ใช้งานทั่วไป (user)'}
                  </p>
                </div>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* Mobile Bottom Navigation Bar: 5 approved buttons (ภาพรวม, โปรเจกต์, สร้างงาน, งานของฉัน, คลังผลงาน) */}
      {!hideBottomBarOnMobile && (
        <nav
          aria-label="แถบนำทางมือถือ"
          className="fixed bottom-0 left-0 right-0 z-40 border-t border-[var(--color-border)] bg-[var(--color-surface)]/95 backdrop-blur-md pb-safe md:hidden"
        >
          <div className="grid h-[60px] grid-cols-5 items-center px-1">
            {PRIMARY_NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = isItemActive(item, activeScreen, activeSettingsTab, user.role);

              if (item.prominent) {
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => navigateItem(item)}
                    aria-current={active ? 'page' : undefined}
                    className="flex min-h-[48px] flex-col items-center justify-center gap-0.5 px-0.5"
                  >
                    <span
                      className={`-mt-3 flex h-10 w-10 items-center justify-center rounded-2xl transition-all shadow-md ${
                        active
                          ? 'bg-[var(--color-primary)] text-white ring-2 ring-[var(--color-accent)]'
                          : 'bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)]'
                      }`}
                    >
                      <Icon className="h-5 w-5 shrink-0" />
                    </span>
                    <span
                      className={`max-w-full truncate text-[10px] font-semibold leading-none tracking-tight ${
                        active ? 'text-[var(--color-accent)]' : 'text-[var(--color-text)]'
                      }`}
                    >
                      {item.label}
                    </span>
                  </button>
                );
              }

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigateItem(item)}
                  aria-current={active ? 'page' : undefined}
                  className={`flex min-h-[48px] flex-col items-center justify-center gap-1 px-0.5 transition-colors ${
                    active
                      ? 'text-[var(--color-accent)]'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="max-w-full truncate text-[10px] font-medium leading-none tracking-tight">
                    {item.label}
                  </span>
                </button>
              );
            })}
          </div>
        </nav>
      )}
    </div>
  );
}
