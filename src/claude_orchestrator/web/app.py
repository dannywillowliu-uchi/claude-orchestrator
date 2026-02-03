"""Starlette app with route assembly."""

from __future__ import annotations

import logging

from starlette.applications import Starlette
from starlette.routing import Route

from ..instrumentation import ToolCallStore
from .api import (
	api_calls,
	api_registered_tools,
	api_session_detail,
	api_sessions,
	api_stats,
	api_stream,
	index,
)

logger = logging.getLogger(__name__)


def _get_registered_tool_names() -> list[str]:
	"""Get all tool names registered in the MCP server."""
	try:
		from ..server import mcp

		tool_manager = getattr(mcp, "_tool_manager", None)
		if tool_manager:
			tools = getattr(tool_manager, "_tools", None) or getattr(tool_manager, "tools", {})
			return sorted(tools.keys())
	except Exception as e:
		logger.debug(f"Could not load registered tools: {e}")
	return []


def build_app(db_path: str = "") -> Starlette:
	"""Build and return the Starlette ASGI app."""
	routes = [
		Route("/", index),
		Route("/api/stats", api_stats),
		Route("/api/calls", api_calls),
		Route("/api/sessions", api_sessions),
		Route("/api/session/{id}", api_session_detail),
		Route("/api/stream", api_stream),
		Route("/api/registered-tools", api_registered_tools),
	]

	app = Starlette(routes=routes)
	app.state.store = ToolCallStore(db_path=db_path)
	app.state.registered_tools = _get_registered_tool_names()
	return app
