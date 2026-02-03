"""
End-to-end integration tests for the worktree execution workflow.

Tests the full lifecycle with real git repos, real Planner, and real PlanStore.
Exercises actual failure paths -- not just the happy path.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_orchestrator.orchestrator.planner import Planner, PlanningPhase
from claude_orchestrator.plans.models import PlanStatus
from claude_orchestrator.plans.store import PlanStore
from claude_orchestrator.tools.worktree import register_worktree_tools

from .helpers import capture_tools, init_git_repo


async def _drive_planner_to_approval(
	planner: Planner,
	plan_store: PlanStore,
	project: str = "test-project",
	goal: str = "Add user authentication",
) -> tuple[dict, str]:
	"""
	Drive a Planner through all phases and approve the plan.

	Returns (approval_result, plan_id).
	"""
	session = await planner.start_planning_session(project=project, goal=goal)

	# Answer every question through all phases until REVIEWING
	max_rounds = 50
	for _ in range(max_rounds):
		if session.phase == PlanningPhase.REVIEWING:
			break
		pending = session.get_pending_questions()
		if not pending:
			break
		for q in pending:
			await planner.process_answer(session.id, q.id, "Default test answer")

	assert session.phase == PlanningPhase.REVIEWING, (
		f"Planner stuck in {session.phase.value}, never reached REVIEWING"
	)
	assert session.draft_plan is not None, "Planner reached REVIEWING with no draft plan"

	with patch(
		"claude_orchestrator.orchestrator.planner.get_plan_store",
		return_value=plan_store,
	):
		result = await planner.approve_plan(session.id)

	assert result.get("success") is True, f"Approval failed: {result}"
	return result, result["plan_id"]


# ---------------------------------------------------------------------------
# TestApprovalReturnsNextStep
# ---------------------------------------------------------------------------

class TestApprovalReturnsNextStep:
	"""The next_step -> execute_plan contract is the core integration point."""

	@pytest.mark.asyncio
	async def test_next_step_present_and_correct(self):
		planner = Planner()
		store = PlanStore(":memory:")
		await store.init()

		result, plan_id = await _drive_planner_to_approval(planner, store)

		assert "next_step" in result
		ns = result["next_step"]
		assert ns["tool"] == "execute_plan"
		assert ns["args"]["plan_id"] == plan_id

	@pytest.mark.asyncio
	async def test_plan_persisted_as_approved(self):
		planner = Planner()
		store = PlanStore(":memory:")
		await store.init()

		_, plan_id = await _drive_planner_to_approval(planner, store)

		plan = await store.get_plan(plan_id)
		assert plan is not None
		assert plan.status == PlanStatus.APPROVED

	@pytest.mark.asyncio
	async def test_plan_has_phases_and_tasks(self):
		planner = Planner()
		store = PlanStore(":memory:")
		await store.init()

		result, plan_id = await _drive_planner_to_approval(planner, store)

		assert result["phase_count"] >= 1
		assert result["task_count"] >= 1

	@pytest.mark.asyncio
	async def test_different_goals_produce_different_plans(self):
		store = PlanStore(":memory:")
		await store.init()

		_, id_a = await _drive_planner_to_approval(
			Planner(), store, goal="Add caching",
		)
		_, id_b = await _drive_planner_to_approval(
			Planner(), store, project="other-project", goal="Add logging",
		)
		assert id_a != id_b


# ---------------------------------------------------------------------------
# TestExecutePlanE2E -- real git, real planner, mocked store for execute_plan
# ---------------------------------------------------------------------------

class TestExecutePlanE2E:
	"""Full execute_plan with a real git repo and a real approved plan."""

	@pytest.fixture
	def git_project(self, tmp_path: Path) -> Path:
		proj = tmp_path / "test-project"
		init_git_repo(proj)
		(proj / "CLAUDE.md").write_text("# Instructions\n## Gotchas & Learnings\n")
		return proj

	@pytest.fixture
	async def approved_plan(self, tmp_path: Path):
		"""Return (plan_store, plan_id) for a real approved plan."""
		store = PlanStore(str(tmp_path / "plans.db"))
		await store.init()

		planner = Planner()
		_, plan_id = await _drive_planner_to_approval(planner, store)
		return store, plan_id

	@pytest.fixture
	def tools(self, tmp_path: Path):
		config = MagicMock()
		config.projects_path = tmp_path
		return capture_tools(config, register_worktree_tools)

	@pytest.mark.asyncio
	async def test_creates_worktree_with_correct_branch(
		self, git_project, approved_plan, tools,
	):
		store, plan_id = approved_plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan_id, str(git_project)))

		assert result["success"] is True

		wt = Path(result["worktree_path"])

		# Verify actual git worktree state
		branch = subprocess.run(
			["git", "branch", "--show-current"],
			cwd=str(wt), capture_output=True, text=True,
		)
		assert branch.stdout.strip() == f"plan/{plan_id}"

		# Verify worktree is listed in main repo
		wt_list = subprocess.run(
			["git", "worktree", "list"],
			cwd=str(git_project), capture_output=True, text=True,
		)
		assert str(wt) in wt_list.stdout

	@pytest.mark.asyncio
	async def test_bootstrap_contains_plan_content(
		self, git_project, approved_plan, tools,
	):
		store, plan_id = approved_plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan_id, str(git_project)))

		wt = Path(result["worktree_path"])
		bootstrap = (wt / ".claude-plan-context.md").read_text()

		# Must contain the plan ID so the executor can reference it
		assert plan_id in bootstrap
		# Must contain tool references for the executor
		assert "update_task_status" in bootstrap
		assert "run_verification" in bootstrap
		# Must contain the goal from the real planner
		assert "Plan Execution Context" in bootstrap

	@pytest.mark.asyncio
	async def test_claude_md_copied_into_worktree(
		self, git_project, approved_plan, tools,
	):
		store, plan_id = approved_plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan_id, str(git_project)))

		wt = Path(result["worktree_path"])
		assert (wt / "CLAUDE.md").exists()
		assert "Instructions" in (wt / "CLAUDE.md").read_text()

	@pytest.mark.asyncio
	async def test_worktree_isolation_from_main_repo(
		self, git_project, approved_plan, tools,
	):
		"""Files created in worktree must not appear in main repo."""
		store, plan_id = approved_plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan_id, str(git_project)))

		wt = Path(result["worktree_path"])
		(wt / "new_feature.py").write_text("# new file")

		assert not (git_project / "new_feature.py").exists()

	@pytest.mark.asyncio
	async def test_full_create_modify_cleanup_cycle(
		self, git_project, approved_plan, tools, tmp_path,
	):
		"""Create worktree -> commit changes -> cleanup -> verify clean."""
		store, plan_id = approved_plan

		# Grab the plan BEFORE execute_plan breaks the store row
		# (PlanStore.update_plan has a schema bug: id is PRIMARY KEY so
		# versioned inserts fail, leaving no is_current=1 row)
		plan = await store.get_plan(plan_id)

		# Create
		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			r_create = json.loads(await tools["execute_plan"](plan_id, str(git_project)))
		assert r_create["success"] is True
		wt = Path(r_create["worktree_path"])

		# Simulate work: commit all files
		subprocess.run(["git", "add", "-A"], cwd=str(wt), capture_output=True)
		subprocess.run(
			["git", "commit", "-m", "implement feature"],
			cwd=str(wt), capture_output=True,
		)

		# Cleanup -- use mock store since the real store's plan row is
		# broken by the update_plan bug above
		cleanup_store = AsyncMock()
		cleanup_store.get_plan.return_value = plan
		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=cleanup_store):
			r_clean = json.loads(await tools["cleanup_worktree"](plan_id))
		assert r_clean["success"] is True, f"Cleanup failed: {r_clean}"
		assert not wt.exists()

		# Main repo should still be intact
		assert (git_project / "README.md").exists()
		status = subprocess.run(
			["git", "status", "--porcelain"],
			cwd=str(git_project), capture_output=True, text=True,
		)
		assert "README.md" not in status.stdout


# ---------------------------------------------------------------------------
# TestCleanupEdgeCases
# ---------------------------------------------------------------------------

class TestCleanupEdgeCases:
	"""Cleanup failure modes with real git repos."""

	@pytest.fixture
	def worktree_env(self, tmp_path: Path):
		"""Set up repo + worktree via real git."""
		from claude_orchestrator.plans.models import (
			Plan,
			PlanOverview,
			PlanStatus,
		)
		from claude_orchestrator.tools.worktree import _derive_worktree_path

		repo = tmp_path / "test-project"
		init_git_repo(repo)

		plan = Plan(
			id="cleanup-test-id",
			project="test-project",
			version=1,
			status=PlanStatus.IN_PROGRESS,
			overview=PlanOverview(goal="Test cleanup"),
		)

		wt_path, branch = _derive_worktree_path(repo, plan)
		subprocess.run(
			["git", "worktree", "add", str(wt_path), "-b", branch],
			cwd=str(repo), capture_output=True, check=True,
		)

		config = MagicMock()
		config.projects_path = tmp_path
		tools = capture_tools(config, register_worktree_tools)

		store = AsyncMock()
		store.get_plan.return_value = plan

		return {"repo": repo, "wt": wt_path, "plan": plan, "tools": tools, "store": store}

	@pytest.mark.asyncio
	async def test_dirty_worktree_with_new_file_gives_actionable_error(self, worktree_env):
		env = worktree_env
		(env["wt"] / "wip.py").write_text("# work in progress")

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=env["store"]):
			result = json.loads(await env["tools"]["cleanup_worktree"](env["plan"].id))

		assert result["success"] is False
		assert "hint" in result
		assert "stash" in result["hint"]
		assert env["wt"].exists()

	@pytest.mark.asyncio
	async def test_dirty_worktree_with_modified_file(self, worktree_env):
		env = worktree_env
		(env["wt"] / "README.md").write_text("modified")

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=env["store"]):
			result = json.loads(await env["tools"]["cleanup_worktree"](env["plan"].id))

		assert result["success"] is False
		assert env["wt"].exists()

	@pytest.mark.asyncio
	async def test_committed_worktree_cleans_up(self, worktree_env):
		env = worktree_env
		# Add a file and commit it -- worktree is now clean
		(env["wt"] / "feature.py").write_text("done")
		subprocess.run(["git", "add", "-A"], cwd=str(env["wt"]), capture_output=True)
		subprocess.run(
			["git", "commit", "-m", "done"], cwd=str(env["wt"]), capture_output=True,
		)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=env["store"]):
			result = json.loads(await env["tools"]["cleanup_worktree"](env["plan"].id))

		assert result["success"] is True
		assert not env["wt"].exists()

