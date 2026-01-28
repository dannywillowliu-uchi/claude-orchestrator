"""Personal context tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..context import ContextManager


def register_context_tools(mcp: FastMCP, config: Config) -> None:
	"""Register context management tools."""
	context_manager = ContextManager()

	@mcp.tool()
	async def get_my_context() -> str:
		"""
		Get personal context including preferences, projects, and style.
		Use this to personalize responses and understand the user's background.
		"""
		return context_manager.get_full_context()

	@mcp.tool()
	async def find_project(query: str) -> str:
		"""
		Find a project by name or alias.

		Args:
			query: Project name, partial name, or alias (e.g., "mlb", "health", "trading")

		Returns project details including path, description, and technologies.
		"""
		project = context_manager.find_project(query)

		if not project:
			ctx = context_manager.load()
			available = [p.name for p in ctx.projects]
			return json.dumps({
				"error": f"Project '{query}' not found",
				"available_projects": available,
			})

		return json.dumps({
			"name": project.name,
			"path": project.path,
			"description": project.description,
			"technologies": project.technologies,
			"aliases": project.aliases,
		}, indent=2)

	@mcp.tool()
	async def list_my_projects() -> str:
		"""List all personal projects with descriptions."""
		ctx = context_manager.load()

		return json.dumps([{
			"name": p.name,
			"description": p.description,
			"technologies": p.technologies,
		} for p in ctx.projects], indent=2)

	@mcp.tool()
	async def update_context_notes(notes: str) -> str:
		"""
		Update personal context notes with important information to remember.

		Args:
			notes: Notes to store (replaces existing notes)
		"""
		context_manager.update_notes(notes)
		return json.dumps({"success": True, "message": "Notes updated"})
