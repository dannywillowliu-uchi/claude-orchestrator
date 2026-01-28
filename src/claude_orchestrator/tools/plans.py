"""Plan management tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..plans.models import (
	Decision,
	Phase,
	Plan,
	PlanOverview,
	PlanStatus,
	Task,
	TaskStatus,
)
from ..plans.store import OptimisticLockError, PlanNotFoundError, get_plan_store


def register_plans_tools(mcp: FastMCP, config: Config) -> None:
	"""Register plan management tools."""

	@mcp.tool()
	async def create_plan(
		project: str,
		goal: str,
		success_criteria: str = "",
		constraints: str = "",
	) -> str:
		"""
		Create a new implementation plan for a project.

		Args:
			project: Project name (e.g., "my-app")
			goal: What the plan achieves
			success_criteria: Comma-separated success criteria
			constraints: Comma-separated constraints
		"""
		store = await get_plan_store()

		overview = PlanOverview(
			goal=goal,
			success_criteria=[c.strip() for c in success_criteria.split(",") if c.strip()],
			constraints=[c.strip() for c in constraints.split(",") if c.strip()],
		)

		plan = Plan(
			id="",
			project=project,
			overview=overview,
		)

		plan_id = await store.create_plan(project, plan)

		return json.dumps({
			"success": True,
			"plan_id": plan_id,
			"project": project,
			"status": plan.status.value,
		}, indent=2)

	@mcp.tool()
	async def get_plan(plan_id: str, version: int = 0) -> str:
		"""
		Get a plan by ID.

		Args:
			plan_id: The plan ID
			version: Optional version number (0 = current)
		"""
		store = await get_plan_store()
		plan = await store.get_plan(plan_id, version if version > 0 else None)

		if not plan:
			return json.dumps({"error": f"Plan not found: {plan_id}"})

		return json.dumps({
			"plan": plan.model_dump(),
			"progress": plan.get_progress(),
			"markdown": plan.to_markdown(),
		}, indent=2)

	@mcp.tool()
	async def get_project_plan(project: str) -> str:
		"""
		Get the current plan for a project.

		Args:
			project: Project name
		"""
		store = await get_plan_store()
		plan = await store.get_current_plan(project)

		if not plan:
			return json.dumps({
				"error": f"No plan found for project: {project}",
				"hint": "Use create_plan to create one",
			})

		return json.dumps({
			"plan": plan.model_dump(),
			"progress": plan.get_progress(),
		}, indent=2)

	@mcp.tool()
	async def add_phase_to_plan(
		plan_id: str,
		phase_name: str,
		description: str,
		tasks: str,
		expected_version: int,
	) -> str:
		"""
		Add a phase to an existing plan.

		Args:
			plan_id: Plan ID
			phase_name: Name of the phase
			description: What this phase accomplishes
			tasks: Semicolon-separated list of task descriptions
			expected_version: Current plan version (for optimistic locking)
		"""
		store = await get_plan_store()

		plan = await store.get_plan(plan_id)
		if not plan:
			return json.dumps({"error": f"Plan not found: {plan_id}"})

		phase_id = f"phase-{len(plan.phases) + 1}"
		task_list = [
			Task(
				id=f"{phase_id}-task-{i+1}",
				description=t.strip(),
			)
			for i, t in enumerate(tasks.split(";")) if t.strip()
		]

		phase = Phase(
			id=phase_id,
			name=phase_name,
			description=description,
			tasks=task_list,
		)

		try:
			updated = await store.update_plan(
				plan_id,
				{"phases": plan.phases + [phase]},
				expected_version,
			)
			return json.dumps({
				"success": True,
				"plan_id": plan_id,
				"new_version": updated.version,
				"phase_added": phase_name,
				"task_count": len(task_list),
			}, indent=2)
		except OptimisticLockError as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def update_task_status(
		plan_id: str,
		phase_id: str,
		task_id: str,
		status: str,
		expected_version: int,
	) -> str:
		"""
		Update a task's status in a plan.

		Args:
			plan_id: Plan ID
			phase_id: Phase ID (e.g., "phase-1")
			task_id: Task ID (e.g., "phase-1-task-1")
			status: New status (pending, in_progress, completed, blocked, skipped)
			expected_version: Current plan version
		"""
		store = await get_plan_store()

		try:
			task_status = TaskStatus(status)
		except ValueError:
			return json.dumps({
				"error": f"Invalid status: {status}",
				"valid_statuses": [s.value for s in TaskStatus],
			})

		try:
			updated = await store.update_task_status(
				plan_id, phase_id, task_id, task_status, expected_version
			)
			return json.dumps({
				"success": True,
				"plan_id": plan_id,
				"new_version": updated.version,
				"progress": updated.get_progress(),
			}, indent=2)
		except (OptimisticLockError, PlanNotFoundError, ValueError) as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def add_decision_to_plan(
		plan_id: str,
		decision: str,
		rationale: str,
		alternatives: str = "",
		expected_version: int = 0,
	) -> str:
		"""
		Add a decision to a plan.

		Args:
			plan_id: Plan ID
			decision: What was decided
			rationale: Why this decision was made
			alternatives: Comma-separated rejected alternatives
			expected_version: Current plan version
		"""
		store = await get_plan_store()

		plan = await store.get_plan(plan_id)
		if not plan:
			return json.dumps({"error": f"Plan not found: {plan_id}"})

		new_decision = Decision(
			id=f"decision-{len(plan.decisions) + 1}",
			decision=decision,
			rationale=rationale,
			alternatives=[a.strip() for a in alternatives.split(",") if a.strip()],
		)

		try:
			updated = await store.update_plan(
				plan_id,
				{"decisions": plan.decisions + [new_decision]},
				expected_version,
			)
			return json.dumps({
				"success": True,
				"plan_id": plan_id,
				"new_version": updated.version,
				"decision_count": len(updated.decisions),
			}, indent=2)
		except OptimisticLockError as e:
			return json.dumps({"error": str(e)})

	@mcp.tool()
	async def list_plans(project: str = "", status: str = "") -> str:
		"""
		List plans, optionally filtered by project or status.

		Args:
			project: Filter by project name (empty = all)
			status: Filter by status (draft, approved, in_progress, completed)
		"""
		store = await get_plan_store()

		plan_status = None
		if status:
			try:
				plan_status = PlanStatus(status)
			except ValueError:
				return json.dumps({
					"error": f"Invalid status: {status}",
					"valid_statuses": [s.value for s in PlanStatus],
				})

		plans = await store.search_plans(
			project=project if project else None,
			status=plan_status,
		)

		return json.dumps({
			"plans": [
				{
					"id": p.id,
					"project": p.project,
					"version": p.version,
					"status": p.status.value,
					"goal": p.overview.goal,
					"progress": p.get_progress(),
					"updated_at": p.updated_at,
				}
				for p in plans
			],
			"total": len(plans),
		}, indent=2)

	@mcp.tool()
	async def get_plan_history(plan_id: str) -> str:
		"""
		Get all versions of a plan.

		Args:
			plan_id: Plan ID
		"""
		store = await get_plan_store()
		versions = await store.get_plan_history(plan_id)

		if not versions:
			return json.dumps({"error": f"Plan not found: {plan_id}"})

		return json.dumps({
			"plan_id": plan_id,
			"versions": [
				{
					"version": p.version,
					"status": p.status.value,
					"updated_at": p.updated_at,
					"progress": p.get_progress(),
				}
				for p in versions
			],
			"total_versions": len(versions),
		}, indent=2)
