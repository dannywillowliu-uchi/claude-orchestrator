"""Tests for server startup and tool registration."""




def test_server_imports():
	"""Server module should import without errors."""
	from claude_orchestrator.server import mcp
	assert mcp is not None


def test_server_has_tools():
	"""Server should register the expected number of tools."""
	from claude_orchestrator.server import mcp
	tools = mcp._tool_manager._tools
	# At least 45 core tools (visual + knowledge are optional)
	assert len(tools) >= 45, f"Expected >=45 tools, got {len(tools)}"


def test_server_tool_names():
	"""Server should register all expected core tool names."""
	from claude_orchestrator.server import mcp
	tool_names = set(mcp._tool_manager._tools.keys())

	# Core tools (always required)
	expected_core = {
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
		"setup_github", "get_github_repos", "get_github_issues", "create_github_issue",
		"get_github_prs", "get_github_notifications", "search_github_repos",
		"get_github_file", "comment_on_github_issue", "get_github_rate_limit",
		"check_github_security",
		"list_claude_sessions", "start_claude_session", "stop_claude_session",
		"send_to_claude_session", "get_session_output", "approve_session_action",
		"execute_plan", "cleanup_worktree",
	}

	missing_core = expected_core - tool_names
	assert not missing_core, f"Missing core tools: {missing_core}"

	# Optional tools (present only if deps installed)
	optional = {
		"take_screenshot", "take_element_screenshot", "verify_element",
		"get_page_content", "list_screenshots", "delete_screenshot",
		"search_docs", "get_doc", "list_doc_sources", "index_docs", "crawl_and_index_docs",
	}
	present_optional = optional & tool_names
	if present_optional:
		pass  # Good, some optional tools loaded
