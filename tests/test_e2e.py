"""End-to-end tests for the workflow system."""

from pathlib import Path

from claude_orchestrator.project_memory import log_gotcha
from claude_orchestrator.workflow import (
	WORKFLOW_DIR,
	check_tool_availability,
	get_workflow_state,
	init_workflow,
	update_progress,
)


def test_full_workflow_lifecycle(tmp_path: Path):
	"""Test a complete workflow lifecycle: init -> progress updates -> tool checks."""
	# 1. Initialize workflow
	result = init_workflow(str(tmp_path))
	assert result["success"] is True

	# 2. Verify fresh state
	state = get_workflow_state(str(tmp_path))
	assert state.exists is True
	assert state.current_phase == "Not started"

	# 3. Complete discovery phase
	update_progress(
		str(tmp_path),
		phase_completed="Discovery",
		phase_started="Research",
		summary="Identified requirements and constraints.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Research"

	# 4. Add research files
	research_dir = tmp_path / WORKFLOW_DIR / "research"
	(research_dir / "api-design.md").write_text("# API Design\nFindings here.")
	state = get_workflow_state(str(tmp_path))
	assert "api-design" in state.research_topics

	# 5. Complete research, start planning
	update_progress(
		str(tmp_path),
		phase_completed="Research",
		phase_started="Phase 1 - Core Implementation",
		summary="Research complete, synthesized findings.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Phase 1 - Core Implementation"

	# 6. Complete with commit hash
	update_progress(
		str(tmp_path),
		phase_completed="Phase 1 - Core Implementation",
		phase_started="Phase 2 - Tests",
		commit_hash="abc1234",
		summary="Implemented core module.",
	)
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Phase 2 - Tests"
	assert state.last_commit == "abc1234"

	# 7. Verify progress file has history
	content = (tmp_path / WORKFLOW_DIR / "progress.md").read_text(encoding="utf-8")
	assert "Discovery" in content
	assert "Research" in content
	assert "Phase 1 - Core Implementation" in content
	assert "abc1234" in content

	# 8. Check tool availability
	tools_result = check_tool_availability(["git", "run_verification"])
	assert tools_result["tools"]["git"] == "available"
	assert tools_result["tools"]["run_verification"] == "mcp (assumed available)"


def test_mcp_server_starts_with_expected_tools():
	"""MCP server should start and register exactly 14 tools."""
	from claude_orchestrator.server import mcp

	tools = mcp._tool_manager._tools
	assert len(tools) == 14, f"Expected 14 tools, got {len(tools)}: {set(tools.keys())}"

	expected = {
		"health_check",
		"find_project", "list_my_projects",
		"update_project_status", "log_project_decision",
		"log_project_gotcha", "log_global_learning",
		"run_verification",
		"init_project_workflow", "workflow_progress", "check_tools",
		"get_phase_tools", "bootstrap_project", "generate_review_artifact",
	}
	assert set(tools.keys()) == expected


def test_workflow_state_parsing(tmp_path: Path):
	"""Test that workflow state is correctly parsed from various progress.md states."""
	workflow_dir = tmp_path / WORKFLOW_DIR
	workflow_dir.mkdir(parents=True)
	(workflow_dir / "discover.md").write_text("# Discovery")
	(workflow_dir / "plan.md").write_text("# Plan")

	# Custom progress with specific values
	progress = workflow_dir / "progress.md"
	progress.write_text(
		"# Progress\n\n"
		"## Current State\n"
		"Phase: Phase 3 - Deployment\n"
		"Active Task: Configure CI pipeline\n"
		"Blocked: Waiting for API keys\n"
		"Last Commit: def5678\n\n"
		"## Next Up\n"
		"- Continue deployment\n\n"
		"## Phase History\n",
		encoding="utf-8",
	)

	state = get_workflow_state(str(tmp_path))
	assert state.exists is True
	assert state.current_phase == "Phase 3 - Deployment"
	assert state.active_task == "Configure CI pipeline"
	assert state.blocked == "Waiting for API keys"
	assert state.last_commit == "def5678"
	assert state.has_discover is True
	assert state.has_plan is True
	assert state.has_progress is True


def test_protocol_includes_team_guidance():
	"""protocol.md should contain team-related sections."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	# Section 1.1: Team vs Subagent Decision
	assert "### Team vs Subagent Decision" in protocol
	assert "Use Subagents" in protocol
	assert "Use Teams" in protocol

	# Section 1.2: Team Research option
	assert "#### Option B: Team Research" in protocol
	assert "TeamCreate" in protocol

	# Section 1.3: Team-Based Verification
	assert "### Team-Based Verification" in protocol
	assert "consensus" in protocol.lower()

	# Section 1.4: Model Tier Guidance includes teams
	assert "Team teammates" in protocol
	assert "Team lead" in protocol

	# Section 1.5: Team Lifecycle
	assert "### Team Lifecycle" in protocol
	assert "Constraints (NEVER violate)" in protocol


def test_protocol_includes_playground_guidance():
	"""protocol.md should contain playground integration guidance."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	# Playground section exists
	assert "### Playground Integration" in protocol
	assert "/playground" in protocol

	# Phase-specific guidance
	assert "concept-map" in protocol
	assert "code-map" in protocol
	assert "diff-review" in protocol

	# Discovery phase reference
	assert "visually map the domain" in protocol

	# Planning phase reference
	assert "visualize component relationships" in protocol

	# Verification phase reference
	assert "visual line-by-line code review" in protocol


def test_protocol_constraints_language():
	"""protocol.md should use constraint-based language (MUST/NEVER/NO) for rules."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	# 1.1: Constraint-based language for rules
	assert "MUST be initialized" in protocol
	assert "Each phase MUST specify" in protocol
	assert "No execution proceeds without user approval" in protocol
	assert "MUST execute before any commit" in protocol
	assert "MUST be updated before any phase transition" in protocol
	assert "MUST NOT remain running" in protocol
	assert "Constraints (NEVER violate)" in protocol
	assert "NO teams for < 3 parallel tasks" in protocol
	assert "NO broadcasts when DM suffices" in protocol
	assert "NO teams left running after completion" in protocol
	assert "NO teams for sequential dependencies" in protocol

	# 1.2: Context Freshness section
	assert "### Context Freshness" in protocol
	assert "MUST reflect only current phase" in protocol
	assert "NO modifications once Discovery phase is complete" in protocol
	assert "Immutable once execution begins" in protocol

	# 1.3: Tiered error handling
	assert "Verification Gate (MANDATORY before every commit)" in protocol
	assert "Critical" in protocol
	assert "Non-critical" in protocol
	assert "Self-correction principle" in protocol
	assert "Escalation criteria" in protocol


def test_tool_groups_cover_all_registered_tools():
	"""Every registered MCP tool must appear in at least one tool group."""
	from claude_orchestrator.server import mcp
	from claude_orchestrator.tool_groups import ALL_TOOLS

	registered = set(mcp._tool_manager._tools.keys())
	assert registered == ALL_TOOLS, (
		f"Mismatch between registered tools and tool groups.\n"
		f"  In server but not in groups: {registered - ALL_TOOLS}\n"
		f"  In groups but not in server: {ALL_TOOLS - registered}"
	)


def test_tool_groups_phase_returns_subset():
	"""get_tools_for_phase returns correct subset for known phases."""
	from claude_orchestrator.tool_groups import VALID_PHASES, get_tools_for_phase

	for phase in VALID_PHASES:
		tools = get_tools_for_phase(phase)
		# Always includes the 'always' tools
		assert "health_check" in tools
		assert "get_phase_tools" in tools
		# Returns a non-empty list
		assert len(tools) >= 2

	# Discovery includes init but not run_verification
	discovery_tools = get_tools_for_phase("discovery")
	assert "init_project_workflow" in discovery_tools
	assert "run_verification" not in discovery_tools

	# Verification includes run_verification but not init_project_workflow
	verification_tools = get_tools_for_phase("verification")
	assert "run_verification" in verification_tools
	assert "init_project_workflow" not in verification_tools

	# Execution is the largest group
	execution_tools = get_tools_for_phase("execution")
	assert "run_verification" in execution_tools
	assert "workflow_progress" in execution_tools
	assert "log_project_gotcha" in execution_tools


def test_tool_groups_unknown_phase_returns_all():
	"""Unknown phase returns all tools as fallback."""
	from claude_orchestrator.tool_groups import ALL_TOOLS, get_tools_for_phase

	tools = get_tools_for_phase("nonexistent")
	assert set(tools) == ALL_TOOLS


def test_protocol_references_tool_groups():
	"""protocol.md should reference progressive tool disclosure."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Tool Disclosure" in protocol
	assert "get_phase_tools" in protocol


def test_bootstrap_python_project(tmp_path: Path):
	"""Bootstrap should detect Python project and generate CLAUDE.md."""
	from claude_orchestrator.bootstrap import detect_project_type, generate_claude_md

	# Create a Python project with uv
	(tmp_path / "pyproject.toml").write_text(
		"[project]\nname = 'my-app'\n\n[tool.pytest.ini_options]\n\n[tool.ruff]\n",
		encoding="utf-8",
	)
	(tmp_path / "uv.lock").write_text("", encoding="utf-8")
	(tmp_path / "src").mkdir()

	profile = detect_project_type(str(tmp_path))

	assert profile.project_type == "python"
	assert profile.manifest_file == "pyproject.toml"
	assert profile.package_manager == "uv"
	assert "uv run pytest" in profile.test_command
	assert "uv run ruff check" in profile.lint_command
	assert "uv run mypy" in profile.type_check_command
	assert profile.detected_tools.get("ruff") is True
	assert profile.detected_tools.get("pytest") is True
	assert not profile.has_claude_md

	# Generate CLAUDE.md
	content = generate_claude_md(profile, "my-app")
	assert "uv run pytest" in content
	assert "uv run ruff check" in content
	assert "python" in content
	assert "uv" in content


def test_bootstrap_node_project(tmp_path: Path):
	"""Bootstrap should detect Node project and generate CLAUDE.md."""
	from claude_orchestrator.bootstrap import detect_project_type, generate_claude_md

	# Create a Node project with TypeScript
	(tmp_path / "package.json").write_text(
		'{"name": "my-app", "scripts": {"test": "jest"}}',
		encoding="utf-8",
	)
	(tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
	(tmp_path / ".eslintrc.json").write_text("{}", encoding="utf-8")

	profile = detect_project_type(str(tmp_path))

	assert profile.project_type == "node"
	assert profile.manifest_file == "package.json"
	assert profile.package_manager == "npm"
	assert "npm test" in profile.test_command
	assert "eslint" in profile.lint_command
	assert "tsc" in profile.type_check_command
	assert profile.detected_tools.get("typescript") is True
	assert profile.detected_tools.get("eslint") is True
	assert not profile.has_claude_md

	content = generate_claude_md(profile, "my-app")
	assert "npm test" in content
	assert "node" in content


def test_bootstrap_unknown_project(tmp_path: Path):
	"""Bootstrap should handle unknown project types gracefully."""
	from claude_orchestrator.bootstrap import detect_project_type

	profile = detect_project_type(str(tmp_path))

	assert profile.project_type == "unknown"
	assert profile.manifest_file == ""
	assert profile.verification_commands == []


def test_bootstrap_skips_existing_claude_md(tmp_path: Path):
	"""Bootstrap should not overwrite existing CLAUDE.md."""
	from claude_orchestrator.bootstrap import detect_project_type

	(tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
	(tmp_path / "CLAUDE.md").write_text("# Custom config\n", encoding="utf-8")

	profile = detect_project_type(str(tmp_path))
	assert profile.has_claude_md is True


def test_bootstrap_init_workflow_unchanged(tmp_path: Path):
	"""init_workflow should still work the same way (backwards compatible)."""
	result = init_workflow(str(tmp_path))
	assert result["success"] is True
	assert "discover.md" in result["created"]
	assert "plan.md" in result["created"]
	assert "progress.md" in result["created"]


def test_review_artifact_generation(tmp_path: Path):
	"""generate_review should create a review artifact in .claude-project/reviews/."""
	from claude_orchestrator.review import generate_review
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))

	result = generate_review(
		str(tmp_path),
		phase_name="Phase 1 - Core Implementation",
		summary="Implemented core module with 5 functions.",
		changes="Created core.py, updated __init__.py",
		verification_passed=True,
		verification_details="pytest: 20 passed, ruff: clean, mypy: clean",
		decisions=["Use dataclasses over pydantic", "SQLite for storage"],
		risks=["No migration strategy yet"],
		next_steps="Phase 2: Add API layer",
		commit_hash="abc1234",
	)

	assert result["success"]
	artifact_path = Path(result["artifact_path"])
	assert artifact_path.exists()
	assert "reviews" in str(artifact_path)

	content = artifact_path.read_text(encoding="utf-8")
	assert "Phase 1 - Core Implementation" in content
	assert "Implemented core module" in content
	assert "abc1234" in content
	assert "dataclasses over pydantic" in content
	assert "No migration strategy" in content
	assert "PASSED" in content

	# Telegram summary should be present
	assert "telegram_summary" in result
	assert "Phase complete" in result["telegram_summary"]


def test_review_artifact_with_failures(tmp_path: Path):
	"""Review artifact should reflect verification failures."""
	from claude_orchestrator.review import generate_review
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))

	result = generate_review(
		str(tmp_path),
		phase_name="Phase 2 - Tests",
		verification_passed=False,
		verification_details="pytest: 3 failed",
		risks=["Test failures unresolved", "Blocked on API keys"],
	)

	assert result["success"]
	content = Path(result["artifact_path"]).read_text(encoding="utf-8")
	assert "FAILED" in content
	assert "Test failures unresolved" in content
	assert "review recommended" in result["telegram_summary"]


def test_review_list(tmp_path: Path):
	"""list_reviews should return all review artifacts."""
	from claude_orchestrator.review import generate_review, list_reviews
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))

	generate_review(str(tmp_path), "Phase 1 - Alpha")
	generate_review(str(tmp_path), "Phase 2 - Beta")

	reviews = list_reviews(str(tmp_path))
	assert len(reviews) == 2
	names = [r["name"] for r in reviews]
	assert "phase-1-alpha" in names
	assert "phase-2-beta" in names


def test_init_workflow_creates_reviews_dir(tmp_path: Path):
	"""init_workflow should create the reviews/ subdirectory."""
	init_workflow(str(tmp_path))
	assert (tmp_path / ".claude-project" / "reviews").is_dir()


def test_protocol_references_review_artifacts():
	"""protocol.md should reference review artifacts at checkpoints."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "generate_review_artifact" in protocol
	assert ".claude-project/reviews/" in protocol


def test_gotcha_deduplication(tmp_path: Path):
	"""log_gotcha should skip duplicates instead of appending them again."""
	claude_md = tmp_path / "CLAUDE.md"
	claude_md.write_text(
		"# Project\n\n## Gotchas & Learnings\n\n## Other\n",
		encoding="utf-8",
	)

	# First log
	result1 = log_gotcha(str(tmp_path), "dont", "Use naive string matching")
	assert result1["success"] is True
	assert "skipped" not in result1.get("message", "")

	# Duplicate log
	result2 = log_gotcha(str(tmp_path), "dont", "Use naive string matching")
	assert result2["success"] is True
	assert "skipped" in result2["message"]

	# Verify only one entry exists
	content = claude_md.read_text(encoding="utf-8")
	assert content.count("Use naive string matching") == 1
