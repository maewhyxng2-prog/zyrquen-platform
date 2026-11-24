"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  PlatformHealthProvider,
  usePlatformHealth,
} from "@/hooks/usePlatformHealth";
import type { Session } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";
import {
  COGNITIVE_STATE_EVENT,
  type CognitiveStateDetail,
  ZyrquenLogo,
} from "./ZyrquenLogo";

type NavItem = {
  href: string;
  label: string;
  mobileLabel: string;
  icon: IconName;
  exact?: boolean;
};

const appNavigation: NavItem[] = [
  {
    href: "/",
    label: "หน้าหลัก",
    mobileLabel: "หน้าหลัก",
    icon: "home",
    exact: true,
  },
  {
    href: "/workspace",
    label: "พื้นที่ทำงาน AI",
    mobileLabel: "แชท AI",
    icon: "sparkles",
  },
  {
    href: "/capabilities",
    label: "ความสามารถ",
    mobileLabel: "ความสามารถ",
    icon: "layers",
  },
  {
    href: "/knowledge",
    label: "คลังความรู้",
    mobileLabel: "ความรู้",
    icon: "book",
  },
  {
    href: "/settings",
    label: "การตั้งค่า",
    mobileLabel: "ตั้งค่า",
    icon: "settings",
  },
];

const routeMeta: Record<string, { title: string; subtitle?: string }> = {
  "/": { title: "หน้าหลัก" },
  "/workspace": { title: "พื้นที่ทำงาน AI" },
  "/capabilities": { title: "ความสามารถ AI" },
  "/knowledge": { title: "คลังความรู้และข้อมูล" },
  "/system": { title: "สถานะระบบ" },
  "/settings": { title: "การตั้งค่าบัญชี" },
  "/developer": { title: "นักพัฒนา · API Management" },
  "/developer/keys": { title: "นักพัฒนา · API Keys" },
  "/developer/console": { title: "นักพัฒนา · Developer Console" },
  "/developer/usage": { title: "นักพัฒนา · Usage & Quotas" },
  "/admin": { title: "ผู้ดูแลระบบ" },
  "/login": { title: "การเข้าถึงบัญชี" },
};

function isNavItemActive(pathname: string, item: NavItem): boolean {
  if (item.exact) {
    return pathname === item.href;
  }
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <PlatformHealthProvider>
      <AppShellInner>{children}</AppShellInner>
    </PlatformHealthProvider>
  );
}

function AppShellInner({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    apiHealth,
    nativeHealth,
    loading: healthLoading,
    platformVersion,
    modelVersion,
  } = usePlatformHealth();

  const [accountOpen, setAccountOpen] = useState(false);
  const [prevPathname, setPrevPathname] = useState(pathname);
  const [session, setSession] = useState<Session | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [accountError, setAccountError] = useState("");
  const [isCognitiveProcessing, setIsCognitiveProcessing] = useState(false);
  const accountMenuRef = useRef<HTMLDivElement>(null);

  const authPage = pathname === "/login";
  const workspacePage = pathname === "/workspace";
  const isAdmin = Boolean(session?.authenticated && session?.role === "admin");
  const currentTitle = routeMeta[pathname]?.title ?? "ZYRQUEN Ω∞";
  const runtimeReady =
    apiHealth?.status === "healthy" && Boolean(nativeHealth?.inference_available);
  const versionTag = platformVersion || modelVersion;

  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    if (accountOpen) {
      setAccountOpen(false);
    }
    if (isCognitiveProcessing && pathname !== "/workspace") {
      setIsCognitiveProcessing(false);
    }
  }

  useEffect(() => {
    const handleCognitiveState = (event: Event) => {
      const custom = event as CustomEvent<CognitiveStateDetail>;
      setIsCognitiveProcessing(Boolean(custom.detail?.processing));
    };
    window.addEventListener(COGNITIVE_STATE_EVENT, handleCognitiveState);
    return () => {
      window.removeEventListener(COGNITIVE_STATE_EVENT, handleCognitiveState);
    };
  }, []);

  useEffect(() => {
    const refreshSession = () => {
      fetch("/api/session", { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : null))
        .then((data: Session | null) => setSession(data))
        .catch(() => setSession(null));
    };

    refreshSession();
    window.addEventListener("zyrquen:session-change", refreshSession);

    return () => {
      window.removeEventListener("zyrquen:session-change", refreshSession);
    };
  }, []);

  useEffect(() => {
    if (!accountOpen) return;

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (
        accountMenuRef.current &&
        !accountMenuRef.current.contains(event.target as Node)
      ) {
        setAccountOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAccountOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [accountOpen]);

  async function signOut() {
    setSigningOut(true);
    setAccountError("");
    setAccountOpen(false);

    try {
      const response = await fetch("/api/logout", {
        method: "POST",
      });
      const payload = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;

      setSession({
        authenticated: false,
        email: null,
        role: null,
        verified: true,
      });
      window.dispatchEvent(new Event("zyrquen:session-change"));

      if (!response.ok) {
        const message =
          typeof payload?.detail === "string"
            ? payload.detail
            : "ไม่สามารถเพิกถอนเซสชันกับ Backend ได้";
        throw new Error(message);
      }

      router.push("/login");
      router.refresh();
    } catch (reason) {
      setAccountError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถยุติเซสชันนี้ได้",
      );
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div
      className={[
        "app-shell",
        authPage ? "shell-auth" : "",
        workspacePage ? "shell-workspace" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-cognitive-state={isCognitiveProcessing ? "processing" : "idle"}
    >
      {!authPage && (
        <header className="app-header">
          <div className="app-header-left">
            {workspacePage && (
              <Link
                aria-label="กลับไปหน้าหลัก"
                className="app-back-button"
                href="/"
              >
                <Icon name="arrow-left" size={18} />
              </Link>
            )}

            <Link
              aria-label="หน้าหลัก ZYRQUEN Ω∞"
              className="app-brand"
              href="/"
            >
              <ZyrquenLogo
                className="app-brand-mark"
                processing={isCognitiveProcessing}
                size={32}
              />
              <span className="app-brand-text">
                <strong>ZYRQUEN Ω∞</strong>
              </span>
            </Link>

            <span aria-hidden="true" className="app-header-divider" />

            <div className="app-context-title">
              <span>{currentTitle}</span>
              {versionTag && (
                <small className="app-version-tag">{versionTag}</small>
              )}
            </div>
          </div>

          <nav aria-label="การนำทางหลัก" className="app-header-nav">
            {appNavigation.map((item) => {
              const active = isNavItemActive(pathname, item);
              return (
                <Link
                  key={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`app-header-link${
                    active ? " app-header-link-active" : ""
                  }`}
                  href={item.href}
                >
                  <Icon name={item.icon} size={15} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="app-header-right" ref={accountMenuRef}>
            {!workspacePage && (
              <Link
                className="button button-primary app-header-workspace-btn"
                href="/workspace"
              >
                <Icon name="sparkles" size={15} />
                <span>เปิดพื้นที่ทำงาน</span>
              </Link>
            )}

            {session?.authenticated ? (
              <button
                aria-controls="account-popover-menu"
                aria-expanded={accountOpen}
                aria-haspopup="menu"
                aria-label="เมนูบัญชีผู้ใช้"
                className={`account-trigger${accountOpen ? " account-trigger-open" : ""}`}
                onClick={() => setAccountOpen((open) => !open)}
                type="button"
              >
                <span className="account-avatar">
                  {(session.email || "U").slice(0, 1).toUpperCase()}
                </span>
                <span className="account-trigger-label">
                  {session.email || "บัญชีผู้ใช้"}
                </span>
                <Icon name="chevron-down" size={14} />
              </button>
            ) : (
              <div className="app-header-guest-actions">
                <Link className="topbar-login" href="/login">
                  เข้าสู่ระบบ
                </Link>
                <button
                  aria-controls="account-popover-menu"
                  aria-expanded={accountOpen}
                  aria-haspopup="menu"
                  aria-label="เมนูระบบและนักพัฒนา"
                  className="app-more-button"
                  onClick={() => setAccountOpen((open) => !open)}
                  type="button"
                >
                  <Icon name="more" size={18} />
                </button>
              </div>
            )}

            {accountOpen && (
              <div
                aria-label="เมนูด่วนบัญชีและเครื่องมือ"
                className="account-popover"
                id="account-popover-menu"
                role="menu"
              >
                <div className="account-popover-header">
                  {session?.authenticated ? (
                    <>
                      <span className="account-avatar account-avatar-lg">
                        {(session.email || "U").slice(0, 1).toUpperCase()}
                      </span>
                      <div className="account-popover-identity">
                        <strong>{session.email}</strong>
                        <small>
                          {isAdmin ? "ผู้ดูแลระบบ (Admin)" : "บัญชีผู้ใช้งาน"}
                        </small>
                      </div>
                    </>
                  ) : (
                    <div className="account-popover-identity">
                      <strong>โหมดผู้เยี่ยมชม</strong>
                      <small>เข้าสู่ระบบเพื่อบันทึกประวัติและการตั้งค่า</small>
                    </div>
                  )}
                </div>

                <div className="account-popover-runtime">
                  <span
                    className={`connection-indicator${
                      runtimeReady
                        ? " connection-indicator-ready"
                        : healthLoading
                          ? ""
                          : " connection-indicator-warn"
                    }`}
                  />
                  <span>
                    {runtimeReady
                      ? "Native AI พร้อมใช้งาน"
                      : healthLoading
                        ? "กำลังตรวจสอบรันไทม์..."
                        : "ตรวจสอบความพร้อมระบบ"}
                  </span>
                </div>

                <div className="account-popover-group">
                  <Link
                    className="account-popover-item"
                    href="/workspace"
                    onClick={() => setAccountOpen(false)}
                    role="menuitem"
                  >
                    <Icon name="sparkles" size={16} />
                    <span>พื้นที่ทำงาน AI</span>
                  </Link>
                  <Link
                    className="account-popover-item"
                    href="/system"
                    onClick={() => setAccountOpen(false)}
                    role="menuitem"
                  >
                    <Icon name="activity" size={16} />
                    <span>สถานะระบบ</span>
                  </Link>
                  {session?.authenticated && (
                    <Link
                      className="account-popover-item"
                      href="/settings"
                      onClick={() => setAccountOpen(false)}
                      role="menuitem"
                    >
                      <Icon name="settings" size={16} />
                      <span>การตั้งค่าบัญชี</span>
                    </Link>
                  )}
                </div>

                <div className="account-popover-group account-popover-group-separated">
                  <span className="account-popover-section-title">
                    เครื่องมือขั้นสูง
                  </span>
                  <Link
                    className="account-popover-item"
                    href="/developer"
                    onClick={() => setAccountOpen(false)}
                    role="menuitem"
                  >
                    <Icon name="code" size={16} />
                    <span>ตั้งค่าสำหรับนักพัฒนา (Developer)</span>
                  </Link>
                  {isAdmin && (
                    <Link
                      className="account-popover-item"
                      href="/admin"
                      onClick={() => setAccountOpen(false)}
                      role="menuitem"
                    >
                      <Icon name="shield" size={16} />
                      <span>แดชบอร์ดผู้ดูแลระบบ</span>
                    </Link>
                  )}
                </div>

                {session?.authenticated ? (
                  <div className="account-popover-group account-popover-group-separated">
                    <button
                      className="account-popover-item account-popover-danger"
                      disabled={signingOut}
                      onClick={() => void signOut()}
                      role="menuitem"
                      type="button"
                    >
                      <Icon name="logout" size={16} />
                      <span>{signingOut ? "กำลังออกจากระบบ..." : "ออกจากระบบ"}</span>
                    </button>
                  </div>
                ) : (
                  <div className="account-popover-group account-popover-group-separated">
                    <Link
                      className="account-popover-item account-popover-primary"
                      href="/login"
                      onClick={() => setAccountOpen(false)}
                      role="menuitem"
                    >
                      <Icon name="lock" size={16} />
                      <span>เข้าสู่ระบบ / สมัครสมาชิก</span>
                    </Link>
                  </div>
                )}
              </div>
            )}
          </div>
        </header>
      )}

      {accountError && (
        <div className="topbar-error" role="alert">
          {accountError}
        </div>
      )}

      {authPage && (
        <header className="auth-topbar">
          <Link
            aria-label="หน้าหลัก ZYRQUEN"
            className="brand-lockup"
            href="/"
          >
            <ZyrquenLogo
              className="brand-mark"
              processing={isCognitiveProcessing}
              size={36}
            />
            <span className="brand-copy">
              <strong>ZYRQUEN Ω∞</strong>
              <small>NATIVE AI PLATFORM</small>
            </span>
          </Link>

          <StatusBadge icon="shield" tone="info">
            การเข้าถึงที่ปลอดภัย
          </StatusBadge>
        </header>
      )}

      <main
        className={
          authPage
            ? "main-content auth-content"
            : workspacePage
              ? "main-content main-content-workspace"
              : "main-content main-content-with-tabbar"
        }
      >
        {children}
      </main>

      {!authPage && !workspacePage && (
        <nav
          aria-label="แถบนำทางล่างสำหรับมือถือ"
          className="mobile-bottom-nav"
        >
          {appNavigation.map((item) => {
            const active = isNavItemActive(pathname, item);
            return (
              <Link
                key={item.href}
                aria-current={active ? "page" : undefined}
                className={`mobile-tab-item${
                  active ? " mobile-tab-item-active" : ""
                }`}
                href={item.href}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.mobileLabel}</span>
              </Link>
            );
          })}
        </nav>
      )}
    </div>
  );
}
