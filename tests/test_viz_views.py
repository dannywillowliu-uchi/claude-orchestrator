"""Tests for visualizer Rich views."""

from pathlib import Path

from rich.console import Console

from claude_orchestrator.instrumentation import ToolCallRecord, ToolCallStore
from claude_orchestrator.plans.models import (
	Decision,
	Phase,
	Plan,
	PlanOverview,
	PlanStatus,
	Task,
	TaskStatus,
)
from claude_orchestrator.visualizer.dashboard import render_dashboard
from claude_orchestrator.visualizer.plan_progress import render_plan_progress, render_plan_summary
from claude_orchestrator.visualizer.session_timeline import render_session_detail, render_session_list
from claude_orchestrator.visualizer.tool_stats import render_tool_detail, render_tool_stats, render_tool_timeline
from claude_orchestrator.visualizer.utils import (
	format_duration,
	format_timestamp,
	status_style,
	status_text,
	truncate_args,
)

# -- utils tests --

def test_format_duration_submillisecond():
	assert format_duration(0.0001) == "<1ms"


def test_format_duration_milliseconds():
	assert format_duration(0.045) == "45ms"


def test_format_duration_seconds():
	assert format_duration(1.23) == "1.2s"


def test_format_duration_minutes():
	result = format_duration(125.0)
	assert "2m" in result


def test_format_timestamp_recent():
	from datetime import datetime
	ts = datetime.now().isoformat()
	result = format_timestamp(ts)
	assert "ago" in result or "0s" in result


def test_format_timestamp_invalid():
	assert format_timestamp("not-a-date") == "not-a-date"


def test_truncate_args_short():
	assert truncate_args('{"a": 1}') == '{"a": 1}'


def test_truncate_args_long():
	long = "x" * 100
	result = truncate_args(long, max_len=20)
	assert len(result) == 20
	assert result.endswith("...")


def test_truncate_args_empty():
	assert truncate_args("") == ""


def test_status_style():
	assert status_style(True) == "green"
	assert status_style(False) == "red"


def test_status_text():
	assert status_text(True) == "OK"
	assert status_text(False) == "FAIL"


# -- helper to make a populated store --

def _make_store(tmp_path: Path) -> ToolCallStore:
	store = ToolCallStore(str(tmp_path / "viz_test.db"))
	store.record(ToolCallRecord(tool_name="get_plan", args_json='{"id":"p1"}', duration_seconds=0.1, session_id="s1"))
	store.record(ToolCallRecord(
		tool_name="create_plan", args_json='{"goal":"test"}', duration_seconds=0.5, session_id="s1",
	))
	store.record(ToolCallRecord(
		tool_name="get_plan", args_json='{"id":"p2"}', duration_seconds=0.2, session_id="s2", success=False,
	))
	return store


def _make_plan() -> Plan:
	return Plan(
		id="plan-123",
		project="test-project",
		version=2,
		status=PlanStatus.IN_PROGRESS,
		overview=PlanOverview(
			goal="Build observability dashboard",
			success_criteria=["All tests pass", "CLI works"],
			constraints=["Use Rich library"],
		),
		phases=[
			Phase(
				id="phase-1",
				name="Phase 1: Setup",
				description="Initial project setup",
				status=TaskStatus.COMPLETED,
				tasks=[
					Task(id="t1", description="Create package structure", status=TaskStatus.COMPLETED),
					Task(id="t2", description="Add dependencies", status=TaskStatus.COMPLETED),
				],
			),
			Phase(
				id="phase-2",
				name="Phase 2: Implementation",
				description="Build core features",
				status=TaskStatus.IN_PROGRESS,
				tasks=[
					Task(id="t3", description="Implement tool stats view", status=TaskStatus.COMPLETED),
					Task(id="t4", description="Implement dashboard", status=TaskStatus.IN_PROGRESS),
					Task(id="t5", description="Write tests", status=TaskStatus.PENDING),
				],
			),
			Phase(
				id="phase-3",
				name="Phase 3: CLI",
				description="Add CLI commands",
				status=TaskStatus.PENDING,
				tasks=[
					Task(id="t6", description="Add viz subcommand", status=TaskStatus.PENDING),
				],
			),
		],
		decisions=[
			Decision(
				id="d1",
				decision="Use Rich for terminal UI",
				rationale="Best Python terminal rendering library",
			),
		],
	)


# -- tool_stats view tests --

def test_render_tool_stats_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_stats(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "get_plan" in output
	assert "create_plan" in output


def test_render_tool_stats_empty(tmp_path: Path):
	store = ToolCallStore(str(tmp_path / "empty.db"))
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_stats(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No tool call data" in output


def test_render_tool_timeline_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_timeline(store, console=console, limit=10)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "Timeline" in output


def test_render_tool_timeline_empty(tmp_path: Path):
	store = ToolCallStore(str(tmp_path / "empty.db"))
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_timeline(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No tool calls" in output


def test_render_tool_detail_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_detail(store, "get_plan", console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "get_plan" in output


def test_render_tool_detail_no_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_tool_detail(store, "nonexistent_tool", console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No calls recorded" in output


# -- session_timeline view tests --

def test_render_session_list_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_session_list(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "s1" in output
	assert "s2" in output


def test_render_session_list_empty(tmp_path: Path):
	store = ToolCallStore(str(tmp_path / "empty.db"))
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_session_list(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No sessions" in output


def test_render_session_detail_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_session_detail(store, "s1", console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "s1" in output
	assert "get_plan" in output


def test_render_session_detail_no_data(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_session_detail(store, "nonexistent", console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No calls found" in output


# -- plan_progress view tests --

def test_render_plan_progress(tmp_path: Path):
	plan = _make_plan()
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_plan_progress(plan, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "Build observability dashboard" in output
	assert "Phase 1" in output
	assert "Phase 2" in output


def test_render_plan_summary(tmp_path: Path):
	plan = _make_plan()
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_plan_summary(plan, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "plan-123" in output
	assert "test-project" in output
	assert "Rich" in output


# -- dashboard view tests --

def test_render_dashboard_with_data(tmp_path: Path):
	store = _make_store(tmp_path)
	plan = _make_plan()
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_dashboard(store, plan=plan, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "Dashboard" in output
	assert "Summary" in output


def test_render_dashboard_empty(tmp_path: Path):
	store = ToolCallStore(str(tmp_path / "empty.db"))
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_dashboard(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No data recorded" in output


def test_render_dashboard_no_plan(tmp_path: Path):
	store = _make_store(tmp_path)
	console = Console(file=open(tmp_path / "out.txt", "w"), force_terminal=True)
	render_dashboard(store, console=console)
	console.file.close()
	output = (tmp_path / "out.txt").read_text()
	assert "No active plan" in output
