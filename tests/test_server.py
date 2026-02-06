"""Tests for server startup and tool registration."""


EXPECTED_TOOLS = {
	"health_check",
	"find_project",
	"list_my_projects",
	"update_project_status",
	"log_project_decision",
	"log_project_gotcha",
	"log_global_learning",
	"run_verification",
	"init_project_workflow",
	"workflow_progress",
	"check_tools",
}


def test_server_imports():
	"""Server module should import without errors."""
	from claude_orchestrator.server import mcp
	assert mcp is not None


def test_server_has_tools():
	"""Server should register the expected number of tools."""
	from claude_orchestrator.server import mcp
	tools = mcp._tool_manager._tools
	assert len(tools) == len(EXPECTED_TOOLS), (
		f"Expected {len(EXPECTED_TOOLS)} tools, got {len(tools)}: {set(tools.keys())}"
	)


def test_server_tool_names():
	"""Server should register all expected tool names."""
	from claude_orchestrator.server import mcp
	tool_names = set(mcp._tool_manager._tools.keys())

	missing = EXPECTED_TOOLS - tool_names
	assert not missing, f"Missing tools: {missing}"

	extra = tool_names - EXPECTED_TOOLS
	assert not extra, f"Unexpected tools: {extra}"
