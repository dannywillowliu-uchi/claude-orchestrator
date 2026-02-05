"""Workflow lifecycle MCP tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
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
	async def check_tools(tools_required: str) -> str:
		"""
		Check if required tools are available before starting a phase.

		Args:
			tools_required: Comma-separated list of tool names to check
		"""
		tools = [t.strip() for t in tools_required.split(",") if t.strip()]
		result = check_tool_availability(tools)
		return json.dumps(result, indent=2)
