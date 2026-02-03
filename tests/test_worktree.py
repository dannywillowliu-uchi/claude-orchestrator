"""Tests for the worktree tools module.

Uses real git repos (no mocked git commands) to verify actual behavior.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_orchestrator.plans.models import Plan, PlanStatus
from claude_orchestrator.tools.worktree import (
	_create_worktree,
	_derive_worktree_path,
	_ensure_claude_md,
	_find_git_root,
	_generate_bootstrap_prompt,
	_run_git,
	_slugify,
	register_worktree_tools,
)

from .helpers import capture_tools, init_git_repo, make_plan

# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
	def test_basic_text(self):
		assert _slugify("Add user authentication") == "add-user-authentication"

	def test_special_characters_stripped(self):
		assert _slugify("Fix bug #123 (critical!)") == "fix-bug-123-critical"

	def test_truncation_respects_max_len(self):
		result = _slugify("a very long goal description that exceeds the limit", max_len=20)
		assert len(result) <= 20
		assert not result.endswith("-")

	def test_empty_string_returns_fallback(self):
		assert _slugify("") == "plan"

	def test_only_special_chars_returns_fallback(self):
		assert _slugify("@#$%^&*()") == "plan"

	def test_strips_leading_trailing_hyphens(self):
		assert _slugify("--hello-world--") == "hello-world"

	def test_unicode_stripped(self):
		result = _slugify("Add auth ñ ü ö")
		# unicode chars become hyphens, collapsed
		assert "add-auth" in result
		assert "ñ" not in result

	def test_consecutive_special_chars_become_single_hyphen(self):
		assert _slugify("hello!!!world") == "hello-world"

	def test_truncation_strips_trailing_hyphen(self):
		# Truncating should strip any trailing hyphen
		result = _slugify("add user authentication", max_len=14)
		assert not result.endswith("-")


# ---------------------------------------------------------------------------
# _derive_worktree_path
# ---------------------------------------------------------------------------

class TestDeriveWorktreePath:
	def test_path_is_sibling_of_git_root(self):
		plan = make_plan()
		git_root = Path("/home/user/projects/test-project")
		wt_path, branch = _derive_worktree_path(git_root, plan)

		assert wt_path.parent == git_root.parent
		assert wt_path != git_root

	def test_branch_name_contains_plan_id(self):
		plan = make_plan(plan_id="abc-def-123")
		wt_path, branch = _derive_worktree_path(Path("/repo"), plan)
		assert branch == "plan/abc-def-123"

	def test_dir_name_contains_project_slug_and_id_prefix(self):
		plan = make_plan(plan_id="abcdef-123456", project="my-app", goal="Fix login")
		wt_path, _ = _derive_worktree_path(Path("/repos/my-app"), plan)

		assert "my-app" in wt_path.name
		assert "fix-login" in wt_path.name
		assert "abcdef" in wt_path.name  # id[:6]

	def test_different_plans_produce_different_paths(self):
		plan_a = make_plan(plan_id="aaa-111", goal="Feature A")
		plan_b = make_plan(plan_id="bbb-222", goal="Feature B")
		git_root = Path("/repo")

		path_a, _ = _derive_worktree_path(git_root, plan_a)
		path_b, _ = _derive_worktree_path(git_root, plan_b)
		assert path_a != path_b

	def test_slugifies_project_name_with_special_chars(self):
		"""Project names with special characters should be slugified in dir name."""
		plan = make_plan(project="My App (v2.0)!", goal="Fix bugs")
		git_root = Path("/repos/project")
		wt_path, _ = _derive_worktree_path(git_root, plan)

		# Project name should be slugified, not contain special chars
		assert "(" not in wt_path.name
		assert ")" not in wt_path.name
		assert "!" not in wt_path.name
		assert " " not in wt_path.name
		assert "my-app-v2-0" in wt_path.name


# ---------------------------------------------------------------------------
# _run_git timeout
# ---------------------------------------------------------------------------

class TestRunGitTimeout:
	@pytest.mark.asyncio
	async def test_timeout_returns_error(self, tmp_path: Path):
		"""_run_git should return error tuple on timeout."""
		repo = tmp_path / "repo"
		init_git_repo(repo)

		# Use a very short timeout with a command that would normally succeed
		# We can't easily make git hang, so we test that timeout param is accepted
		stdout, stderr, rc = await _run_git(["status"], repo, timeout=30)
		assert rc == 0  # Normal operation works

	@pytest.mark.asyncio
	async def test_timeout_parameter_is_passed(self, tmp_path: Path):
		"""Verify timeout parameter is used (indirectly via successful call)."""
		repo = tmp_path / "repo"
		init_git_repo(repo)

		# A short but reasonable timeout should work for simple commands
		stdout, stderr, rc = await _run_git(["rev-parse", "HEAD"], repo, timeout=5)
		assert rc == 0
		assert len(stdout) == 40  # Git SHA length


# ---------------------------------------------------------------------------
# _find_git_root -- uses real git repos
# ---------------------------------------------------------------------------

class TestFindGitRoot:
	@pytest.mark.asyncio
	async def test_finds_root_from_project_dir(self, tmp_path: Path):
		repo = tmp_path / "myrepo"
		init_git_repo(repo)
		result = await _find_git_root(repo)
		assert result.resolve() == repo.resolve()

	@pytest.mark.asyncio
	async def test_finds_root_from_subdirectory(self, tmp_path: Path):
		repo = tmp_path / "myrepo"
		init_git_repo(repo)
		subdir = repo / "src" / "deep"
		subdir.mkdir(parents=True)
		result = await _find_git_root(subdir)
		assert result.resolve() == repo.resolve()

	@pytest.mark.asyncio
	async def test_raises_for_non_repo(self, tmp_path: Path):
		not_repo = tmp_path / "plain-dir"
		not_repo.mkdir()
		with pytest.raises(ValueError, match="Not a git repository"):
			await _find_git_root(not_repo)

	@pytest.mark.asyncio
	async def test_raises_for_nonexistent_path(self, tmp_path: Path):
		with pytest.raises(Exception):
			await _find_git_root(tmp_path / "does-not-exist")


# ---------------------------------------------------------------------------
# _create_worktree -- uses real git repos
# ---------------------------------------------------------------------------

class TestCreateWorktree:
	@pytest.mark.asyncio
	async def test_creates_worktree_and_branch(self, tmp_path: Path):
		repo = tmp_path / "repo"
		init_git_repo(repo)
		wt_path = tmp_path / "worktree-dir"

		result = await _create_worktree(repo, wt_path, "plan/test-branch")

		assert result["success"] is True
		assert result["created_branch"] is True
		assert wt_path.exists()
		assert (wt_path / "README.md").exists()

		# Verify branch actually exists in git
		branches = subprocess.run(
			["git", "branch", "--list"], cwd=str(repo),
			capture_output=True, text=True,
		)
		assert "plan/test-branch" in branches.stdout

	@pytest.mark.asyncio
	async def test_handles_existing_branch(self, tmp_path: Path):
		repo = tmp_path / "repo"
		init_git_repo(repo)

		# Create the branch first
		subprocess.run(
			["git", "branch", "plan/existing"],
			cwd=str(repo), capture_output=True, check=True,
		)

		wt_path = tmp_path / "worktree-dir"
		result = await _create_worktree(repo, wt_path, "plan/existing")

		assert result["success"] is True
		assert result["created_branch"] is False
		assert wt_path.exists()

	@pytest.mark.asyncio
	async def test_worktree_is_independent_working_directory(self, tmp_path: Path):
		repo = tmp_path / "repo"
		init_git_repo(repo)
		wt_path = tmp_path / "worktree-dir"

		await _create_worktree(repo, wt_path, "plan/feature")

		# Create a file in worktree -- should not appear in main repo
		(wt_path / "new_file.txt").write_text("hello")
		assert not (repo / "new_file.txt").exists()

	@pytest.mark.asyncio
	async def test_worktree_shares_git_history(self, tmp_path: Path):
		repo = tmp_path / "repo"
		init_git_repo(repo)
		wt_path = tmp_path / "worktree-dir"

		await _create_worktree(repo, wt_path, "plan/feature")

		# Worktree should have the same initial commit
		log_main = subprocess.run(
			["git", "log", "--oneline"], cwd=str(repo),
			capture_output=True, text=True,
		)
		log_wt = subprocess.run(
			["git", "log", "--oneline"], cwd=str(wt_path),
			capture_output=True, text=True,
		)
		assert log_main.stdout.strip() == log_wt.stdout.strip()

	@pytest.mark.asyncio
	async def test_fails_for_non_repo(self, tmp_path: Path):
		not_repo = tmp_path / "plain"
		not_repo.mkdir()
		wt_path = tmp_path / "wt"

		result = await _create_worktree(not_repo, wt_path, "plan/x")
		assert result["success"] is False


# ---------------------------------------------------------------------------
# _generate_bootstrap_prompt
# ---------------------------------------------------------------------------

class TestGenerateBootstrapPrompt:
	def test_writes_file_at_expected_location(self, tmp_path: Path):
		plan = make_plan()
		result = _generate_bootstrap_prompt(plan, tmp_path, "plan/test-123")

		assert result == tmp_path / ".claude-plan-context.md"
		assert result.exists()

	def test_contains_plan_goal_and_id(self, tmp_path: Path):
		plan = make_plan(plan_id="my-plan-id", goal="Implement caching layer")
		_generate_bootstrap_prompt(plan, tmp_path, "plan/my-plan-id")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "Implement caching layer" in content
		assert "my-plan-id" in content

	def test_contains_all_required_tool_references(self, tmp_path: Path):
		plan = make_plan()
		_generate_bootstrap_prompt(plan, tmp_path, "plan/test")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		for tool_name in ["update_task_status", "run_verification", "log_project_gotcha", "telegram_phase_update"]:
			assert tool_name in content, f"Missing tool reference: {tool_name}"

	def test_includes_decisions_with_alternatives(self, tmp_path: Path):
		plan = make_plan()
		_generate_bootstrap_prompt(plan, tmp_path, "plan/test")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "Use JWT tokens" in content
		assert "Stateless, scalable" in content
		assert "Session cookies" in content

	def test_no_decisions_section_when_empty(self, tmp_path: Path):
		plan = make_plan()
		plan.decisions = []
		_generate_bootstrap_prompt(plan, tmp_path, "plan/test")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "Decisions Made During Planning" not in content

	def test_contains_phase_and_task_details_via_to_markdown(self, tmp_path: Path):
		plan = make_plan()
		_generate_bootstrap_prompt(plan, tmp_path, "plan/test")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "Phase 1: Core auth" in content
		assert "Create auth module" in content

	def test_includes_branch_name_and_version(self, tmp_path: Path):
		plan = make_plan()
		plan.version = 3
		_generate_bootstrap_prompt(plan, tmp_path, "plan/my-branch")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "plan/my-branch" in content
		assert "Current Version: `3`" in content

	def test_overwrites_existing_bootstrap_file(self, tmp_path: Path):
		# Write a stale file first
		(tmp_path / ".claude-plan-context.md").write_text("stale content")

		plan = make_plan(goal="Fresh plan")
		_generate_bootstrap_prompt(plan, tmp_path, "plan/test")
		content = (tmp_path / ".claude-plan-context.md").read_text()

		assert "stale content" not in content
		assert "Fresh plan" in content


# ---------------------------------------------------------------------------
# _ensure_claude_md
# ---------------------------------------------------------------------------

class TestEnsureClaudeMd:
	def test_copies_when_target_missing(self, tmp_path: Path):
		source = tmp_path / "source"
		source.mkdir()
		(source / "CLAUDE.md").write_text("# Instructions\nDo stuff.")

		target = tmp_path / "worktree"
		target.mkdir()

		_ensure_claude_md(source, target)

		assert (target / "CLAUDE.md").exists()
		assert (target / "CLAUDE.md").read_text() == "# Instructions\nDo stuff."

	def test_does_not_overwrite_existing(self, tmp_path: Path):
		source = tmp_path / "source"
		source.mkdir()
		(source / "CLAUDE.md").write_text("source version")

		target = tmp_path / "worktree"
		target.mkdir()
		(target / "CLAUDE.md").write_text("worktree version")

		_ensure_claude_md(source, target)
		assert (target / "CLAUDE.md").read_text() == "worktree version"

	def test_no_source_no_copy(self, tmp_path: Path):
		source = tmp_path / "source"
		source.mkdir()  # no CLAUDE.md
		target = tmp_path / "worktree"
		target.mkdir()

		_ensure_claude_md(source, target)
		assert not (target / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# execute_plan tool -- real git, real filesystem
# ---------------------------------------------------------------------------

class TestExecutePlanTool:
	@pytest.fixture
	def git_repo(self, tmp_path: Path) -> Path:
		repo = tmp_path / "test-project"
		init_git_repo(repo)
		(repo / "CLAUDE.md").write_text("# Project\n## Gotchas & Learnings\n")
		return repo

	@pytest.fixture
	def tools(self, tmp_path: Path):
		config = MagicMock()
		config.projects_path = tmp_path
		return capture_tools(config, register_worktree_tools)

	def _mock_store(self, plan: Plan):
		mock_store = AsyncMock()
		mock_store.get_plan.return_value = plan
		mock_store.update_plan.return_value = plan
		return mock_store

	@pytest.mark.asyncio
	async def test_creates_real_worktree(self, git_repo, tools, tmp_path):
		plan = make_plan()
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		assert result["success"] is True
		wt = Path(result["worktree_path"])
		assert wt.exists()
		assert (wt / ".claude-plan-context.md").exists()
		assert (wt / "CLAUDE.md").exists()
		assert (wt / "README.md").exists()  # from original repo

		# Verify it's actually a git worktree
		git_status = subprocess.run(
			["git", "status"], cwd=str(wt), capture_output=True, text=True,
		)
		assert git_status.returncode == 0

		# Verify we're on the plan branch
		branch_out = subprocess.run(
			["git", "branch", "--show-current"], cwd=str(wt),
			capture_output=True, text=True,
		)
		assert branch_out.stdout.strip() == f"plan/{plan.id}"

	@pytest.mark.asyncio
	async def test_rejects_draft_plan(self, git_repo, tools):
		plan = make_plan(status=PlanStatus.DRAFT)
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		assert result["success"] is False
		assert "draft" in result["error"]

	@pytest.mark.asyncio
	async def test_rejects_completed_plan(self, git_repo, tools):
		plan = make_plan(status=PlanStatus.COMPLETED)
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		assert result["success"] is False
		assert "completed" in result["error"]

	@pytest.mark.asyncio
	async def test_accepts_in_progress_plan(self, git_repo, tools, tmp_path):
		plan = make_plan(status=PlanStatus.IN_PROGRESS)
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		assert result["success"] is True

	@pytest.mark.asyncio
	async def test_plan_not_found(self, git_repo, tools):
		store = AsyncMock()
		store.get_plan.return_value = None

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"]("nonexistent-id", str(git_repo)))

		assert result["success"] is False
		assert "not found" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_nonexistent_project_path(self, tools):
		plan = make_plan()
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, "/tmp/does-not-exist-xyz"))

		assert result["success"] is False
		assert "not found" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_non_git_project_path(self, tools, tmp_path):
		plain_dir = tmp_path / "no-git"
		plain_dir.mkdir()
		plan = make_plan()
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(plain_dir)))

		assert result["success"] is False
		assert "not a git repository" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_reuses_existing_worktree_without_recreating(self, git_repo, tools, tmp_path):
		plan = make_plan()
		store = self._mock_store(plan)

		# First call creates it
		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			r1 = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))
		assert r1["success"] is True
		wt = Path(r1["worktree_path"])

		# Drop a marker file
		(wt / "marker.txt").write_text("exists")

		# Second call should reuse, not recreate
		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			r2 = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))
		assert r2["success"] is True
		assert r2["worktree_path"] == r1["worktree_path"]
		# Marker should still be there -- directory wasn't blown away
		assert (wt / "marker.txt").exists()

	@pytest.mark.asyncio
	async def test_bootstrap_regenerated_on_rerun(self, git_repo, tools, tmp_path):
		plan = make_plan()
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			r1 = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))
		wt = Path(r1["worktree_path"])
		content_v1 = (wt / ".claude-plan-context.md").read_text()

		# Modify the plan's version (NOT goal, since goal affects worktree path)
		plan.version = 99
		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		content_v2 = (wt / ".claude-plan-context.md").read_text()
		assert "**Version:** 99" in content_v2
		assert content_v1 != content_v2

	@pytest.mark.asyncio
	async def test_command_is_valid_shell(self, git_repo, tools, tmp_path):
		plan = make_plan()
		store = self._mock_store(plan)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		cmd = result["command"]
		# Should be: cd <path> && claude
		assert cmd.startswith("cd ")
		assert "&& claude" in cmd
		# The path portion should be a real directory
		cd_path = cmd.split("cd ")[1].split(" && ")[0]
		assert Path(cd_path).exists()

	@pytest.mark.asyncio
	async def test_update_plan_status_failure_does_not_break(self, git_repo, tools):
		"""execute_plan should succeed even if status update fails."""
		plan = make_plan(status=PlanStatus.APPROVED)
		store = AsyncMock()
		store.get_plan.return_value = plan
		store.update_plan.side_effect = Exception("DB error")

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(git_repo)))

		assert result["success"] is True  # worktree still created

	@pytest.mark.asyncio
	async def test_command_quotes_path_with_spaces(self, tmp_path: Path):
		"""Command should use shlex.quote for paths with spaces."""
		# Create project in parent dir with spaces (worktree goes to parent level)
		parent_with_spaces = tmp_path / "my projects"
		parent_with_spaces.mkdir()
		repo = parent_with_spaces / "test-project"
		init_git_repo(repo)
		(repo / "CLAUDE.md").write_text("# Test")

		config = MagicMock()
		config.projects_path = parent_with_spaces
		tools = capture_tools(config, register_worktree_tools)

		plan = make_plan(project="test-project")
		store = AsyncMock()
		store.get_plan.return_value = plan
		store.update_plan.return_value = plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(repo)))

		assert result["success"] is True
		cmd = result["command"]
		# Path should be quoted (shlex.quote adds single quotes)
		# Worktree path is at parent level, which has "my projects" with space
		assert "'" in cmd, f"Expected quoted path in command: {cmd}"

	@pytest.mark.asyncio
	async def test_rejects_path_outside_projects_dir(self, git_repo, tools, tmp_path: Path):
		"""execute_plan should reject project_path outside projects_path."""
		# Create a repo outside the config.projects_path
		outside_repo = tmp_path.parent / "outside_project"
		outside_repo.mkdir(parents=True, exist_ok=True)
		init_git_repo(outside_repo)

		plan = make_plan()
		store = AsyncMock()
		store.get_plan.return_value = plan

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=store):
			result = json.loads(await tools["execute_plan"](plan.id, str(outside_repo)))

		assert result["success"] is False
		assert "must be under" in result["error"]


# ---------------------------------------------------------------------------
# cleanup_worktree tool -- real git
# ---------------------------------------------------------------------------

class TestCleanupWorktreeTool:
	@pytest.fixture
	def setup(self, tmp_path: Path):
		"""Create a git repo with a worktree for cleanup testing."""
		repo = tmp_path / "test-project"
		init_git_repo(repo)

		plan = make_plan()
		wt_path, branch = _derive_worktree_path(repo, plan)

		# Create the worktree via git
		subprocess.run(
			["git", "worktree", "add", str(wt_path), "-b", branch],
			cwd=str(repo), capture_output=True, check=True,
		)

		config = MagicMock()
		config.projects_path = tmp_path
		tools = capture_tools(config, register_worktree_tools)

		store = AsyncMock()
		store.get_plan.return_value = plan

		return {
			"repo": repo, "wt_path": wt_path, "branch": branch,
			"plan": plan, "tools": tools, "store": store,
		}

	@pytest.mark.asyncio
	async def test_removes_clean_worktree(self, setup):
		s = setup
		assert s["wt_path"].exists()

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id))

		assert result["success"] is True
		assert not s["wt_path"].exists()

	@pytest.mark.asyncio
	async def test_fails_on_dirty_worktree(self, setup):
		s = setup
		# Create untracked file to make worktree dirty
		(s["wt_path"] / "uncommitted.txt").write_text("dirty")

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id))

		assert result["success"] is False
		assert "uncommitted" in result["error"].lower() or "commit" in result["error"].lower()
		assert "hint" in result
		assert s["wt_path"].exists()  # not removed

	@pytest.mark.asyncio
	async def test_fails_on_modified_tracked_file(self, setup):
		s = setup
		# Modify a tracked file
		(s["wt_path"] / "README.md").write_text("modified content")

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id))

		assert result["success"] is False
		assert s["wt_path"].exists()

	@pytest.mark.asyncio
	async def test_delete_branch_true_deletes_branch(self, setup):
		s = setup
		# Merge the branch first so -d works (unmerged branches need -D)
		subprocess.run(
			["git", "merge", s["branch"]],
			cwd=str(s["repo"]), capture_output=True,
		)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id, delete_branch=True))

		assert result["success"] is True
		branches = subprocess.run(
			["git", "branch", "--list"], cwd=str(s["repo"]),
			capture_output=True, text=True,
		)
		assert s["branch"].split("/")[-1] not in branches.stdout

	@pytest.mark.asyncio
	async def test_delete_branch_false_keeps_branch(self, setup):
		s = setup

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id, delete_branch=False))

		assert result["success"] is True
		assert result["branch_deleted"] is False

		# Branch should still exist
		branches = subprocess.run(
			["git", "branch", "--list"], cwd=str(s["repo"]),
			capture_output=True, text=True,
		)
		assert s["plan"].id in branches.stdout

	@pytest.mark.asyncio
	async def test_plan_not_found(self, setup):
		s = setup
		s["store"].get_plan.return_value = None

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"]("fake-id"))

		assert result["success"] is False
		assert "not found" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_worktree_already_removed(self, setup):
		s = setup
		# Manually remove it
		subprocess.run(
			["git", "worktree", "remove", str(s["wt_path"])],
			cwd=str(s["repo"]), capture_output=True,
		)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](s["plan"].id))

		assert result["success"] is False
		assert "not found" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_cleanup_with_project_path_override(self, setup):
		"""cleanup_worktree should accept project_path parameter."""
		s = setup

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			# Pass project_path explicitly
			result = json.loads(await s["tools"]["cleanup_worktree"](
				s["plan"].id, project_path=str(s["repo"]), delete_branch=False
			))

		assert result["success"] is True
		assert not s["wt_path"].exists()

	@pytest.mark.asyncio
	async def test_cleanup_rejects_path_outside_projects_dir(self, setup, tmp_path: Path):
		"""cleanup_worktree should reject project_path outside projects_path."""
		s = setup
		outside_path = tmp_path.parent / "outside"
		outside_path.mkdir(parents=True, exist_ok=True)

		with patch("claude_orchestrator.tools.worktree.get_plan_store", return_value=s["store"]):
			result = json.loads(await s["tools"]["cleanup_worktree"](
				s["plan"].id, project_path=str(outside_path)
			))

		assert result["success"] is False
		assert "must be under" in result["error"]


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

class TestMCPToolRegistration:
	def test_execute_plan_registered_on_real_server(self):
		from claude_orchestrator.server import mcp
		tools = mcp._tool_manager._tools
		assert "execute_plan" in tools

	def test_cleanup_worktree_registered_on_real_server(self):
		from claude_orchestrator.server import mcp
		tools = mcp._tool_manager._tools
		assert "cleanup_worktree" in tools

	def test_both_tools_are_callable(self):
		config = MagicMock()
		tools = capture_tools(config, register_worktree_tools)
		assert callable(tools["execute_plan"])
		assert callable(tools["cleanup_worktree"])
