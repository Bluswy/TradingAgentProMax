from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


class AgentExecutionTimeoutError(TimeoutError):
    pass


class AgentExecutionFailedError(RuntimeError):
    def __init__(self, agent_name: str, attempts: list[dict[str, Any]], last_error: Exception):
        self.agent_name = agent_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(str(last_error))


@dataclass
class _ThreadResult:
    value: Any = None
    error: Exception | None = None


def is_retryable_agent_error(error: Exception) -> bool:
    if isinstance(error, AgentExecutionTimeoutError):
        return True
    if isinstance(error, json.JSONDecodeError):
        return True

    message = str(error).lower()
    non_retryable_markers = (
        "unsupported",
        "no market data found",
        "missing tushare token",
        "no open trading day found",
        "no trade calendar data found",
        "ticker not resolved",
        "research not found",
        "run not found",
        "artifact not found",
    )
    if any(marker in message for marker in non_retryable_markers):
        return False

    retryable_markers = (
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "service unavailable",
        "rate limit",
        "json",
        "parse",
        "validation",
        "schema",
        "did not return valid json",
    )
    if any(marker in message for marker in retryable_markers):
        return True

    return isinstance(error, (RuntimeError, TimeoutError, ConnectionError, OSError))


def _run_with_timeout(call: Callable[[], Any], timeout_seconds: int) -> tuple[Any, Exception | None, int]:
    result = _ThreadResult()

    def target() -> None:
        try:
            result.value = call()
        except Exception as error:  # pragma: no cover - delegated execution path
            result.error = error

    started_at = time.time()
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    duration_ms = int((time.time() - started_at) * 1000)
    if thread.is_alive():
        return None, AgentExecutionTimeoutError(f"Agent execution timed out after {timeout_seconds}s"), duration_ms
    return result.value, result.error, duration_ms


def run_with_timeout_and_retry(
    *,
    call: Callable[[], Any],
    agent_name: str,
    timeout_seconds: int = 180,
    max_retries: int = 1,
    on_attempt_start: Callable[[int, int], None] | None = None,
    on_attempt_end: Callable[[int, dict[str, Any]], None] | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    max_attempts = max_retries + 1
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        if on_attempt_start is not None:
            on_attempt_start(attempt, max_attempts)

        value, error, duration_ms = _run_with_timeout(call, timeout_seconds)
        attempt_payload = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "timeout_seconds": timeout_seconds,
            "duration_ms": duration_ms,
            "status": "success" if error is None else "failed",
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
        }

        if error is None:
            attempts.append(attempt_payload)
            if on_attempt_end is not None:
                on_attempt_end(attempt, attempt_payload)
            return value, attempts

        retryable = attempt < max_attempts and is_retryable_agent_error(error)
        attempt_payload["will_retry"] = retryable
        attempts.append(attempt_payload)
        if on_attempt_end is not None:
            on_attempt_end(attempt, attempt_payload)
        last_error = error
        if not retryable:
            break

    assert last_error is not None
    failed = AgentExecutionFailedError(agent_name=agent_name, attempts=attempts, last_error=last_error)
    raise failed
