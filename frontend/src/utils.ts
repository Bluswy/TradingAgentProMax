import type { ReportSection } from "./types";

export function formatDate(ts?: number | null): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN");
}

export function formatDateMinute(ts?: number | null): string {
  if (!ts) return "-";
  const date = new Date(ts * 1000);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}`;
}

export function formatDuration(ms?: number | null): string {
  if (ms === undefined || ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function statusClass(status?: string | null): string {
  switch (status) {
    case "running":
    case "run_started":
    case "step_started":
    case "node_started":
      return "is-running";
    case "success":
    case "run_finished":
    case "step_finished":
    case "node_finished":
      return "is-success";
    case "failed":
    case "step_failed":
    case "node_failed":
      return "is-failed";
    default:
      return "is-queued";
  }
}

export function safeStringify(value: unknown, limit = 600): string {
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  } catch {
    const text = String(value);
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }
}

const NODE_LABELS: Record<string, string> = {
  company_context: "公司上下文",
  technical: "技术分析",
  fundamental: "基本面分析",
  event_news: "事件新闻",
  sector_flow: "板块资金面",
  collect_results: "汇总结果",
  strategy_style: "策略范式",
  dispatch_post_strategy: "后处理分发",
  strategy_decision: "策略决策",
  company_report: "公司报告",
  collect_postprocess: "后处理汇总",
  final_report: "最终报告",
};

const EVENT_LABELS: Record<string, string> = {
  run_started: "开始执行",
  run_finished: "研究完成",
  step_started: "执行中",
  step_finished: "已完成",
  step_failed: "执行失败",
  node_started: "节点启动",
  node_finished: "节点完成",
  node_failed: "节点失败",
  artifact_written: "产物写入",
};

const AGENT_LABELS: Record<string, string> = {
  StructuredAnalysisGraph: "研究流程",
  TechnicalAgent: "技术分析",
  FundamentalAgent: "基本面分析",
  EventNewsAgent: "事件新闻",
  SectorFlowAgent: "板块资金面",
  StrategyStyleAgent: "策略框架",
  StrategyDecisionAgent: "形成结论",
  CompanyAnalysisReportAgent: "完整报告",
};

export function displayNodeName(nodeName?: string | null): string {
  if (!nodeName) return "未知节点";
  return NODE_LABELS[nodeName] || nodeName;
}

export function displayEventType(eventType?: string | null): string {
  if (!eventType) return "未知事件";
  return EVENT_LABELS[eventType] || eventType;
}

export function displayAgentName(agentName?: string | null): string {
  if (!agentName) return "研究引擎";
  return AGENT_LABELS[agentName] || agentName;
}

export function displayResearchStatus(status?: string | null, runStatus?: string | null): string {
  const normalized = runStatus === "running" ? "running" : status;
  switch (normalized) {
    case "draft":
      return "待补充";
    case "ready":
      return "待确认";
    case "running":
      return "进行中";
    case "completed":
    case "success":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return "处理中";
  }
}

export function compactSummary(value: unknown, limit = 120): string {
  if (value === null || value === undefined) return "等待输出";
  if (typeof value === "string") {
    return value.length > limit ? `${value.slice(0, limit)}...` : value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const text = value
      .slice(0, 3)
      .map((item) => compactSummary(item, 40))
      .join(" / ");
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== null && item !== undefined && item !== "")
      .slice(0, 3)
      .map(([key, item]) => `${key}: ${compactSummary(item, 36)}`);
    const text = entries.join(" · ");
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }
  return String(value);
}

export function stripMarkdownDecorators(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/[*_`>#]/g, "")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .trim();
}

export function extractCompanyName(raw?: string | null): string {
  if (!raw) return "";
  const cleaned = stripMarkdownDecorators(raw)
    .replace(/（.*$/, "")
    .replace(/\(.*$/, "")
    .replace(/分析报告.*$/, "")
    .replace(/综合报告.*$/, "")
    .trim();
  return cleaned;
}

export function readableAction(action?: string | null): string {
  switch (action) {
    case "buy":
      return "买入";
    case "sell":
      return "卖出";
    case "hold":
      return "继续持有";
    case "wait":
      return "等待验证";
    default:
      return action || "-";
  }
}

export function extractReportSections(markdown: string | undefined | null): ReportSection[] {
  if (!markdown) return [];
  const lines = markdown.split("\n");
  const sections: ReportSection[] = [];
  let currentTitle = "报告概览";
  let currentBody: string[] = [];

  const pushSection = () => {
    if (!currentBody.length && sections.length) return;
    const id = currentTitle
      .toLowerCase()
      .replace(/[^\u4e00-\u9fa5a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "");
    sections.push({
      id: id || `section-${sections.length + 1}`,
      title: currentTitle,
      body: currentBody.join("\n").trim(),
    });
  };

  for (const line of lines) {
    const match = line.match(/^##\s+(.+)$/);
    if (match) {
      pushSection();
      currentTitle = match[1].trim();
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  pushSection();
  return sections.filter((section) => section.title || section.body);
}
