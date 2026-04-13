import type { HTMLAttributes, ReactNode } from "react";

type PanelCardProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
};

export function PanelCard({ children, className = "", ...props }: PanelCardProps) {
  return (
    <div {...props} className={`panel-card ${className}`.trim()}>
      {children}
    </div>
  );
}
