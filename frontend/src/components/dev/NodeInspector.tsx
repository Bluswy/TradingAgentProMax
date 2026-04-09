import { useEffect, useMemo, useState } from "react";
import type { NodeDetail } from "../../types";
import { displayNodeName } from "../../utils";
import { PanelCard } from "../common/PanelCard";
import { SectionHeader } from "../common/SectionHeader";
import { ArtifactPanel } from "./ArtifactPanel";
import { ErrorPanel } from "./ErrorPanel";
import { NodeSummaryPanel } from "./NodeSummaryPanel";
import { StepTracePanel } from "./StepTracePanel";

type NodeInspectorProps = {
  selectedNodeName: string | null;
  nodeDetail: NodeDetail | null;
};

type InspectorTab = "summary" | "steps" | "artifacts" | "error";

const TAB_LABELS: Record<InspectorTab, string> = {
  summary: "概览",
  steps: "步骤",
  artifacts: "产物",
  error: "错误",
};

export function NodeInspector({ selectedNodeName, nodeDetail }: NodeInspectorProps) {
  const availableTabs = useMemo<InspectorTab[]>(() => {
    const tabs: InspectorTab[] = ["summary"];
    if (nodeDetail?.steps?.length) tabs.push("steps");
    if (nodeDetail?.artifacts?.length) tabs.push("artifacts");
    if (nodeDetail?.node?.error) tabs.push("error");
    return tabs;
  }, [nodeDetail]);
  const [tab, setTab] = useState<InspectorTab>("summary");
  useEffect(() => {
    setTab("summary");
  }, [selectedNodeName]);

  const activeTab = availableTabs.includes(tab) ? tab : availableTabs[0] || "summary";

  return (
    <PanelCard className="inspector-card">
      <SectionHeader
        title="节点详情"
        right={<span className="signal-pill">{displayNodeName(selectedNodeName)}</span>}
      />
      <div className="inspector-tabs">
        {availableTabs.map((item) => (
          <button
            key={item}
            className={`inspector-tab ${activeTab === item ? "is-active" : ""}`}
            onClick={() => setTab(item)}
            aria-pressed={activeTab === item}
          >
            {TAB_LABELS[item]}
          </button>
        ))}
      </div>
      <div className="inspector-body">
        <div key={`${selectedNodeName || "empty"}-${activeTab}`} className="inspector-pane">
          {activeTab === "summary" ? <NodeSummaryPanel nodeDetail={nodeDetail} /> : null}
          {activeTab === "steps" ? <StepTracePanel nodeDetail={nodeDetail} /> : null}
          {activeTab === "artifacts" ? <ArtifactPanel nodeDetail={nodeDetail} /> : null}
          {activeTab === "error" ? <ErrorPanel nodeDetail={nodeDetail} /> : null}
        </div>
      </div>
    </PanelCard>
  );
}
