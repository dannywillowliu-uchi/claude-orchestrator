"""Task Automation MCP - Google Tasks to Claude Code automation."""

from .server import mcp

def main():
    """Entry point for the MCP server."""
    mcp.run()

__all__ = ["main", "mcp"]
