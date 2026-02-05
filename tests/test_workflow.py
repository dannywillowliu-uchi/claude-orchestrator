"""Tests for the workflow lifecycle system."""

from pathlib import Path

from claude_orchestrator.workflow import (
	WORKFLOW_DIR,
	check_tool_availability,
	get_workflow_state,
	init_workflow,
	update_progress,
)


def test_init_creates_structure(tmp_path: Path):
	"""init_workflow should create .claude-project/ with all template files."""
	result = init_workflow(str(tmp_path))

	assert result["success"] is True
	assert "discover.md" in result["created"]
	assert "plan.md" in result["created"]
	assert "progress.md" in result["created"]

	workflow_dir = tmp_path / WORKFLOW_DIR
	assert workflow_dir.exists()
	assert (workflow_dir / "discover.md").exists()
	assert (workflow_dir / "plan.md").exists()
	assert (workflow_dir / "progress.md").exists()
	assert (workflow_dir / "research").is_dir()


def test_init_idempotent(tmp_path: Path):
	"""init_workflow should not overwrite existing files."""
	# First init
	init_workflow(str(tmp_path))

	# Modify a file
	discover = tmp_path / WORKFLOW_DIR / "discover.md"
	discover.write_text("custom content", encoding="utf-8")

	# Second init
	result = init_workflow(str(tmp_path))

	assert "discover.md" in result["skipped"]
	assert discover.read_text(encoding="utf-8") == "custom content"


def test_get_state_no_workflow(tmp_path: Path):
	"""get_workflow_state should return exists=False when no workflow."""
	state = get_workflow_state(str(tmp_path))

	assert state.exists is False
	assert state.current_phase == ""
	assert state.has_discover is False
	assert state.has_plan is False
	assert state.has_progress is False


def test_get_state_fresh(tmp_path: Path):
	"""get_workflow_state should return correct defaults for fresh workflow."""
	init_workflow(str(tmp_path))
	state = get_workflow_state(str(tmp_path))

	assert state.exists is True
	assert state.current_phase == "Not started"
	assert state.active_task == "None"
	assert state.blocked == "None"
	assert state.last_commit == "None"
	assert state.has_discover is True
	assert state.has_plan is True
	assert state.has_progress is True
	assert state.research_topics == []


def test_update_progress_completes_phase(tmp_path: Path):
	"""update_progress should record completed phase in history."""
	init_workflow(str(tmp_path))

	result = update_progress(
		str(tmp_path),
		phase_completed="Phase 1 - Discovery",
		phase_started="Phase 2 - Research",
		summary="Completed initial discovery.",
	)

	assert result["success"] is True

	# Check progress file was updated
	content = (tmp_path / WORKFLOW_DIR / "progress.md").read_text(encoding="utf-8")
	assert "Phase 2 - Research" in content
	assert "Phase 1 - Discovery" in content
	assert "Completed initial discovery." in content

	# Verify state reflects update
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Phase 2 - Research"


def test_update_progress_with_commit_hash(tmp_path: Path):
	"""update_progress should record commit hash."""
	init_workflow(str(tmp_path))

	result = update_progress(
		str(tmp_path),
		phase_completed="Phase 1",
		commit_hash="abc123",
	)

	assert result["success"] is True
	assert result["commit_hash"] == "abc123"

	content = (tmp_path / WORKFLOW_DIR / "progress.md").read_text(encoding="utf-8")
	assert "abc123" in content

	state = get_workflow_state(str(tmp_path))
	assert state.last_commit == "abc123"


def test_check_tool_availability():
	"""check_tool_availability should detect available CLI tools."""
	result = check_tool_availability(["git", "nonexistent_tool_xyz"])

	assert result["tools"]["git"] == "available"
	assert result["tools"]["nonexistent_tool_xyz"] == "not found"
	assert result["all_available"] is False


def test_check_tool_availability_mcp():
	"""MCP tools should be reported as assumed available."""
	result = check_tool_availability(["run_verification"])

	assert result["tools"]["run_verification"] == "mcp (assumed available)"
	assert result["all_available"] is True


def test_research_topics(tmp_path: Path):
	"""get_workflow_state should detect research topic files."""
	init_workflow(str(tmp_path))

	research_dir = tmp_path / WORKFLOW_DIR / "research"
	(research_dir / "api-design.md").write_text("# API Design Research")
	(research_dir / "testing-strategy.md").write_text("# Testing Strategy")

	state = get_workflow_state(str(tmp_path))
	assert "api-design" in state.research_topics
	assert "testing-strategy" in state.research_topics
