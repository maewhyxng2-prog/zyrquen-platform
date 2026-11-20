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
  return (
    <div className="page-header">
      <div className="page-heading">
        <div className="eyebrow">{icon && <Icon name={icon} size={14} />}{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}
