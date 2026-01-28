"""Tests for server startup and tool registration."""




def test_server_imports():
	"""Server module should import without errors."""
	from claude_orchestrator.server import mcp
	assert mcp is not None


def test_server_has_tools():
	"""Server should register the expected number of tools."""
	from claude_orchestrator.server import mcp
	tools = mcp._tool_manager._tools
	# 33 core tools expected
	assert len(tools) >= 30, f"Expected ~33 tools, got {len(tools)}"


def test_server_tool_names():
	"""Server should register all expected core tool names."""
	from claude_orchestrator.server import mcp
	tool_names = set(mcp._tool_manager._tools.keys())

	expected = {
		"health_check",
		"get_secret", "list_secrets", "set_secret", "deactivate_secret", "activate_secret",
		"get_my_context", "find_project", "list_my_projects", "update_context_notes",
		"update_project_status", "log_project_decision", "log_project_gotcha", "log_global_learning",
		"create_plan", "get_plan", "get_project_plan", "add_phase_to_plan",
		"update_task_status", "add_decision_to_plan", "list_plans", "get_plan_history",
		"start_planning_session", "answer_planning_question", "get_planning_session",
		"approve_planning_session", "list_planning_sessions",
		"run_verification",
		"list_skills", "get_skill_details", "create_skill_template",
		"execute_skill", "list_skill_executions",
	}

	missing = expected - tool_names
	assert not missing, f"Missing tools: {missing}"
