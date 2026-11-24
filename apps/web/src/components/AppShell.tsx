"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  PlatformHealthProvider,
  usePlatformHealth,
} from "@/hooks/usePlatformHealth";
import type { Session } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";

type NavItem = {
  href: string;
  label: string;
  icon: IconName;
  exact?: boolean;
};

const primaryNavigation: NavItem[] = [
  { href: "/", label: "หน้าหลัก", icon: "home", exact: true },
  { href: "/workspace", label: "พื้นที่ทำงาน AI", icon: "message" },
  { href: "/capabilities", label: "ความสามารถ AI", icon: "sparkles" },
  { href: "/knowledge", label: "คลังความรู้และข้อมูล", icon: "book" },
  { href: "/system", label: "สถานะระบบ", icon: "activity" },
  { href: "/settings", label: "การตั้งค่า", icon: "settings" },
];

const advancedNavigation: NavItem[] = [
  { href: "/developer", label: "API Management", icon: "code", exact: true },
  { href: "/developer/keys", label: "API Keys", icon: "key" },
  { href: "/developer/console", label: "Developer Console", icon: "terminal" },
  { href: "/developer/usage", label: "Usage & Quotas", icon: "layers" },
  { href: "/admin", label: "ผู้ดูแลระบบ", icon: "shield" },
];

const titles: Record<string, string> = {
  "/": "หน้าหลัก",
  "/workspace": "พื้นที่ทำงาน AI",
  "/capabilities": "ความสามารถ AI",
  "/knowledge": "คลังความรู้และข้อมูล",
  "/system": "สถานะระบบ",
  "/settings": "การตั้งค่า",
  "/developer": "API Management",
  "/developer/keys": "API Keys",
  "/developer/console": "Developer Console",
  "/developer/usage": "Usage & Quotas",
  "/admin": "ผู้ดูแลระบบ",
  "/login": "การเข้าถึงบัญชี",
};

function isNavItemActive(pathname: string, item: NavItem): boolean {
  if (item.exact) {
    return pathname === item.href;
  }
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function isAdvancedRoute(pathname: string): boolean {
  return pathname.startsWith("/developer") || pathname.startsWith("/admin");
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
    apiError,
    nativeError,
    loading: healthLoading,
    platformVersion,
    platformStage,
    modelVersion,
  } = usePlatformHealth();
  const topbarVersion = platformVersion || modelVersion;

  const connectionOk =
    apiHealth?.status === "healthy" && Boolean(nativeHealth?.inference_available);
  const connectionHasError = Boolean(apiError || nativeError);
  const connectionIndicatorClass = connectionOk
    ? "connection-indicator connection-indicator-ready"
    : connectionHasError
      ? "connection-indicator connection-indicator-warn"
      : "connection-indicator";
  const connectionSummary =
    healthLoading && !apiHealth
      ? "กำลังตรวจสอบสถานะระบบ"
      : connectionOk
        ? "Native AI พร้อมใช้งาน"
        : connectionHasError
          ? "ตรวจสอบการเชื่อมต่อบางส่วนไม่สำเร็จ"
          : apiHealth?.status === "healthy"
            ? "ระบบเชื่อมต่อแล้ว · รอความพร้อม Native Model"
            : "ตรวจสอบความพร้อมของระบบ";

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(() =>
    isAdvancedRoute(pathname),
  );
  const [prevPathname, setPrevPathname] = useState(pathname);
  const [session, setSession] = useState<Session | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [accountError, setAccountError] = useState("");

  const authPage = pathname === "/login";

  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    if (mobileOpen) {
      setMobileOpen(false);
    }
    if (isAdvancedRoute(pathname) && !advancedOpen) {
      setAdvancedOpen(true);
    }
  }

  useEffect(() => {
    const collapseTimer = window.setTimeout(() => {
      setCollapsed(
        window.localStorage.getItem("zyrquen.sidebar-collapsed") === "true",
      );
    }, 0);

    const refreshSession = () => {
      fetch("/api/session", { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : null))
        .then((data: Session | null) => setSession(data))
        .catch(() => setSession(null));
    };

    refreshSession();
    window.addEventListener("zyrquen:session-change", refreshSession);

    return () => {
      window.clearTimeout(collapseTimer);
      window.removeEventListener("zyrquen:session-change", refreshSession);
    };
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 701px)");
    const handleViewportChange = (event: MediaQueryListEvent) => {
      if (event.matches) {
        setMobileOpen(false);
      }
    };
    mediaQuery.addEventListener("change", handleViewportChange);
    return () => {
      mediaQuery.removeEventListener("change", handleViewportChange);
    };
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileOpen]);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("zyrquen.sidebar-collapsed", String(next));
      return next;
    });
  }

  async function signOut() {
    setSigningOut(true);
    setAccountError("");

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
        collapsed ? "shell-collapsed" : "",
        authPage ? "shell-auth" : "",
        mobileOpen ? "shell-mobile-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {!authPage && (
        <>
          {mobileOpen && (
            <button
              type="button"
              aria-label="ปิดการนำทาง"
              className="mobile-scrim"
              onClick={() => setMobileOpen(false)}
            />
          )}

          <aside
            id="platform-sidebar"
            className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}
            aria-label="แถบเมนูหลัก"
          >
            <Link
              aria-label="หน้าหลัก ZYRQUEN Ω∞"
              className="brand-lockup"
              href="/"
              onClick={() => setMobileOpen(false)}
            >
              <Image
                alt=""
                className="brand-mark"
                height={40}
                priority
                src="/zyrquen-icon.svg"
                unoptimized
                width={40}
              />
              <span className="brand-copy">
                <strong>ZYRQUEN Ω∞</strong>
                <small>NATIVE AI PLATFORM</small>
              </span>
            </Link>

            <div className="nav-section-label">แพลตฟอร์ม</div>

            <nav aria-label="การนำทางหลัก" className="primary-nav">
              {primaryNavigation.map((item) => {
                const active = isNavItemActive(pathname, item);
                const featured = item.href === "/workspace";

                return (
                  <Link
                    key={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`nav-link${
                      featured ? " nav-link-featured" : ""
                    }${active ? " nav-link-active" : ""}`}
                    href={item.href}
                    onClick={() => setMobileOpen(false)}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon name={item.icon} size={18} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </nav>

            <div className="sidebar-advanced-group">
              <button
                aria-controls="sidebar-advanced-nav"
                aria-expanded={advancedOpen}
                className={`sidebar-advanced-toggle${
                  isAdvancedRoute(pathname)
                    ? " sidebar-advanced-toggle-active"
                    : ""
                }`}
                onClick={() => setAdvancedOpen((current) => !current)}
                title={collapsed ? "นักพัฒนา & ขั้นสูง" : undefined}
                type="button"
              >
                <span className="sidebar-advanced-toggle-label">
                  <Icon name="code" size={16} />
                  <span>นักพัฒนา &amp; ขั้นสูง</span>
                </span>
                <Icon
                  className={`sidebar-advanced-chevron${
                    advancedOpen ? " sidebar-advanced-chevron-open" : ""
                  }`}
                  name="chevron-down"
                  size={15}
                />
              </button>

              {advancedOpen && (
                <nav
                  aria-label="การนำทางขั้นสูงและนักพัฒนา"
                  className="primary-nav sidebar-advanced-nav"
                  id="sidebar-advanced-nav"
                >
                  {advancedNavigation.map((item) => {
                    const active = isNavItemActive(pathname, item);

                    return (
                      <Link
                        key={item.href}
                        aria-current={active ? "page" : undefined}
                        className={`nav-link nav-link-advanced${
                          active ? " nav-link-active" : ""
                        }`}
                        href={item.href}
                        onClick={() => setMobileOpen(false)}
                        title={collapsed ? item.label : undefined}
                      >
                        <Icon name={item.icon} size={17} />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}
                </nav>
              )}
            </div>

            <div className="sidebar-bottom">
              <div className="sidebar-connection">
                <span className={connectionIndicatorClass} />

                <span className="connection-copy">
                  <strong>รันไทม์ NATIVE AI</strong>
                  <small>{connectionSummary}</small>
                </span>
              </div>

              <button
                type="button"
                aria-label={collapsed ? "ขยายแถบด้านข้าง" : "ยุบแถบด้านข้าง"}
                aria-expanded={!collapsed}
                className="collapse-button"
                onClick={toggleCollapsed}
                title={collapsed ? "ขยายแถบด้านข้าง" : "ยุบแถบด้านข้าง"}
              >
                <Icon
                  name={collapsed ? "panel-open" : "panel-close"}
                  size={17}
                />
                <span>{collapsed ? "ขยาย" : "ยุบแถบด้านข้าง"}</span>
              </button>
            </div>
          </aside>
        </>
      )}

      <div aria-hidden={mobileOpen || undefined} className="main-column">
        {!authPage && (
          <header className="topbar">
            <div className="topbar-left">
              <button
                type="button"
                aria-label={mobileOpen ? "ปิดเมนูนำทาง" : "เปิดเมนูนำทาง"}
                aria-expanded={mobileOpen}
                aria-controls="platform-sidebar"
                className="mobile-menu-button"
                onClick={() => setMobileOpen((current) => !current)}
              >
                <Icon name={mobileOpen ? "close" : "menu"} size={20} />
              </button>

              <div className="breadcrumb">
                <span>ZYRQUEN Ω∞</span>
                {topbarVersion && (
                  <span
                    className="topbar-version"
                    title={platformStage ?? undefined}
                  >
                    {topbarVersion}
                  </span>
                )}
                <Icon name="chevron-right" size={13} />
                <strong>{titles[pathname] || "แพลตฟอร์ม"}</strong>
              </div>
            </div>

            <div className="topbar-right">
              {pathname !== "/workspace" && (
                <Link
                  className="button button-primary topbar-workspace-cta"
                  href="/workspace"
                >
                  <Icon name="sparkles" size={15} />
                  เปิดพื้นที่ทำงาน AI
                </Link>
              )}

              {session?.authenticated ? (
                <div className="account-menu">
                  <span className="account-avatar">
                    {(session.email || "U").slice(0, 1).toUpperCase()}
                  </span>

                  <span className="account-copy">
                    <strong>{session.email || "เข้าสู่ระบบแล้ว"}</strong>
                    <small>เซสชันที่ได้รับการยืนยัน</small>
                  </span>

                  <button
                    type="button"
                    aria-label="ออกจากระบบ"
                    className="icon-button signout-button"
                    disabled={signingOut}
                    onClick={() => void signOut()}
                    title="ออกจากระบบ"
                  >
                    <Icon name="logout" size={16} />
                  </button>
                </div>
              ) : (
                <Link className="topbar-login" href="/login">
                  เข้าสู่ระบบ
                  <Icon name="arrow-up-right" size={14} />
                </Link>
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
              <Image
                alt=""
                className="brand-mark"
                height={40}
                priority
                src="/zyrquen-icon.svg"
                unoptimized
                width={40}
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
          className={authPage ? "main-content auth-content" : "main-content"}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
