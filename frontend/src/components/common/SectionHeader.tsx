import type { ReactNode } from "react";

type SectionHeaderProps = {
  title: string;
  subtitle?: string;
  right?: ReactNode;
};

export function SectionHeader({ title, subtitle, right }: SectionHeaderProps) {
  return (
    <header className="panel-header">
      <div>
        <h2 className="panel-title">{title}</h2>
        {subtitle ? <div className="panel-subtitle">{subtitle}</div> : null}
      </div>
      {right}
    </header>
  );
}
