"""Stub tools for missing optional dependencies.

When optional extras (visual, knowledge) aren't installed, these stubs
register placeholder tools that return helpful JSON errors with install
instructions instead of silently vanishing.
"""

import json

from mcp.server.fastmcp import FastMCP

VISUAL_TOOL_NAMES = [
	"take_screenshot",
	"take_element_screenshot",
	"verify_element",
	"get_page_content",
	"list_screenshots",
	"delete_screenshot",
]

KNOWLEDGE_TOOL_NAMES = [
	"search_docs",
	"get_doc",
	"list_doc_sources",
	"index_docs",
	"crawl_and_index_docs",
]

EXTRAS_META = {
	"visual": {
		"tools": VISUAL_TOOL_NAMES,
		"install": "pip install claude-orchestrator[visual]",
		"description": "Visual verification tools (screenshots, element checking) require the 'visual' extras.",
	},
	"knowledge": {
		"tools": KNOWLEDGE_TOOL_NAMES,
		"install": "pip install claude-orchestrator[knowledge]",
		"description": "Knowledge base tools (doc search, indexing, crawling) require the 'knowledge' extras.",
	},
}


def _make_stub_response(tool_name: str, extra: str) -> str:
	"""Build the JSON error response for a stub tool."""
	meta = EXTRAS_META[extra]
	return json.dumps({
		"error": "missing_dependency",
		"tool": tool_name,
		"extra": extra,
		"install": meta["install"],
		"message": f"This tool requires the '{extra}' extras. Install with: {meta['install']}",
	})


def _register_stubs(mcp: FastMCP, extra: str) -> None:
	"""Register stub tools for all tools in a given extras group."""
	meta = EXTRAS_META[extra]
	for tool_name in meta["tools"]:
		# Capture tool_name and extra in closure
		_register_single_stub(mcp, tool_name, extra)


def _register_single_stub(mcp: FastMCP, tool_name: str, extra: str) -> None:
	"""Register a single stub tool."""
	meta = EXTRAS_META[extra]

	@mcp.tool(name=tool_name)
	async def stub(**kwargs: object) -> str:
		return _make_stub_response(tool_name, extra)

	# Override the docstring for discoverability
	stub.__doc__ = (
		f"[NOT INSTALLED] {meta['description']}\n\n"
		f"Install with: {meta['install']}"
	)


def register_visual_stubs(mcp: FastMCP) -> None:
	"""Register stub tools for missing visual extras."""
	_register_stubs(mcp, "visual")


def register_knowledge_stubs(mcp: FastMCP) -> None:
	"""Register stub tools for missing knowledge extras."""
	_register_stubs(mcp, "knowledge")
