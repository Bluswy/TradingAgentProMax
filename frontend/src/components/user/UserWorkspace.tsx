import { Suspense, lazy, useEffect, useRef, type KeyboardEvent } from "react";
import type { EventItem, ReportSection, Research, ResearchMessage, ResearchParseResult, Run } from "../../types";
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
  strategy: LooseRecord;
  decision: LooseRecord;
  parseResult: ResearchParseResult | null;
  messages: ResearchMessage[];
  events: EventItem[];
  chatInput: string;
  chatLoading: boolean;
  isParsingResearch: boolean;
  isStartingResearch: boolean;
  onConfirmResearch: () => void;
  setChatInput: (value: string) => void;
  onSendChat: () => void;
  reportSections: ReportSection[];
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
  strategy,
  decision,
  parseResult,
  messages,
  events,
  chatInput,
  chatLoading,
  isParsingResearch,
  isStartingResearch,
  onConfirmResearch,
  setChatInput,
  onSendChat,
  reportSections,
}: UserWorkspaceProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const starterExamples = [
    "分析一下通富微电现在是否值得继续持有",
    "贵州茅台短期还有没有回调风险",
  ];
  const companyIdentity = asRecord(company.identity);
  const decisionInfo = asRecord(decision.decision);
  const primaryStrategy = asRecord(strategy.primary_strategy);

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
  const decisionRiskFlags = readStringArray(decision.risk_flags);
  const decisionInvalidations = readStringArray(decision.invalidations);
  const strategyInvalidations = readStringArray(strategy.invalidations);
  const triggerConditions = readStringArray(decision.trigger_conditions);
  const trackingVariables = readStringArray(strategy.decision_priority_variables);
  const keyRisk = decisionRiskFlags[0] || "当前未识别到显性风险";
  const riskMeta = decisionRiskFlags.slice(1, 3).join(" / ");
  const invalidation = decisionInvalidations[0] || strategyInvalidations[0] || "目前还没有明确失效信号";
  const invalidationMeta = decisionInvalidations.slice(1, 3).join(" / ") || strategyInvalidations.slice(1, 3).join(" / ") || "如果出现反向信号，系统会在这里提示。";
  const keyTracking = trackingVariables[0] || "等待关键变量更新";
  const trigger = triggerConditions[0] || "等待新的触发信号";
  const trackingItems = trackingVariables.slice(0, 3);
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
    ? "正在识别公司、代码和时间。"
    : "识别完成，正在开始分析。";
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
              <div className="research-decision-content">
                <div className="research-decision-header">
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

                <div className="research-decision-main">
                  <div className="strategy-label">核心判断</div>
                  <MarkdownContent className="research-decision-summary markdown-large" content={heroSummary} />
                </div>

                <div className="research-decision-follow">
                  <div className="strategy-label">接下来重点看</div>
                  <div className="research-decision-follow-lead">{keyTracking}</div>
                  <div className="research-decision-follow-list">
                    {(trackingItems.length ? trackingItems : [trigger]).map((item) => (
                      <div key={item} className="research-decision-follow-item">
                        {item}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="research-decision-detail-grid">
                  <article className="strategy-card">
                    <div className="strategy-label">何时失效</div>
                    <div className="strategy-value">{invalidation}</div>
                    <div className="strategy-note">{invalidationMeta}</div>
                  </article>

                  <article className="strategy-card">
                    <div className="strategy-label">当前风险</div>
                    <div className="strategy-value">{keyRisk}</div>
                    <div className="strategy-note">{riskMeta || "如果出现新的风险信号，会优先显示在这里。"}</div>
                  </article>
                </div>
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
                      <button className="primary-btn" onClick={onConfirmResearch} disabled={isStartingResearch || Boolean(parseResult?.needs_confirmation)}>
                        {isStartingResearch ? "开始中..." : "确认并开始"}
                      </button>
                    </div>
                  </div>
                ) : null}

                {isResearchRunning ? (
                  <ResearchFlow companyName={companyName} research={research} events={progressFeed} />
                ) : null}
              </div>
            )}
          </section>
        ) : null}

        <PanelCard className="thread-panel conversation-panel module-reveal reveal-strategy">
          <SectionHeader title={threadTitle} />

          <div className="conversation-thread">
            {isWelcomeState ? (
              <div className="research-welcome-card">
                  <div className="research-welcome-copy">
                    <div className="research-welcome-eyebrow">开始一次研究</div>
                    <div className="research-welcome-title">直接输入你的研究问题</div>
                  <div className="research-welcome-text">直接描述你的问题，我们会自动识别公司并开始分析。</div>
                </div>
                <div className="research-starter-hint">支持自然语言、公司名称和股票代码。</div>
                <div className="research-starter-examples">
                  {starterExamples.map((item) => (
                    <button
                      key={item}
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
                  text="发送后会自动识别公司，并开始分析。"
                />
                <div className="research-starter-hint">支持自然语言、公司名称和股票代码。</div>
                {parseResult?.clarification_question ? (
                  <div className="thread-inline-note">{parseResult.clarification_question}</div>
                ) : null}
                <div className="research-starter-examples">
                  {starterExamples.map((item) => (
                    <button
                      key={item}
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
                  text="请补充更明确的问题后重新发送。我们会重新识别公司并开始分析。"
                />
                <div className="thread-inline-note">
                  补充公司、时间或问题后重新发送即可。
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

        {shouldRevealModules ? (
          <PanelCard className="report-panel module-reveal reveal-report">
            <SectionHeader title="完整报告" />
            <Suspense fallback={<div className="workspace-loading">正在加载完整报告...</div>}>
              <ReportNavigator sections={reportSections} />
            </Suspense>
          </PanelCard>
        ) : null}
      </div>
    </section>
  );
}
