"""Worktree tools - git worktree-based plan execution."""

import asyncio
import json
import logging
import re
import shlex
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..plans.models import Plan, PlanStatus
from ..plans.store import get_plan_store

logger = logging.getLogger(__name__)


async def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> tuple[str, str, int]:
	"""Run a git command and return (stdout, stderr, returncode)."""
	proc = await asyncio.create_subprocess_exec(
		"git", *args,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
		cwd=str(cwd),
	)
	try:
		stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
	except asyncio.TimeoutError:
		proc.kill()
		return ("", f"git {args[0]} timed out after {timeout}s", -1)
	return (
		stdout.decode().strip(),
		stderr.decode().strip(),
		proc.returncode or 0,
	)


async def _find_git_root(project_path: Path) -> Path:
	"""Find the git root for a project path."""
	stdout, stderr, rc = await _run_git(["rev-parse", "--show-toplevel"], project_path)
	if rc != 0:
		raise ValueError(f"Not a git repository: {project_path} ({stderr})")
	return Path(stdout)


def _slugify(text: str, max_len: int = 40) -> str:
	"""Convert text to a filesystem-safe slug."""
	slug = text.lower()
	slug = re.sub(r"[^a-z0-9]+", "-", slug)
	slug = slug.strip("-")
	if len(slug) > max_len:
		slug = slug[:max_len].rstrip("-")
	return slug or "plan"


async def _create_worktree(
	git_root: Path,
	worktree_path: Path,
	branch_name: str,
) -> dict[str, object]:
	"""Create a git worktree. Handles existing branches gracefully."""
	# Try with -b (new branch)
	stdout, stderr, rc = await _run_git(
		["worktree", "add", str(worktree_path), "-b", branch_name],
		git_root,
	)
	if rc == 0:
		return {"success": True, "output": stdout, "created_branch": True}

	# Branch might already exist -- try without -b
	if "already exists" in stderr:
		stdout, stderr, rc = await _run_git(
			["worktree", "add", str(worktree_path), branch_name],
			git_root,
		)
		if rc == 0:
			return {"success": True, "output": stdout, "created_branch": False}

	return {"success": False, "output": stderr}


def _generate_bootstrap_prompt(
	plan: Plan,
	worktree_path: Path,
	branch_name: str,
) -> Path:
	"""Write .claude-plan-context.md bootstrap file into the worktree."""
	decisions_md = ""
	if plan.decisions:
		decisions_md = "\n## Decisions Made During Planning\n\n"
		for d in plan.decisions:
			decisions_md += f"- **{d.decision}**: {d.rationale}\n"
			if d.alternatives:
				decisions_md += f"  - Rejected: {', '.join(d.alternatives)}\n"

	content = f"""# Plan Execution Context

## Overview
{plan.overview.goal}

## Plan
{plan.to_markdown()}
{decisions_md}
## Execution Instructions

You are executing this plan phase by phase in a git worktree.

### Workflow
1. Read this file first to understand the full plan
2. Start with Phase 1 and work sequentially
3. For each task, update status via `update_task_status`:
   - plan_id="{plan.id}"
   - phase_id, task_id, status ("in_progress" / "completed")
   - expected_version (current plan version)
4. Before EVERY commit: `run_verification()`
5. After each phase: `telegram_phase_update(...)`
6. On issues: `log_project_gotcha(..., gotcha_type="dont")`

### Plan Reference
- Plan ID: `{plan.id}`
- Current Version: `{plan.version}`
- Project: `{plan.project}`
- Branch: `{branch_name}`

### Verification
Run `run_verification` before every commit. If verification fails, fix the issues before proceeding.
The verification tool will automatically log gotchas from failures.

### When Done
After all phases are complete, commit your work and inform the user.
They can merge the branch `{branch_name}` and run `cleanup_worktree(plan_id="{plan.id}")`.
"""

	target = worktree_path / ".claude-plan-context.md"
	target.write_text(content, encoding="utf-8")
	return target


def _ensure_claude_md(source_root: Path, worktree_path: Path) -> None:
	"""Copy CLAUDE.md into worktree if not present."""
	target = worktree_path / "CLAUDE.md"
	if target.exists():
		return
	source = source_root / "CLAUDE.md"
	if source.exists():
		shutil.copy2(str(source), str(target))


def _derive_worktree_path(
	git_root: Path,
	plan: Plan,
) -> tuple[Path, str]:
	"""Derive worktree path and branch name from a plan."""
	slug = _slugify(plan.overview.goal)
	project_slug = _slugify(plan.project, max_len=30)
	dir_name = f"{project_slug}-{slug}-{plan.id[:6]}"
	worktree_path = git_root.parent / dir_name
	branch_name = f"plan/{plan.id}"
	return worktree_path, branch_name


def register_worktree_tools(mcp: FastMCP, config: Config) -> None:
	"""Register git worktree tools for plan execution."""

	@mcp.tool()
	async def execute_plan(plan_id: str, project_path: str = "") -> str:
		"""
		Create a git worktree for plan execution and return a terminal command.

		After a plan is approved, call this to set up an isolated worktree
		where a separate Claude session can execute the plan without
		disrupting the current conversation.

		Args:
			plan_id: The approved plan ID
			project_path: Optional project root override
		"""
		store = await get_plan_store()
		plan = await store.get_plan(plan_id)
		if not plan:
			return json.dumps({"success": False, "error": f"Plan not found: {plan_id}"})

		if plan.status not in (PlanStatus.APPROVED, PlanStatus.IN_PROGRESS):
			return json.dumps({
				"success": False,
				"error": f"Plan status is '{plan.status.value}', must be 'approved' or 'in_progress'",
			})

		# Resolve project path
		if project_path:
			proj_path = Path(project_path).expanduser().resolve()
		else:
			proj_path = config.projects_path / plan.project
		if not proj_path.is_dir():
			return json.dumps({"success": False, "error": f"Project directory not found: {proj_path}"})
		# Path containment check: must be under config.projects_path
		try:
			proj_path.relative_to(config.projects_path.resolve())
		except ValueError:
			return json.dumps({
				"success": False,
				"error": f"Project path must be under {config.projects_path}",
			})

		# Find git root
		try:
			git_root = await _find_git_root(proj_path)
		except ValueError as e:
			return json.dumps({"success": False, "error": str(e)})

		worktree_path, branch_name = _derive_worktree_path(git_root, plan)

		# Create worktree if it doesn't exist
		if worktree_path.exists():
			logger.info(f"Worktree already exists: {worktree_path}")
		else:
			result = await _create_worktree(git_root, worktree_path, branch_name)
			if not result["success"]:
				return json.dumps({
					"success": False,
					"error": f"Failed to create worktree: {result['output']}",
				})

		# Generate bootstrap prompt
		bootstrap_path = _generate_bootstrap_prompt(plan, worktree_path, branch_name)

		# Ensure CLAUDE.md is present
		_ensure_claude_md(git_root, worktree_path)

		# Update plan status to IN_PROGRESS
		if plan.status == PlanStatus.APPROVED:
			try:
				await store.update_plan(
					plan_id,
					{"status": PlanStatus.IN_PROGRESS},
					plan.version,
				)
			except Exception as e:
				logger.warning(f"Failed to update plan status: {e}")

		# Build initial prompt for descriptive session naming
		goal_short = plan.overview.goal[:60].replace('"', '\\"')
		initial_prompt = f"[{plan.project}] {goal_short} - Read .claude-plan-context.md to begin."
		command = f"cd {shlex.quote(str(worktree_path))} && claude -p {shlex.quote(initial_prompt)}"

		return json.dumps({
			"success": True,
			"command": command,
			"worktree_path": str(worktree_path),
			"branch_name": branch_name,
			"plan_id": plan_id,
			"project": plan.project,
			"bootstrap_file": str(bootstrap_path),
			"instructions": (
				"Open a new terminal tab and run the command above. "
				"The worktree contains .claude-plan-context.md with the full plan and execution instructions. "
				"Your current conversation will remain active."
			),
		}, indent=2)

	@mcp.tool()
	async def cleanup_worktree(plan_id: str, project_path: str = "", delete_branch: bool = True) -> str:
		"""
		Remove a git worktree created for plan execution.

		Call this after the plan is complete and changes have been merged.

		Args:
			plan_id: The plan ID whose worktree to remove
			project_path: Optional project root override
			delete_branch: Whether to also delete the plan branch (default True)
		"""
		store = await get_plan_store()
		plan = await store.get_plan(plan_id)
		if not plan:
			return json.dumps({"success": False, "error": f"Plan not found: {plan_id}"})

		# Resolve project path
		if project_path:
			proj_path = Path(project_path).expanduser().resolve()
		else:
			proj_path = config.projects_path / plan.project
		if not proj_path.is_dir():
			return json.dumps({"success": False, "error": f"Project directory not found: {proj_path}"})
		# Path containment check
		try:
			proj_path.relative_to(config.projects_path.resolve())
		except ValueError:
			return json.dumps({
				"success": False,
				"error": f"Project path must be under {config.projects_path}",
			})

		try:
			git_root = await _find_git_root(proj_path)
		except ValueError as e:
			return json.dumps({"success": False, "error": str(e)})

		worktree_path, branch_name = _derive_worktree_path(git_root, plan)

		if not worktree_path.exists():
			return json.dumps({
				"success": False,
				"error": f"Worktree not found: {worktree_path}",
			})

		# Remove worktree
		stdout, stderr, rc = await _run_git(
			["worktree", "remove", str(worktree_path)],
			git_root,
		)
		if rc != 0:
			if "contains modified or untracked files" in stderr or "is dirty" in stderr:
				return json.dumps({
					"success": False,
					"error": "Worktree has uncommitted changes. Commit or stash them first, then retry.",
					"hint": f"cd {worktree_path} && git stash",
				})
			return json.dumps({"success": False, "error": f"Failed to remove worktree: {stderr}"})

		# Optionally delete branch
		branch_deleted = False
		if delete_branch:
			_, stderr_br, rc_br = await _run_git(
				["branch", "-d", branch_name],
				git_root,
			)
			branch_deleted = rc_br == 0
			if rc_br != 0:
				logger.warning(f"Could not delete branch {branch_name}: {stderr_br}")

		return json.dumps({
			"success": True,
			"worktree_removed": str(worktree_path),
			"branch_deleted": branch_deleted,
			"plan_id": plan_id,
		}, indent=2)
