"""Tests for the session-start hook script."""

import os
import subprocess
from pathlib import Path

HOOK_SCRIPT = Path(__file__).parent.parent / "src" / "claude_orchestrator" / "hooks" / "session-start.sh"


def test_hook_outputs_nothing_without_workflow(tmp_path: Path):
	"""Hook should produce no workflow output when no .claude-project exists."""
	env = os.environ.copy()
	env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

	result = subprocess.run(
		["bash", str(HOOK_SCRIPT)],
		capture_output=True,
		text=True,
		env=env,
	)

	# Should not contain workflow state markers
	assert "--- Workflow State ---" not in result.stdout


def test_hook_outputs_state_with_workflow(tmp_path: Path):
	"""Hook should output workflow state when .claude-project/progress.md exists."""
	# Create workflow structure
	workflow_dir = tmp_path / ".claude-project"
	workflow_dir.mkdir()
	progress = workflow_dir / "progress.md"
	progress.write_text(
		"# Progress\n\n"
		"## Current State\n"
		"Phase: Phase 2 - Implementation\n"
		"Active Task: Writing tests\n"
		"Blocked: None\n"
		"Last Commit: abc123\n\n"
		"## Phase History\n"
		"<!-- history here -->\n",
		encoding="utf-8",
	)

	env = os.environ.copy()
	env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

	result = subprocess.run(
		["bash", str(HOOK_SCRIPT)],
		capture_output=True,
		text=True,
		env=env,
	)

	assert "--- Workflow State ---" in result.stdout
	assert "Phase: Phase 2 - Implementation" in result.stdout
	assert "Active Task: Writing tests" in result.stdout
