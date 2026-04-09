import type { NodeDetail } from "../../types";
import { safeStringify } from "../../utils";
import { EmptyState } from "../common/EmptyState";

type ErrorPanelProps = {
  nodeDetail: NodeDetail | null;
};

export function ErrorPanel({ nodeDetail }: ErrorPanelProps) {
  if (!nodeDetail?.node?.error) {
    return <EmptyState text="当前节点没有报错" />;
  }

  return (
    <div className="step-item">
      <div className="subsection-title">错误详情</div>
      <div className="result-meta">{safeStringify(nodeDetail.node.error, 1200)}</div>
    </div>
  );
}
