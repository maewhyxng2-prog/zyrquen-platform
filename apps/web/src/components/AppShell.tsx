"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Session } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import { StatusBadge } from "./StatusBadge";

const navigation: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Overview", icon: "gauge" },
  { href: "/workspace", label: "AI workspace", icon: "message" },
  { href: "/training", label: "Training", icon: "layers" },
  { href: "/system", label: "System health", icon: "activity" },
];

const titles: Record<string, string> = {
  "/": "Overview",
  "/workspace": "AI workspace",
  "/training": "Training workspace",
  "/system": "System health",
  "/settings": "Settings",
  "/login": "Account access",
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
    const collapseTimer = window.setTimeout(() => {
      setCollapsed(window.localStorage.getItem("zyrquen.sidebar-collapsed") === "true");
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

  function toggleCollapsed() {
    setCollapsed((current) => {
      window.localStorage.setItem("zyrquen.sidebar-collapsed", String(!current));
      return !current;
    });
  }

  async function signOut() {
    setSigningOut(true);
    setAccountError("");
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      if (!response.ok) throw new Error("Unable to end this session.");
      setSession({ authenticated: false, email: null });
      window.dispatchEvent(new Event("zyrquen:session-change"));
      router.push("/login");
      router.refresh();
    } catch (reason) {
      setAccountError(reason instanceof Error ? reason.message : "Unable to end this session.");
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className={`app-shell${collapsed ? " shell-collapsed" : ""}${authPage ? " shell-auth" : ""}`}>
      {!authPage && (
        <>
          {mobileOpen && (
            <button
              aria-label="Close navigation"
              className="mobile-scrim"
              onClick={() => setMobileOpen(false)}
              type="button"
            />
          )}
          <aside className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}>
            <Link aria-label="ZYRQUEN overview" className="brand-lockup" href="/">
              <span className="brand-mark">Ω</span>
              <span className="brand-copy">
                <strong>ZYRQUEN</strong>
                <small>INTELLIGENCE PLATFORM</small>
              </span>
            </Link>

            <div className="workspace-switcher">
              <span className="workspace-symbol"><Icon name="command" size={16} /></span>
              <span className="workspace-label">
                <strong>Personal workspace</strong>
                <small>Web application</small>
              </span>
              <span className="workspace-caret"><Icon name="chevron-down" size={14} /></span>
            </div>

            <div className="nav-section-label">PLATFORM</div>
            <nav aria-label="Primary navigation" className="primary-nav">
              {navigation.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={`nav-link${active ? " nav-link-active" : ""}`}
                    href={item.href}
                    key={item.href}
                    onClick={() => setMobileOpen(false)}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon name={item.icon} size={18} />
                    <span>{item.label}</span>
                    {item.href === "/workspace" && <span className="nav-live-dot" />}
                  </Link>
                );
              })}
            </nav>

            <div className="nav-section-label nav-section-spaced">PREFERENCES</div>
            <Link
              aria-current={pathname === "/settings" ? "page" : undefined}
              className={`nav-link${pathname === "/settings" ? " nav-link-active" : ""}`}
              href="/settings"
              onClick={() => setMobileOpen(false)}
              title={collapsed ? "Settings" : undefined}
            >
              <Icon name="settings" size={18} />
              <span>Settings</span>
            </Link>

            <div className="sidebar-bottom">
              <div className="sidebar-connection">
                <span className="connection-indicator" />
                <span className="connection-copy">
                  <strong>API connection</strong>
                  <small>Health checked on demand</small>
                </span>
              </div>
              <button
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                className="collapse-button"
                onClick={toggleCollapsed}
                title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                type="button"
              >
                <Icon name={collapsed ? "panel-open" : "panel-close"} size={17} />
                <span>{collapsed ? "Expand" : "Collapse sidebar"}</span>
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
                aria-label="Open navigation"
                className="mobile-menu-button"
                onClick={() => setMobileOpen(true)}
                type="button"
              >
                <Icon name="menu" size={20} />
              </button>
              <div className="breadcrumb">
                <span>ZYRQUEN</span>
                <Icon name="chevron-right" size={13} />
                <strong>{titles[pathname] || "Platform"}</strong>
              </div>
            </div>
            <div className="topbar-right">
              <StatusBadge icon="command" tone="info">PLATFORM WORKSPACE</StatusBadge>
              {session?.authenticated ? (
                <div className="account-menu">
                  <span className="account-avatar">{(session.email || "U").slice(0, 1).toUpperCase()}</span>
                  <span className="account-copy">
                    <strong>{session.email || "Signed in"}</strong>
                    <small>Authenticated session</small>
                  </span>
                  <button
                    aria-label="Sign out"
                    className="icon-button signout-button"
                    disabled={signingOut}
                    onClick={() => void signOut()}
                    title="Sign out"
                    type="button"
                  >
                    <Icon name="logout" size={16} />
                  </button>
                </div>
              ) : (
                <Link className="topbar-login" href="/login">Sign in <Icon name="arrow-up-right" size={14} /></Link>
              )}
            </div>
          </header>
        )}
        {accountError && <div className="topbar-error" role="alert">{accountError}</div>}
        {authPage && (
          <header className="auth-topbar">
            <Link aria-label="ZYRQUEN overview" className="brand-lockup" href="/">
              <span className="brand-mark">Ω</span>
              <span className="brand-copy"><strong>ZYRQUEN</strong><small>INTELLIGENCE PLATFORM</small></span>
            </Link>
            <StatusBadge icon="shield" tone="info">SECURE ACCESS</StatusBadge>
          </header>
        )}
        <main className={authPage ? "main-content auth-content" : "main-content"}>
          {children}
        </main>
      </div>
    </div>
  );
}
