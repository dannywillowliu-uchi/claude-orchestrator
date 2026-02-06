"""Workflow lifecycle management for the four-document system."""

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WORKFLOW_DIR = ".claude-project"

DISCOVER_TEMPLATE = """# Discovery

## Problem Statement
<!-- What problem are we solving? -->

## Goals
<!-- What does success look like? -->

## Non-Goals
<!-- What is explicitly out of scope? -->

## Constraints
<!-- Technical, time, resource constraints -->

## Q&A Log
<!-- Agent records Q&A pairs here during discovery -->
"""

PLAN_TEMPLATE = """# Plan

## Overview
<!-- Synthesized from discover.md and research/ -->

## Success Criteria
<!-- Measurable criteria -->

## Phases
<!-- Each phase:
### Phase N - Name
checkpoint: false
tools_required: [list]
verification_criteria: [list]
- [ ] Task 1
- [ ] Task 2
-->
"""

PROGRESS_TEMPLATE = """# Progress

## Current State
Phase: Not started
Active Task: None
Blocked: None
Last Commit: None

## Next Up
- Begin discovery phase

## Phase History
<!-- Completed phases appear here with <details> tags -->
"""


@dataclass
class WorkflowState:
	"""Current state of a project's workflow."""
	project_path: str
	exists: bool
	current_phase: str
	active_task: str
	blocked: str
	last_commit: str
	last_updated: str
	has_discover: bool
	has_plan: bool
	has_progress: bool
	research_topics: list[str]


def init_workflow(project_path: str) -> dict[str, object]:
	"""Create .claude-project/ with template files.

	Idempotent: does not overwrite existing files.
	"""
	base = Path(project_path).expanduser().resolve()
	workflow_dir = base / WORKFLOW_DIR

	created: list[str] = []
	skipped: list[str] = []

	workflow_dir.mkdir(parents=True, exist_ok=True)

	# Create research directory
	research_dir = workflow_dir / "research"
	research_dir.mkdir(exist_ok=True)

	templates = {
		"discover.md": DISCOVER_TEMPLATE,
		"plan.md": PLAN_TEMPLATE,
		"progress.md": PROGRESS_TEMPLATE,
	}

	for filename, content in templates.items():
		filepath = workflow_dir / filename
		if filepath.exists():
			skipped.append(filename)
		else:
			filepath.write_text(content, encoding="utf-8")
			created.append(filename)

	return {
		"success": True,
		"path": str(workflow_dir),
		"created": created,
		"skipped": skipped,
	}


def get_workflow_state(project_path: str) -> WorkflowState:
	"""Parse progress.md for current workflow state."""
	base = Path(project_path).expanduser().resolve()
	workflow_dir = base / WORKFLOW_DIR

	if not workflow_dir.exists():
		return WorkflowState(
			project_path=str(base),
			exists=False,
			current_phase="",
			active_task="",
			blocked="",
			last_commit="",
			last_updated="",
			has_discover=False,
			has_plan=False,
			has_progress=False,
			research_topics=[],
		)

	has_discover = (workflow_dir / "discover.md").exists()
	has_plan = (workflow_dir / "plan.md").exists()
	has_progress = (workflow_dir / "progress.md").exists()

	# Scan research topics
	research_dir = workflow_dir / "research"
	research_topics: list[str] = []
	if research_dir.exists():
		research_topics = [
			f.stem for f in sorted(research_dir.iterdir())
			if f.suffix == ".md"
		]

	# Parse progress.md
	current_phase = "Not started"
	active_task = "None"
	blocked = "None"
	last_commit = "None"

	if has_progress:
		content = (workflow_dir / "progress.md").read_text(encoding="utf-8")
		for line in content.splitlines():
			line_stripped = line.strip()
			if line_stripped.startswith("Phase:"):
				current_phase = line_stripped[len("Phase:"):].strip()
			elif line_stripped.startswith("Active Task:"):
				active_task = line_stripped[len("Active Task:"):].strip()
			elif line_stripped.startswith("Blocked:"):
				blocked = line_stripped[len("Blocked:"):].strip()
			elif line_stripped.startswith("Last Commit:"):
				last_commit = line_stripped[len("Last Commit:"):].strip()

	return WorkflowState(
		project_path=str(base),
		exists=True,
		current_phase=current_phase,
		active_task=active_task,
		blocked=blocked,
		last_commit=last_commit,
		last_updated=_get_last_modified(workflow_dir / "progress.md") if has_progress else "",
		has_discover=has_discover,
		has_plan=has_plan,
		has_progress=has_progress,
		research_topics=research_topics,
	)


def update_progress(
	project_path: str,
	phase_completed: str = "",
	phase_started: str = "",
	commit_hash: str = "",
	summary: str = "",
) -> dict[str, object]:
	"""Update progress.md with phase transition."""
	base = Path(project_path).expanduser().resolve()
	progress_file = base / WORKFLOW_DIR / "progress.md"

	if not progress_file.exists():
		return {"success": False, "error": f"No progress.md found at {progress_file}"}

	content = progress_file.read_text(encoding="utf-8")
	now = datetime.now().strftime("%Y-%m-%d %H:%M")

	# Update Current State section
	if phase_started:
		content = _replace_field(content, "Phase", phase_started)
		content = _replace_field(content, "Active Task", "None")
		content = _replace_field(content, "Blocked", "None")
	if commit_hash:
		content = _replace_field(content, "Last Commit", commit_hash)

	# Add completed phase to history
	if phase_completed:
		history_entry = f"\n<details>\n<summary>{phase_completed} - {now}</summary>\n\n"
		if commit_hash:
			history_entry += f"Commit: {commit_hash}\n"
		if summary:
			history_entry += f"\n{summary}\n"
		history_entry += "\n</details>\n"

		# Insert before end of file (after Phase History header)
		history_marker = "## Phase History"
		idx = content.find(history_marker)
		if idx != -1:
			insert_at = content.find("\n", idx) + 1
			content = content[:insert_at] + history_entry + content[insert_at:]

	# Update Next Up section
	if phase_started:
		next_marker = "## Next Up"
		idx = content.find(next_marker)
		if idx != -1:
			next_end = content.find("\n## ", idx + len(next_marker))
			if next_end == -1:
				next_end = len(content)
			next_section = f"{next_marker}\n- Continue with {phase_started}\n\n"
			content = content[:idx] + next_section + content[next_end:]

	progress_file.write_text(content, encoding="utf-8")

	return {
		"success": True,
		"phase_completed": phase_completed,
		"phase_started": phase_started,
		"commit_hash": commit_hash,
	}


def check_tool_availability(tools_required: list[str]) -> dict[str, object]:
	"""Check availability of MCP tools and CLI tools."""
	results: dict[str, str] = {}

	for tool in tools_required:
		if _is_mcp_tool(tool):
			results[tool] = "mcp (assumed available)"
		else:
			# Check PATH first, then fall back to .venv/bin/
			if shutil.which(tool) is not None:
				results[tool] = "available"
			elif (Path(".venv") / "bin" / tool).exists():
				results[tool] = "available (venv)"
			else:
				results[tool] = "not found"

	all_available = all(v != "not found" for v in results.values())

	return {
		"all_available": all_available,
		"tools": results,
	}


def _replace_field(content: str, field: str, value: str) -> str:
	"""Replace a 'Field: value' line in the content."""
	lines = content.splitlines()
	for i, line in enumerate(lines):
		if line.strip().startswith(f"{field}:"):
			lines[i] = f"{field}: {value}"
			break
	return "\n".join(lines)


def _get_last_modified(path: Path) -> str:
	"""Get last modified time of a file as ISO string."""
	if not path.exists():
		return ""
	mtime = path.stat().st_mtime
	return datetime.fromtimestamp(mtime).isoformat()


_MCP_TOOL_NAMES = {
	"health_check", "find_project", "list_my_projects",
	"update_project_status", "log_project_decision", "log_project_gotcha",
	"log_global_learning", "run_verification",
	"init_project_workflow", "workflow_progress", "check_tools",
}


def _is_mcp_tool(name: str) -> bool:
	"""Check if a tool name is a known MCP tool."""
	return name in _MCP_TOOL_NAMES or name.startswith("mcp__")
