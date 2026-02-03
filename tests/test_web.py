"""Tests for the web dashboard API endpoints."""

from pathlib import Path

import pytest

from claude_orchestrator.instrumentation import ToolCallRecord, ToolCallStore

try:
	from starlette.testclient import TestClient

	from claude_orchestrator.web.app import build_app

	HAS_WEB = True
except ImportError:
	HAS_WEB = False

pytestmark = pytest.mark.skipif(not HAS_WEB, reason="web extras not installed")


@pytest.fixture
def store(tmp_path: Path) -> ToolCallStore:
	"""Create a ToolCallStore with seeded data."""
	s = ToolCallStore(str(tmp_path / "test.db"))
	s.record(ToolCallRecord(
		tool_name="health_check",
		args_json="{}",
		result_summary="ok",
		duration_seconds=0.05,
		timestamp="2026-01-29T10:00:00",
		session_id="sess-1",
		success=True,
	))
	s.record(ToolCallRecord(
		tool_name="get_plan",
		args_json='{"id": "abc"}',
		result_summary="plan data",
		duration_seconds=0.12,
		timestamp="2026-01-29T10:00:01",
		session_id="sess-1",
		success=True,
	))
	s.record(ToolCallRecord(
		tool_name="run_verification",
		args_json="{}",
		result_summary="failed",
		duration_seconds=2.5,
		timestamp="2026-01-29T10:00:02",
		session_id="sess-2",
		success=False,
	))
	return s


@pytest.fixture
def client(store: ToolCallStore) -> "TestClient":
	"""Create a test client with the seeded store."""
	app = build_app(db_path=str(store.db_path))
	# Override the store with our seeded one
	app.state.store = store
	return TestClient(app)


def test_index_returns_html(client: "TestClient"):
	resp = client.get("/")
	assert resp.status_code == 200
	assert "text/html" in resp.headers["content-type"]
	assert "Claude Orchestrator" in resp.text


def test_api_stats(client: "TestClient"):
	resp = client.get("/api/stats")
	assert resp.status_code == 200
	stats = resp.json()
	assert isinstance(stats, list)
	assert len(stats) == 3
	names = {s["tool_name"] for s in stats}
	assert "health_check" in names
	assert "get_plan" in names
	assert "run_verification" in names
	# Check shape
	for s in stats:
		assert "call_count" in s
		assert "avg_duration" in s
		assert "success_rate" in s


def test_api_calls(client: "TestClient"):
	resp = client.get("/api/calls?limit=10")
	assert resp.status_code == 200
	calls = resp.json()
	assert len(calls) == 3
	# Newest first
	assert calls[0]["tool_name"] == "run_verification"
	assert calls[0]["success"] is False


def test_api_calls_filter_session(client: "TestClient"):
	resp = client.get("/api/calls?session_id=sess-1")
	assert resp.status_code == 200
	calls = resp.json()
	assert len(calls) == 2
	assert all(c["session_id"] == "sess-1" for c in calls)


def test_api_sessions(client: "TestClient"):
	resp = client.get("/api/sessions")
	assert resp.status_code == 200
	sessions = resp.json()
	assert len(sessions) == 2
	ids = {s["session_id"] for s in sessions}
	assert "sess-1" in ids
	assert "sess-2" in ids
	# sess-1 has 2 calls
	sess1 = next(s for s in sessions if s["session_id"] == "sess-1")
	assert sess1["call_count"] == 2


def test_api_session_detail(client: "TestClient"):
	resp = client.get("/api/session/sess-1")
	assert resp.status_code == 200
	calls = resp.json()
	assert len(calls) == 2
	assert all(c["session_id"] == "sess-1" for c in calls)


def test_api_stream_route_exists(client: "TestClient"):
	"""SSE endpoint route should be registered."""
	# The SSE endpoint is a long-lived stream, so we just verify
	# the route exists by checking it doesn't 404.
	# Full SSE testing requires async test client.
	routes = [r.path for r in client.app.routes]
	assert "/api/stream" in routes
