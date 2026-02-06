"""End-to-end tests for the workflow system."""

from pathlib import Path

from claude_orchestrator.project_memory import log_gotcha
from claude_orchestrator.workflow import (
	WORKFLOW_DIR,
	check_tool_availability,
	get_workflow_state,
	init_workflow,
	update_progress,
)


def test_full_workflow_lifecycle(tmp_path: Path):
	"""Test a complete workflow lifecycle: init -> progress updates -> tool checks."""
	# 1. Initialize workflow
	result = init_workflow(str(tmp_path))
	assert result["success"] is True

	# 2. Verify fresh state
	state = get_workflow_state(str(tmp_path))
	assert state.exists is True
	assert state.current_phase == "Not started"

	# 3. Complete discovery phase
	update_progress(
		str(tmp_path),
		phase_completed="Discovery",
		phase_started="Research",
		summary="Identified requirements and constraints.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Research"

	# 4. Add research files
	research_dir = tmp_path / WORKFLOW_DIR / "research"
	(research_dir / "api-design.md").write_text("# API Design\nFindings here.")
	state = get_workflow_state(str(tmp_path))
	assert "api-design" in state.research_topics

	# 5. Complete research, start planning
	update_progress(
		str(tmp_path),
		phase_completed="Research",
		phase_started="Phase 1 - Core Implementation",
		summary="Research complete, synthesized findings.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Phase 1 - Core Implementation"

	# 6. Complete with commit hash
	update_progress(
		str(tmp_path),
		phase_completed="Phase 1 - Core Implementation",
		phase_started="Phase 2 - Tests",
		commit_hash="abc1234",
		summary="Implemented core module.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Phase 2 - Tests"
	assert state.last_commit == "abc1234"

	# 7. Verify progress file has history
	content = (tmp_path / WORKFLOW_DIR / "progress.md").read_text(encoding="utf-8")
	assert "Discovery" in content
	assert "Research" in content
	assert "Phase 1 - Core Implementation" in content
	assert "abc1234" in content

	# 8. Check tool availability
	tools_result = check_tool_availability(["git", "run_verification"])
	assert tools_result["tools"]["git"] == "available"
	assert tools_result["tools"]["run_verification"] == "mcp (assumed available)"


def test_mcp_server_starts_with_expected_tools():
	"""MCP server should start and register exactly 11 tools."""
	from claude_orchestrator.server import mcp

	tools = mcp._tool_manager._tools
	assert len(tools) == 11, f"Expected 11 tools, got {len(tools)}: {set(tools.keys())}"

	expected = {
		"health_check",
		"find_project", "list_my_projects",
		"update_project_status", "log_project_decision",
		"log_project_gotcha", "log_global_learning",
		"run_verification",
		"init_project_workflow", "workflow_progress", "check_tools",
	}
	assert set(tools.keys()) == expected


def test_workflow_state_parsing(tmp_path: Path):
	"""Test that workflow state is correctly parsed from various progress.md states."""
	workflow_dir = tmp_path / WORKFLOW_DIR
	workflow_dir.mkdir(parents=True)
	(workflow_dir / "discover.md").write_text("# Discovery")
	(workflow_dir / "plan.md").write_text("# Plan")

	# Custom progress with specific values
	progress = workflow_dir / "progress.md"
	progress.write_text(
		"# Progress\n\n"
		"## Current State\n"
		"Phase: Phase 3 - Deployment\n"
		"Active Task: Configure CI pipeline\n"
		"Blocked: Waiting for API keys\n"
		"Last Commit: def5678\n\n"
		"## Next Up\n"
		"- Continue deployment\n\n"
		"## Phase History\n",
		encoding="utf-8",
	)

	state = get_workflow_state(str(tmp_path))
	assert state.exists is True
	assert state.current_phase == "Phase 3 - Deployment"
	assert state.active_task == "Configure CI pipeline"
	assert state.blocked == "Waiting for API keys"
	assert state.last_commit == "def5678"
	assert state.has_discover is True
	assert state.has_plan is True
	assert state.has_progress is True


def test_gotcha_deduplication(tmp_path: Path):
	"""log_gotcha should skip duplicates instead of appending them again."""
	claude_md = tmp_path / "CLAUDE.md"
	claude_md.write_text(
		"# Project\n\n## Gotchas & Learnings\n\n## Other\n",
		encoding="utf-8",
	)

	# First log
	result1 = log_gotcha(str(tmp_path), "dont", "Use naive string matching")
	assert result1["success"] is True
	assert "skipped" not in result1.get("message", "")

	# Duplicate log
	result2 = log_gotcha(str(tmp_path), "dont", "Use naive string matching")
	assert result2["success"] is True
	assert "skipped" in result2["message"]

	# Verify only one entry exists
	content = claude_md.read_text(encoding="utf-8")
	assert content.count("Use naive string matching") == 1
