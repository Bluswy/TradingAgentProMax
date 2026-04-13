import { Suspense, lazy, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import type {
  DecisionEvidence,
  DecisionWatchItem,
  EventItem,
  GraphNode,
  ModuleContribution,
  ReportSection,
  Research,
  ResearchMessage,
  ResearchParseResult,
  Run,
  StructuredInvalidation,
  StructuredRisk,
} from "../../types";
import { formatDate, readableAction } from "../../utils";
import { MessageSquareIcon, SendIcon } from "../common/Icons";
import { EmptyState } from "../common/EmptyState";
import { MarkdownContent } from "../common/MarkdownContent";
import { PanelCard } from "../common/PanelCard";
import { ResearchFlow } from "./ResearchFlow";
import { SectionHeader } from "../common/SectionHeader";

const ReportNavigator = lazy(async () => import("./ReportNavigator").then((module) => ({ default: module.ReportNavigator })));

type LooseRecord = Record<string, unknown>;

type UserWorkspaceProps = {
  research: Research | null;
  run: Run | null;
  company: LooseRecord;
  companyDisplayName?: string;
  technical: LooseRecord;
  fundamental: LooseRecord;
  eventNews: LooseRecord;
  sectorFlow: LooseRecord;
  strategy: LooseRecord;
  decision: LooseRecord;
  parseResult: ResearchParseResult | null;
  messages: ResearchMessage[];
  events: EventItem[];
  runNodes: GraphNode[];
  chatInput: string;
  chatLoading: boolean;
  isParsingResearch: boolean;
  isStartingResearch: boolean;
  onConfirmResearch: () => void;
  setChatInput: (value: string) => void;
  onSendChat: () => void;
  reportSections: ReportSection[];
  reportNotice?: string | null;
};

type ModuleDetailSection = {
  key: string;
  label: string;
  summary: string;
  summaryItems: { key: string; label: string; conclusion: string; rationale: string }[];
  insights: { label: string; value: string }[];
};

function resolveActionTone(action?: string | null) {
  switch (action) {
    case "buy":
    case "hold":
      return "tone-positive";
    case "sell":
      return "tone-negative";
    case "wait":
      return "tone-wait";
    default:
      return "tone-neutral";
  }
}

function asRecord(value: unknown): LooseRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as LooseRecord) : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readRecordArray<T extends LooseRecord = LooseRecord>(value: unknown): T[] {
  return Array.isArray(value)
    ? value.filter((item): item is T => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

const MODULE_LABELS: Record<string, string> = {
  technical: "技术",
  fundamental: "基本面",
  event_news: "事件",
  sector_flow: "资金面",
};

const STANCE_LABELS: Record<string, string> = {
  supporting: "支撑",
  neutral: "中性",
  conflicting: "拖累",
};

const HORIZON_LABELS: Record<string, string> = {
  short_term: "短期",
  medium_term: "中期",
  long_term: "长期",
};

const PRIORITY_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

const POSITIONING_LABELS: Record<string, string> = {
  aggressive: "激进",
  balanced: "均衡",
  conservative: "保守",
};

function firstNonEmpty(...values: unknown[]): string {
  for (const value of values) {
    const text = readString(value);
    if (text) return text;
  }
  return "";
}

function firstTextFromStringArray(value: unknown): string {
  return readStringArray(value)[0] || "";
}

const MODULE_SUMMARY_LABELS: Record<string, { key: string; label: string }[]> = {
  technical: [
    { key: "trend", label: "趋势" },
    { key: "momentum", label: "动量" },
    { key: "volume_confirmation", label: "量价" },
    { key: "key_levels", label: "关键位" },
  ],
  fundamental: [
    { key: "growth", label: "增长" },
    { key: "profitability", label: "盈利" },
    { key: "cashflow_quality", label: "现金流" },
    { key: "valuation", label: "估值" },
  ],
  event_news: [
    { key: "event_bias", label: "事件倾向" },
    { key: "core_catalyst", label: "核心催化" },
    { key: "bullish_factor", label: "利好" },
    { key: "bearish_factor", label: "利空" },
  ],
  sector_flow: [
    { key: "theme_strength", label: "板块强弱" },
    { key: "theme_heat", label: "热度" },
    { key: "crowding", label: "拥挤" },
    { key: "stock_role_in_theme", label: "个股位置" },
  ],
};

function readModuleSummaryItems(
  moduleKey: keyof typeof MODULE_SUMMARY_LABELS,
  value: unknown,
): { key: string; label: string; conclusion: string; rationale: string }[] {
  const items = Array.isArray(value)
    ? value.filter((item): item is LooseRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
  const itemMap = new Map(
    items.map((item) => [
      readString(item.key),
      {
        conclusion: readString(item.conclusion_zh),
        rationale: readString(item.rationale_zh),
      },
    ]),
  );
  return MODULE_SUMMARY_LABELS[moduleKey].map((spec) => {
    const current = itemMap.get(spec.key);
    return {
      key: spec.key,
      label: spec.label,
      conclusion: current?.conclusion || "待补充",
      rationale: current?.rationale || "该项解释生成中，请稍后查看。",
    };
  });
}

function compactInsights(items: { label: string; value: string }[]): { label: string; value: string }[] {
  return items.filter((item) => item.value).slice(0, 2);
}

function sanitizeStatusMessage(content: string, kind: string | null): string {
  if (kind !== "failed") return content;
  const text = content.trim();
  if (!text) return "这次分析未完成，请补充更明确的问题后重新发送。";
  if (/Error code:|AllocationQuota|request_id|chatcmpl-|free tier|trace|Traceback|stack/i.test(text)) {
    return "这次分析未完成，请稍后重试，或补充更明确的公司、时间和问题后重新发送。";
  }
  if (text.length > 140) {
    return "这次分析未完成，请补充更明确的问题后重新发送。";
  }
  return text;
}

export function UserWorkspace({
  research,
  run,
  company,
  companyDisplayName,
  technical,
  fundamental,
  eventNews,
  sectorFlow,
  strategy,
  decision,
  parseResult,
  messages,
  events,
  runNodes,
  chatInput,
  chatLoading,
  isParsingResearch,
  isStartingResearch,
  onConfirmResearch,
  setChatInput,
  onSendChat,
  reportSections,
  reportNotice,
}: UserWorkspaceProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const starterExamples = [
    "分析一下通富微电现在是否值得继续持有",
    "贵州茅台短期还有没有回调风险",
    "对比一下宁德时代和比亚迪当前更适合配置哪一家",
  ];
  const onboardingHighlights = [
    { label: "输入方式", text: "自然语言、公司简称或股票代码都可以。" },
    { label: "看到初步结论", text: "通常 2 到 3 分钟内可获取判断、风险和后续关注点。" },
    { label: "继续追问", text: "分析完成后，可以继续追问依据、催化和失效条件。" },
  ];
  const companyIdentity = asRecord(company.identity);
  const decisionInfo = asRecord(decision.decision);
  const executionPlan = asRecord(decision.execution_plan);
  const primaryStrategy = asRecord(strategy.primary_strategy);
  const topSupportingEvidence = readRecordArray<DecisionEvidence>(decision.top_supporting_evidence);
  const watchlist = readRecordArray<DecisionWatchItem>(decision.watchlist);
  const invalidationsStructured = readRecordArray<StructuredInvalidation>(decision.invalidations_structured);
  const primaryRiskRecord = asRecord(decision.primary_risk) as StructuredRisk | null;
  const secondaryRisks = readRecordArray<StructuredRisk>(decision.secondary_risks);
  const moduleContributionMap = asRecord(decision.module_contributions);
  const rationale = asRecord(decision.decision_rationale);
  const supportingEvidenceFallback = readStringArray(rationale?.supporting_evidence);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "0px";
    const nextHeight = Math.min(element.scrollHeight, 144);
    element.style.height = `${nextHeight}px`;
    element.style.overflowY = element.scrollHeight > 144 ? "auto" : "hidden";
  }, [chatInput]);

  const companyName =
    companyDisplayName ||
    readString(companyIdentity?.company_name) ||
    readString(company.company_name) ||
    readString(company.name) ||
    readString(company.security_name) ||
    readString(company.ticker) ||
    (research?.title && research.title !== "新的研究" ? research.title : "") ||
    readString(run?.input_summary?.ticker) ||
    "新的研究";
  const action = readString(decisionInfo?.action) || null;
  const actionLabel = readString(decisionInfo?.label_zh) || readableAction(action);
  const actionTone = resolveActionTone(action);
  const heroSummary =
    readString(decisionInfo?.summary) ||
    readString(primaryStrategy?.summary) ||
    "研究结论仍在生成，验证完成后会先在这里给出核心判断。";
  const heroMetaItems = [
    { label: "周期", value: HORIZON_LABELS[readString(executionPlan?.horizon)] || "待判断", tone: "is-muted" },
    { label: "优先级", value: PRIORITY_LABELS[readString(executionPlan?.priority)] || "待判断", tone: "is-accent" },
    { label: "仓位倾向", value: POSITIONING_LABELS[readString(executionPlan?.positioning_bias)] || "待判断", tone: "is-warm" },
  ];
  const derivedEvidence =
    topSupportingEvidence.length > 0
      ? topSupportingEvidence.slice(0, 3).map((item, index) => ({
          key: `${item.module || "evidence"}-${index}`,
          module: MODULE_LABELS[readString(item.module)] || "综合",
          title: readString(item.title) || `依据 ${index + 1}`,
          fact: readString(item.fact),
          importance: readNumber(item.importance),
        }))
      : supportingEvidenceFallback.slice(0, 3).map((fact, index) => ({
          key: `fallback-${index}`,
          module: "综合",
          title: `依据 ${index + 1}`,
          fact,
          importance: null,
        }));
  const fallbackEvidence = {
    key: "empty",
    module: "综合",
    title: "等待补充",
    fact: "当前还没有形成可展示的关键依据。",
    importance: null,
  };
  const evidenceCards = derivedEvidence.length ? derivedEvidence : [fallbackEvidence];
  const primaryEvidenceCard = evidenceCards[0];
  const supportingEvidenceCards = evidenceCards.slice(1);
  const decisionRiskFlags = readStringArray(decision.risk_flags);
  const decisionInvalidations = readStringArray(decision.invalidations);
  const strategyInvalidations = readStringArray(strategy.invalidations);
  const triggerConditions = readStringArray(decision.trigger_conditions);
  const trackingVariables = readStringArray(strategy.decision_priority_variables);
  const primaryRisk = readString(primaryRiskRecord?.label) || decisionRiskFlags[0] || "当前未识别到显性风险";
  const primaryRiskLevel = readString(primaryRiskRecord?.risk_level);
  const primaryRiskImpactPath = readString(primaryRiskRecord?.impact_path);
  const primaryRiskMeta =
    [primaryRiskImpactPath, ...secondaryRisks.slice(0, 2).map((item) => readString(item.label))]
      .filter(Boolean)
      .join(" / ") || decisionRiskFlags.slice(1, 3).join(" / ");
  const primaryInvalidation =
    readString(invalidationsStructured[0]?.label) || decisionInvalidations[0] || strategyInvalidations[0] || "目前还没有明确失效信号";
  const primaryInvalidationCondition = readString(invalidationsStructured[0]?.condition);
  const primaryInvalidationAction =
    readString(invalidationsStructured[0]?.action_after_trigger) ||
    decisionInvalidations.slice(1, 2).join("") ||
    strategyInvalidations.slice(1, 2).join("");
  const primaryInvalidationMeta =
    [primaryInvalidationCondition, primaryInvalidationAction]
      .filter(Boolean)
      .join(" / ") ||
    decisionInvalidations.slice(1, 3).join(" / ") ||
    strategyInvalidations.slice(1, 3).join(" / ") ||
    "如果出现反向信号，系统会在这里提示。";
  const keyTracking = readString(watchlist[0]?.variable) || trackingVariables[0] || "等待关键变量更新";
  const watchItems =
    watchlist.length > 0
      ? watchlist.slice(0, 3).map((item, index) => ({
          key: `${readString(item.variable) || "watch"}-${index}`,
          variable: readString(item.variable),
          reason: readString(item.reason),
          window: readString(item.window),
          bull: readString(item.bull_case_if_met),
          bear: readString(item.bear_case_if_missed),
        }))
      : (trackingVariables.length ? trackingVariables : triggerConditions).slice(0, 3).map((item, index) => ({
          key: `watch-fallback-${index}`,
          variable: item,
          reason: "",
          window: "",
          bull: "",
          bear: "",
        }));
  const fallbackWatchItem = {
    key: "watch-empty",
    variable: triggerConditions[0] || "等待新的触发信号",
    reason: "",
    window: "",
    bull: "",
    bear: "",
  };
  const decisionWatchItems = watchItems.length ? watchItems : [fallbackWatchItem];
  const primaryWatchItem = decisionWatchItems[0];
  const supportingWatchItems = decisionWatchItems.slice(1);
  const moduleCards = ["technical", "fundamental", "event_news", "sector_flow"].map((moduleKey) => {
    const record = asRecord(moduleContributionMap?.[moduleKey]) as ModuleContribution | null;
    const stance = readString(record?.stance) || "neutral";
    const weight = readNumber(record?.weight);
    return {
      key: moduleKey,
      label: MODULE_LABELS[moduleKey] || moduleKey,
      stanceLabel: STANCE_LABELS[stance] || "中性",
      stanceTone: `tone-${stance}`,
      summary: readString(record?.summary) || "等待结构化模块贡献评估",
      weightText: weight !== null ? `${Math.round(weight * 100)}%` : "--",
    };
  });
  const [selectedModuleKey, setSelectedModuleKey] = useState<string>("technical");
  const moduleDetails = useMemo<Record<string, ModuleDetailSection>>(
    () => ({
      technical: {
        key: "technical",
        label: "技术面",
        summary:
          firstNonEmpty(technical.technical_summary_zh, moduleCards.find((item) => item.key === "technical")?.summary) ||
          "技术面结论尚未形成稳定判断。",
        summaryItems: readModuleSummaryItems("technical", technical.module_summary_items),
        insights: compactInsights([
          {
            label: "趋势判断",
            value: firstNonEmpty(asRecord(technical.trend)?.summary, firstTextFromStringArray(asRecord(technical.trend)?.evidence)),
          },
          {
            label: "节奏确认",
            value: firstNonEmpty(
              asRecord(technical.volume_confirmation)?.summary,
              firstTextFromStringArray(asRecord(technical.volume_confirmation)?.evidence),
              asRecord(technical.momentum)?.summary,
              firstTextFromStringArray(asRecord(technical.momentum)?.evidence),
            ),
          },
        ]),
      },
      fundamental: {
        key: "fundamental",
        label: "基本面",
        summary:
          firstNonEmpty(fundamental.fundamental_summary_zh, moduleCards.find((item) => item.key === "fundamental")?.summary) ||
          "基本面结论尚未形成稳定判断。",
        summaryItems: readModuleSummaryItems("fundamental", fundamental.module_summary_items),
        insights: compactInsights([
          {
            label: "经营判断",
            value: firstNonEmpty(asRecord(fundamental.growth)?.summary, asRecord(fundamental.profitability)?.summary),
          },
          {
            label: "质量与估值",
            value: firstNonEmpty(asRecord(fundamental.valuation)?.summary, asRecord(fundamental.cashflow_quality)?.summary, asRecord(fundamental.balance_sheet_health)?.summary),
          },
        ]),
      },
      event_news: {
        key: "event_news",
        label: "事件",
        summary:
          firstNonEmpty(eventNews.event_summary_zh, moduleCards.find((item) => item.key === "event_news")?.summary) ||
          "事件层暂未形成明确驱动判断。",
        summaryItems: readModuleSummaryItems("event_news", eventNews.module_summary_items),
        insights: compactInsights([
          {
            label: "关键催化",
            value: firstNonEmpty(asRecord(eventNews.event_context_snapshot)?.most_actionable_catalyst, asRecord(eventNews.event_overview)?.summary),
          },
          {
            label: "事件判断",
            value: firstNonEmpty(
              asRecord(eventNews.event_overview)?.summary,
              asRecord(eventNews.event_context_snapshot)?.dominant_driver_type,
              eventNews.event_summary_zh,
            ),
          },
        ]),
      },
      sector_flow: {
        key: "sector_flow",
        label: "资金面",
        summary:
          firstNonEmpty(sectorFlow.flow_summary_zh, moduleCards.find((item) => item.key === "sector_flow")?.summary) ||
          "资金面暂未形成明确交易环境判断。",
        summaryItems: readModuleSummaryItems("sector_flow", sectorFlow.module_summary_items),
        insights: compactInsights([
          {
            label: "板块交易性",
            value: firstNonEmpty(asRecord(sectorFlow.theme_strength)?.summary, asRecord(sectorFlow.theme_heat)?.summary),
          },
          {
            label: "个股位置",
            value: firstNonEmpty(asRecord(sectorFlow.stock_role_in_theme)?.summary, asRecord(sectorFlow.flow_persistence)?.summary),
          },
        ]),
      },
    }),
    [eventNews, fundamental, moduleCards, sectorFlow, technical],
  );
  useEffect(() => {
    const sorted = [...moduleCards].sort((left, right) => {
      const leftWeight = Number.parseFloat(left.weightText) || 0;
      const rightWeight = Number.parseFloat(right.weightText) || 0;
      return rightWeight - leftWeight;
    });
    const preferred = sorted[0]?.key || "technical";
    setSelectedModuleKey((current) => (moduleDetails[current] ? current : preferred));
  }, [moduleCards, moduleDetails]);
  const activeModule = moduleDetails[selectedModuleKey] || moduleDetails.technical;
  const activeModuleCardMeta = moduleCards.find((item) => item.key === activeModule.key) || moduleCards[0];
  const shouldRevealModules = reportSections.length > 0;
  const chatHasValue = Boolean(chatInput.trim());
  const tickerText = readString(run?.input_summary?.ticker) || research?.ticker || readString(company.ticker) || "-";
  const progressFeed = events.filter((event) => ["run_started", "step_started", "step_finished", "step_failed"].includes(event.event_type));
  const isWelcomeState = !research;
  const needsConfirmation = Boolean(parseResult?.needs_confirmation);
  const isResearchBooting = Boolean(research && !research.active_run_id && (isParsingResearch || isStartingResearch) && !needsConfirmation);
  const isBlankResearch = Boolean(research && research.status === "draft" && !research.active_run_id && !isResearchBooting);
  const isReadyResearch = Boolean(research && research.status === "ready" && !research.active_run_id);
  const isFailedResearch = Boolean(research && research.status === "failed");
  const isResearchRunning =
    research?.status === "running" || research?.run_status === "running" || (Boolean(research?.active_run_id) && !shouldRevealModules && progressFeed.length > 0);
  const showDecisionPanel =
    Boolean(
      shouldRevealModules ||
        isResearchRunning ||
        isReadyResearch ||
        research?.status === "completed",
    );
  const canContinueChat = research?.status === "completed" && (!isResearchRunning || shouldRevealModules);
  const composerBusy = chatLoading || isParsingResearch || isStartingResearch;
  const composerDisabled = composerBusy || isResearchRunning;
  const threadTitle =
    isResearchBooting
      ? "正在启动"
      : canContinueChat || isResearchRunning || messages.length || shouldRevealModules
        ? "研究对话"
        : "开始研究";
  const showIdleNote = Boolean(research && research.status === "completed" && !messages.length && !isResearchRunning);
  const composerPlaceholder = !research
      ? "直接输入你的问题，例如：通富微电现在是否值得继续持有"
    : isBlankResearch
      ? "直接输入问题，系统会自动识别公司、代码和时间"
      : isResearchBooting
        ? "正在开始分析，请稍候..."
      : isReadyResearch
        ? "如果识别对象不对，直接补充公司、代码或时间"
      : isFailedResearch
        ? "补充更明确的公司、时间或问题，然后重新发送"
        : !canContinueChat
          ? "分析进行中，完成后可继续追问"
          : "继续追问这次分析，例如风险、依据或触发条件";
  const bootingStatus = isParsingResearch ? "正在识别研究对象" : "正在启动研究";
  const bootingHint = isParsingResearch
    ? "正在识别公司"
    : "识别完成，正在开始分析";
  const pendingQuestion = chatInput.trim();

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!composerDisabled && chatHasValue) {
        onSendChat();
      }
    }
  }

  function focusComposerWithValue(value?: string) {
    if (value !== undefined) {
      setChatInput(value);
    }
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  }

  return (
    <section className="workspace-pane is-active">
      <div className={`user-mode-grid ${showDecisionPanel ? "" : "is-chat-only"}`.trim()}>
        {showDecisionPanel ? (
          <section className="research-decision module-reveal reveal-overview">
            <SectionHeader title="研究结论" />

            {shouldRevealModules ? (
              <div className="research-decision-content research-decision-top">
                <div className="research-decision-header decision-motion decision-motion-header">
                  <div className="research-decision-company-block">
                    <div className="research-decision-company">{companyName}</div>
                    <div className="research-decision-meta">
                      <span className="inline-code">{tickerText}</span>
                      <span>{readString(company.industry) || readString(company.company_type) || "公司研究"}</span>
                      <span className="inline-code">{formatDate(run?.updated_at || run?.finished_at || run?.started_at)}</span>
                    </div>
                  </div>
                  <div className={`strategy-state ${actionTone}`}>{actionLabel}</div>
                </div>

                <div className="research-decision-hero decision-motion decision-motion-hero">
                  <div className="research-decision-main decision-surface">
                    <div className="strategy-label">当前判断</div>
                    <MarkdownContent className="research-decision-summary markdown-large" content={heroSummary} />
                  </div>

                  <div className="research-decision-summary-strip decision-surface">
                    {heroMetaItems.map((item, index) => (
                      <div
                        key={item.label}
                        className={`research-decision-summary-chip ${item.tone}`.trim()}
                        style={{ "--decision-order": index + 1 } as CSSProperties}
                      >
                        <div className="research-decision-summary-label">{item.label}</div>
                        <div className="research-decision-summary-value">{item.value}</div>
                      </div>
                    ))}
                  </div>
                </div>

                <section className="research-risk-guardrail decision-motion decision-motion-risks">
                  <div className="research-risk-guardrail-head">
                    <div className="strategy-label">风险护栏</div>
                    <div className="research-risk-guardrail-copy">先看什么信号会推翻当前判断，再决定是否继续观察。</div>
                  </div>
                  <div className="research-decision-detail-grid">
                    <article className="strategy-card strategy-card-risk decision-surface is-risk" style={{ "--decision-order": 1 } as CSSProperties}>
                      <div className="strategy-risk-head">
                        <div className="strategy-risk-kicker">失效条件</div>
                        {primaryInvalidationAction ? <div className="strategy-risk-pill">触发后：{primaryInvalidationAction}</div> : null}
                      </div>
                      <div className="strategy-value">{primaryInvalidation}</div>
                      <div className="strategy-note">{primaryInvalidationCondition || primaryInvalidationMeta}</div>
                    </article>

                    <article className="strategy-card strategy-card-risk decision-surface is-risk" style={{ "--decision-order": 2 } as CSSProperties}>
                      <div className="strategy-risk-head">
                        <div className="strategy-risk-kicker">核心风险</div>
                        {primaryRiskLevel ? <div className="strategy-risk-pill is-risk-level">{primaryRiskLevel}</div> : null}
                      </div>
                      <div className="strategy-value">{primaryRisk}</div>
                      <div className="strategy-note">{primaryRiskImpactPath || primaryRiskMeta || "如果出现新的风险信号，会优先显示在这里。"}</div>
                    </article>
                  </div>
                </section>
              </div>
            ) : (
              <div className="research-decision-content research-decision-pending">
                <div className="research-decision-header">
                  <div className="research-decision-company-block">
                    <div className="research-decision-company">{companyName}</div>
                    <div className="research-decision-meta">
                      <span className="inline-code">{tickerText}</span>
                      <span>{formatDate(run?.updated_at || run?.started_at || research?.updated_at)}</span>
                    </div>
                  </div>
                  <div className={`strategy-state ${actionTone}`}>{actionLabel}</div>
                </div>
                {!isResearchRunning ? (
                  <div className="research-decision-pending-copy">
                    {isReadyResearch
                      ? "已识别研究对象。信息正确就继续分析；如果不对，直接补充公司、代码或时间。"
                      : "直接输入问题即可。系统会先识别研究对象；只有无法确认时，才会请你补充信息。"}
                  </div>
                ) : null}

                {isReadyResearch ? (
                  <div className="research-live-card" role="status" aria-live="polite">
                    <div className="research-live-head">
                      <div>
                        <div className="research-live-eyebrow">研究对象已识别</div>
                        <div className="research-live-title">{parseResult?.company_name || research?.company_name || companyName}</div>
                      </div>
                      <div className="research-live-state is-success">
                        <span className="research-live-state-dot" aria-hidden="true" />
                        <span>{parseResult?.ticker || research?.ticker || "-"}</span>
                      </div>
                    </div>

                    <div className="research-live-current">
                      <div className="research-live-current-label">已识别信息</div>
                      <div className="research-live-current-value">
                        {(parseResult?.analysis_date || research?.analysis_date || "-") + " · 研究对象已确认"}
                      </div>
                    </div>

                    {parseResult?.clarification_question ? (
                      <div className="thread-inline-note">{parseResult.clarification_question}</div>
                    ) : null}

                    <div className="research-welcome-actions">
                      <button type="button" className="primary-btn" onClick={onConfirmResearch} disabled={isStartingResearch || Boolean(parseResult?.needs_confirmation)}>
                        {isStartingResearch ? "开始中..." : "确认并开始"}
                      </button>
                    </div>
                  </div>
                ) : null}

                {isResearchRunning ? (
                  <ResearchFlow companyName={companyName} research={research} events={progressFeed} runNodes={runNodes} />
                ) : null}
              </div>
            )}
          </section>
        ) : null}

        <PanelCard className="thread-panel conversation-panel module-reveal reveal-strategy">
          <div className="conversation-scroll-region">
            <SectionHeader title={threadTitle} />

            <div className="conversation-thread">
            {isWelcomeState ? (
              <div className="research-welcome-card">
                <div className="research-welcome-copy">
                  <div className="research-welcome-eyebrow">首次使用</div>
                  <div className="research-welcome-title">一句话开始分析，先看到结论，再决定是否深挖</div>
                  <div className="research-welcome-text">
                    直接描述你的问题。我们会自动识别公司、代码和时间，并生成一版适合快速决策的研究结论。
                  </div>
                </div>
                <div className="research-welcome-steps">
                  {onboardingHighlights.map((item, index) => (
                    <div key={item.label} className="research-welcome-step">
                      <span className="research-welcome-step-index">{index + 1}</span>
                      <div className="research-welcome-step-copy">
                        <div className="research-welcome-step-label">{item.label}</div>
                        <div className="research-welcome-step-text">{item.text}</div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="research-starter-hint">试着直接问投资问题。问题越具体，第一次返回的结论越可用。</div>
                <div className="research-example-label">可以这样开始</div>
                <div className="research-starter-examples">
                  {starterExamples.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className="ghost-btn ghost-btn-small research-example-btn"
                      onClick={() => focusComposerWithValue(item)}
                      title={item}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {isResearchBooting ? (
              <div className="research-starter-card research-booting-card" role="status" aria-live="polite">
                <div className="research-live-card">
                <div className="research-live-head">
                  <div className="research-live-title-wrap">
                      <div className="research-live-title">{bootingStatus}</div>
                      <div className="research-live-summary">{bootingHint}</div>
                    </div>
                    <div className="research-live-state is-running">
                      <span className="research-live-state-dot" aria-hidden="true" />
                      <span>处理中</span>
                    </div>
                  </div>
                  {pendingQuestion ? <div className="research-starting-query">“{pendingQuestion}”</div> : null}
                </div>
              </div>
            ) : null}

            {isBlankResearch ? (
              <div className="research-starter-card">
                <EmptyState
                  className="research-starter-state"
                  icon={<MessageSquareIcon />}
                  title="直接输入你的研究问题"
                  text="我们会先识别公司，再开始分析。首轮通常会先返回当前判断、风险和后续关注点。"
                />
                <div className="research-starter-hint">支持自然语言、公司名称和股票代码。也可以补充时间、对比对象或你的关注点。</div>
                {parseResult?.clarification_question ? (
                  <div className="thread-inline-note">{parseResult.clarification_question}</div>
                ) : null}
                <div className="research-example-label">示例问题</div>
                <div className="research-starter-examples">
                  {starterExamples.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className="ghost-btn ghost-btn-small research-example-btn"
                      onClick={() => focusComposerWithValue(item)}
                      title={item}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {isFailedResearch ? (
              <div className="research-starter-card">
                <EmptyState
                  className="research-starter-state"
                  icon={<MessageSquareIcon />}
                  title="这次分析未完成"
                  text="不用重新建研究，直接补充更明确的问题后重新发送即可。我们会重新识别公司并开始分析。"
                />
                <div className="thread-inline-note">
                  优先补充公司、时间、比较对象或你最关心的判断点，通常更容易直接得到可用结论。
                </div>
              </div>
            ) : null}

            {messages.length
              ? messages.map((message) => {
                  const isStatusMessage = message.metadata?.source === "viewer_research_status";
                  const statusKind =
                    typeof message.metadata?.kind === "string" ? String(message.metadata.kind) : null;
                  const displayContent = isStatusMessage ? sanitizeStatusMessage(message.content, statusKind) : message.content;
                  return (
                    <div
                      key={message.message_id}
                      className={`message ${message.role} ${isStatusMessage ? "message-status" : ""} ${statusKind ? `message-${statusKind}` : ""}`.trim()}
                    >
                      {message.role === "assistant" ? <MarkdownContent content={displayContent} /> : displayContent}
                    </div>
                  );
                })
              : null}
            {showIdleNote ? (
              <div className="thread-inline-note">
                分析已完成，可以继续追问结论依据、风险拆解或触发条件。
              </div>
            ) : null}
          </div>
          </div>

          <div className="chat-composer chat-composer-standalone">
            <textarea
              ref={textareaRef}
              rows={1}
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={composerPlaceholder}
              disabled={composerDisabled}
              aria-label="研究提问输入框"
            />
            <button
              className={`primary-btn chat-send-btn ${chatHasValue ? "has-value" : ""} ${composerBusy ? "is-loading" : ""}`.trim()}
              onClick={onSendChat}
              disabled={composerDisabled || !chatHasValue}
              aria-label={composerBusy ? "正在启动研究" : "发送问题"}
              title={composerBusy ? "正在启动研究" : "发送问题"}
            >
              <SendIcon className="btn-icon" />
            </button>
          </div>
        </PanelCard>

        {showDecisionPanel && shouldRevealModules ? (
          <section className="research-insights-band module-reveal reveal-strategy">
            <div className="research-decision-insight-grid decision-motion decision-motion-insights">
              <section className="research-evidence-panel decision-surface is-accent">
                <div className="strategy-label">最强依据</div>
                <article className="research-evidence-primary-block" style={{ "--decision-order": 1 } as CSSProperties}>
                  <div className="research-evidence-head">
                    <span className="research-evidence-tag">{primaryEvidenceCard.module}</span>
                    {primaryEvidenceCard.importance !== null ? (
                      <span className="research-evidence-importance">{Math.round(primaryEvidenceCard.importance * 100)}%</span>
                    ) : null}
                  </div>
                  <div className="research-evidence-title">{primaryEvidenceCard.title}</div>
                  <div className="research-evidence-fact">{primaryEvidenceCard.fact}</div>
                </article>
                {supportingEvidenceCards.length ? (
                  <div className="research-evidence-support-list">
                    {supportingEvidenceCards.map((item, index) => (
                      <article key={item.key} className="research-evidence-support-item" style={{ "--decision-order": index + 2 } as CSSProperties}>
                        <div className="research-evidence-head">
                          <span className="research-evidence-tag">{item.module}</span>
                          {item.importance !== null ? <span className="research-evidence-importance">{Math.round(item.importance * 100)}%</span> : null}
                        </div>
                        <div className="research-evidence-title">{item.title}</div>
                        <div className="research-evidence-fact">{item.fact}</div>
                      </article>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="research-decision-follow research-follow-panel decision-surface is-warm">
                <div className="strategy-label">接下来重点看</div>
                <article className="research-watch-primary-block" style={{ "--decision-order": 4 } as CSSProperties}>
                  <div className="research-watch-head">
                    <span className="research-watch-kicker">当前关键变量</span>
                    {primaryWatchItem.window ? <span className="research-watch-meta">窗口：{primaryWatchItem.window}</span> : null}
                  </div>
                  <div className="research-decision-follow-lead">{primaryWatchItem.variable || keyTracking}</div>
                  {primaryWatchItem.reason ? <div className="research-watch-copy">{primaryWatchItem.reason}</div> : null}
                  {primaryWatchItem.bull || primaryWatchItem.bear ? (
                    <div className="research-watch-outcome">
                      {primaryWatchItem.bull ? (
                        <div className="research-watch-outcome-row">
                          <span className="research-watch-outcome-label is-positive">验证通过</span>
                          <span>{primaryWatchItem.bull}</span>
                        </div>
                      ) : null}
                      {primaryWatchItem.bear ? (
                        <div className="research-watch-outcome-row">
                          <span className="research-watch-outcome-label is-warning">未达预期</span>
                          <span>{primaryWatchItem.bear}</span>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </article>
                {supportingWatchItems.length ? (
                  <div className="research-decision-follow-list">
                    {supportingWatchItems.map((item, index) => (
                      <article key={item.key} className="research-watch-support-item" style={{ "--decision-order": index + 5 } as CSSProperties}>
                        <div className="research-watch-head">
                          <div className="research-watch-title">{item.variable}</div>
                          {item.window ? <div className="research-watch-meta">窗口：{item.window}</div> : null}
                        </div>
                        {item.reason ? <div className="research-watch-copy">{item.reason}</div> : null}
                        {item.bull || item.bear ? (
                          <div className="research-watch-outcome">
                            {item.bull ? (
                              <div className="research-watch-outcome-row">
                                <span className="research-watch-outcome-label is-positive">验证通过</span>
                                <span>{item.bull}</span>
                              </div>
                            ) : null}
                            {item.bear ? (
                              <div className="research-watch-outcome-row">
                                <span className="research-watch-outcome-label is-warning">未达预期</span>
                                <span>{item.bear}</span>
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </article>
                    ))}
                  </div>
                ) : null}
              </section>
            </div>

            <div className="research-module-map decision-motion decision-motion-modules">
              <div className="research-module-map-head">
                <div className="strategy-label">研究维度拆解</div>
              </div>
              <div className="research-module-grid">
                {moduleCards.map((item, index) => (
                  <article
                    key={item.key}
                    className={`research-module-card ${item.stanceTone} ${selectedModuleKey === item.key ? "is-active" : ""}`.trim()}
                    style={{ "--decision-order": index + 1 } as CSSProperties}
                    onClick={() => setSelectedModuleKey(item.key)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedModuleKey(item.key);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selectedModuleKey === item.key}
                  >
                    <div className="research-module-head">
                      <div className="research-module-meta-block">
                        <div className="research-module-name">{item.label}</div>
                        <div className="research-module-weight">贡献权重 {item.weightText}</div>
                      </div>
                      <div className={`research-module-stance ${item.stanceTone}`}>{item.stanceLabel}</div>
                    </div>
                    <div className="research-module-summary">{item.summary}</div>
                  </article>
                ))}
              </div>

              <article className={`research-module-focus decision-surface ${activeModuleCardMeta?.stanceTone || "tone-neutral"}`.trim()}>
                <div className="research-module-focus-top">
                  <div className="research-module-focus-hero">
                    <div className="research-module-focus-meta">
                      <div className="research-module-focus-heading">
                        <div className="research-module-focus-kicker">{activeModule.label}解读</div>
                        <div className="research-module-focus-weightline">贡献权重 {activeModuleCardMeta?.weightText || "--"}</div>
                      </div>
                      <div className="research-module-focus-badges">
                        <div className={`research-module-focus-state ${activeModuleCardMeta?.stanceTone || "tone-neutral"}`.trim()}>
                          {activeModuleCardMeta?.stanceLabel || "中性"}
                        </div>
                      </div>
                    </div>
                    <div className="research-module-focus-summary">{activeModule.summary}</div>
                  </div>

                  <aside className="research-module-state-panel">
                    <div className="research-module-section-title">维度摘要</div>
                    <div className="research-module-state-list">
                      {activeModule.summaryItems.map((item) => (
                        <div key={`${activeModule.key}-${item.key}`} className="research-module-state-row">
                          <div className="research-module-state-label">{item.label}</div>
                          <div className="research-module-state-copy">
                            <div className="research-module-state-value">{item.conclusion}</div>
                            <div className="research-module-state-value is-rationale">{item.rationale}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </aside>
                </div>

                <div className="research-module-focus-block">
                  <div className="research-module-section-title">核心解读</div>
                  <div className="research-module-insight-list">
                    {activeModule.insights.map((item) => (
                      <article key={`${activeModule.key}-${item.label}`} className="research-module-insight-item">
                        <div className="research-module-insight-title">{item.label}</div>
                        <div className="research-module-insight-body">{item.value}</div>
                      </article>
                    ))}
                  </div>
                </div>
              </article>
            </div>
          </section>
        ) : null}

        {shouldRevealModules ? (
          <PanelCard className="report-panel module-reveal reveal-report">
            <SectionHeader title="完整报告" />
            {reportNotice ? <div className="thread-inline-note">{reportNotice}</div> : null}
            <Suspense fallback={<div className="workspace-loading">正在加载完整报告...</div>}>
              <ReportNavigator sections={reportSections} />
            </Suspense>
          </PanelCard>
        ) : null}
      </div>
    </section>
  );
}
