from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict


TraceStatus = Literal["running", "success", "failed", "skipped"]
TraceStepType = Literal[
    "node",
    "context",
    "bundle",
    "planner",
    "llm",
    "tool_call",
    "search",
    "rerank",
    "normalize",
    "parse",
    "quality_gate",
    "repair",
    "signal_generation",
    "merge",
]


class AgentTraceError(TypedDict, total=False):
    error_type: str
    error_message: str
    traceback: str


class AgentTraceStep(TypedDict, total=False):
    step_id: str
    step_type: TraceStepType
    name: str
    status: TraceStatus
    started_at: float
    finished_at: float
    duration_ms: int
    input: dict[str, Any]
    output: dict[str, Any]
    metrics: dict[str, Any]
    error: AgentTraceError | None
    artifacts: dict[str, Any]


class AgentTraceRun(TypedDict, total=False):
    run_id: str
    agent_name: str
    agent_type: str
    status: TraceStatus
    started_at: float
    finished_at: float
    duration_ms: int
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error: AgentTraceError | None
    steps: list[AgentTraceStep]
    observability: dict[str, Any]


class TraceArtifactRef(TypedDict, total=False):
    relative_path: str
    absolute_path: str


class TraceArtifactManifest(TypedDict, total=False):
    run_id: str
    root_dir: str
    run_trace: TraceArtifactRef
    summary: TraceArtifactRef
    final_state: TraceArtifactRef
    nodes: dict[str, dict[str, TraceArtifactRef]]
