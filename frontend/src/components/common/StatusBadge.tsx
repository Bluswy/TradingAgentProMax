import { statusClass } from "../../utils";

type StatusBadgeProps = {
  status?: string | null;
  label?: string;
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const text = label || status || "queued";
  return <span className={`status-badge ${statusClass(status || label || "queued")}`}>{text}</span>;
}
