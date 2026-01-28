"""
Plan Store - SQLite-backed versioned plan storage.

Features:
- CRUD operations for plans
- Version history tracking
- Optimistic locking for concurrent updates
- Search by project/status/tags
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from .models import Plan, PlanStatus, TaskStatus

logger = logging.getLogger(__name__)


class OptimisticLockError(Exception):
	"""Raised when a concurrent update conflicts."""
	pass


class PlanNotFoundError(Exception):
	"""Raised when a plan is not found."""
	pass


class PlanStore:
	"""
	SQLite-backed plan storage with versioning.

	Usage:
		store = PlanStore("data/plans.db")
		await store.init()

		# Create a plan
		plan_id = await store.create_plan("my-project", plan)

		# Update with optimistic locking
		updated = await store.update_plan(plan_id, updates, expected_version=1)

		# Get current plan for a project
		plan = await store.get_current_plan("my-project")
	"""

	def __init__(self, db_path: str):
		"""Initialize the plan store."""
		self.db_path = Path(db_path)
		self.db_path.parent.mkdir(parents=True, exist_ok=True)
		self._db: Optional[aiosqlite.Connection] = None

	async def init(self):
		"""Initialize the database schema."""
		self._db = await aiosqlite.connect(str(self.db_path))
		self._db.row_factory = aiosqlite.Row

		await self._db.execute("""
			CREATE TABLE IF NOT EXISTS plans (
				id TEXT PRIMARY KEY,
				project TEXT NOT NULL,
				version INTEGER NOT NULL,
				status TEXT NOT NULL,
				data TEXT NOT NULL,
				created_at TEXT NOT NULL,
				updated_at TEXT NOT NULL,
				is_current INTEGER DEFAULT 1,
				UNIQUE(project, version)
			)
		""")

		await self._db.execute("""
			CREATE INDEX IF NOT EXISTS idx_plans_project ON plans(project)
		""")

		await self._db.execute("""
			CREATE INDEX IF NOT EXISTS idx_plans_project_current ON plans(project, is_current)
		""")

		await self._db.commit()
		logger.info(f"Plan store initialized: {self.db_path}")

	async def close(self):
		"""Close the database connection."""
		if self._db:
			await self._db.close()
			self._db = None

	async def create_plan(self, project: str, plan: Plan) -> str:
		"""
		Create a new plan.

		Args:
			project: Project name
			plan: Plan object to create

		Returns:
			Plan ID
		"""
		if not self._db:
			await self.init()

		plan_id = plan.id or str(uuid.uuid4())[:12]
		plan.id = plan_id
		plan.project = project
		plan.version = 1
		plan.created_at = datetime.now().isoformat()
		plan.updated_at = plan.created_at

		# Mark any existing current plans as not current
		await self._db.execute(
			"UPDATE plans SET is_current = 0 WHERE project = ?",
			(project,)
		)

		await self._db.execute(
			"""
			INSERT INTO plans (id, project, version, status, data, created_at, updated_at, is_current)
			VALUES (?, ?, ?, ?, ?, ?, ?, 1)
			""",
			(
				plan_id,
				project,
				plan.version,
				plan.status.value,
				plan.model_dump_json(),
				plan.created_at,
				plan.updated_at,
			)
		)

		await self._db.commit()
		logger.info(f"Created plan {plan_id} for project {project}")

		return plan_id

	async def update_plan(
		self,
		plan_id: str,
		updates: dict,
		expected_version: int,
	) -> Plan:
		"""
		Update a plan with optimistic locking.

		Creates a new version instead of modifying the existing one.

		Args:
			plan_id: Plan ID to update
			updates: Dictionary of fields to update
			expected_version: Expected current version (for optimistic locking)

		Returns:
			Updated Plan object

		Raises:
			OptimisticLockError: If version doesn't match
			PlanNotFoundError: If plan not found
		"""
		if not self._db:
			await self.init()

		# Get current plan
		async with self._db.execute(
			"SELECT * FROM plans WHERE id = ? AND is_current = 1",
			(plan_id,)
		) as cursor:
			row = await cursor.fetchone()

		if not row:
			raise PlanNotFoundError(f"Plan not found: {plan_id}")

		current_version = row["version"]
		if current_version != expected_version:
			raise OptimisticLockError(
				f"Version mismatch: expected {expected_version}, got {current_version}"
			)

		# Load current plan and apply updates
		plan = Plan.model_validate_json(row["data"])

		for key, value in updates.items():
			if hasattr(plan, key):
				setattr(plan, key, value)

		# Increment version
		plan.parent_version = plan.version
		plan.version = current_version + 1
		plan.updated_at = datetime.now().isoformat()

		# Mark old version as not current
		await self._db.execute(
			"UPDATE plans SET is_current = 0 WHERE id = ? AND version = ?",
			(plan_id, current_version)
		)

		# Insert new version
		await self._db.execute(
			"""
			INSERT INTO plans (id, project, version, status, data, created_at, updated_at, is_current)
			VALUES (?, ?, ?, ?, ?, ?, ?, 1)
			""",
			(
				plan_id,
				plan.project,
				plan.version,
				plan.status.value,
				plan.model_dump_json(),
				plan.created_at,
				plan.updated_at,
			)
		)

		await self._db.commit()
		logger.info(f"Updated plan {plan_id} to version {plan.version}")

		return plan

	async def get_plan(self, plan_id: str, version: Optional[int] = None) -> Optional[Plan]:
		"""
		Get a plan by ID, optionally at a specific version.

		Args:
			plan_id: Plan ID
			version: Optional version number (defaults to current)

		Returns:
			Plan object or None if not found
		"""
		if not self._db:
			await self.init()

		if version:
			query = "SELECT * FROM plans WHERE id = ? AND version = ?"
			params = (plan_id, version)
		else:
			query = "SELECT * FROM plans WHERE id = ? AND is_current = 1"
			params = (plan_id,)

		async with self._db.execute(query, params) as cursor:
			row = await cursor.fetchone()

		if not row:
			return None

		return Plan.model_validate_json(row["data"])

	async def get_current_plan(self, project: str) -> Optional[Plan]:
		"""
		Get the current plan for a project.

		Args:
			project: Project name

		Returns:
			Current Plan or None
		"""
		if not self._db:
			await self.init()

		async with self._db.execute(
			"SELECT * FROM plans WHERE project = ? AND is_current = 1",
			(project,)
		) as cursor:
			row = await cursor.fetchone()

		if not row:
			return None

		return Plan.model_validate_json(row["data"])

	async def get_plan_history(self, plan_id: str) -> list[Plan]:
		"""
		Get all versions of a plan.

		Args:
			plan_id: Plan ID

		Returns:
			List of Plan objects, newest first
		"""
		if not self._db:
			await self.init()

		async with self._db.execute(
			"SELECT * FROM plans WHERE id = ? ORDER BY version DESC",
			(plan_id,)
		) as cursor:
			rows = await cursor.fetchall()

		return [Plan.model_validate_json(row["data"]) for row in rows]

	async def search_plans(
		self,
		project: Optional[str] = None,
		status: Optional[PlanStatus] = None,
		current_only: bool = True,
	) -> list[Plan]:
		"""
		Search for plans.

		Args:
			project: Filter by project name
			status: Filter by status
			current_only: Only return current versions

		Returns:
			List of matching Plan objects
		"""
		if not self._db:
			await self.init()

		conditions = []
		params = []

		if project:
			conditions.append("project = ?")
			params.append(project)

		if status:
			conditions.append("status = ?")
			params.append(status.value)

		if current_only:
			conditions.append("is_current = 1")

		where_clause = " AND ".join(conditions) if conditions else "1=1"

		async with self._db.execute(
			f"SELECT * FROM plans WHERE {where_clause} ORDER BY updated_at DESC",
			params
		) as cursor:
			rows = await cursor.fetchall()

		return [Plan.model_validate_json(row["data"]) for row in rows]

	async def update_task_status(
		self,
		plan_id: str,
		phase_id: str,
		task_id: str,
		status: TaskStatus,
		expected_version: int,
	) -> Plan:
		"""
		Update a task's status within a plan.

		Args:
			plan_id: Plan ID
			phase_id: Phase ID containing the task
			task_id: Task ID to update
			status: New task status
			expected_version: Expected plan version

		Returns:
			Updated Plan
		"""
		plan = await self.get_plan(plan_id)
		if not plan:
			raise PlanNotFoundError(f"Plan not found: {plan_id}")

		# Find and update the task
		updated = False
		for phase in plan.phases:
			if phase.id == phase_id:
				for task in phase.tasks:
					if task.id == task_id:
						task.status = status
						if status == TaskStatus.COMPLETED:
							task.completed_at = datetime.now().isoformat()
						updated = True
						break
				break

		if not updated:
			raise ValueError(f"Task {task_id} not found in phase {phase_id}")

		# Auto-update phase status based on tasks
		for phase in plan.phases:
			task_statuses = [t.status for t in phase.tasks]
			if all(s == TaskStatus.COMPLETED for s in task_statuses):
				phase.status = TaskStatus.COMPLETED
				phase.completed_at = datetime.now().isoformat()
			elif any(s == TaskStatus.IN_PROGRESS for s in task_statuses):
				phase.status = TaskStatus.IN_PROGRESS
				if not phase.started_at:
					phase.started_at = datetime.now().isoformat()

		return await self.update_plan(
			plan_id,
			{"phases": [p.model_dump() for p in plan.phases]},
			expected_version,
		)

	async def delete_plan(self, plan_id: str):
		"""
		Delete a plan and all its versions.

		Args:
			plan_id: Plan ID to delete
		"""
		if not self._db:
			await self.init()

		await self._db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
		await self._db.commit()
		logger.info(f"Deleted plan {plan_id}")

	async def list_projects(self) -> list[dict]:
		"""
		List all projects with plans.

		Returns:
			List of project info dictionaries
		"""
		if not self._db:
			await self.init()

		async with self._db.execute(
			"""
			SELECT
				project,
				COUNT(DISTINCT id) as plan_count,
				MAX(updated_at) as last_updated
			FROM plans
			WHERE is_current = 1
			GROUP BY project
			ORDER BY last_updated DESC
			"""
		) as cursor:
			rows = await cursor.fetchall()

		return [
			{
				"project": row["project"],
				"plan_count": row["plan_count"],
				"last_updated": row["last_updated"],
			}
			for row in rows
		]


# Global store instance
_store: Optional[PlanStore] = None


async def get_plan_store(db_path: str = "") -> PlanStore:
	"""Get or create the global plan store."""
	global _store
	if _store is None:
		if not db_path:
			from ..config import get_config
			db_path = str(get_config().plans_db_path)
		_store = PlanStore(db_path)
		await _store.init()
	return _store
