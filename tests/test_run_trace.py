import asyncio
import json

import pytest

from backend.services.gitlab_mcp import GitLabClient
from backend.services.run_trace import RunTrace, bind_trace, reset_trace


pytestmark = pytest.mark.unit


def _read_events(trace: RunTrace) -> list[dict]:
    return [
        json.loads(line)
        for line in trace.log_path.read_text(encoding="utf-8").splitlines()
    ]


def test_run_trace_writes_jsonl_and_summary(tmp_path):
    trace = RunTrace("revival", "unit_test", "org/repo", run_id="trace-test", base_dir=tmp_path)
    trace.event("custom_event", answer=42)
    trace.finish("completed", features_found=3)

    events = _read_events(trace)
    summary = json.loads(trace.summary_path.read_text(encoding="utf-8"))

    assert [event["event"] for event in events] == [
        "run_started", "custom_event", "run_finished",
    ]
    assert summary["status"] == "completed"
    assert summary["features_found"] == 3
    assert summary["event_count"] == 3


def test_wrap_emit_records_progress_without_dumping_report(tmp_path):
    trace = RunTrace("revival", "unit_test", "org/repo", run_id="emit-test", base_dir=tmp_path)
    received = []

    async def emit(message):
        received.append(message)

    async def run():
        traced_emit = trace.wrap_emit(emit)
        await traced_emit("phase one")
        await traced_emit('__REPORT__:{"large": "payload"}')

    asyncio.run(run())
    events = _read_events(trace)

    assert received == ["phase one", '__REPORT__:{"large": "payload"}']
    assert events[-2] == {
        **{key: events[-2][key] for key in (
            "timestamp", "sequence", "run_id", "feature", "workflow", "project_path",
        )},
        "event": "progress",
        "message": "phase one",
    }
    assert events[-1]["event"] == "report_emitted"
    assert "message" not in events[-1]


def test_gitlab_no_token_is_recorded(monkeypatch, tmp_path):
    from backend.services import gitlab_mcp

    monkeypatch.setattr(gitlab_mcp.settings, "GITLAB_TOKEN", "")
    trace = RunTrace("revival", "unit_test", "org/repo", run_id="gitlab-test", base_dir=tmp_path)
    token = bind_trace(trace)
    try:
        assert asyncio.run(GitLabClient().list_commits("org/repo")) == []
    finally:
        reset_trace(token)

    assert _read_events(trace)[-1] == {
        **{key: _read_events(trace)[-1][key] for key in (
            "timestamp", "sequence", "run_id", "feature", "workflow", "project_path",
        )},
        "event": "gitlab_http",
        "method": "GET",
        "path": "/projects/org%2Frepo/repository/commits",
        "status": "skipped_no_token",
    }


def test_clean_revival_pipeline_returns_completed_trace(monkeypatch, tmp_path):
    from backend.routes import stream
    from backend.services import git_forensics, run_trace

    async def assess(_emit, _project_path, max_commits, lookback_months):
        return max_commits, lookback_months

    async def detect(*_args, **_kwargs):
        return []

    monkeypatch.setattr(run_trace, "OUTPUT_PATH", tmp_path)
    monkeypatch.setattr(stream.settings, "MONGODB_URI", "")
    monkeypatch.setattr(stream, "_run_adk_pre_scan_assessment", assess)
    monkeypatch.setattr(git_forensics, "detect_dead_features", detect)
    messages = []

    async def emit(message):
        messages.append(message)

    asyncio.run(stream._stream_live(emit, "org/repo", 10, 6))

    report_message = next(message for message in messages if message.startswith("__REPORT__:"))
    report = json.loads(report_message.removeprefix("__REPORT__:"))
    summary = json.loads(
        (tmp_path / "traces" / "revival" / f"{report['trace']['run_id']}.summary.json")
        .read_text(encoding="utf-8")
    )

    assert report["clean_scan"] is True
    assert report["trace"]["feature"] == "revival"
    assert summary["status"] == "completed"
