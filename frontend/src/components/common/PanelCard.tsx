import type { ReactNode } from "react";

type PanelCardProps = {
  children: ReactNode;
  className?: string;
};

export function PanelCard({ children, className = "" }: PanelCardProps) {
  return <div className={`panel-card ${className}`.trim()}>{children}</div>;
}
