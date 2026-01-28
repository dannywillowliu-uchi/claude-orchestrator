"""MCP tool registration - modular tool definitions."""

import logging

from mcp.server.fastmcp import FastMCP

from ..config import Config
from .context import register_context_tools
from .core import register_core_tools
from .github import register_github_tools
from .memory import register_memory_tools
from .orchestrator import register_orchestrator_tools
from .plans import register_plans_tools
from .secrets import register_secrets_tools
from .sessions import register_session_tools
from .skills import register_skills_tools

logger = logging.getLogger(__name__)


def register_all_tools(mcp: FastMCP, config: Config) -> None:
	"""Register all MCP tools. Optional modules degrade gracefully."""
	# Core tools (always available)
	register_core_tools(mcp, config)
	register_secrets_tools(mcp, config)
	register_context_tools(mcp, config)
	register_memory_tools(mcp, config)
	register_plans_tools(mcp, config)
	register_orchestrator_tools(mcp, config)
	register_skills_tools(mcp, config)
	register_github_tools(mcp, config)
	register_session_tools(mcp, config)

	# Optional: visual verification (requires playwright)
	try:
		from .visual import register_visual_tools
		register_visual_tools(mcp, config)
	except ImportError:
		logger.info("Visual verification tools unavailable (install playwright)")

	# Optional: knowledge base (requires lancedb, sentence-transformers, aiohttp, markdownify)
	try:
		from .knowledge import register_knowledge_tools
		register_knowledge_tools(mcp, config)
	except ImportError:
		logger.info("Knowledge tools unavailable (install claude-orchestrator[knowledge])")
