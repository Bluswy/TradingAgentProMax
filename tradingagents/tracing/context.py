from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_trace_parent_run_id: ContextVar[str | None] = ContextVar("trace_parent_run_id", default=None)
_trace_parent_node_name: ContextVar[str | None] = ContextVar("trace_parent_node_name", default=None)
_trace_parent_meta: ContextVar[dict[str, Any] | None] = ContextVar("trace_parent_meta", default=None)


@contextmanager
def trace_parent_scope(run_id: str | None, node_name: str | None, meta: dict[str, Any] | None = None):
    token_run = _trace_parent_run_id.set(run_id)
    token_node = _trace_parent_node_name.set(node_name)
    token_meta = _trace_parent_meta.set(meta or {})
    try:
        yield
    finally:
        _trace_parent_run_id.reset(token_run)
        _trace_parent_node_name.reset(token_node)
        _trace_parent_meta.reset(token_meta)


def get_trace_parent() -> dict[str, Any]:
    return {
        "parent_run_id": _trace_parent_run_id.get(),
        "parent_node_name": _trace_parent_node_name.get(),
        "parent_meta": _trace_parent_meta.get() or {},
    }
