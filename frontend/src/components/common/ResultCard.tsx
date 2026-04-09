import { MarkdownContent } from "./MarkdownContent";

type ResultCardProps = {
  label: string;
  value: string;
  meta: string;
};

export function ResultCard({ label, value, meta }: ResultCardProps) {
  return (
    <div className="result-card">
      <div className="result-label">{label}</div>
      <div className="result-value">{value}</div>
      <MarkdownContent className="result-meta markdown-compact" content={meta} />
    </div>
  );
}
