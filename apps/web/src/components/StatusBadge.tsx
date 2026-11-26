import { Icon, type IconName } from "./Icon";
import type { ReactNode } from "react";
import type { StatusTone } from "@/lib/types";

export function StatusBadge({
  children,
  tone = "neutral",
  icon,
}: {
  children: ReactNode;
  tone?: StatusTone;
  icon?: IconName;
}) {
  return (
    <span className={`status-badge status-${tone}`}>
      {icon ? <Icon name={icon} size={13} /> : <span className="status-dot" />}
      {children}
    </span>
  );
}
