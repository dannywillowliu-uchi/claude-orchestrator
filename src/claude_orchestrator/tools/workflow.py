"""Workflow lifecycle MCP tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..bootstrap import detect_project_type, generate_claude_md
from ..config import Config
from ..review import generate_review
from ..tool_groups import VALID_PHASES, get_tools_for_phase
from ..workflow import check_tool_availability, init_workflow, update_progress


def register_workflow_tools(mcp: FastMCP, config: Config) -> None:
	"""Register workflow lifecycle tools."""

	@mcp.tool()
	async def init_project_workflow(project_path: str = "") -> str:
		"""
		Initialize a .claude-project/ workflow structure for a project.

		Creates discover.md, plan.md, progress.md templates and a research/ directory.
		Idempotent: does not overwrite existing files.

		Args:
			project_path: Path to project directory (default: current directory)
		"""
		path = project_path or "."
		result = init_workflow(path)
		return json.dumps(result, indent=2)

	@mcp.tool()
	async def workflow_progress(
		project_path: str = "",
		phase_completed: str = "",
		phase_started: str = "",
		commit_hash: str = "",
		summary: str = "",
	) -> str:
		"""
		Update workflow progress after completing a phase or task.

		Args:
			project_path: Path to project (default: current directory)
			phase_completed: Phase that was just completed
			phase_started: Phase that is now starting
			commit_hash: Git commit hash for the completed phase
			summary: Brief summary of what was accomplished
		"""
		path = project_path or "."
		result = update_progress(path, phase_completed, phase_started, commit_hash, summary)
		return json.dumps(result, indent=2)

	@mcp.tool()
	async def get_phase_tools(phase: str) -> str:
		"""
		Get the list of tools relevant to a workflow phase.

		Call this at each phase transition to know which tools to use.
		Reduces cognitive overhead by focusing on phase-relevant tools only.

		Args:
			phase: Workflow phase (discovery, research, planning, execution, verification)
		"""
		tools = get_tools_for_phase(phase)
		result = {
			"phase": phase,
			"tools": tools,
			"count": len(tools),
		}
		if phase.lower() not in VALID_PHASES:
			result["note"] = (
				f"Unknown phase '{phase}'. "
				f"Valid phases: {sorted(VALID_PHASES)}. "
				"Returning all tools."
			)
		return json.dumps(result, indent=2)

	@mcp.tool()
	async def bootstrap_project(project_path: str = "") -> str:
		"""
		Detect project type and configure environment for verification.

		Scans for manifest files (pyproject.toml, package.json, Cargo.toml, go.mod),
		detects the package manager, and determines verification commands. Generates
		a starter CLAUDE.md with project-specific verification if one doesn't exist.

		Call this when starting work on a new or unfamiliar project.

		Args:
			project_path: Path to project directory (default: current directory)
		"""
		from pathlib import Path

		path = project_path or "."
		profile = detect_project_type(path)

		result: dict[str, object] = {
			"project_type": profile.project_type,
			"manifest_file": profile.manifest_file,
			"package_manager": profile.package_manager,
			"verification_commands": profile.verification_commands,
			"detected_tools": profile.detected_tools,
		}

		if profile.project_type == "unknown":
			result["note"] = (
				"Could not detect project type. "
				"No manifest file found (pyproject.toml, package.json, Cargo.toml, go.mod)."
			)
			return json.dumps(result, indent=2)

		# Generate CLAUDE.md if it doesn't exist
		if not profile.has_claude_md:
			base = Path(path).expanduser().resolve()
			project_name = base.name
			claude_md_content = generate_claude_md(profile, project_name)
			(base / "CLAUDE.md").write_text(claude_md_content, encoding="utf-8")
			result["claude_md_generated"] = True
			result["claude_md_path"] = str(base / "CLAUDE.md")
		else:
			result["claude_md_generated"] = False
			result["note"] = "CLAUDE.md already exists, skipping generation"

		return json.dumps(result, indent=2)

	@mcp.tool()
	async def generate_review_artifact(
		project_path: str = "",
		phase_name: str = "",
		summary: str = "",
		changes: str = "",
		verification_passed: bool = True,
		verification_details: str = "",
		decisions: str = "",
		risks: str = "",
		next_steps: str = "",
		commit_hash: str = "",
	) -> str:
		"""
		Generate a review artifact for a completed checkpoint phase.

		Call this at checkpoint phases to produce a structured review
		summary stored in .claude-project/reviews/. Returns a Telegram-
		friendly summary for notification.

		Args:
			project_path: Path to project (default: current directory)
			phase_name: Name of the completed phase
			summary: Brief description of what was accomplished
			changes: Description of files modified/created
			verification_passed: Whether verification suite passed
			verification_details: Detailed verification output
			decisions: Semicolon-separated list of key decisions
			risks: Semicolon-separated list of risks or concerns
			next_steps: What's coming in the next phase
			commit_hash: Git commit hash for this phase
		"""
		path = project_path or "."
		decisions_list = (
			[d.strip() for d in decisions.split(";") if d.strip()]
			if decisions else []
		)
		risks_list = (
			[r.strip() for r in risks.split(";") if r.strip()]
			if risks else []
		)
		result = generate_review(
			path, phase_name, summary, changes,
			verification_passed, verification_details,
			decisions_list, risks_list, next_steps, commit_hash,
		)
		return json.dumps(result, indent=2)

	@mcp.tool()
	async def check_tools(tools_required: str) -> str:
		"""
		Check if required tools are available before starting a phase.

		Args:
			tools_required: Comma-separated list of tool names to check
		"""
		tools = [t.strip() for t in tools_required.split(",") if t.strip()]
		result = check_tool_availability(tools)
		return json.dumps(result, indent=2)
