import type { NodeDetail, RunDetail } from "../../types";
import type { CSSProperties } from "react";
import { displayNodeName, formatDuration } from "../../utils";
import { AlertTriangleIcon } from "../common/Icons";
import { DagView } from "./DagView";
import { NodeInspector } from "./NodeInspector";
import { PanelCard } from "../common/PanelCard";
import { SectionHeader } from "../common/SectionHeader";

type DevWorkspaceProps = {
  runDetail: RunDetail | null;
  selectedNodeName: string | null;
  nodeDetail: NodeDetail | null;
  onSelectNode: (nodeName: string) => void;
};

export function DevWorkspace({ runDetail, selectedNodeName, nodeDetail, onSelectNode }: DevWorkspaceProps) {
  const nodes = runDetail?.graph.nodes || [];
  const maxDuration = Math.max(...nodes.map((item) => item.duration_ms || 0), 1);
  const longestDuration = Math.max(...nodes.map((item) => item.duration_ms || 0), 0);

  return (
    <section className="workspace-pane is-active">
      <div className="dev-grid">
        <PanelCard className="dev-graph-panel">
          <SectionHeader title="执行流程图" />
          <DagView runDetail={runDetail} selectedNodeName={selectedNodeName} onSelectNode={onSelectNode} />
        </PanelCard>

        <div className="dev-side">
          <NodeInspector selectedNodeName={selectedNodeName} nodeDetail={nodeDetail} />
        </div>

        <PanelCard className="dev-timeline-panel">
          <SectionHeader title="执行时间线" />
          <div className="timeline-panel">
            {nodes.map((node) => {
              const width = Math.max(0.06, (node.duration_ms || 0) / maxDuration);
              const isLongest = Boolean(node.duration_ms) && node.duration_ms === longestDuration && longestDuration > 0;
              return (
                <div key={node.node_name} className="timeline-row">
                  <div className="timeline-meta">{displayNodeName(node.node_name)}</div>
                  <div className="timeline-bar-track">
                    <div
                      className={`timeline-bar ${node.status || "queued"} ${isLongest ? "is-longest" : ""}`.trim()}
                      style={{ "--timeline-scale": width } as CSSProperties}
                    />
                  </div>
                  <div className={`timeline-value ${isLongest ? "is-alert" : ""}`.trim()}>
                    {isLongest ? <AlertTriangleIcon className="status-icon" /> : null}
                    <span>{formatDuration(node.duration_ms)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </PanelCard>
      </div>
    </section>
  );
}
