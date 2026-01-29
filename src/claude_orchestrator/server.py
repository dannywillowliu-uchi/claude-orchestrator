"""claude-orchestrator MCP server."""

import os

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .tools import register_all_tools

mcp = FastMCP("claude-orchestrator")
config = load_config()
register_all_tools(mcp, config)

# Instrument tool calls for observability (enabled by default)
if os.getenv("ORCHESTRATOR_INSTRUMENT", "1") != "0":
	try:
		from .instrumentation import instrument_mcp_server
		instrument_mcp_server(mcp)
	except Exception:
		pass  # Don't break server if instrumentation fails
