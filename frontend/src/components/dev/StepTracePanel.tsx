import type { NodeDetail } from "../../types";
import { compactSummary, formatDuration, safeStringify } from "../../utils";
import { EmptyState } from "../common/EmptyState";
import { StatusBadge } from "../common/StatusBadge";

type StepTracePanelProps = {
  nodeDetail: NodeDetail | null;
};

export function StepTracePanel({ nodeDetail }: StepTracePanelProps) {
  if (!nodeDetail?.steps?.length) {
    return <EmptyState text="当前节点还没有执行步骤" />;
  }

  return (
    <>
      {nodeDetail.steps.map((step) => (
        <div key={step.step_id} className="step-item">
          <div className="section-row">
            <div className="subsection-title">{step.step_name}</div>
            <StatusBadge status={step.status} />
          </div>
          <div className="step-meta">
            {step.step_type} · {formatDuration(step.duration_ms)}
          </div>
          <div className="result-meta">{compactSummary(step.output || step.input, 180)}</div>
          <details className="raw-json-block">
            <summary>查看完整步骤数据</summary>
            <div className="result-meta">{safeStringify(step.output || step.input)}</div>
          </details>
        </div>
      ))}
    </>
  );
}
