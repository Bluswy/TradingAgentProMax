export type RunStatus = "running" | "success" | "failed" | "queued" | "skipped" | string;

export type Run = {
  run_id: string;
  agent_name: string;
  agent_type: string;
  parent_run_id?: string | null;
  parent_node_name?: string | null;
  status: RunStatus;
  started_at: number;
  finished_at?: number | null;
  duration_ms?: number | null;
  input_summary?: Record<string, unknown> | null;
  output_summary?: Record<string, unknown> | null;
  error?: unknown;
  created_at?: number;
  updated_at?: number;
};

export type GraphNode = {
  run_id: string;
  node_name: string;
  status: RunStatus;
  started_at?: number | null;
  finished_at?: number | null;
  duration_ms?: number | null;
  input_summary?: Record<string, unknown> | null;
  output_summary?: Record<string, unknown> | null;
  error?: unknown;
};

export type TraceStep = {
  step_id: string;
  run_id: string;
  node_name?: string | null;
  step_name: string;
  step_type: string;
  status: RunStatus;
  started_at?: number | null;
  finished_at?: number | null;
  duration_ms?: number | null;
  input?: unknown;
  output?: unknown;
  metrics?: unknown;
  error?: unknown;
};

export type Artifact = {
  artifact_id: number;
  run_id: string;
  node_name?: string | null;
  step_id?: string | null;
  artifact_type: string;
  relative_path?: string | null;
  absolute_path?: string | null;
  created_at: number;
};

export type RunDetail = {
  run: Run;
  graph: {
    nodes: GraphNode[];
    edges: [string, string][];
  };
  child_runs: Run[];
  artifacts: Artifact[];
};

export type EventItem = {
  event_id: number;
  run_id: string;
  node_name?: string | null;
  step_id?: string | null;
  agent_name: string;
  agent_type: string;
  event_type: string;
  payload?: Record<string, unknown>;
  created_at: number;
};

export type NodeDetail = {
  run_id: string;
  node: GraphNode;
  steps: TraceStep[];
  artifacts: Artifact[];
  child_runs: Run[];
};

export type ResearchStatus = "draft" | "ready" | "running" | "completed" | "failed" | string;

export type Research = {
  research_id: string;
  title: string;
  query_text?: string | null;
  ticker?: string | null;
  company_name?: string | null;
  analysis_date?: string | null;
  parse_result?: ResearchParseResult | null;
  status: ResearchStatus;
  active_run_id?: string | null;
  run_status?: RunStatus | null;
  created_at: number;
  updated_at: number;
};

export type ResearchMessage = {
  message_id: number;
  research_id: string;
  role: "user" | "assistant" | string;
  content: string;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: number;
};

export type ResearchParseResult = {
  query_text: string;
  ticker?: string | null;
  company_name?: string | null;
  analysis_date: string;
  query_intent?: string | null;
  parse_confidence: number;
  needs_confirmation: boolean;
  clarification_question?: string | null;
};

export type FinalState = {
  ticker?: string;
  analysis_date?: string;
  company_context?: Record<string, unknown>;
  technical_result?: Record<string, unknown>;
  fundamental_result?: Record<string, unknown>;
  event_news_result?: Record<string, unknown>;
  sector_flow_result?: Record<string, unknown>;
  strategy_style_result?: Record<string, unknown>;
  strategy_decision_result?: Record<string, unknown>;
  company_report_result?: Record<string, unknown>;
  final_report_result?: Record<string, unknown>;
  _report_artifact_status?: Record<string, unknown>;
};

export type ReportSection = {
  id: string;
  title: string;
  body: string;
};

export type DecisionEvidence = {
  module?: string;
  title?: string;
  fact?: string;
  importance?: number;
};

export type ModuleContribution = {
  stance?: string;
  weight?: number;
  summary?: string;
};

export type DecisionWatchItem = {
  variable?: string;
  reason?: string;
  window?: string;
  bull_case_if_met?: string;
  bear_case_if_missed?: string;
};

export type StructuredInvalidation = {
  type?: string;
  label?: string;
  condition?: string;
  action_after_trigger?: string;
  severity?: string;
};

export type StructuredRisk = {
  label?: string;
  category?: string;
  impact_path?: string;
  risk_level?: string;
};
