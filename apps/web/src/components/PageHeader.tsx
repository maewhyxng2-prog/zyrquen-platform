"use client";

import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { Icon, type IconName } from "./Icon";
import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  icon,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
  icon?: IconName;
}) {
  const { platformVersion, platformStage, modelVersion, loading, nativeError } =
    usePlatformHealth();

  const versionFromBackend = platformVersion || modelVersion;
  const versionText = versionFromBackend
    ? `รุ่น ${versionFromBackend}`
    : loading
      ? "กำลังตรวจสอบรุ่น..."
      : nativeError
        ? "ไม่ทราบรุ่น (Backend ไม่พร้อม)"
        : "ยังไม่ระบุรุ่นจาก Backend";

  return (
    <div className="page-header">
      <div className="page-heading">
        <div className="eyebrow">
          {icon && <Icon name={icon} size={14} />}
          <span>{eyebrow}</span>
          <span aria-hidden="true" className="eyebrow-separator">
            ·
          </span>
          <span
            className="header-version-tag"
            title={platformStage ?? undefined}
          >
            {versionText}
          </span>
        </div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}

