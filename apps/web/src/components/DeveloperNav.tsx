"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { readSession } from "@/lib/api";
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

export function DeveloperNav() {
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const syncSession = () => {
      readSession()
        .then(setSession)
        .catch(() => setSession(null));
    };
    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => window.removeEventListener("zyrquen:session-change", syncSession);
  }, []);

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
    </nav>
  );
}
