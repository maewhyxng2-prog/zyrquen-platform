"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiRequest, readSession } from "@/lib/api";
import type { Session } from "@/lib/types";
import { Icon, type IconName } from "./Icon";

const developerTabs: {
  href: string;
  label: string;
  icon: IconName;
  exact?: boolean;
  adminOnly?: boolean;
}[] = [
  { href: "/developer", label: "API Management", icon: "code", exact: true },
  { href: "/developer/keys", label: "API Keys", icon: "key" },
  { href: "/developer/console", label: "Developer Console", icon: "terminal" },
  { href: "/developer/usage", label: "Usage & Quotas", icon: "layers" },
  { href: "/admin", label: "ผู้ดูแลระบบ", icon: "shield", adminOnly: true },
];

type ApprovalSummary = {
  id?: string;
  status?: string;
};

export function DeveloperNav() {
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<number | null>(null);

  const loadPendingApprovals = useCallback(async (isAdminUser: boolean) => {
    if (!isAdminUser) {
      setPendingApprovals(null);
      return;
    }
    try {
      const response = await apiRequest<{ items?: ApprovalSummary[] }>(
        "v1/workflows/approvals?status=pending&limit=100",
      );
      const items = Array.isArray(response.items) ? response.items : [];
      const pendingCount = items.filter(
        (item) => (item.status ?? "pending").toLowerCase() === "pending",
      ).length;
      setPendingApprovals(pendingCount);
    } catch {
      setPendingApprovals(null);
    }
  }, []);

  useEffect(() => {
    let active = true;

    const syncSessionAndApprovals = async () => {
      try {
        const nextSession = await readSession();
        if (!active) return;
        setSession(nextSession);
        const admin = Boolean(
          nextSession.authenticated && nextSession.role === "admin",
        );
        await loadPendingApprovals(admin);
      } catch {
        if (!active) return;
        setSession(null);
        setPendingApprovals(null);
      }
    };

    const handleApprovalsChange = () => {
      if (!active) return;
      const admin = Boolean(session?.authenticated && session?.role === "admin");
      if (admin) {
        void loadPendingApprovals(true);
      } else {
        void syncSessionAndApprovals();
      }
    };

    void syncSessionAndApprovals();
    window.addEventListener("zyrquen:session-change", syncSessionAndApprovals);
    window.addEventListener("zyrquen:approvals-change", handleApprovalsChange);
    return () => {
      active = false;
      window.removeEventListener(
        "zyrquen:session-change",
        syncSessionAndApprovals,
      );
      window.removeEventListener(
        "zyrquen:approvals-change",
        handleApprovalsChange,
      );
    };
  }, [loadPendingApprovals, session?.authenticated, session?.role]);

  const isAdmin = Boolean(session?.authenticated && session?.role === "admin");

  return (
    <nav aria-label="ส่วนนักพัฒนาและขั้นสูง" className="developer-subnav">
      {developerTabs
        .filter((tab) => !tab.adminOnly || isAdmin)
        .map((tab) => {
          const active = tab.exact
            ? pathname === tab.href
            : pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              aria-current={active ? "page" : undefined}
              className={`developer-subnav-link${
                active ? " developer-subnav-link-active" : ""
              }`}
              href={tab.href}
              key={tab.href}
            >
              <Icon name={tab.icon} size={15} />
              <span>{tab.label}</span>
            </Link>
          );
        })}

      {isAdmin ? (
        <Link
          aria-label={
            pendingApprovals === null
              ? "Tier-2 Approval workflows awaiting review"
              : `Tier-2 Approval workflows awaiting review: ${pendingApprovals}`
          }
          className={`developer-subnav-bell${
            pendingApprovals && pendingApprovals > 0
              ? " developer-subnav-bell-pending"
              : ""
          }`}
          href="/developer/console#tier2-approvals"
          title={
            pendingApprovals === null
              ? "Tier-2 Approval workflows awaiting review"
              : `Tier-2 Approval workflows awaiting review: ${pendingApprovals}`
          }
        >
          <Icon name="bell" size={15} />
          <span className="developer-subnav-bell-label">Tier-2 Approval</span>
          {pendingApprovals !== null ? (
            <span className="developer-subnav-bell-badge tabular-nums">
              {pendingApprovals}
            </span>
          ) : null}
        </Link>
      ) : null}
    </nav>
  );
}
