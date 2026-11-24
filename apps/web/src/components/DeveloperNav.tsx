"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./Icon";

const developerTabs: {
  href: string;
  label: string;
  icon: IconName;
  exact?: boolean;
}[] = [
  { href: "/developer", label: "API Management", icon: "code", exact: true },
  { href: "/developer/keys", label: "API Keys", icon: "key" },
  { href: "/developer/console", label: "Developer Console", icon: "terminal" },
  { href: "/developer/usage", label: "Usage & Quotas", icon: "layers" },
  { href: "/admin", label: "ผู้ดูแลระบบ", icon: "shield" },
];

export function DeveloperNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="ส่วนนักพัฒนาและขั้นสูง" className="developer-subnav">
      {developerTabs.map((tab) => {
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
