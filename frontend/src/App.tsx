import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Sidebar } from "./components/sidebar/Sidebar";
import { UserWorkspace } from "./components/user/UserWorkspace";
import type {
  EventItem,
  FinalState,
  NodeDetail,
  ReportSection,
  Research,
  ResearchMessage,
  ResearchParseResult,
  Run,
  RunDetail,
} from "./types";
import { extractCompanyName, extractReportSections } from "./utils";

const DevWorkspace = lazy(async () => import("./components/dev/DevWorkspace").then((module) => ({ default: module.DevWorkspace })));

function isNotFoundError(error: unknown) {
  return error instanceof Error && error.message.startsWith("404");
}

function logDevError(error: unknown) {
  if (typeof window !== "undefined" && /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname)) {
    console.error(error);
  }
}

type LooseRecord = Record<string, unknown>;

function asRecord(value: unknown): LooseRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as LooseRecord) : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function App() {
  type ErrorAction = "reloadResearches" | "reloadSelectedResearch" | "reloadSelectedRun" | null;
  const [mode, setMode] = useState<"user" | "dev">("user");
  const [selectedResearch, setSelectedResearch] = useState<Research | null>(null);
  const [selectedResearchId, setSelectedResearchId] = useState<string | null>(null);
  const [researches, setResearches] = useState<Research[]>([]);
  const [parseResult, setParseResult] = useState<ResearchParseResult | null>(null);
  const [messages, setMessages] = useState<ResearchMessage[]>([]);

  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [runResults, setRunResults] = useState<FinalState | null>(null);
  const [selectedNodeName, setSelectedNodeName] = useState<string | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);

  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [isDraftingResearch, setIsDraftingResearch] = useState(false);
  const [isParsingResearch, setIsParsingResearch] = useState(false);
  const [isStartingResearch, setIsStartingResearch] = useState(false);
  const [deletingResearchId, setDeletingResearchId] = useState<string | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [appError, setAppError] = useState<string | null>(null);
  const [errorAction, setErrorAction] = useState<ErrorAction>(null);

  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    void loadResearches();
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!selectedResearchId) {
      setSelectedResearch(null);
      setParseResult(null);
      setMessages([]);
      clearRunContext();
      return;
    }
    setIsDraftingResearch(false);
    void loadResearch(selectedResearchId);
  }, [selectedResearchId]);

  useEffect(() => {
    const runId = selectedResearch?.active_run_id || null;
    if (!runId) {
      clearRunContext();
      return;
    }
    void loadRun(runId);
    openEventStream(runId);
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, [selectedResearch?.active_run_id]);

  const reportMarkdown =
    (runResults?.final_report_result as Record<string, unknown> | undefined)?.report_markdown ||
    (((runResults?.company_report_result as Record<string, unknown> | undefined)?.analysis_result as Record<string, unknown> | undefined)
      ?.report_markdown as string | undefined);
  const reportArtifactStatus = asRecord(runResults?._report_artifact_status);
  const reportIsTruncated =
    Boolean(reportArtifactStatus?.truncated) || (typeof reportMarkdown === "string" && reportMarkdown.includes("...<truncated>"));
  const reportNotice = reportIsTruncated
    ? "这次历史研究的完整报告在旧版持久化链路中已被截断，当前只能展示已保存部分。重新运行一次研究可获取完整报告。"
    : null;

  const reportSections = useMemo<ReportSection[]>(
    () => extractReportSections(typeof reportMarkdown === "string" ? reportMarkdown : ""),
    [reportMarkdown],
  );

  const reportTitle =
    ((runResults?.final_report_result as Record<string, unknown> | undefined)?.report_title as string | undefined) ||
    ((((runResults?.company_report_result as Record<string, unknown> | undefined)?.analysis_result as Record<string, unknown> | undefined)
      ?.report_title as string | undefined) ||
      "");

  function clearRunContext() {
    setRunDetail(null);
    setRunResults(null);
    setEvents([]);
    setSelectedNodeName(null);
    setNodeDetail(null);
  }

  function describeError(error: unknown, fallback: string): string {
    if (!(error instanceof Error)) return fallback;
    if (error.message.startsWith("409")) return error.message.replace(/^409\s+/, "");
    if (error.message.startsWith("500")) return "服务端暂时不可用，请稍后重试。";
    if (error.message.includes("Failed to fetch")) return "无法连接研究服务，请检查后端 API 是否正在运行。";
    return fallback;
  }

  function showAppError(message: string, nextAction: ErrorAction = null) {
    setAppError(message);
    setErrorAction(nextAction);
  }

  function clearAppError() {
    setAppError(null);
    setErrorAction(null);
  }

  function applyResearchesSnapshot(items: Research[]) {
    setResearches(items);
    setSelectedResearchId((current) => {
      if (isDraftingResearch) return null;
      if (current && items.some((item) => item.research_id === current)) return current;
      return items[0]?.research_id ?? null;
    });
  }

  function upsertResearch(nextResearch: Research) {
    setSelectedResearch(nextResearch);
    setParseResult(nextResearch.parse_result || null);
    setResearches((current) => {
      const rest = current.filter((item) => item.research_id !== nextResearch.research_id);
      return [nextResearch, ...rest];
    });
  }

  async function loadResearches() {
    try {
      const data = await api.listResearches();
      applyResearchesSnapshot(data.researches);
      clearAppError();
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error)
          ? "暂时无法读取研究列表，请稍后重试。"
          : describeError(error, "研究列表加载失败，请重试。"),
        "reloadResearches",
      );
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function loadRun(runId: string) {
    try {
      const detail = await api.getRun(runId);
      let results: FinalState | null = null;
      try {
        results = await api.getRunResults(runId);
      } catch (error) {
        if (!isNotFoundError(error)) {
          throw error;
        }
      }
      setRunDetail(detail);
      setRunResults(results);
      setSelectedNodeName(null);
      setNodeDetail(null);
      setEvents([]);
      clearAppError();
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error) ? "当前研究结果已不存在，请刷新后重试。" : describeError(error, "研究结果加载失败，请重试。"),
        "reloadSelectedRun",
      );
    }
  }

  async function loadResearch(researchId: string) {
    try {
      const data = await api.getResearch(researchId);
      setSelectedResearchId(researchId);
      setSelectedResearch(data.research);
      setParseResult(data.research.parse_result || null);
      setMessages(data.messages);
      clearAppError();
    } catch (error) {
      logDevError(error);
      if (isNotFoundError(error)) {
        try {
          const data = await api.listResearches();
          applyResearchesSnapshot(data.researches);
        } catch (refreshError) {
          logDevError(refreshError);
        }
        showAppError("当前研究已不存在，已刷新研究列表。", "reloadResearches");
        return;
      }
      showAppError(describeError(error, "研究详情加载失败，请重试。"), "reloadSelectedResearch");
    }
  }

  async function startResearchDraft() {
    setMode("user");
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    clearRunContext();
    setSelectedResearch(null);
    setSelectedResearchId(null);
    setMessages([]);
    setChatLoading(false);
    setIsParsingResearch(false);
    setIsStartingResearch(false);
    setParseResult(null);
    setIsDraftingResearch(true);
    setChatInput("");
    clearAppError();
  }

  async function parseSelectedResearch(messageText: string) {
    setIsParsingResearch(true);
    let researchId = selectedResearchId;
    try {
      if (!researchId) {
        const created = await api.createResearch({ title: "新的研究", query_text: null });
        upsertResearch(created.research);
        researchId = created.research.research_id;
        setSelectedResearchId(researchId);
        setIsDraftingResearch(false);
      }
      if (!researchId) return;

      const response = await api.parseResearch(researchId, { query_text: messageText.trim() });
      upsertResearch(response.research);
      setSelectedResearchId(response.research.research_id);
      setParseResult(response.parse_result);
      if (!response.parse_result.needs_confirmation) {
        setIsStartingResearch(true);
        try {
          const runResponse = await api.runResearch(response.research.research_id, { confirm: true });
          upsertResearch(runResponse.research);
          setMessages((current) => {
            const known = new Set(current.map((item) => item.message_id));
            return [...current, ...runResponse.messages.filter((item) => !known.has(item.message_id))];
          });
          setIsDraftingResearch(false);
          setChatInput("");
        } finally {
          setIsStartingResearch(false);
        }
      } else {
        setChatInput(messageText.trim());
      }
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error)
          ? "暂时无法开始分析，请稍后重试。"
          : describeError(error, "研究对象识别失败，请补充更明确的信息后重试。"),
        "reloadSelectedResearch",
      );
      if (researchId) {
        await loadResearch(researchId);
      }
    } finally {
      setIsParsingResearch(false);
    }
  }

  async function confirmResearchRun() {
    if (!selectedResearch?.research_id) return;
    setIsStartingResearch(true);
    try {
      const response = await api.runResearch(selectedResearch.research_id, { confirm: true });
      upsertResearch(response.research);
      setMessages((current) => {
        const known = new Set(current.map((item) => item.message_id));
        return [...current, ...response.messages.filter((item) => !known.has(item.message_id))];
      });
      setIsDraftingResearch(false);
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error) ? "当前研究已不存在，无法继续执行。" : describeError(error, "启动研究失败，请重试。"),
        "reloadSelectedResearch",
      );
      await loadResearch(selectedResearch.research_id);
    } finally {
      setIsStartingResearch(false);
    }
  }

  async function sendChat() {
    if (!chatInput.trim()) return;
    const canChatInResearch =
      Boolean(selectedResearch?.active_run_id) &&
      selectedResearch?.status === "completed" &&
      selectedResearch?.run_status !== "running";
    if (!selectedResearch || !canChatInResearch) {
      await parseSelectedResearch(chatInput);
      return;
    }

    setChatLoading(true);
    try {
      const response = await api.chatResearch(selectedResearch.research_id, { message: chatInput.trim() });
      upsertResearch(response.research);
      setSelectedResearchId(response.research.research_id);
      setMessages((current) => {
        const known = new Set(current.map((item) => item.message_id));
        return [...current, ...response.messages.filter((item) => !known.has(item.message_id))];
      });
      setChatInput("");
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error) ? "当前研究会话已失效，请刷新后重试。" : describeError(error, "继续追问失败，请稍后重试。"),
        "reloadSelectedResearch",
      );
      await loadResearch(selectedResearch.research_id);
    } finally {
      setChatLoading(false);
    }
  }

  function handleSelectResearch(researchId: string) {
    setIsDraftingResearch(false);
    setSelectedResearchId(researchId);
  }

  async function deleteResearch(researchId: string) {
    if (deletingResearchId) return;
    const currentItems = researches;
    const index = currentItems.findIndex((item) => item.research_id === researchId);
    if (index < 0) return;
    const remaining = currentItems.filter((item) => item.research_id !== researchId);
    const fallbackResearch = remaining[index] || remaining[index - 1] || null;

    setDeletingResearchId(researchId);
    try {
      await api.deleteResearch(researchId);
      clearAppError();
      setResearches(remaining);

      if (selectedResearchId === researchId) {
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        setSelectedResearch(null);
        setParseResult(null);
        setMessages([]);
        clearRunContext();

        if (fallbackResearch) {
          setIsDraftingResearch(false);
          setSelectedResearchId(fallbackResearch.research_id);
        } else {
          setSelectedResearchId(null);
          setIsDraftingResearch(true);
        }
      }
    } catch (error) {
      logDevError(error);
      if (isNotFoundError(error)) {
        setResearches(remaining);
        if (selectedResearchId === researchId) {
          eventSourceRef.current?.close();
          eventSourceRef.current = null;
          setSelectedResearch(null);
          setParseResult(null);
          setMessages([]);
          clearRunContext();
          if (fallbackResearch) {
            setIsDraftingResearch(false);
            setSelectedResearchId(fallbackResearch.research_id);
          } else {
            setSelectedResearchId(null);
            setIsDraftingResearch(true);
          }
        }
        showAppError("这条研究已不存在，研究列表已刷新。", "reloadResearches");
        return;
      }
      showAppError(describeError(error, "删除研究失败，请稍后重试。"));
    } finally {
      setDeletingResearchId(null);
    }
  }

  async function selectNode(nodeName: string) {
    const runId = selectedResearch?.active_run_id;
    if (!runId) return;
    setSelectedNodeName(nodeName);
    try {
      const detail = await api.getNode(runId, nodeName);
      setNodeDetail(detail);
      clearAppError();
    } catch (error) {
      logDevError(error);
      showAppError(
        isNotFoundError(error) ? "当前节点详情已不存在，请刷新后重试。" : describeError(error, "节点详情加载失败，请重试。"),
        "reloadSelectedRun",
      );
    }
  }

  async function handleRetryError() {
    if (errorAction === "reloadResearches") {
      await loadResearches();
      return;
    }
    if (errorAction === "reloadSelectedResearch" && selectedResearchId) {
      await loadResearch(selectedResearchId);
      return;
    }
    if (errorAction === "reloadSelectedRun" && selectedResearch?.active_run_id) {
      await loadRun(selectedResearch.active_run_id);
    }
  }

  function openEventStream(runId: string) {
    eventSourceRef.current?.close();
    const activeResearchId = selectedResearchId;
    const source = new EventSource(`/api/runs/${runId}/stream?after_event_id=0&poll_interval_ms=1000`);
    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as EventItem;
      const runFinishedStatus =
        payload.event_type === "run_finished" && typeof payload.payload?.status === "string"
          ? String(payload.payload.status)
          : null;
      setEvents((current) => [payload, ...current].slice(0, 120));
      if (payload.event_type === "run_started" || payload.event_type === "step_started") {
        setSelectedResearch((current) => (current ? { ...current, run_status: "running", status: "running" } : current));
        setResearches((current) =>
          current.map((item) =>
            item.research_id === activeResearchId ? { ...item, run_status: "running", status: "running" } : item,
          ),
        );
      }
      setRunDetail((current) => {
        if (!current) return current;
        if (!payload.node_name) {
          const nextRunStatus =
            payload.event_type === "run_finished"
              ? runFinishedStatus === "failed"
                ? "failed"
                : "success"
              : payload.event_type === "run_started"
                ? "running"
                : current.run.status;
          return {
            ...current,
            run: { ...current.run, status: nextRunStatus },
          };
        }
        const nextNodes = current.graph.nodes.map((node) => {
          if (node.node_name !== payload.node_name) return node;
          if (payload.event_type === "step_started") return { ...node, status: "running" };
          if (payload.event_type === "step_finished" && payload.payload?.step_type === "node") {
            return {
              ...node,
              status: "success",
              duration_ms: Number(payload.payload?.duration_ms || node.duration_ms || 0),
            };
          }
          if (payload.event_type === "step_failed" && payload.payload?.step_type === "node") {
            return { ...node, status: "failed" };
          }
          return node;
        });
        return {
          ...current,
          run:
            payload.event_type === "run_finished"
              ? { ...current.run, status: runFinishedStatus === "failed" ? "failed" : "success" }
              : payload.event_type === "run_started"
                ? { ...current.run, status: "running" }
                : current.run,
          graph: { ...current.graph, nodes: nextNodes },
        };
      });
      if (payload.event_type === "run_finished" || payload.event_type === "step_failed") {
        const isRunFailed = payload.event_type === "run_finished" && runFinishedStatus === "failed";
        const nextStatus = payload.event_type === "step_failed" || isRunFailed ? "failed" : "completed";
        const nextRunStatus = payload.event_type === "step_failed" || isRunFailed ? "failed" : "success";
        setSelectedResearch((current) =>
          current ? { ...current, run_status: nextRunStatus, status: nextStatus } : current,
        );
        setResearches((current) =>
          current.map((item) =>
            item.research_id === activeResearchId ? { ...item, run_status: nextRunStatus, status: nextStatus } : item,
          ),
        );
      }
    };
    source.addEventListener("completed", () => {
      source.close();
      if (activeResearchId) {
        void loadResearch(activeResearchId);
      }
      void loadRun(runId);
    });
    eventSourceRef.current = source;
  }

  const run = runDetail?.run || null;
  const technical = (asRecord(runResults?.technical_result)?.analysis_result as LooseRecord | undefined) || {};
  const fundamental = (asRecord(runResults?.fundamental_result)?.analysis_result as LooseRecord | undefined) || {};
  const eventNews = (asRecord(runResults?.event_news_result)?.analysis_result as LooseRecord | undefined) || {};
  const sectorFlow = (asRecord(runResults?.sector_flow_result)?.analysis_result as LooseRecord | undefined) || {};
  const strategy = (asRecord(runResults?.strategy_style_result)?.analysis_result as LooseRecord | undefined) || {};
  const decision = (asRecord(runResults?.strategy_decision_result)?.analysis_result as LooseRecord | undefined) || {};
  const company = asRecord(runResults?.company_context) || {};
  const companyIdentity = asRecord(company.identity);

  return (
    <div className="app-shell">
      <Sidebar
        mode={mode}
        onModeChange={setMode}
        researches={researches}
        isLoading={isBootstrapping}
        selectedResearchId={selectedResearchId}
        onSelectResearch={handleSelectResearch}
        onDeleteResearch={(researchId) => void deleteResearch(researchId)}
        deletingResearchId={deletingResearchId}
      />

      <main className="main-stage">
        <header className="topbar">
          <div>
            <h1 className="topbar-title">Agent工作区</h1>
          </div>
          <div className="topbar-right">
            <button className="primary-btn topbar-create-btn" onClick={() => void startResearchDraft()}>
              新的研究
            </button>
          </div>
        </header>

        {appError ? (
          <div className="app-alert" role="alert" aria-live="polite">
            <div className="app-alert-copy">{appError}</div>
            <div className="app-alert-actions">
              {errorAction ? (
                <button className="ghost-btn ghost-btn-small" onClick={() => void handleRetryError()}>
                  重试
                </button>
              ) : null}
              <button className="ghost-btn ghost-btn-small" onClick={clearAppError}>
                关闭
              </button>
            </div>
          </div>
        ) : null}

        {mode === "user" ? (
          <UserWorkspace
            key={`user-${selectedResearch?.research_id ?? "empty"}-${selectedResearch?.active_run_id ?? "blank"}`}
            research={selectedResearch}
            run={run}
            company={company}
            companyDisplayName={
              extractCompanyName(reportTitle) ||
              readString(companyIdentity?.company_name) ||
              readString(company.company_name) ||
              readString(company.name) ||
              ""
            }
            technical={technical}
            fundamental={fundamental}
            eventNews={eventNews}
            sectorFlow={sectorFlow}
            strategy={strategy}
            decision={decision}
            parseResult={parseResult}
            messages={messages}
            events={events}
            runNodes={runDetail?.graph.nodes || []}
            chatInput={chatInput}
            chatLoading={chatLoading || isParsingResearch || isStartingResearch}
            isParsingResearch={isParsingResearch}
            isStartingResearch={isStartingResearch}
            onConfirmResearch={() => void confirmResearchRun()}
            setChatInput={setChatInput}
            onSendChat={() => void sendChat()}
            reportSections={reportSections}
            reportNotice={reportNotice}
          />
        ) : (
          <Suspense fallback={<div className="workspace-loading">正在加载开发工作区...</div>}>
            <DevWorkspace
              key={`dev-${selectedResearch?.active_run_id ?? "empty"}`}
              runDetail={runDetail}
              selectedNodeName={selectedNodeName}
              nodeDetail={nodeDetail}
              onSelectNode={(nodeName) => void selectNode(nodeName)}
            />
          </Suspense>
        )}
      </main>
    </div>
  );
}
