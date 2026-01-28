"""MCP tool registration - modular tool definitions."""

from mcp.server.fastmcp import FastMCP

from ..config import Config
from .context import register_context_tools
from .core import register_core_tools
from .memory import register_memory_tools
from .orchestrator import register_orchestrator_tools
from .plans import register_plans_tools
from .secrets import register_secrets_tools
from .skills import register_skills_tools


def register_all_tools(mcp: FastMCP, config: Config) -> None:
	"""Register all core MCP tools."""
	register_core_tools(mcp, config)
	register_secrets_tools(mcp, config)
	register_context_tools(mcp, config)
	register_memory_tools(mcp, config)
	register_plans_tools(mcp, config)
	register_orchestrator_tools(mcp, config)
	register_skills_tools(mcp, config)
