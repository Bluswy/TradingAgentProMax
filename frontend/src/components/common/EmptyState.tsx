import type { ReactNode } from "react";

type EmptyStateProps = {
  title?: string;
  text: string;
  icon?: ReactNode;
  compact?: boolean;
  className?: string;
};

export function EmptyState({ title, text, icon, compact = false, className = "" }: EmptyStateProps) {
  return (
    <div className={`empty-state ${compact ? "is-compact" : ""} ${className}`.trim()}>
      {icon ? <div className="empty-state-icon">{icon}</div> : null}
      {title ? <div className="empty-state-title">{title}</div> : null}
      <div className="empty-state-text">{text}</div>
    </div>
  );
}
