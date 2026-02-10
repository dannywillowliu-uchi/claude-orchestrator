"""Eval scenarios for the workflow system.

Each scenario is a structured test case with:
- setup: creates the test state in a temp directory
- check: validates the expected outcome
- dimension: what aspect of the system this tests

Dimensions:
- workflow_lifecycle: init, phase transitions, progress tracking
- bootstrap: project type detection, CLAUDE.md generation
- tool_disclosure: phase-tool mapping correctness
- verification_gate: error tiers, gotcha derivation
- project_memory: decisions, gotchas, deduplication
- context_recovery: state reconstruction from progress.md
- edge_cases: unknown types, missing files, malformed input

To add a new scenario: append a Scenario to SCENARIOS list with
a unique id, setup function, and check function.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from claude_orchestrator.bootstrap import detect_project_type, generate_claude_md
from claude_orchestrator.fixer import analyze_verification, track_convergence
from claude_orchestrator.plan_parser import PlanPhase, PlanTree, parse_plan
from claude_orchestrator.project_memory import log_decision, log_gotcha
from claude_orchestrator.replanner import apply_replan
from claude_orchestrator.review import generate_review, list_reviews
from claude_orchestrator.session_report import (
	format_blocked,
	format_checkpoint,
	format_phase_complete,
)
from claude_orchestrator.tool_groups import (
	ALL_TOOLS,
	TOOL_GROUPS,
	VALID_PHASES,
	get_tools_for_phase,
)
from claude_orchestrator.workflow import (
	get_workflow_state,
	init_workflow,
	update_progress,
)


@dataclass
class Scenario:
	"""A single eval scenario."""

	id: str
	name: str
	dimension: str
	phase: str  # which workflow phase this is relevant to
	setup: Callable[[Path], None]
	check: Callable[[Path], dict[str, Any]]
	tags: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
	"""Result of running a scenario."""

	id: str
	name: str
	dimension: str
	passed: bool
	details: dict[str, Any] = field(default_factory=dict)
	error: str = ""


def _noop_setup(tmp: Path) -> None:
	pass


# ── Workflow Lifecycle ──────────────────────────────────────────────


def _check_init_creates_structure(tmp: Path) -> dict[str, Any]:
	result = init_workflow(str(tmp))
	wdir = tmp / ".claude-project"
	return {
		"passed": (
			result["success"]
			and wdir.exists()
			and (wdir / "discover.md").exists()
			and (wdir / "plan.md").exists()
			and (wdir / "progress.md").exists()
			and (wdir / "research").is_dir()
		),
		"created": result.get("created"),
	}


def _check_init_idempotent(tmp: Path) -> dict[str, Any]:
	init_workflow(str(tmp))
	r2 = init_workflow(str(tmp))
	return {
		"passed": r2["success"] and len(r2["skipped"]) == 3,
		"skipped": r2.get("skipped"),
	}


def _setup_workflow_for_transitions(tmp: Path) -> None:
	init_workflow(str(tmp))


def _check_phase_transition(tmp: Path) -> dict[str, Any]:
	result = update_progress(
		str(tmp),
		phase_completed="Discovery",
		phase_started="Research",
		summary="Done discovering.",
	)
	state = get_workflow_state(str(tmp))
	return {
		"passed": (
			result["success"]
			and state.current_phase == "Research"
		),
		"current_phase": state.current_phase,
	}


def _check_commit_hash_tracking(tmp: Path) -> dict[str, Any]:
	update_progress(str(tmp), phase_completed="Discovery", phase_started="Phase 1")
	update_progress(
		str(tmp),
		phase_completed="Phase 1",
		phase_started="Phase 2",
		commit_hash="abc1234",
	)
	state = get_workflow_state(str(tmp))
	return {
		"passed": state.last_commit == "abc1234",
		"last_commit": state.last_commit,
	}


def _check_phase_history_appended(tmp: Path) -> dict[str, Any]:
	update_progress(str(tmp), phase_completed="Discovery", phase_started="Research")
	update_progress(str(tmp), phase_completed="Research", phase_started="Phase 1")
	content = (tmp / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	return {
		"passed": "Discovery" in content and "Research" in content,
	}


# ── Bootstrap ───────────────────────────────────────────────────────


def _setup_python_project(tmp: Path) -> None:
	(tmp / "pyproject.toml").write_text(
		"[project]\nname='test'\n\n[tool.pytest.ini_options]\n\n[tool.ruff]\n",
		encoding="utf-8",
	)
	(tmp / "uv.lock").write_text("", encoding="utf-8")
	(tmp / "src").mkdir()


def _check_python_detection(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": (
			profile.project_type == "python"
			and profile.package_manager == "uv"
			and "uv run pytest" in profile.test_command
		),
		"project_type": profile.project_type,
		"package_manager": profile.package_manager,
	}


def _setup_node_project(tmp: Path) -> None:
	(tmp / "package.json").write_text('{"name":"test"}', encoding="utf-8")
	(tmp / "tsconfig.json").write_text("{}", encoding="utf-8")


def _check_node_detection(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": (
			profile.project_type == "node"
			and profile.package_manager == "npm"
			and "npm test" in profile.test_command
			and profile.detected_tools.get("typescript") is True
		),
		"project_type": profile.project_type,
	}


def _setup_yarn_project(tmp: Path) -> None:
	(tmp / "package.json").write_text('{"name":"test"}', encoding="utf-8")
	(tmp / "yarn.lock").write_text("", encoding="utf-8")


def _check_yarn_detection(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": profile.package_manager == "yarn",
		"package_manager": profile.package_manager,
	}


def _check_unknown_project(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": (
			profile.project_type == "unknown"
			and profile.verification_commands == []
		),
		"project_type": profile.project_type,
	}


def _check_claude_md_generation(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	content = generate_claude_md(profile, "test-project")
	return {
		"passed": (
			"uv run pytest" in content
			and "uv run ruff" in content
			and "test-project" in content
		),
	}


def _setup_existing_claude_md(tmp: Path) -> None:
	(tmp / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
	(tmp / "CLAUDE.md").write_text("# Custom\n", encoding="utf-8")


def _check_existing_claude_md_preserved(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": profile.has_claude_md is True,
	}


# ── Tool Disclosure ─────────────────────────────────────────────────


def _check_all_tools_in_groups(tmp: Path) -> dict[str, Any]:
	# Import registered tools
	from claude_orchestrator.server import mcp
	registered = set(mcp._tool_manager._tools.keys())
	return {
		"passed": registered == ALL_TOOLS,
		"registered": sorted(registered),
		"in_groups": sorted(ALL_TOOLS),
	}


def _check_discovery_tools(tmp: Path) -> dict[str, Any]:
	tools = get_tools_for_phase("discovery")
	return {
		"passed": (
			"init_project_workflow" in tools
			and "bootstrap_project" in tools
			and "run_verification" not in tools
		),
		"tools": tools,
	}


def _check_execution_tools(tmp: Path) -> dict[str, Any]:
	tools = get_tools_for_phase("execution")
	return {
		"passed": (
			"run_verification" in tools
			and "workflow_progress" in tools
			and "log_project_gotcha" in tools
		),
		"tools": tools,
	}


def _check_unknown_phase_fallback(tmp: Path) -> dict[str, Any]:
	tools = get_tools_for_phase("nonexistent")
	return {
		"passed": set(tools) == ALL_TOOLS,
	}


def _check_always_tools_present(tmp: Path) -> dict[str, Any]:
	results = {}
	for phase in VALID_PHASES:
		tools = get_tools_for_phase(phase)
		for always_tool in TOOL_GROUPS["always"]:
			if always_tool not in tools:
				results[f"{phase}_missing_{always_tool}"] = False
	return {
		"passed": len(results) == 0,
		"failures": results,
	}


# ── Project Memory ──────────────────────────────────────────────────


def _setup_project_with_gotchas(tmp: Path) -> None:
	(tmp / "CLAUDE.md").write_text(
		"# Project\n\n## Gotchas & Learnings\n\n## Other\n",
		encoding="utf-8",
	)


def _check_gotcha_logging(tmp: Path) -> dict[str, Any]:
	result = log_gotcha(str(tmp), "dont", "Use eval() on user input")
	content = (tmp / "CLAUDE.md").read_text(encoding="utf-8")
	return {
		"passed": (
			result["success"]
			and "eval()" in content
		),
	}


def _check_gotcha_dedup(tmp: Path) -> dict[str, Any]:
	log_gotcha(str(tmp), "dont", "Duplicate entry")
	r2 = log_gotcha(str(tmp), "dont", "Duplicate entry")
	content = (tmp / "CLAUDE.md").read_text(encoding="utf-8")
	return {
		"passed": (
			"skipped" in r2.get("message", "")
			and content.count("Duplicate entry") == 1
		),
	}


def _setup_project_with_decisions(tmp: Path) -> None:
	(tmp / "CLAUDE.md").write_text(
		"# Project\n\n## Decisions Log\n"
		"| Date | Decision | Rationale | Alternatives |\n"
		"| ---- | -------- | --------- | ------------ |\n\n"
		"## Other\n",
		encoding="utf-8",
	)


def _check_decision_logging(tmp: Path) -> dict[str, Any]:
	result = log_decision(str(tmp), "Use SQLite", "Simplest option", "Postgres")
	content = (tmp / "CLAUDE.md").read_text(encoding="utf-8")
	return {
		"passed": (
			result["success"]
			and "SQLite" in content
			and "Simplest option" in content
		),
	}


# ── Context Recovery ────────────────────────────────────────────────


def _setup_complex_progress(tmp: Path) -> None:
	wdir = tmp / ".claude-project"
	wdir.mkdir(parents=True)
	(wdir / "discover.md").write_text("# Discovery\n")
	(wdir / "plan.md").write_text("# Plan\n")
	(wdir / "progress.md").write_text(
		"# Progress\n\n"
		"## Current State\n"
		"Phase: Phase 3 - Deployment\n"
		"Active Task: Configure CI\n"
		"Blocked: Waiting for keys\n"
		"Last Commit: def5678\n\n"
		"## Next Up\n- Deploy\n\n"
		"## Phase History\n",
		encoding="utf-8",
	)
	research = wdir / "research"
	research.mkdir()
	(research / "api-design.md").write_text("# API\n")
	(research / "auth.md").write_text("# Auth\n")


def _check_state_parsing(tmp: Path) -> dict[str, Any]:
	state = get_workflow_state(str(tmp))
	return {
		"passed": (
			state.exists
			and state.current_phase == "Phase 3 - Deployment"
			and state.active_task == "Configure CI"
			and state.blocked == "Waiting for keys"
			and state.last_commit == "def5678"
			and state.has_discover
			and state.has_plan
			and "api-design" in state.research_topics
			and "auth" in state.research_topics
		),
		"phase": state.current_phase,
		"research_topics": state.research_topics,
	}


def _check_nonexistent_workflow(tmp: Path) -> dict[str, Any]:
	state = get_workflow_state(str(tmp))
	return {
		"passed": (
			not state.exists
			and state.current_phase == ""
		),
	}


def _setup_fresh_workflow(tmp: Path) -> None:
	init_workflow(str(tmp))


def _check_fresh_state(tmp: Path) -> dict[str, Any]:
	state = get_workflow_state(str(tmp))
	return {
		"passed": (
			state.exists
			and state.current_phase == "Not started"
			and state.active_task == "None"
			and state.blocked == "None"
		),
	}


# ── Review Artifacts ─────────────────────────────────────────────────


def _setup_workflow_for_review(tmp: Path) -> None:
	init_workflow(str(tmp))


def _check_review_created(tmp: Path) -> dict[str, Any]:
	result = generate_review(
		str(tmp),
		phase_name="Phase 1 - Core",
		summary="Built core module.",
		commit_hash="abc1234",
		decisions=["Use SQLite"],
		risks=["No backups"],
	)
	artifact = Path(result["artifact_path"])
	content = artifact.read_text(encoding="utf-8")
	return {
		"passed": (
			result["success"]
			and artifact.exists()
			and "Phase 1 - Core" in content
			and "abc1234" in content
			and "SQLite" in content
		),
	}


def _check_review_telegram_summary(tmp: Path) -> dict[str, Any]:
	result = generate_review(
		str(tmp),
		phase_name="Phase 2",
		summary="Added tests.",
		risks=["Flaky test"],
	)
	summary = result.get("telegram_summary", "")
	return {
		"passed": (
			"Phase complete" in summary
			and "review recommended" in summary
		),
		"summary": summary,
	}


def _check_review_list(tmp: Path) -> dict[str, Any]:
	generate_review(str(tmp), phase_name="Phase A")
	generate_review(str(tmp), phase_name="Phase B")
	reviews = list_reviews(str(tmp))
	return {
		"passed": len(reviews) == 2,
		"count": len(reviews),
	}


# ── Edge Cases ──────────────────────────────────────────────────────


def _check_init_on_missing_dir(tmp: Path) -> dict[str, Any]:
	target = tmp / "nonexistent" / "deep" / "path"
	result = init_workflow(str(target))
	return {
		"passed": result["success"] and (target / ".claude-project").exists(),
	}


def _check_progress_without_workflow(tmp: Path) -> dict[str, Any]:
	result = update_progress(str(tmp), phase_completed="X", phase_started="Y")
	return {
		"passed": not result["success"] and "error" in result,
	}


def _setup_rust_project(tmp: Path) -> None:
	(tmp / "Cargo.toml").write_text('[package]\nname = "test"\n', encoding="utf-8")


def _check_rust_detection(tmp: Path) -> dict[str, Any]:
	profile = detect_project_type(str(tmp))
	return {
		"passed": (
			profile.project_type == "rust"
			and profile.package_manager == "cargo"
			and "cargo test" in profile.test_command
		),
		"project_type": profile.project_type,
	}


# ── Plan Parsing ────────────────────────────────────────────────────


def _setup_flat_plan(tmp: Path) -> None:
	wdir = tmp / ".claude-project"
	wdir.mkdir(parents=True)
	(wdir / "plan.md").write_text(
		"# Plan\n\n"
		"## Overview\nSome overview.\n\n"
		"## Phase 1 - Setup\n"
		"checkpoint: false\n"
		"- [ ] Create structure\n\n"
		"## Phase 2 - Build\n"
		"checkpoint: true\n"
		"- [ ] Implement core\n",
		encoding="utf-8",
	)


def _check_flat_plan_parsed(tmp: Path) -> dict[str, Any]:
	tree = parse_plan(str(tmp))
	return {
		"passed": (
			len(tree.phases) == 2
			and tree.phases[0].name == "Phase 1 - Setup"
			and tree.phases[0].checkpoint is False
			and tree.phases[1].checkpoint is True
			and len(tree.phases[0].tasks) == 1
		),
		"phase_count": len(tree.phases),
	}


def _setup_nested_plan(tmp: Path) -> None:
	wdir = tmp / ".claude-project"
	wdir.mkdir(parents=True)
	(wdir / "plan.md").write_text(
		"# Plan\n\n"
		"## Phase 1 - Core\n"
		"- [ ] Setup\n\n"
		"### Sub-phase 1.1 - Models\n"
		"- [ ] Create models\n\n"
		"### Sub-phase 1.2 - Services\n"
		"- [ ] Create services\n\n"
		"## Phase 2 - API\n"
		"- [ ] Endpoints\n",
		encoding="utf-8",
	)


def _check_nested_plan_parsed(tmp: Path) -> dict[str, Any]:
	tree = parse_plan(str(tmp))
	flat = tree.flatten()
	paths = [p for p, _ in flat]
	return {
		"passed": (
			len(tree.phases) == 2
			and len(tree.phases[0].children) == 2
			and "Phase 1 - Core > Sub-phase 1.1 - Models" in paths
			and "Phase 1 - Core > Sub-phase 1.2 - Services" in paths
		),
		"paths": paths,
	}


def _check_depth_first_navigation(tmp: Path) -> dict[str, Any]:
	tree = PlanTree(phases=[
		PlanPhase(name="Phase 1", depth=0, children=[
			PlanPhase(name="Sub 1.1", depth=1),
		]),
		PlanPhase(name="Phase 2", depth=0),
	])
	return {
		"passed": (
			tree.next_phase("Phase 1") == "Phase 1 > Sub 1.1"
			and tree.next_phase("Phase 1 > Sub 1.1") == "Phase 2"
			and tree.next_phase("Phase 2") is None
		),
	}


# ── Self-Correction ─────────────────────────────────────────────────


def _check_critical_blocks(tmp: Path) -> dict[str, Any]:
	checks = [
		{"name": "pytest", "status": "failed", "output_preview": "FAILED tests/test_x.py::test_y"},
		{"name": "ruff", "status": "passed", "output_preview": ""},
	]
	result = analyze_verification(checks)
	return {
		"passed": (
			result.should_block is True
			and result.critical_count >= 1
			and any(t.severity == "critical" for t in result.fix_tasks)
		),
	}


def _check_non_critical_allows(tmp: Path) -> dict[str, Any]:
	checks = [
		{"name": "pytest", "status": "passed", "output_preview": ""},
		{"name": "ruff", "status": "failed", "output_preview": "src/f.py:1:1: E501 Line too long"},
	]
	result = analyze_verification(checks)
	return {
		"passed": (
			result.should_block is False
			and result.non_critical_count >= 1
			and any(t.severity == "non-critical" for t in result.fix_tasks)
		),
	}


def _check_circuit_breaker(tmp: Path) -> dict[str, Any]:
	violations = "\n".join(
		f"src/f.py:{i}:1: E{500 + i} Violation {i}" for i in range(7)
	)
	checks = [
		{"name": "ruff", "status": "failed", "output_preview": violations},
	]
	result = analyze_verification(checks, circuit_breaker_threshold=5)
	return {
		"passed": (
			result.circuit_breaker_triggered is True
			and result.should_block is False
		),
	}


# ── Session Reporting ───────────────────────────────────────────────


def _check_phase_complete_format(tmp: Path) -> dict[str, Any]:
	msg = format_phase_complete(
		"Phase 1", "proj",
		verification_passed=True,
		commit_hash="abc1234",
	)
	return {
		"passed": (
			"[proj]" in msg
			and "Phase 1" in msg
			and "PASS" in msg
			and "abc1234" in msg
		),
	}


def _check_checkpoint_format(tmp: Path) -> dict[str, Any]:
	msg = format_checkpoint(
		"Phase 2", "proj",
		risks=["Risk A"],
		next_phase="Phase 3",
	)
	return {
		"passed": (
			"CHECKPOINT" in msg
			and "Risk A" in msg
			and "Awaiting approval" in msg
		),
	}


def _check_blocked_format(tmp: Path) -> dict[str, Any]:
	msg = format_blocked("Phase 3", "proj", reason="API key missing")
	return {
		"passed": (
			"BLOCKED" in msg
			and "API key missing" in msg
			and "Human intervention" in msg
		),
	}


# ── Error Convergence ────────────────────────────────────────────────


def _check_convergence_converging(tmp: Path) -> dict[str, Any]:
	history = [
		{"critical_count": 3, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
			{"check": "pytest", "rule_code": "", "file_path": "b.py"},
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
		]},
		{"critical_count": 1, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
		]},
	]
	result = track_convergence(history)
	return {
		"passed": result.trend == "converging" and result.recommendation == "continue_fixing",
		"trend": result.trend,
	}


def _check_convergence_stable_accept(tmp: Path) -> dict[str, Any]:
	run = {"critical_count": 0, "non_critical_count": 2, "fix_tasks": [
		{"check": "ruff", "rule_code": "E501", "file_path": "a.py"},
		{"check": "ruff", "rule_code": "E502", "file_path": "b.py"},
	]}
	result = track_convergence([run, run], tolerance=2)
	return {
		"passed": result.trend == "stable" and result.recommendation == "accept_and_commit",
		"trend": result.trend,
	}


def _check_convergence_diverging_escalate(tmp: Path) -> dict[str, Any]:
	history = [
		{"critical_count": 1, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
		]},
		{"critical_count": 2, "non_critical_count": 1, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
			{"check": "pytest", "rule_code": "", "file_path": "b.py"},
			{"check": "ruff", "rule_code": "E501", "file_path": "c.py"},
		]},
	]
	result = track_convergence(history)
	return {
		"passed": result.trend == "diverging" and result.recommendation == "escalate",
		"trend": result.trend,
	}


# ── Adaptive Replanning ──────────────────────────────────────────────


def _setup_workflow_for_replan(tmp: Path) -> None:
	init_workflow(str(tmp))


def _check_replan_applies(tmp: Path) -> dict[str, Any]:
	result = apply_replan(
		str(tmp), "scope_change", "Test replan",
		"# New Plan\n\n## Phase 1 - Updated\n- [ ] New task\n",
		phases_added=["Phase 1 - Updated"],
	)
	plan = (tmp / ".claude-project" / "plan.md").read_text(encoding="utf-8")
	return {
		"passed": result.success and "New Plan" in plan,
		"replan_count": result.replan_count,
	}


def _check_replan_preserves_history(tmp: Path) -> dict[str, Any]:
	update_progress(str(tmp), phase_completed="Discovery", phase_started="Phase 1")
	apply_replan(str(tmp), "phase_split", "Split", "# v2\n")
	content = (tmp / ".claude-project" / "progress.md").read_text(encoding="utf-8")
	return {
		"passed": "Discovery" in content and "Replan #1" in content,
	}


def _check_replan_limit(tmp: Path) -> dict[str, Any]:
	for i in range(3):
		apply_replan(str(tmp), "scope_change", f"r{i + 1}", f"# v{i + 2}\n")
	result = apply_replan(str(tmp), "scope_change", "overflow", "# overflow\n")
	return {
		"passed": not result.success and "limit" in result.error.lower(),
	}


# ── Integration ──────────────────────────────────────────────────────


def _check_convergence_feeds_replan(tmp: Path) -> dict[str, Any]:
	"""Diverging convergence should trigger replan with verification_feedback."""
	init_workflow(str(tmp))
	# Simulate diverging errors
	history = [
		{"critical_count": 1, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
		]},
		{"critical_count": 3, "non_critical_count": 0, "fix_tasks": [
			{"check": "pytest", "rule_code": "", "file_path": "a.py"},
			{"check": "pytest", "rule_code": "", "file_path": "b.py"},
			{"check": "pytest", "rule_code": "", "file_path": "c.py"},
		]},
	]
	conv = track_convergence(history)
	# Convergence says escalate -> agent would replan with verification_feedback
	replan_result = apply_replan(
		str(tmp), "verification_feedback",
		f"Errors diverging ({conv.recommendation})",
		"# Revised Plan\n\n## Phase 1 - Fix regressions\n- [ ] Fix test failures\n",
	)
	return {
		"passed": (
			conv.recommendation == "escalate"
			and replan_result.success
			and replan_result.replan_count == 1
		),
		"convergence_trend": conv.trend,
	}


def _setup_workflow_with_plan(tmp: Path) -> None:
	init_workflow(str(tmp))
	plan = (
		"# Plan\n\n"
		"## Phase 1 - Core\n"
		"checkpoint: false\n"
		"- [ ] Build core\n\n"
		"### Sub-phase 1.1 - Models\n"
		"- [ ] Create models\n\n"
		"## Phase 2 - API\n"
		"checkpoint: true\n"
		"- [ ] Build endpoints\n"
	)
	(tmp / ".claude-project" / "plan.md").write_text(plan, encoding="utf-8")


def _check_replan_produces_parseable_plan(tmp: Path) -> dict[str, Any]:
	"""Replan with phase_split should produce a parseable plan tree."""
	new_plan = (
		"# Plan\n\n"
		"## Phase 1 - Core\n"
		"checkpoint: false\n"
		"- [ ] Build core\n\n"
		"### Sub-phase 1.1 - Models\n"
		"- [ ] Create models\n\n"
		"### Sub-phase 1.2 - Validation\n"
		"- [ ] Add validation\n\n"
		"## Phase 2 - API\n"
		"checkpoint: true\n"
		"- [ ] Build endpoints\n"
	)
	result = apply_replan(
		str(tmp), "phase_split", "Split Phase 1 into sub-phases",
		new_plan, phases_added=["Sub-phase 1.2 - Validation"],
	)
	tree = parse_plan(str(tmp))
	flat_paths = [p for p, _ in tree.flatten()]
	return {
		"passed": (
			result.success
			and len(tree.phases) == 2
			and len(tree.phases[0].children) == 2
			and "Phase 1 - Core > Sub-phase 1.2 - Validation" in flat_paths
		),
		"paths": flat_paths,
	}


def _setup_full_lifecycle(tmp: Path) -> None:
	init_workflow(str(tmp))


def _check_full_lifecycle(tmp: Path) -> dict[str, Any]:
	"""Full lifecycle: init -> plan -> execute -> replan -> verify -> complete."""
	# Write initial plan
	plan = "# Plan\n\n## Phase 1 - Build\n- [ ] Build\n\n## Phase 2 - Test\n- [ ] Test\n"
	(tmp / ".claude-project" / "plan.md").write_text(plan, encoding="utf-8")

	# Execute phase 1
	update_progress(str(tmp), phase_completed="Discovery", phase_started="Phase 1 - Build")
	state = get_workflow_state(str(tmp))
	assert state.current_phase == "Phase 1 - Build"

	# Replan: add Phase 1.5
	new_plan = (
		"# Plan\n\n## Phase 1 - Build\n- [ ] Build\n\n"
		"## Phase 1.5 - Refactor\n- [ ] Refactor\n\n"
		"## Phase 2 - Test\n- [ ] Test\n"
	)
	replan = apply_replan(
		str(tmp), "scope_change", "Need refactoring phase",
		new_plan, phases_added=["Phase 1.5 - Refactor"],
	)

	# Complete remaining phases
	update_progress(
		str(tmp), phase_completed="Phase 1 - Build",
		phase_started="Phase 1.5 - Refactor", commit_hash="aaa1111",
	)
	update_progress(
		str(tmp), phase_completed="Phase 1.5 - Refactor",
		phase_started="Phase 2 - Test", commit_hash="bbb2222",
	)
	update_progress(
		str(tmp), phase_completed="Phase 2 - Test",
		phase_started="Complete", commit_hash="ccc3333",
	)

	final_state = get_workflow_state(str(tmp))
	content = (tmp / ".claude-project" / "progress.md").read_text(encoding="utf-8")

	return {
		"passed": (
			replan.success
			and final_state.current_phase == "Complete"
			and final_state.last_commit == "ccc3333"
			and "Replan #1" in content
			and "Phase 1 - Build" in content
			and "Phase 1.5 - Refactor" in content
		),
	}


# ── Scenario Registry ──────────────────────────────────────────────

SCENARIOS: list[Scenario] = [
	# Workflow lifecycle (5)
	Scenario(
		"wf-01", "Init creates workflow structure",
		"workflow_lifecycle", "discovery",
		_noop_setup, _check_init_creates_structure,
	),
	Scenario(
		"wf-02", "Init is idempotent",
		"workflow_lifecycle", "discovery",
		_noop_setup, _check_init_idempotent,
	),
	Scenario(
		"wf-03", "Phase transition updates state",
		"workflow_lifecycle", "execution",
		_setup_workflow_for_transitions, _check_phase_transition,
	),
	Scenario(
		"wf-04", "Commit hash tracked across phases",
		"workflow_lifecycle", "execution",
		_setup_workflow_for_transitions, _check_commit_hash_tracking,
	),
	Scenario(
		"wf-05", "Phase history appended correctly",
		"workflow_lifecycle", "execution",
		_setup_workflow_for_transitions, _check_phase_history_appended,
	),
	# Bootstrap (6)
	Scenario(
		"bs-01", "Detect Python project with uv",
		"bootstrap", "discovery",
		_setup_python_project, _check_python_detection,
	),
	Scenario(
		"bs-02", "Detect Node project with TypeScript",
		"bootstrap", "discovery",
		_setup_node_project, _check_node_detection,
	),
	Scenario(
		"bs-03", "Detect yarn package manager",
		"bootstrap", "discovery",
		_setup_yarn_project, _check_yarn_detection,
	),
	Scenario(
		"bs-04", "Unknown project handled gracefully",
		"bootstrap", "discovery",
		_noop_setup, _check_unknown_project,
	),
	Scenario(
		"bs-05", "CLAUDE.md generated with correct commands",
		"bootstrap", "discovery",
		_setup_python_project, _check_claude_md_generation,
	),
	Scenario(
		"bs-06", "Existing CLAUDE.md not overwritten",
		"bootstrap", "discovery",
		_setup_existing_claude_md, _check_existing_claude_md_preserved,
	),
	# Tool disclosure (4)
	Scenario(
		"td-01", "All registered tools appear in groups",
		"tool_disclosure", "any",
		_noop_setup, _check_all_tools_in_groups,
	),
	Scenario(
		"td-02", "Discovery phase has correct tools",
		"tool_disclosure", "discovery",
		_noop_setup, _check_discovery_tools,
	),
	Scenario(
		"td-03", "Execution phase has correct tools",
		"tool_disclosure", "execution",
		_noop_setup, _check_execution_tools,
	),
	Scenario(
		"td-04", "Unknown phase returns all tools",
		"tool_disclosure", "any",
		_noop_setup, _check_unknown_phase_fallback,
	),
	Scenario(
		"td-05", "Always-tools present in every phase",
		"tool_disclosure", "any",
		_noop_setup, _check_always_tools_present,
	),
	# Project memory (3)
	Scenario(
		"pm-01", "Gotcha logged to CLAUDE.md",
		"project_memory", "execution",
		_setup_project_with_gotchas, _check_gotcha_logging,
	),
	Scenario(
		"pm-02", "Duplicate gotcha deduplicated",
		"project_memory", "execution",
		_setup_project_with_gotchas, _check_gotcha_dedup,
	),
	Scenario(
		"pm-03", "Decision logged to CLAUDE.md",
		"project_memory", "execution",
		_setup_project_with_decisions, _check_decision_logging,
	),
	# Context recovery (3)
	Scenario(
		"cr-01", "Complex progress.md parsed correctly",
		"context_recovery", "any",
		_setup_complex_progress, _check_state_parsing,
	),
	Scenario(
		"cr-02", "Nonexistent workflow returns empty state",
		"context_recovery", "any",
		_noop_setup, _check_nonexistent_workflow,
	),
	Scenario(
		"cr-03", "Fresh workflow has correct initial state",
		"context_recovery", "discovery",
		_setup_fresh_workflow, _check_fresh_state,
	),
	# Review artifacts (3)
	Scenario(
		"rv-01", "Review artifact created with all sections",
		"review_artifacts", "execution",
		_setup_workflow_for_review, _check_review_created,
	),
	Scenario(
		"rv-02", "Telegram summary includes risks warning",
		"review_artifacts", "execution",
		_setup_workflow_for_review, _check_review_telegram_summary,
	),
	Scenario(
		"rv-03", "Multiple reviews listed correctly",
		"review_artifacts", "execution",
		_setup_workflow_for_review, _check_review_list,
	),
	# Plan parsing (3)
	Scenario(
		"pp-01", "Flat plan phases parsed correctly",
		"plan_parsing", "planning",
		_setup_flat_plan, _check_flat_plan_parsed,
	),
	Scenario(
		"pp-02", "Nested sub-phases parsed with paths",
		"plan_parsing", "planning",
		_setup_nested_plan, _check_nested_plan_parsed,
	),
	Scenario(
		"pp-03", "Depth-first navigation works correctly",
		"plan_parsing", "planning",
		_noop_setup, _check_depth_first_navigation,
	),
	# Self-correction (3)
	Scenario(
		"sc-01", "Critical issues block commit",
		"self_correction", "verification",
		_noop_setup, _check_critical_blocks,
	),
	Scenario(
		"sc-02", "Non-critical issues allow commit with fix tasks",
		"self_correction", "verification",
		_noop_setup, _check_non_critical_allows,
	),
	Scenario(
		"sc-03", "Circuit breaker triggers on excess issues",
		"self_correction", "verification",
		_noop_setup, _check_circuit_breaker,
	),
	# Session reporting (3)
	Scenario(
		"sr-01", "Phase complete message formatted correctly",
		"session_reporting", "execution",
		_noop_setup, _check_phase_complete_format,
	),
	Scenario(
		"sr-02", "Checkpoint message includes risks and approval prompt",
		"session_reporting", "execution",
		_noop_setup, _check_checkpoint_format,
	),
	Scenario(
		"sr-03", "Blocked message includes reason and intervention prompt",
		"session_reporting", "execution",
		_noop_setup, _check_blocked_format,
	),
	# Error convergence (3)
	Scenario(
		"ec-converge-01", "Converging errors recommend continue_fixing",
		"error_convergence", "verification",
		_noop_setup, _check_convergence_converging,
	),
	Scenario(
		"ec-converge-02", "Stable non-critical accepts and commits",
		"error_convergence", "verification",
		_noop_setup, _check_convergence_stable_accept,
	),
	Scenario(
		"ec-converge-03", "Diverging errors recommend escalate",
		"error_convergence", "verification",
		_noop_setup, _check_convergence_diverging_escalate,
	),
	# Adaptive replanning (3)
	Scenario(
		"ar-01", "Replan applies new plan content",
		"adaptive_replanning", "execution",
		_setup_workflow_for_replan, _check_replan_applies,
	),
	Scenario(
		"ar-02", "Replan preserves phase history",
		"adaptive_replanning", "execution",
		_setup_workflow_for_replan, _check_replan_preserves_history,
	),
	Scenario(
		"ar-03", "Replan limit enforced",
		"adaptive_replanning", "execution",
		_setup_workflow_for_replan, _check_replan_limit,
	),
	# Integration (3)
	Scenario(
		"int-01", "Diverging convergence feeds replan via verification_feedback",
		"integration", "execution",
		_noop_setup, _check_convergence_feeds_replan,
	),
	Scenario(
		"int-02", "Replan with phase_split produces parseable sub-phases",
		"integration", "execution",
		_setup_workflow_with_plan, _check_replan_produces_parseable_plan,
	),
	Scenario(
		"int-03", "Full lifecycle: init -> plan -> execute -> replan -> complete",
		"integration", "execution",
		_setup_full_lifecycle, _check_full_lifecycle,
	),
	# Edge cases (3)
	Scenario(
		"ec-01", "Init on deeply nested path",
		"edge_cases", "discovery",
		_noop_setup, _check_init_on_missing_dir,
	),
	Scenario(
		"ec-02", "Progress update without workflow fails gracefully",
		"edge_cases", "execution",
		_noop_setup, _check_progress_without_workflow,
	),
	Scenario(
		"ec-03", "Detect Rust project",
		"edge_cases", "discovery",
		_setup_rust_project, _check_rust_detection,
	),
]

assert len(SCENARIOS) >= 37, f"Expected >= 37 scenarios, got {len(SCENARIOS)}"
