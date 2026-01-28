"""claude-orchestrator MCP server."""

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .tools import register_all_tools

mcp = FastMCP("claude-orchestrator")
config = load_config()
register_all_tools(mcp, config)
