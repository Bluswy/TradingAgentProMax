import type { NodeDetail } from "../../types";
import { compactSummary, formatDuration, safeStringify } from "../../utils";
import { EmptyState } from "../common/EmptyState";
import { StatusBadge } from "../common/StatusBadge";

type NodeSummaryPanelProps = {
  nodeDetail: NodeDetail | null;
};

export function NodeSummaryPanel({ nodeDetail }: NodeSummaryPanelProps) {
  if (!nodeDetail) {
    return <EmptyState text="选择一个节点查看执行详情" />;
  }

  return (
    <div className="step-item">
      <div className="section-row">
        <div className="subsection-title">节点概览</div>
        <StatusBadge status={nodeDetail.node.status} />
      </div>
      <div className="event-meta">
        {formatDuration(nodeDetail.node.duration_ms)} · {nodeDetail.node.node_name}
      </div>
      <div className="result-meta">{compactSummary(nodeDetail.node.output_summary || nodeDetail.node.input_summary, 220)}</div>
      <details className="raw-json-block">
        <summary>查看完整输入 / 输出</summary>
        <div className="result-meta">{safeStringify(nodeDetail.node.output_summary || nodeDetail.node.input_summary)}</div>
      </details>
    </div>
  );
}
