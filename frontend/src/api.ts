import type {
  Artifact,
  EventItem,
  FinalState,
  NodeDetail,
  Research,
  ResearchMessage,
  ResearchParseResult,
  Run,
  RunDetail,
  TraceStep,
} from "./types";

export class HttpError extends Error {
  status: number;
  detail: string;
  url: string;

  constructor(status: number, detail: string, url: string) {
    super(`${status} ${detail}`);
    this.name = "HttpError";
    this.status = status;
    this.detail = detail;
    this.url = url;
  }
}

function extractErrorDetail(raw: string, contentType: string | null): string {
  const text = raw.trim();
  if (!text) return "Request failed";
  if (contentType?.includes("application/json") || text.startsWith("{")) {
    try {
      const payload = JSON.parse(text) as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) return payload.detail.trim();
      if (typeof payload.message === "string" && payload.message.trim()) return payload.message.trim();
    } catch {
      return text;
    }
  }
  return text;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const text = await response.text();
    throw new HttpError(
      response.status,
      extractErrorDetail(text, response.headers.get("content-type")) || response.statusText || "Request failed",
      url,
    );
  }
  return response.json() as Promise<T>;
}

export const api = {
  listRuns: () => requestJson<{ runs: Run[] }>("/api/runs?limit=50"),
  getRun: (runId: string) => requestJson<RunDetail>(`/api/runs/${runId}`),
  getRunResults: (runId: string) => requestJson<FinalState>(`/api/runs/${runId}/results`),
  getNode: (runId: string, nodeName: string) =>
    requestJson<NodeDetail>(`/api/runs/${runId}/nodes/${encodeURIComponent(nodeName)}`),
  getEvents: (runId: string, afterEventId = 0) =>
    requestJson<{ events: EventItem[]; next_after_event_id: number }>(
      `/api/runs/${runId}/events?after_event_id=${afterEventId}`,
    ),
  getSteps: (runId: string, nodeName?: string) =>
    requestJson<{ steps: TraceStep[] }>(
      `/api/runs/${runId}/steps${nodeName ? `?node_name=${encodeURIComponent(nodeName)}` : ""}`,
    ),
  listResearches: () => requestJson<{ researches: Research[] }>("/api/researches"),
  createResearch: (payload: { title?: string; query_text?: string | null }) =>
    requestJson<{ research: Research }>("/api/researches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getResearch: (researchId: string) =>
    requestJson<{ research: Research; messages: ResearchMessage[] }>(`/api/researches/${researchId}`),
  parseResearch: (researchId: string, payload: { query_text: string; analysis_date?: string }) =>
    requestJson<{ research: Research; parse_result: ResearchParseResult }>(
      `/api/researches/${researchId}/parse`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  runResearch: (researchId: string, payload: { confirm?: boolean } = {}) =>
    requestJson<{ research: Research; messages: ResearchMessage[]; run_id: string }>(
      `/api/researches/${researchId}/run`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  getResearchMessages: (researchId: string) =>
    requestJson<{ messages: ResearchMessage[] }>(`/api/researches/${researchId}/messages`),
  chatResearch: (researchId: string, payload: { message: string }) =>
    requestJson<{ research: Research; messages: ResearchMessage[] }>(
      `/api/researches/${researchId}/chat`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  artifactUrl: (artifactId: number) => `/api/artifacts/${artifactId}`,
};
