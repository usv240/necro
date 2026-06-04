"""Durable JSONL traces for end-to-end NECRO workflow debugging."""

from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.config import OUTPUT_PATH


_CURRENT_TRACE: contextvars.ContextVar["RunTrace | None"] = contextvars.ContextVar(
    "necro_current_trace", default=None
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class RunTrace:
    """Append-only trace file plus a compact final summary for one workflow run."""

    def __init__(
        self,
        feature: str,
        workflow: str,
        project_path: str,
        run_id: str | None = None,
        base_dir: Path | None = None,
    ) -> None:
        self.feature = feature
        self.workflow = workflow
        self.project_path = project_path
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.started_at = _utc_now()
        self._started_perf = time.perf_counter()
        self._sequence = 0
        self._finished = False
        self._lock = threading.Lock()

        trace_dir = (base_dir or OUTPUT_PATH / "traces") / feature
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = trace_dir / f"{self.run_id}.jsonl"
        self.summary_path = trace_dir / f"{self.run_id}.summary.json"
        self.event("run_started", workflow=workflow)

    def metadata(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "feature": self.feature,
            "workflow": self.workflow,
            "log_path": str(self.log_path),
            "summary_path": str(self.summary_path),
        }

    def event(self, event: str, **details: Any) -> None:
        with self._lock:
            self._sequence += 1
            record = {
                "timestamp": _utc_now(),
                "sequence": self._sequence,
                "run_id": self.run_id,
                "feature": self.feature,
                "workflow": self.workflow,
                "project_path": self.project_path,
                "event": event,
                **details,
            }
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=_json_default, ensure_ascii=True) + "\n")

    def finish(self, status: str, **details: Any) -> None:
        if self._finished:
            return
        self._finished = True
        duration_ms = round((time.perf_counter() - self._started_perf) * 1000, 2)
        self.event("run_finished", status=status, duration_ms=duration_ms, **details)
        summary = {
            **self.metadata(),
            "project_path": self.project_path,
            "started_at": self.started_at,
            "finished_at": _utc_now(),
            "status": status,
            "duration_ms": duration_ms,
            "event_count": self._sequence,
            **details,
        }
        self.summary_path.write_text(
            json.dumps(summary, indent=2, default=_json_default, ensure_ascii=True),
            encoding="utf-8",
        )

    def wrap_emit(self, emit: Callable[[str], Awaitable[None]]) -> Callable[[str], Awaitable[None]]:
        async def traced_emit(message: str) -> None:
            if message.startswith("__REPORT__:"):
                self.event("report_emitted")
            else:
                self.event("progress", message=message)
            await emit(message)

        return traced_emit


def bind_trace(trace: RunTrace):
    return _CURRENT_TRACE.set(trace)


def reset_trace(token) -> None:
    _CURRENT_TRACE.reset(token)


def current_trace_metadata() -> dict[str, str] | None:
    trace = _CURRENT_TRACE.get()
    return trace.metadata() if trace else None


def trace_event(event: str, **details: Any) -> None:
    trace = _CURRENT_TRACE.get()
    if trace:
        trace.event(event, **details)
