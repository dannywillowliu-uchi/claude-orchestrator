"""Shared test fixtures and helpers for claude-orchestrator tests."""

import subprocess
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

from claude_orchestrator.plans.models import (
	Decision,
	Phase,
	Plan,
	PlanOverview,
	PlanStatus,
	Research,
	Task,
)


def init_git_repo(path: Path) -> None:
	"""Create a real git repo with an initial commit."""
	path.mkdir(parents=True, exist_ok=True)
	subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
	subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
	subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)
	(path / "README.md").write_text("# Test\n")
	subprocess.run(["git", "add", "README.md"], cwd=str(path), capture_output=True, check=True)
	subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)


def capture_tools(config: MagicMock, register_fn: Callable) -> dict:
	"""Register tools on a mock MCP and return the captured tool functions.

	Args:
		config: Mock config object to pass to the registration function
		register_fn: The registration function (e.g., register_worktree_tools)

	Returns:
		Dict mapping tool name to the tool function
	"""
	captured = {}

	class MockMCP:
		def tool(self):
			def decorator(fn):
				captured[fn.__name__] = fn
				return fn
			return decorator

	register_fn(MockMCP(), config)
	return captured


def make_plan(
	plan_id: str = "test-plan-123",
	project: str = "test-project",
	status: PlanStatus = PlanStatus.APPROVED,
	goal: str = "Add user authentication",
) -> Plan:
	"""Create a Plan with realistic content for testing."""
	return Plan(
		id=plan_id,
		project=project,
		version=1,
		status=status,
		overview=PlanOverview(
			goal=goal,
			success_criteria=["Tests pass", "No regressions"],
			constraints=["No breaking changes"],
		),
		phases=[
			Phase(
				id="phase-1",
				name="Phase 1: Core auth",
				description="Implement core authentication",
				tasks=[
					Task(id="task-1", description="Create auth module", files=["src/auth.py"]),
					Task(id="task-2", description="Add JWT utils", files=["src/jwt.py"]),
				],
			),
			Phase(
				id="phase-2",
				name="Phase 2: Tests",
				description="Write tests",
				tasks=[
					Task(id="task-3", description="Unit tests for auth", files=["tests/test_auth.py"]),
				],
			),
		],
		decisions=[
			Decision(
				id="d1",
				decision="Use JWT tokens",
				rationale="Stateless, scalable",
				alternatives=["Session cookies", "OAuth tokens"],
			),
		],
		research=Research(),
	)
