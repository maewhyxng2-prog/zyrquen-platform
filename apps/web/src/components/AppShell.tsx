
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Session } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";

const navigation: {
  href: string;
  label: string;
  icon: IconName;
}[] = [
  { href: "/", label: "ภาพรวม", icon: "gauge" },
  { href: "/workspace", label: "พื้นที่ทำงาน AI", icon: "message-square" },
  { href: "/training", label: "การฝึกอบรม", icon: "layers" },
  { href: "/system", label: "สถานะระบบ", icon: "activity" },
];

const titles: Record<string, string> = {
  "/": "ภาพรวม",
  "/workspace": "พื้นที่ทำงาน AI",
  "/training": "พื้นที่ทำงานสำหรับการฝึกอบรม",
  "/system": "สถานะสุขภาพของระบบ",
  "/settings": "การตั้งค่า",
  "/login": "การเข้าถึงบัญชี",
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [accountError, setAccountError] = useState("");

  const authPage = pathname === "/login";

  useEffect(() => {
    setCollapsed(
      window.localStorage.getItem("zyrquen.sidebar-collapsed") === "true"
    );

    const refreshSession = () => {
      fetch("/api/session", { cache: "no-store" })
        .then((response) =>
          response.ok ? response.json() : null
        )
        .then((data: Session | null) => setSession(data))
        .catch(() => setSession(null));
    };

    refreshSession();

    window.addEventListener("zyrquen:session-change", refreshSession);

    return () => {
      window.removeEventListener(
        "zyrquen:session-change",
        refreshSession
      );
    };
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!mobileOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileOpen]);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;

      window.localStorage.setItem(
        "zyrquen.sidebar-collapsed",
        String(next)
      );

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

      if (!response.ok) {
        throw new Error("ไม่สามารถสิ้นสุดเซสชันนี้ได้");
      }

      setSession({
        authenticated: false,
        email: null,
      });

      window.dispatchEvent(
        new Event("zyrquen:session-change")
      );

      router.push("/login");
      router.refresh();
    } catch (reason) {
      setAccountError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถยุติเซสชันนี้ได้"
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
            aria-hidden={undefined}
          >
            <Link
              aria-label="ภาพรวม ZYRQUEN"
              className="brand-lockup"
              href="/"
              onClick={() => setMobileOpen(false)}
            >
              <span className="brand-mark">Ω</span>
              <span className="brand-copy">
                <strong>ZYRQUEN</strong>
                <small>แพลตฟอร์มอัจฉริยะ</small>
              </span>
            </Link>

            <div className="workspace-switcher">
              <span className="workspace-symbol">
                <Icon name="command" size={16} />
              </span>

              <span className="workspace-label">
                <strong>พื้นที่ทำงานส่วนตัว</strong>
                <small>แอปพลิเคชันเว็บ</small>
              </span>

              <span className="workspace-caret">
                <Icon name="chevron-down" size={14} />
              </span>
            </div>

            <div className="nav-section-label">
              แพลตฟอร์ม
            </div>

            <nav
              aria-label="การนำทางหลัก"
              className="primary-nav"
            >
              {navigation.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);

                return (
                  <Link
                    key={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`nav-link${
                      active ? " nav-link-active" : ""
                    }`}
                    href={item.href}
                    onClick={() => setMobileOpen(false)}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon name={item.icon} size={18} />
                    <span>{item.label}</span>

                    {item.href === "/workspace" && (
                      <span className="nav-live-dot" />
                    )}
                  </Link>
                );
              })}
            </nav>

            <div className="nav-section-label nav-section-spaced">
              การตั้งค่า
            </div>

            <Link
              aria-current={
                pathname === "/settings" ? "page" : undefined
              }
              className={`nav-link${
                pathname === "/settings" ? " nav-link-active" : ""
              }`}
              href="/settings"
              onClick={() => setMobileOpen(false)}
              title={collapsed ? "การตั้งค่า" : undefined}
            >
              <Icon name="settings" size={18} />
              <span>การตั้งค่า</span>
            </Link>

            <div className="sidebar-bottom">
              <div className="sidebar-connection">
                <span className="connection-indicator" />

                <span className="connection-copy">
                  <strong>การเชื่อมต่อ API</strong>
                  <small>ตรวจสุขภาพได้ตามความต้องการ</small>
                </span>
              </div>

              <button
                type="button"
                aria-label={
                  collapsed
                    ? "ขยายแถบด้านข้าง"
                    : "ยุบแถบด้านข้าง"
                }
                aria-expanded={!collapsed}
                className="sidebar-collapse-button"
                onClick={toggleCollapsed}
                title={
                  collapsed
                    ? "ขยายแถบด้านข้าง"
                    : "ยุบแถบด้านข้าง"
                }
              >
                <Icon
                  name={collapsed ? "panel-left-open" : "panel-left-close"}
                  size={17}
                />
                <span>
                  {collapsed ? "Expand" : "Collapse sidebar"}
                </span>
              </button>
            </div>
          </aside>
        </>
      )}

      <div className="main-column">
        {!authPage && (
          <header className="topbar">
            <div className="topbar-left">
              <button
                type="button"
                aria-label={
                  mobileOpen
                    ? "ปิดเมนูนำทาง"
                    : "เปิดเมนูนำทาง"
                }
                aria-expanded={mobileOpen}
                aria-controls="platform-sidebar"
                className="mobile-menu-button"
                onClick={() => setMobileOpen((current) => !current)}
              >
                <Icon
                  name={mobileOpen ? "x" : "menu"}
                  size={20}
                />
              </button>

              <div className="breadcrumb">
                <span>ZYRQUEN</span>
                <Icon name="chevron-right" size={13} />
                <strong>
                  {titles[pathname] || "แพลตฟอร์ม"}
                </strong>
              </div>
            </div>

            <div className="topbar-right">
              <StatusBadge
                command="command"
                tone="info"
              >
                พื้นที่ทำงานแพลตฟอร์ม
              </StatusBadge>

              {session?.authenticated ? (
                <div className="account-menu">
                  <span className="account-avatar">
                    {(session.email || "U")
                      .slice(0, 1)
                      .toUpperCase()}
                  </span>

                  <span className="account-copy">
                    <strong>
                      {session.email || "เข้าสู่ระบบแล้ว"}
                    </strong>
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
                    <Icon name="log-out" size={16} />
                  </button>
                </div>
              ) : (
                <Link
                  className="topbar-login"
                  href="/login"
                >
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
              aria-label="ภาพรวม ZYRQUEN"
              className="brand-lockup"
              href="/"
            >
              <span className="brand-mark">Ω</span>
              <span className="brand-copy">
                <strong>ZYRQUEN</strong>
                <small>แพลตฟอร์มอัจฉริยะ</small>
              </span>
            </Link>

            <StatusBadge
              command="shield"
              tone="info"
            >
              การเข้าถึงที่ปลอดภัย
            </StatusBadge>
          </header>
        )}

        <main
          className={
            authPage
              ? "main-content auth-content"
              : "main-content"
          }
        >
          {children}
        </main>
      </div>
    </div>
  );
}
