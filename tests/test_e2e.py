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
	"""MCP server should start and register exactly 15 tools."""
	from claude_orchestrator.server import mcp

	tools = mcp._tool_manager._tools
	assert len(tools) == 17, f"Expected 17 tools, got {len(tools)}: {set(tools.keys())}"

	expected = {
		"health_check",
		"find_project", "list_my_projects",
		"update_project_status", "log_project_decision",
		"log_project_gotcha", "log_global_learning",
		"replan", "run_verification",
		"init_project_workflow", "workflow_progress", "check_tools",
		"get_phase_tools", "bootstrap_project", "generate_review_artifact",
		"suggest_fixes", "track_convergence",
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
	assert "Mutable via `replan` tool only" in protocol

	# 1.3: Tiered error handling
	assert "Verification Gate (MANDATORY before every commit)" in protocol
	assert "Critical" in protocol
	assert "Non-critical" in protocol
	assert "Self-correction flow" in protocol
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


def test_plan_parser_flat_phases(tmp_path: Path):
	"""Plan parser should extract flat phases from plan.md."""
	from claude_orchestrator.plan_parser import parse_plan

	workflow_dir = tmp_path / ".claude-project"
	workflow_dir.mkdir(parents=True)
	(workflow_dir / "plan.md").write_text(
		"# Plan\n\n"
		"## Overview\nSome overview.\n\n"
		"## Phase 1 - Setup\n"
		"checkpoint: false\n"
		"- [ ] Create project structure\n"
		"- [ ] Add configuration\n\n"
		"## Phase 2 - Implementation\n"
		"checkpoint: true\n"
		"- [ ] Build core module\n\n"
		"## Phase 3 - Tests\n"
		"checkpoint: false\n"
		"- [ ] Write unit tests\n",
		encoding="utf-8",
	)

	tree = parse_plan(str(tmp_path))
	assert len(tree.phases) == 3
	assert tree.phases[0].name == "Phase 1 - Setup"
	assert tree.phases[0].checkpoint is False
	assert len(tree.phases[0].tasks) == 2
	assert tree.phases[1].checkpoint is True
	assert tree.phases[2].name == "Phase 3 - Tests"


def test_plan_parser_nested_phases(tmp_path: Path):
	"""Plan parser should handle nested sub-phases."""
	from claude_orchestrator.plan_parser import parse_plan

	workflow_dir = tmp_path / ".claude-project"
	workflow_dir.mkdir(parents=True)
	(workflow_dir / "plan.md").write_text(
		"# Plan\n\n"
		"## Phase 1 - Core\n"
		"- [ ] Setup\n\n"
		"### Sub-phase 1.1 - Models\n"
		"- [ ] Create models\n\n"
		"### Sub-phase 1.2 - Services\n"
		"- [ ] Create services\n\n"
		"## Phase 2 - API\n"
		"- [ ] Build endpoints\n",
		encoding="utf-8",
	)

	tree = parse_plan(str(tmp_path))
	assert len(tree.phases) == 2
	assert len(tree.phases[0].children) == 2
	assert tree.phases[0].children[0].name == "Sub-phase 1.1 - Models"
	assert tree.phases[0].children[0].depth == 1
	assert tree.phases[0].children[1].name == "Sub-phase 1.2 - Services"


def test_plan_parser_flatten_depth_first(tmp_path: Path):
	"""Flattened tree should be in depth-first order with correct paths."""
	from claude_orchestrator.plan_parser import parse_plan

	workflow_dir = tmp_path / ".claude-project"
	workflow_dir.mkdir(parents=True)
	(workflow_dir / "plan.md").write_text(
		"# Plan\n\n"
		"## Phase 1 - Core\n"
		"- [ ] Setup\n\n"
		"### Sub-phase 1.1 - Models\n"
		"- [ ] Create models\n\n"
		"## Phase 2 - API\n"
		"- [ ] Build endpoints\n",
		encoding="utf-8",
	)

	tree = parse_plan(str(tmp_path))
	flat = tree.flatten()
	paths = [p for p, _ in flat]
	assert paths == [
		"Phase 1 - Core",
		"Phase 1 - Core > Sub-phase 1.1 - Models",
		"Phase 2 - API",
	]


def test_plan_parser_next_phase():
	"""next_phase should return the correct subsequent phase path."""
	from claude_orchestrator.plan_parser import PlanPhase, PlanTree

	tree = PlanTree(phases=[
		PlanPhase(name="Phase 1", depth=0, children=[
			PlanPhase(name="Sub-phase 1.1", depth=1),
		]),
		PlanPhase(name="Phase 2", depth=0),
	])

	assert tree.next_phase("Phase 1") == "Phase 1 > Sub-phase 1.1"
	assert tree.next_phase("Phase 1 > Sub-phase 1.1") == "Phase 2"
	assert tree.next_phase("Phase 2") is None
	assert tree.next_phase("Unknown") == "Phase 1"


def test_plan_parser_phase_path_utilities():
	"""Phase path utilities should parse and navigate correctly."""
	from claude_orchestrator.plan_parser import (
		get_parent_phase,
		get_phase_depth,
		parse_phase_path,
	)

	assert parse_phase_path("Phase 1") == ["Phase 1"]
	assert parse_phase_path("Phase 1 > Sub 1.1") == ["Phase 1", "Sub 1.1"]
	assert parse_phase_path("A > B > C") == ["A", "B", "C"]

	assert get_phase_depth("Phase 1") == 0
	assert get_phase_depth("Phase 1 > Sub 1.1") == 1
	assert get_phase_depth("A > B > C") == 2

	assert get_parent_phase("Phase 1") == ""
	assert get_parent_phase("Phase 1 > Sub 1.1") == "Phase 1"
	assert get_parent_phase("A > B > C") == "A > B"


def test_plan_parser_empty_plan(tmp_path: Path):
	"""Parser should handle missing plan.md gracefully."""
	from claude_orchestrator.plan_parser import parse_plan

	tree = parse_plan(str(tmp_path))
	assert len(tree.phases) == 0
	assert tree.flatten() == []
	assert tree.next_phase("anything") is None


def test_fixer_critical_blocks_commit():
	"""Fixer should block commit when critical issues found."""
	from claude_orchestrator.fixer import analyze_verification

	checks = [
		{"name": "pytest", "status": "failed", "output_preview": "FAILED tests/test_foo.py::test_bar"},
		{"name": "ruff", "status": "passed", "output_preview": ""},
	]
	result = analyze_verification(checks)
	assert result.should_block is True
	assert result.critical_count >= 1
	assert result.non_critical_count == 0
	assert any(t.severity == "critical" for t in result.fix_tasks)


def test_fixer_non_critical_allows_commit():
	"""Fixer should allow commit when only non-critical issues found."""
	from claude_orchestrator.fixer import analyze_verification

	checks = [
		{"name": "pytest", "status": "passed", "output_preview": ""},
		{"name": "ruff", "status": "failed", "output_preview": "src/foo.py:10:1: E501 Line too long"},
	]
	result = analyze_verification(checks)
	assert result.should_block is False
	assert result.critical_count == 0
	assert result.non_critical_count >= 1
	assert any(t.rule_code == "E501" for t in result.fix_tasks)


def test_fixer_circuit_breaker():
	"""Circuit breaker should trigger when too many non-critical issues."""
	from claude_orchestrator.fixer import analyze_verification

	# Generate 7 unique ruff violations (> threshold of 5)
	violations = "\n".join(
		f"src/foo.py:{i}:1: E{500 + i} Some violation {i}"
		for i in range(7)
	)
	checks = [
		{"name": "ruff", "status": "failed", "output_preview": violations},
	]
	result = analyze_verification(checks, circuit_breaker_threshold=5)
	assert result.circuit_breaker_triggered is True
	assert result.should_block is False  # non-critical don't block
	assert "ESCALATE" in result.summary


def test_fixer_no_issues():
	"""Fixer should report no issues when all checks pass."""
	from claude_orchestrator.fixer import analyze_verification

	checks = [
		{"name": "pytest", "status": "passed", "output_preview": ""},
		{"name": "ruff", "status": "passed", "output_preview": ""},
		{"name": "mypy", "status": "passed", "output_preview": ""},
	]
	result = analyze_verification(checks)
	assert result.should_block is False
	assert result.critical_count == 0
	assert result.non_critical_count == 0
	assert len(result.fix_tasks) == 0
	assert "No issues" in result.summary


def test_fixer_mypy_errors():
	"""Fixer should extract mypy type errors as critical tasks."""
	from claude_orchestrator.fixer import analyze_verification

	checks = [
		{
			"name": "mypy",
			"status": "failed",
			"output_preview": 'src/foo.py:42: error: Incompatible types [assignment]',
		},
	]
	result = analyze_verification(checks)
	assert result.should_block is True
	assert result.critical_count >= 1
	assert any(t.file_path == "src/foo.py" for t in result.fix_tasks)


def test_session_report_phase_complete():
	"""Session report should format phase completion correctly."""
	from claude_orchestrator.session_report import format_phase_complete

	msg = format_phase_complete(
		"Phase 1 - Core",
		"my-project",
		verification_passed=True,
		verification_summary="5 passed",
		commit_hash="abc1234def",
	)
	assert "[my-project]" in msg
	assert "Phase 1 - Core" in msg
	assert "PASS" in msg
	assert "abc1234" in msg


def test_session_report_checkpoint():
	"""Session report should format checkpoint with risks."""
	from claude_orchestrator.session_report import format_checkpoint

	msg = format_checkpoint(
		"Phase 3 - Deploy",
		"my-project",
		summary="Deployed to staging",
		risks=["No rollback plan"],
		next_phase="Phase 4",
	)
	assert "CHECKPOINT" in msg
	assert "No rollback plan" in msg
	assert "Awaiting approval" in msg


def test_session_report_blocked():
	"""Session report should format blocked state."""
	from claude_orchestrator.session_report import format_blocked

	msg = format_blocked(
		"Phase 2",
		"my-project",
		reason="Missing API keys",
		attempts=3,
	)
	assert "BLOCKED" in msg
	assert "Missing API keys" in msg
	assert "Human intervention" in msg


def test_session_report_session_complete():
	"""Session report should format session completion."""
	from claude_orchestrator.session_report import format_session_complete

	msg = format_session_complete(
		"my-project",
		phases_completed=["Phase 1", "Phase 2"],
		session_id="003",
		total_commits=2,
	)
	assert "SESSION COMPLETE" in msg
	assert "Session 003" in msg
	assert "2 completed" in msg


def test_protocol_references_session_reporting():
	"""protocol.md should reference session reporting guidance."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Session Reporting" in protocol
	assert "Phase start" in protocol
	assert "Phase complete" in protocol
	assert "Checkpoint" in protocol
	assert "Blocked" in protocol
	assert "Session complete" in protocol


def test_replan_applies_new_plan(tmp_path: Path):
	"""Replan should replace plan.md content."""
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))
	new_content = "# Revised Plan\n\n## Phase 1 - New\n- [ ] New task\n"
	result = apply_replan(
		str(tmp_path), "scope_change", "Requirements changed",
		new_content, phases_added=["Phase 1 - New"],
	)
	assert result.success is True
	assert result.replan_count == 1
	plan = (tmp_path / ".claude-project" / "plan.md").read_text(encoding="utf-8")
	assert "Revised Plan" in plan


def test_replan_preserves_progress_history(tmp_path: Path):
	"""Replan should not destroy existing phase history entries."""
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow, update_progress

	init_workflow(str(tmp_path))
	update_progress(str(tmp_path), phase_completed="Discovery", phase_started="Phase 1")

	content = (tmp_path / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	assert "Discovery" in content

	apply_replan(str(tmp_path), "phase_split", "Splitting phase", "# New Plan\n")

	content = (tmp_path / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	assert "Discovery" in content  # History preserved


def test_replan_logs_event(tmp_path: Path):
	"""Replan event should appear in progress.md Phase History."""
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))
	apply_replan(str(tmp_path), "blocked_dependency", "API unavailable", "# Plan v2\n")

	content = (tmp_path / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	assert "Replan #1" in content
	assert "blocked_dependency" in content
	assert "API unavailable" in content


def test_replan_invalid_trigger(tmp_path: Path):
	"""Unknown trigger should be rejected."""
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))
	result = apply_replan(str(tmp_path), "invalid_trigger", "reason", "# Plan\n")
	assert result.success is False
	assert "Invalid trigger" in result.error


def test_replan_count_tracked(tmp_path: Path):
	"""Replan count should increment and be parseable from progress.md."""
	from claude_orchestrator.replanner import _parse_replan_count, apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))
	apply_replan(str(tmp_path), "scope_change", "r1", "# v2\n")
	apply_replan(str(tmp_path), "scope_change", "r2", "# v3\n")

	content = (tmp_path / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	assert _parse_replan_count(content) == 2


def test_replan_count_limit(tmp_path: Path):
	"""Should reject after MAX_REPLANS replans."""
	from claude_orchestrator.replanner import MAX_REPLANS, apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))
	for i in range(MAX_REPLANS):
		result = apply_replan(str(tmp_path), "scope_change", f"replan {i + 1}", f"# v{i + 2}\n")
		assert result.success is True

	result = apply_replan(str(tmp_path), "scope_change", "one too many", "# overflow\n")
	assert result.success is False
	assert "limit" in result.error.lower()


def test_protocol_includes_adaptive_replanning():
	"""protocol.md should include adaptive replanning section."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Adaptive Replanning" in protocol
	assert "replan" in protocol
	assert "max 3 replans" in protocol.lower() or "Max 3 replans" in protocol


def test_convergence_converging():
	"""Decreasing errors should recommend continue_fixing."""
	from claude_orchestrator.fixer import track_convergence

	history = [
		{"critical_count": 3, "non_critical_count": 2, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
			{"check": "pytest", "rule_code": "", "file_path": "b.py"},
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
			{"check": "ruff", "rule_code": "E501", "file_path": "a.py"},
			{"check": "ruff", "rule_code": "E502", "file_path": "a.py"},
		]},
		{"critical_count": 1, "non_critical_count": 1, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
			{"check": "ruff", "rule_code": "E501", "file_path": "a.py"},
		]},
	]
	result = track_convergence(history)
	assert result.trend == "converging"
	assert result.recommendation == "continue_fixing"
	assert len(result.errors_fixed) > 0


def test_convergence_stable_non_critical():
	"""Stable non-critical-only errors for tolerance runs should recommend accept_and_commit."""
	from claude_orchestrator.fixer import track_convergence

	run = {"critical_count": 0, "non_critical_count": 2, "fix_tasks": [
		{"check": "ruff", "rule_code": "E501", "file_path": "a.py"},
		{"check": "ruff", "rule_code": "E502", "file_path": "b.py"},
	]}
	history = [run, run]
	result = track_convergence(history, tolerance=2)
	assert result.trend == "stable"
	assert result.recommendation == "accept_and_commit"


def test_convergence_diverging():
	"""Increasing errors should recommend escalate."""
	from claude_orchestrator.fixer import track_convergence

	history = [
		{"critical_count": 1, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
		]},
		{"critical_count": 3, "non_critical_count": 1, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
			{"check": "pytest", "rule_code": "", "file_path": "b.py"},
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
			{"check": "ruff", "rule_code": "E501", "file_path": "d.py"},
		]},
	]
	result = track_convergence(history)
	assert result.trend == "diverging"
	assert result.recommendation == "escalate"


def test_convergence_stable_critical_escalates():
	"""Stable errors with critical issues should escalate."""
	from claude_orchestrator.fixer import track_convergence

	run = {"critical_count": 1, "non_critical_count": 1, "fix_tasks": [
		{"check": "pytest", "rule_code": "", "file_path": "a.py"},
		{"check": "ruff", "rule_code": "E501", "file_path": "b.py"},
	]}
	history = [run, run, run]
	result = track_convergence(history, tolerance=2)
	assert result.trend == "stable"
	assert result.recommendation == "escalate"


def test_convergence_single_run():
	"""Single run should return insufficient_data."""
	from claude_orchestrator.fixer import track_convergence

	history = [{"critical_count": 1, "non_critical_count": 0, "fix_tasks": []}]
	result = track_convergence(history)
	assert result.trend == "insufficient_data"
	assert result.runs_analyzed == 1


def test_integration_convergence_triggers_replan(tmp_path: Path):
	"""Diverging convergence should be usable as replan trigger."""
	from claude_orchestrator.fixer import track_convergence
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow

	init_workflow(str(tmp_path))

	history = [
		{"critical_count": 1, "non_critical_count": 0, "fix_tasks": []},
		{"critical_count": 3, "non_critical_count": 0, "fix_tasks": []},
	]
	conv = track_convergence(history)
	assert conv.recommendation == "escalate"

	result = apply_replan(
		str(tmp_path), "verification_feedback",
		f"Errors diverging: {conv.trend}",
		"# Revised Plan\n- Fix regressions\n",
	)
	assert result.success is True


def test_integration_full_lifecycle(tmp_path: Path):
	"""Full lifecycle: init -> execute -> replan -> complete."""
	from claude_orchestrator.replanner import apply_replan
	from claude_orchestrator.workflow import init_workflow, update_progress

	init_workflow(str(tmp_path))
	(tmp_path / ".claude-project" / "plan.md").write_text("# Plan\n## Phase 1\n- [ ] Build\n")

	update_progress(str(tmp_path), phase_completed="Discovery", phase_started="Phase 1")
	result = apply_replan(
		str(tmp_path), "phase_split", "Split needed",
		"# Plan\n## Phase 1a\n- [ ] Part A\n## Phase 1b\n- [ ] Part B\n",
		phases_added=["Phase 1b"], phases_modified=["Phase 1"],
	)
	assert result.success

	update_progress(str(tmp_path), phase_completed="Phase 1", phase_started="Phase 1b", commit_hash="aaa111")
	update_progress(str(tmp_path), phase_completed="Phase 1b", phase_started="Complete", commit_hash="bbb222")

	from claude_orchestrator.workflow import get_workflow_state
	state = get_workflow_state(str(tmp_path))
	assert state.current_phase == "Complete"
	assert state.last_commit == "bbb222"


def test_protocol_includes_continuous_improvement():
	"""protocol.md should include continuous improvement loop."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Continuous Improvement Loop" in protocol
	assert "Discover" in protocol
	assert "Plan -> Execute -> Verify -> Discover -> Plan" in protocol


def test_protocol_includes_output_discipline():
	"""protocol.md should include output discipline guidance."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Output Discipline" in protocol
	assert "NEVER do" in protocol
	assert "Context pollution" in protocol


def test_protocol_includes_oracle_partitioning():
	"""protocol.md should include oracle-based task partitioning guidance."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "Oracle-based task partitioning" in protocol
	assert "failing tests FIRST" in protocol


def test_protocol_includes_parallel_decomposition():
	"""protocol.md should include parallel decomposition guidance."""
	from importlib import resources as pkg_resources

	protocol = (
		pkg_resources.files("claude_orchestrator")
		.joinpath("protocol.md")
		.read_text(encoding="utf-8")
	)

	assert "### Parallel Decomposition" in protocol
	assert "Serial collapse" in protocol
	assert "Spurious parallelism" in protocol
	assert "Critical path rule" in protocol


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
