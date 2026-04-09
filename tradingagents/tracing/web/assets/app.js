const GRAPH_LAYERS = [
  ["company_context"],
  ["technical", "fundamental", "event_news", "sector_flow"],
  ["collect_results"],
  ["strategy_style"],
  ["dispatch_post_strategy"],
  ["strategy_decision", "company_report"],
  ["collect_postprocess"],
  ["final_report"],
];

const state = {
  mode: "user",
  runs: [],
  selectedRunId: null,
  selectedNodeName: null,
  runDetail: null,
  runResults: null,
  nodeDetail: null,
  researches: [],
  selectedResearchId: null,
  currentMessages: [],
  eventSource: null,
  afterEventId: 0,
};

function qs(selector) {
  return document.querySelector(selector);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDate(ts) {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("zh-CN");
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function statusClass(status) {
  switch (status) {
    case "running":
      return "status-running";
    case "success":
      return "status-success";
    case "failed":
      return "status-failed";
    default:
      return "status-queued";
  }
}

function setMode(mode) {
  state.mode = mode;
  qs("#mode-user").classList.toggle("is-active", mode === "user");
  qs("#mode-dev").classList.toggle("is-active", mode === "dev");
  qs("#user-workspace").classList.toggle("is-active", mode === "user");
  qs("#dev-workspace").classList.toggle("is-active", mode === "dev");
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${text}`);
  }
  return response.json();
}

async function loadRuns() {
  const data = await fetchJson("/api/runs?limit=40");
  state.runs = data.runs || [];
  renderRuns();
  if (!state.selectedRunId && state.runs.length) {
    await selectRun(state.runs[0].run_id);
  }
}

function renderRuns() {
  const container = qs("#run-list");
  container.innerHTML = "";
  if (!state.runs.length) {
    container.appendChild(el("div", "empty-state", "暂无 runs"));
    return;
  }
  for (const run of state.runs) {
    const template = qs("#run-item-template").content.firstElementChild.cloneNode(true);
    template.classList.toggle("is-selected", run.run_id === state.selectedRunId);
    template.querySelector(".item-title").textContent = run.input_summary?.ticker || run.run_id.slice(0, 8);
    template.querySelector(".item-subtitle").textContent = `${run.status} · ${formatDate(run.started_at)}`;
    const badge = template.querySelector(".status-badge");
    badge.className = `status-badge ${statusClass(run.status)}`;
    badge.textContent = run.status;
    template.addEventListener("click", () => selectRun(run.run_id));
    container.appendChild(template);
  }
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  state.selectedNodeName = null;
  renderRuns();
  state.runDetail = await fetchJson(`/api/runs/${runId}`);
  state.runResults = await fetchJson(`/api/runs/${runId}/results`);
  renderRunHeader();
  renderUserResults();
  renderDag();
  renderTimeline();
  await bindResearchToRun();
  openEventStream();
}

function renderRunHeader() {
  const run = state.runDetail?.run;
  const header = qs("#research-header");
  const strategy = state.runResults?.strategy_style_result?.analysis_result?.primary_strategy;
  const decision = state.runResults?.strategy_decision_result?.analysis_result?.decision;
  const company = state.runResults?.company_context || {};
  header.innerHTML = `
    <div class="section-row">
      <div>
        <div class="brand-kicker">${company.company_type || "company"}</div>
        <div class="brand-title">${company.company_name || company.name || company.ticker || run?.input_summary?.ticker || "-"}</div>
        <div class="brand-subtitle">${company.ticker || run?.input_summary?.ticker || "-"} · ${company.industry || "未知行业"} · ${run?.status || "unknown"}</div>
      </div>
      <div class="result-card-grid" style="min-width:340px;grid-template-columns:1fr 1fr;">
        <div class="result-card">
          <div class="result-label">Primary Strategy</div>
          <div class="result-value">${strategy?.label_zh || strategy?.type || "-"}</div>
          <div class="result-meta">confidence ${strategy?.confidence ?? "-"}</div>
        </div>
        <div class="result-card">
          <div class="result-label">Decision</div>
          <div class="result-value">${decision?.label_zh || decision?.action || "-"}</div>
          <div class="result-meta">updated ${formatDate(run?.updated_at || run?.finished_at || run?.started_at)}</div>
        </div>
      </div>
    </div>
  `;
  qs("#current-run-label").textContent = `${run?.input_summary?.ticker || "-"} · ${run?.status || "-"}`;
  qs("#global-status").className = `status-badge ${statusClass(run?.status)}`;
  qs("#global-status").textContent = run?.status || "idle";
  qs("#chat-context-pill").textContent = run?.input_summary?.ticker || "未绑定上下文";
  qs("#context-bar").textContent = `当前上下文: ${run?.input_summary?.ticker || "-"} / ${strategy?.type || "未识别策略"} / ${decision?.action || "无决策"}`;
}

function renderUserResults() {
  const grid = qs("#result-card-grid");
  const results = state.runResults || {};
  const strategy = results.strategy_style_result?.analysis_result;
  const decision = results.strategy_decision_result?.analysis_result;
  const eventSummary = results.event_news_result?.analysis_result?.event_summary_zh;
  const fundamental = results.fundamental_result?.analysis_result;
  const cards = [
    {
      label: "主策略",
      value: strategy?.primary_strategy?.label_zh || strategy?.primary_strategy?.type || "-",
      meta: strategy?.primary_strategy?.summary || "-",
    },
    {
      label: "当前动作",
      value: decision?.decision?.label_zh || decision?.decision?.action || "-",
      meta: decision?.decision?.summary || "-",
    },
    {
      label: "基本面",
      value: fundamental?.profitability?.state || "-",
      meta: fundamental?.fundamental_summary_zh || "-",
    },
    {
      label: "事件面",
      value: results.event_news_result?.analysis_result?.event_overview?.state || "-",
      meta: eventSummary || "-",
    },
  ];
  grid.innerHTML = "";
  for (const card of cards) {
    const node = el("div", "result-card");
    node.innerHTML = `
      <div class="result-label">${card.label}</div>
      <div class="result-value">${card.value}</div>
      <div class="result-meta">${card.meta}</div>
    `;
    grid.appendChild(node);
  }
  const markdown = results.final_report_result?.report_markdown || results.company_report_result?.analysis_result?.report_markdown || "暂无完整报告";
  qs("#report-viewer").textContent = markdown;
}

function renderDag() {
  const container = qs("#dag-canvas");
  container.innerHTML = "";
  const nodes = new Map((state.runDetail?.graph?.nodes || []).map((node) => [node.node_name, node]));
  for (const layer of GRAPH_LAYERS) {
    const row = el("div", "dag-layer");
    for (const nodeName of layer) {
      const data = nodes.get(nodeName) || { node_name: nodeName, status: "queued" };
      const card = el("button", `dag-node ${data.status || "queued"}`);
      if (state.selectedNodeName === nodeName) card.classList.add("is-selected");
      card.innerHTML = `
        <div class="section-row">
          <div class="dag-node-title">${nodeName}</div>
          <span class="status-badge ${statusClass(data.status)}">${data.status || "queued"}</span>
        </div>
        <div class="dag-node-meta">${formatDuration(data.duration_ms)}</div>
        <div class="result-meta">${data.output_summary ? JSON.stringify(data.output_summary).slice(0, 120) : "等待输出"}</div>
      `;
      card.addEventListener("click", () => selectNode(nodeName));
      row.appendChild(card);
    }
    container.appendChild(row);
  }
}

function renderTimeline() {
  const panel = qs("#timeline-panel");
  panel.innerHTML = "";
  const nodes = state.runDetail?.graph?.nodes || [];
  const maxDuration = Math.max(...nodes.map((node) => node.duration_ms || 0), 1);
  for (const node of nodes) {
    const row = el("div", "timeline-row");
    const width = Math.max(6, Math.round(((node.duration_ms || 0) / maxDuration) * 100));
    row.innerHTML = `
      <div class="timeline-meta">${node.node_name}</div>
      <div class="timeline-bar-track"><div class="timeline-bar" style="width:${width}%"></div></div>
      <div class="timeline-meta">${formatDuration(node.duration_ms)}</div>
    `;
    panel.appendChild(row);
  }
}

async function selectNode(nodeName) {
  if (!state.selectedRunId) return;
  state.selectedNodeName = nodeName;
  renderDag();
  const detail = await fetchJson(`/api/runs/${state.selectedRunId}/nodes/${nodeName}`);
  state.nodeDetail = detail;
  renderNodeInspector();
}

function renderNodeInspector() {
  const detail = state.nodeDetail;
  qs("#selected-node-label").textContent = detail?.node?.node_name || "未选择节点";
  qs("#node-summary").innerHTML = detail
    ? `
      <div class="step-item">
        <div class="section-row">
          <div class="panel-title">Summary</div>
          <span class="status-badge ${statusClass(detail.node.status)}">${detail.node.status}</span>
        </div>
        <div class="event-meta">开始 ${formatDate(detail.node.started_at)} · 耗时 ${formatDuration(detail.node.duration_ms)}</div>
        <pre class="result-meta">${JSON.stringify(detail.node.output_summary || detail.node.input_summary || {}, null, 2)}</pre>
      </div>
    `
    : '<div class="empty-state">点击节点查看详情</div>';

  qs("#step-trace").innerHTML = detail?.steps?.length
    ? detail.steps
        .map(
          (step) => `
            <div class="step-item">
              <div class="section-row">
                <div class="panel-title">${step.step_name}</div>
                <span class="status-badge ${statusClass(step.status)}">${step.status}</span>
              </div>
              <div class="step-meta">${step.step_type} · ${formatDuration(step.duration_ms)}</div>
              <div class="result-meta">${JSON.stringify(step.output || step.input || {}, null, 2).slice(0, 600)}</div>
            </div>
          `,
        )
        .join("")
    : '<div class="empty-state">暂无 step trace</div>';

  qs("#artifact-list").innerHTML = detail?.artifacts?.length
    ? detail.artifacts
        .map(
          (artifact) => `
            <div class="artifact-item">
              <div class="section-row">
                <div class="panel-title">${artifact.artifact_type}</div>
                <a class="artifact-link" href="/api/artifacts/${artifact.artifact_id}" target="_blank" rel="noreferrer">打开</a>
              </div>
              <div class="event-meta">${artifact.relative_path || artifact.absolute_path || "-"}</div>
            </div>
          `,
        )
        .join("")
    : '<div class="empty-state">暂无 artifact</div>';

  qs("#error-panel").innerHTML = detail?.node?.error
    ? `<div class="step-item"><div class="panel-title">Error</div><pre class="result-meta">${JSON.stringify(detail.node.error, null, 2)}</pre></div>`
    : '<div class="empty-state">无错误</div>';
}

function appendEventToFeed(event) {
  const feed = qs("#event-feed");
  const item = el("div", "event-item");
  item.innerHTML = `
    <div class="section-row">
      <div class="panel-title">${event.event_type}</div>
      <div class="event-meta">${event.node_name || event.agent_name || "-"}</div>
    </div>
    <div class="result-meta">${JSON.stringify(event.payload || {}, null, 2).slice(0, 280)}</div>
  `;
  feed.prepend(item);
  while (feed.children.length > 60) {
    feed.removeChild(feed.lastChild);
  }
}

function updateProgressStreamFromEvent(event) {
  const stream = qs("#progress-stream");
  if (!["node_started", "node_finished", "node_failed", "step_started", "step_finished", "step_failed", "run_started", "run_finished"].includes(event.event_type)) {
    return;
  }
  const card = el("div", "progress-card");
  card.innerHTML = `
    <div class="section-row" style="width:100%">
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="pulse-dot"></span>
        <div>
          <div class="panel-title">${event.node_name || event.payload?.step_name || event.event_type}</div>
          <div class="event-meta">${event.event_type}</div>
        </div>
      </div>
      <span class="status-badge ${statusClass(event.payload?.status || (event.event_type.includes('failed') ? 'failed' : event.event_type.includes('finished') ? 'success' : 'running'))}">
        ${event.payload?.status || event.event_type}
      </span>
    </div>
  `;
  stream.prepend(card);
  while (stream.children.length > 20) stream.removeChild(stream.lastChild);
}

function openEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (!state.selectedRunId) return;
  qs("#event-feed").innerHTML = "";
  qs("#progress-stream").innerHTML = "";
  state.afterEventId = 0;
  const source = new EventSource(`/api/runs/${state.selectedRunId}/stream?after_event_id=0&poll_interval_ms=1000`);
  state.eventSource = source;
  source.onmessage = (evt) => {
    const event = JSON.parse(evt.data);
    state.afterEventId = event.event_id;
    appendEventToFeed(event);
    updateProgressStreamFromEvent(event);
  };
  source.addEventListener("completed", () => {
    source.close();
  });
}

async function loadResearches() {
  const data = await fetchJson("/api/researches");
  state.researches = data.researches || [];
  renderResearches();
}

function renderResearches() {
  const container = qs("#conversation-list");
  container.innerHTML = "";
  if (!state.researches.length) {
    container.appendChild(el("div", "empty-state", "暂无研究"));
    return;
  }
  for (const research of state.researches) {
    const template = qs("#conversation-item-template").content.firstElementChild.cloneNode(true);
    template.classList.toggle("is-selected", research.research_id === state.selectedResearchId);
    template.querySelector(".item-title").textContent = research.company_name || research.ticker || research.title;
    template.querySelector(".item-subtitle").textContent = `${research.status || "draft"} · ${formatDate(research.updated_at)}`;
    template.addEventListener("click", () => selectResearch(research.research_id));
    container.appendChild(template);
  }
}

async function createResearchDraft() {
  const data = await fetchJson("/api/researches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "新的研究", query_text: null }),
  });
  await loadResearches();
  await selectResearch(data.research.research_id);
}

async function bindResearchToRun() {
  if (!state.selectedRunId) return;
  const existing = state.researches.find((item) => item.active_run_id === state.selectedRunId);
  if (existing) {
    await selectResearch(existing.research_id);
  } else {
    state.selectedResearchId = null;
    state.currentMessages = [];
    renderResearches();
    renderMessages();
  }
}

async function selectResearch(researchId) {
  state.selectedResearchId = researchId;
  renderResearches();
  const data = await fetchJson(`/api/researches/${researchId}`);
  state.currentMessages = data.messages || [];
  if (data.research?.active_run_id) {
    state.selectedRunId = data.research.active_run_id;
    renderRuns();
    state.runDetail = await fetchJson(`/api/runs/${state.selectedRunId}`);
    state.runResults = await fetchJson(`/api/runs/${state.selectedRunId}/results`);
    renderRunHeader();
    renderUserResults();
    renderDag();
    renderTimeline();
    openEventStream();
  } else {
    state.selectedRunId = null;
    state.runDetail = null;
    state.runResults = null;
    state.nodeDetail = null;
    state.selectedNodeName = null;
    renderRuns();
    renderRunHeader();
    renderUserResults();
    renderDag();
    renderTimeline();
  }
  renderMessages();
}

function renderMessages() {
  const container = qs("#conversation-thread");
  container.innerHTML = "";
  if (!state.currentMessages.length) {
    container.appendChild(el("div", "empty-state", "选择研究后可查看消息与继续追问"));
    return;
  }
  for (const message of state.currentMessages) {
    const node = el("div", `message ${message.role}`);
    node.textContent = message.content;
    container.appendChild(node);
  }
  container.scrollTop = container.scrollHeight;
}

async function sendChatMessage(messageText) {
  if (!state.selectedResearchId) {
    await createResearchDraft();
  }
  if (!state.selectedResearchId) return;
  const research = state.researches.find((item) => item.research_id === state.selectedResearchId);
  if (!research?.active_run_id || research.status !== "completed") {
    throw new Error("静态 viewer 仅支持在已完成研究上继续追问。请在主前端中先创建并完成研究。");
  }
  const payload = await fetchJson(`/api/researches/${state.selectedResearchId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: messageText }),
  });
  state.currentMessages.push(...(payload.messages || []));
  renderMessages();
}

function wireEvents() {
  qs("#mode-user").addEventListener("click", () => setMode("user"));
  qs("#mode-dev").addEventListener("click", () => setMode("dev"));
  qs("#refresh-runs-btn").addEventListener("click", () => loadRuns().catch(handleError));
  qs("#new-conversation-btn").addEventListener("click", () => createResearchDraft().catch(handleError));
  qs("#chat-send-btn").addEventListener("click", async () => {
    const input = qs("#chat-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    await sendChatMessage(text).catch(handleError);
  });
  for (const chip of document.querySelectorAll(".chip-btn")) {
    chip.addEventListener("click", async () => {
      const text = chip.dataset.prompt;
      if (!text) return;
      await sendChatMessage(text).catch(handleError);
    });
  }
}

function handleError(error) {
  console.error(error);
  alert(error.message || String(error));
}

async function bootstrap() {
  wireEvents();
  await loadResearches();
  await loadRuns();
}

bootstrap().catch(handleError);
