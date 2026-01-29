"""Tests for the instrumentation layer."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from claude_orchestrator.instrumentation import (
	ToolCallRecord,
	ToolCallStore,
	instrument_mcp_server,
)


def test_record_and_query(tmp_path: Path):
	"""Record a tool call and query it back."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	record = ToolCallRecord(
		tool_name="health_check",
		args_json="{}",
		result_summary="ok",
		duration_seconds=0.05,
		session_id="sess-1",
	)
	store.record(record)

	results = store.query()
	assert len(results) == 1
	assert results[0].tool_name == "health_check"
	assert results[0].session_id == "sess-1"
	assert results[0].success is True


def test_query_by_tool_name(tmp_path: Path):
	"""Query should filter by tool name."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	store.record(ToolCallRecord(tool_name="get_plan", args_json='{"id": "1"}'))
	store.record(ToolCallRecord(tool_name="create_plan", args_json='{"goal": "test"}'))
	store.record(ToolCallRecord(tool_name="get_plan", args_json='{"id": "2"}'))

	results = store.query(tool_name="get_plan")
	assert len(results) == 2
	assert all(r.tool_name == "get_plan" for r in results)


def test_query_by_session_id(tmp_path: Path):
	"""Query should filter by session ID."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	store.record(ToolCallRecord(tool_name="a", session_id="s1"))
	store.record(ToolCallRecord(tool_name="b", session_id="s2"))
	store.record(ToolCallRecord(tool_name="c", session_id="s1"))

	results = store.query(session_id="s1")
	assert len(results) == 2


def test_query_since(tmp_path: Path):
	"""Query should filter by timestamp."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
	new_ts = datetime.now().isoformat()

	store.record(ToolCallRecord(tool_name="old", timestamp=old_ts))
	store.record(ToolCallRecord(tool_name="new", timestamp=new_ts))

	cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
	results = store.query(since=cutoff)
	assert len(results) == 1
	assert results[0].tool_name == "new"


def test_query_limit(tmp_path: Path):
	"""Query should respect limit."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	for i in range(10):
		store.record(ToolCallRecord(tool_name=f"tool_{i}"))

	results = store.query(limit=3)
	assert len(results) == 3


def test_get_stats(tmp_path: Path):
	"""Stats should aggregate correctly."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	store.record(ToolCallRecord(tool_name="get_plan", duration_seconds=0.1, success=True))
	store.record(ToolCallRecord(tool_name="get_plan", duration_seconds=0.3, success=True))
	store.record(ToolCallRecord(tool_name="get_plan", duration_seconds=0.2, success=False))
	store.record(ToolCallRecord(tool_name="create_plan", duration_seconds=0.5, success=True))

	stats = store.get_stats()
	assert len(stats) == 2

	# get_plan should be first (3 calls > 1)
	gp = stats[0]
	assert gp.tool_name == "get_plan"
	assert gp.call_count == 3
	assert abs(gp.avg_duration - 0.2) < 0.01
	assert abs(gp.success_rate - 66.67) < 1.0

	cp = stats[1]
	assert cp.tool_name == "create_plan"
	assert cp.call_count == 1
	assert cp.success_rate == 100.0


def test_clear_all(tmp_path: Path):
	"""Clear should remove all records."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	for i in range(5):
		store.record(ToolCallRecord(tool_name=f"t{i}"))

	deleted = store.clear()
	assert deleted == 5
	assert len(store.query()) == 0


def test_clear_before(tmp_path: Path):
	"""Clear with before should only remove old records."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
	new_ts = datetime.now().isoformat()

	store.record(ToolCallRecord(tool_name="old", timestamp=old_ts))
	store.record(ToolCallRecord(tool_name="new", timestamp=new_ts))

	cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
	deleted = store.clear(before=cutoff)
	assert deleted == 1

	results = store.query()
	assert len(results) == 1
	assert results[0].tool_name == "new"


def test_failed_record(tmp_path: Path):
	"""Records with success=False should be stored and queryable."""
	store = ToolCallStore(str(tmp_path / "test.db"))

	store.record(ToolCallRecord(tool_name="fail_tool", success=False, result_summary="error: timeout"))

	results = store.query()
	assert len(results) == 1
	assert results[0].success is False
	assert "timeout" in results[0].result_summary


def test_instrument_mcp_server_wraps_tools(tmp_path: Path):
	"""instrument_mcp_server should wrap tool functions."""
	# Mock a FastMCP server with a tool manager
	mock_fn = AsyncMock(return_value="result")
	mock_tool = MagicMock()
	mock_tool.fn = mock_fn

	mock_tool_manager = MagicMock()
	mock_tool_manager.tools = {"test_tool": mock_tool}

	mock_server = MagicMock()
	mock_server._tool_manager = mock_tool_manager

	# Patch the store to use tmp_path
	import claude_orchestrator.instrumentation as instr_mod
	original_init = ToolCallStore.__init__

	def patched_init(self, db_path=""):
		original_init(self, str(tmp_path / "instrument.db"))

	instr_mod.ToolCallStore.__init__ = patched_init
	try:
		instrument_mcp_server(mock_server)
	finally:
		instr_mod.ToolCallStore.__init__ = original_init

	# The tool's fn should have been replaced
	assert mock_tool.fn is not mock_fn

	# Call the instrumented function
	result = asyncio.run(mock_tool.fn(key="value"))
	assert result == "result"
	mock_fn.assert_called_once_with(key="value")


def test_instrument_mcp_server_no_tool_manager():
	"""instrument_mcp_server should handle missing tool_manager gracefully."""
	mock_server = MagicMock(spec=[])  # no _tool_manager attribute
	# Should not raise
	instrument_mcp_server(mock_server)


def test_empty_store_stats(tmp_path: Path):
	"""Stats on empty store should return empty list."""
	store = ToolCallStore(str(tmp_path / "test.db"))
	assert store.get_stats() == []


def test_empty_store_query(tmp_path: Path):
	"""Query on empty store should return empty list."""
	store = ToolCallStore(str(tmp_path / "test.db"))
	assert store.query() == []
