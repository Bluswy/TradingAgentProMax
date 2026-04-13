import type { CSSProperties } from "react";
import type { EventItem, GraphNode, Research } from "../../types";
import { displayResearchStatus, statusClass } from "../../utils";

type FlowStatus = "queued" | "running" | "success" | "failed";

type FlowLeafConfig = {
  id: string;
  label: string;
  nodeKeys: string[];
};

type FlowStageConfig =
  | {
      id: string;
      label: string;
      kind: "single";
      nodeKeys: string[];
    }
  | {
      id: string;
      label: string;
      kind: "parallel";
      children: FlowLeafConfig[];
    };

type FlowLeafView = FlowLeafConfig & {
  status: FlowStatus;
};

type FlowStageView =
  | {
      id: string;
      label: string;
      kind: "single";
      status: FlowStatus;
    }
  | {
      id: string;
      label: string;
      kind: "parallel";
      status: FlowStatus;
      children: FlowLeafView[];
      completedCount: number;
      totalCount: number;
    };

type ResearchFlowProps = {
  companyName: string;
  research: Research | null;
  events: EventItem[];
  runNodes: GraphNode[];
};

type FlowStyle = CSSProperties & {
  "--flow-order": number;
};

const RESEARCH_FLOW_CONFIG: FlowStageConfig[] = [
  {
    id: "identify",
    label: "确认研究对象",
    kind: "single",
    nodeKeys: ["company_context"],
  },
  {
    id: "analysis",
    label: "并行分析",
    kind: "parallel",
    children: [
      { id: "technical", label: "技术分析", nodeKeys: ["technical"] },
      { id: "fundamental", label: "基本面分析", nodeKeys: ["fundamental"] },
      { id: "sector_flow", label: "板块资金面", nodeKeys: ["sector_flow"] },
      { id: "event_news", label: "事件新闻", nodeKeys: ["event_news"] },
    ],
  },
  {
    id: "outputs",
    label: "输出结果",
    kind: "parallel",
    children: [
      {
        id: "decision",
        label: "形成研究结论",
        nodeKeys: ["collect_results", "strategy_style", "dispatch_post_strategy", "strategy_decision"],
      },
      {
        id: "report",
        label: "生成完整报告",
        nodeKeys: ["company_report", "collect_postprocess", "final_report"],
      },
    ],
  },
];

function eventToStatus(eventType?: string | null): FlowStatus {
  switch (eventType) {
    case "step_started":
    case "run_started":
      return "running";
    case "step_finished":
    case "run_finished":
      return "success";
    case "step_failed":
      return "failed";
    default:
      return "queued";
  }
}

function nodeToStatus(status?: string | null): FlowStatus {
  switch (status) {
    case "running":
      return "running";
    case "success":
      return "success";
    case "failed":
      return "failed";
    default:
      return "queued";
  }
}

function mergeStatuses(statuses: FlowStatus[]): FlowStatus {
  if (statuses.some((status) => status === "failed")) return "failed";
  if (statuses.some((status) => status === "running")) return "running";
  if (statuses.length > 0 && statuses.every((status) => status === "success")) return "success";
  if (statuses.some((status) => status === "success")) return "running";
  return "queued";
}

function statusLabel(status: FlowStatus): string {
  switch (status) {
    case "running":
      return "进行中";
    case "success":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return "未开始";
  }
}

function buildNodeStatusMap(runNodes: GraphNode[], events: EventItem[]): Map<string, FlowStatus> {
  const map = new Map<string, FlowStatus>();
  runNodes.forEach((node) => {
    if (!node.node_name) return;
    map.set(node.node_name, nodeToStatus(node.status));
  });
  [...events]
    .reverse()
    .filter((event) => ["step_started", "step_finished", "step_failed"].includes(event.event_type))
    .forEach((event) => {
      if (!event.node_name) return;
      map.set(event.node_name, eventToStatus(event.event_type));
    });
  return map;
}

function resolveLeafStatus(nodeStatusMap: Map<string, FlowStatus>, nodeKeys: string[]): FlowStatus {
  const statuses = nodeKeys.map((nodeKey) => nodeStatusMap.get(nodeKey) || "queued");
  return mergeStatuses(statuses);
}

function buildFlowStages(runNodes: GraphNode[], events: EventItem[]): FlowStageView[] {
  const nodeStatusMap = buildNodeStatusMap(runNodes, events);
  return RESEARCH_FLOW_CONFIG.map((stage) => {
    if (stage.kind === "single") {
      return {
        id: stage.id,
        label: stage.label,
        kind: "single",
        status: resolveLeafStatus(nodeStatusMap, stage.nodeKeys),
      };
    }

    const children = stage.children.map((child) => ({
      ...child,
      status: resolveLeafStatus(nodeStatusMap, child.nodeKeys),
    }));

    return {
      id: stage.id,
      label: stage.label,
      kind: "parallel",
      status: mergeStatuses(children.map((child) => child.status)),
      children,
      completedCount: children.filter((child) => child.status === "success").length,
      totalCount: children.length,
    };
  });
}

function buildProgressSummary(stages: FlowStageView[]): string {
  const leafStages: Array<{ status: FlowStatus }> = [];
  stages.forEach((stage) => {
    if (stage.kind === "parallel") {
      leafStages.push(...stage.children);
      return;
    }
    leafStages.push(stage);
  });
  const completedCount = leafStages.filter((stage) => stage.status === "success").length;
  const totalCount = leafStages.length;
  const activeParallelStage = stages.find((stage) => stage.kind === "parallel" && stage.status === "running");

  if (activeParallelStage && activeParallelStage.kind === "parallel") {
    return `已完成 ${completedCount} / ${totalCount} 个步骤`;
  }

  return `已完成 ${completedCount} / ${totalCount} 个步骤`;
}

function flattenLeafStages(stages: FlowStageView[]): Array<{ id: string; label: string; status: FlowStatus }> {
  const leaves: Array<{ id: string; label: string; status: FlowStatus }> = [];
  stages.forEach((stage) => {
    if (stage.kind === "parallel") {
      stage.children.forEach((child) => leaves.push({ id: child.id, label: child.label, status: child.status }));
      return;
    }
    leaves.push({ id: stage.id, label: stage.label, status: stage.status });
  });
  return leaves;
}

function buildCurrentProgress(stages: FlowStageView[]): string {
  const leaves = flattenLeafStages(stages);
  const running = leaves.filter((item) => item.status === "running");
  if (running.length > 1) {
    return `当前进度：${running.map((item) => item.label).join("、")}同步进行`;
  }
  if (running.length === 1) {
    return `当前进度：正在${running[0].label}`;
  }
  const failed = leaves.find((item) => item.status === "failed");
  if (failed) {
    return `当前进度：${failed.label}执行失败`;
  }
  const completedCount = leaves.filter((item) => item.status === "success").length;
  return `研究进度：已完成 ${completedCount} / ${leaves.length} 个步骤`;
}

function flowStyle(order: number): FlowStyle {
  return { "--flow-order": order };
}

export function ResearchFlow({ companyName, research, events, runNodes }: ResearchFlowProps) {
  const stages = buildFlowStages(runNodes, events);
  const summary = buildProgressSummary(stages);
  const currentProgress = buildCurrentProgress(stages);
  const researchState = displayResearchStatus(research?.status, research?.run_status);
  const stateClass = statusClass(research?.run_status === "running" ? "running" : research?.status);
  const identifyStage = stages[0];
  const analysisStage = stages[1];
  const outputsStage = stages[2];
  const analysisVisible =
    analysisStage?.kind === "parallel" &&
    (analysisStage.children.some((child) => child.status !== "queued") ||
      (identifyStage?.kind === "single" && identifyStage.status === "success"));
  const allAnalysisCompleted =
    analysisStage?.kind === "parallel" && analysisStage.children.length > 0 && analysisStage.children.every((child) => child.status === "success");
  const outputChildren = outputsStage?.kind === "parallel" ? outputsStage.children : [];
  const decisionStep = outputChildren[0];
  const reportStep = outputChildren[1];
  const decisionVisible = Boolean(decisionStep && (decisionStep.status !== "queued" || allAnalysisCompleted));
  const reportVisible = Boolean(reportStep && (reportStep.status !== "queued" || decisionStep?.status === "success"));

  return (
    <div className="research-live-card" role="status" aria-live="polite">
      <div className="research-live-head">
        <div className="research-live-title-wrap">
          <div className="research-live-title">正在研究 {companyName}</div>
          <div className="research-live-summary">{currentProgress}</div>
          <div className="research-live-subsummary">{summary}</div>
        </div>
        <div className={`research-live-state ${stateClass}`.trim()}>
          <span className="research-live-state-dot" aria-hidden="true" />
          <span>{researchState}</span>
        </div>
      </div>

      <div className="research-flow">
        {identifyStage?.kind === "single" ? (
          <div className={`research-flow-row ${statusClass(identifyStage.status)}`.trim()} style={flowStyle(0)}>
            <div className="research-flow-row-main">
              <span className="research-live-item-dot" aria-hidden="true" />
              <span className="research-flow-row-title">{identifyStage.label}</span>
            </div>
            <span className="research-flow-row-status">{statusLabel(identifyStage.status)}</span>
          </div>
        ) : null}

        {analysisVisible && analysisStage?.kind === "parallel" ? (
          <div className="research-flow-cluster">
            <div className="research-flow-parallel-grid">
              {analysisStage.children.map((child, childIndex) => (
                <div
                  key={child.id}
                  className={`research-flow-card ${statusClass(child.status)}`.trim()}
                  style={flowStyle(childIndex + 1)}
                >
                  <div className="research-flow-card-main">
                    <span className="research-live-item-dot" aria-hidden="true" />
                    <span className="research-flow-card-title">{child.label}</span>
                  </div>
                  <span className="research-flow-card-status">{statusLabel(child.status)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {decisionVisible && decisionStep ? (
          <div className={`research-flow-row ${statusClass(decisionStep.status)}`.trim()} style={flowStyle(5)}>
            <div className="research-flow-row-main">
              <span className="research-live-item-dot" aria-hidden="true" />
              <span className="research-flow-row-title">{decisionStep.label}</span>
            </div>
            <span className="research-flow-row-status">{statusLabel(decisionStep.status)}</span>
          </div>
        ) : null}

        {reportVisible && reportStep ? (
          <div className={`research-flow-row ${statusClass(reportStep.status)}`.trim()} style={flowStyle(6)}>
            <div className="research-flow-row-main">
              <span className="research-live-item-dot" aria-hidden="true" />
              <span className="research-flow-row-title">{reportStep.label}</span>
            </div>
            <span className="research-flow-row-status">{statusLabel(reportStep.status)}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
