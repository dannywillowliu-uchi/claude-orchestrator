"""Project memory tools - CLAUDE.md management and global learnings."""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .. import project_memory
from ..config import Config


def register_memory_tools(mcp: FastMCP, config: Config) -> None:
	"""Register project memory tools."""

	@mcp.tool()
	async def update_project_status(
		project_path: str,
		phase_completed: str = "",
		phase_started: str = "",
		commit_hash: str = "",
	) -> str:
		"""
		Update the Implementation Status section of a project CLAUDE.md.

		Use this after completing a phase to mark it done and optionally start a new phase.

		Args:
			project_path: Path to the project directory (e.g., "~/personal_projects/my-app")
			phase_completed: Phase that was just completed
			phase_started: Phase that is now starting (optional)
			commit_hash: Git commit hash for the completed phase (optional)
		"""
		expanded_path = str(Path(project_path).expanduser())
		result = project_memory.update_implementation_status(
			expanded_path, phase_completed, phase_started, commit_hash
		)
		return json.dumps(result)

	@mcp.tool()
	async def log_project_decision(
		project_path: str,
		decision: str,
		rationale: str,
		alternatives: str = "",
	) -> str:
		"""
		Log a significant decision to a project's CLAUDE.md Decisions Log.

		Args:
			project_path: Path to the project directory
			decision: What was decided
			rationale: Why this decision was made
			alternatives: What alternatives were rejected
		"""
		expanded_path = str(Path(project_path).expanduser())
		result = project_memory.log_decision(expanded_path, decision, rationale, alternatives)
		return json.dumps(result)

	@mcp.tool()
	async def log_project_gotcha(
		project_path: str,
		gotcha_type: str,
		description: str,
	) -> str:
		"""
		Log a gotcha or learning to a project's CLAUDE.md.

		Args:
			project_path: Path to the project directory
			gotcha_type: Type of gotcha - "dont" (avoid), "do" (best practice), or "note" (info)
			description: Description of the gotcha
		"""
		expanded_path = str(Path(project_path).expanduser())
		result = project_memory.log_gotcha(expanded_path, gotcha_type, description)
		return json.dumps(result)

	@mcp.tool()
	async def log_global_learning(category: str, content: str) -> str:
		"""
		Add a learning to the global learnings file (~/.claude/global-learnings.md).

		Use this for learnings that apply across ALL projects.

		Args:
			category: Category - "preference", "pattern", "gotcha", or "decision"
			content: The learning to add (formatted as a bullet point)
		"""
		result = project_memory.log_global_learning(category, content)
		return json.dumps(result)
