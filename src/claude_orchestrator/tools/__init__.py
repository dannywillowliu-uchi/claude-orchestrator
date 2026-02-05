"""MCP tool registration - modular tool definitions."""

from mcp.server.fastmcp import FastMCP

from ..config import Config
from .context import register_context_tools
from .core import register_core_tools
from .memory import register_memory_tools
from .verification import register_verification_tools


def register_all_tools(mcp: FastMCP, config: Config) -> None:
	"""Register all MCP tools."""
	register_core_tools(mcp, config)
	register_context_tools(mcp, config)
	register_memory_tools(mcp, config)
	register_verification_tools(mcp, config)
