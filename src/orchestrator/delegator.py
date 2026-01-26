"""
Task Delegator - Breaks down tasks and delegates to subagents.

Responsibilities:
- Task breakdown into subagent-sized chunks
- Context assembly and budgeting
- Subagent spawning with appropriate permissions
- Resource locking during delegation
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from ..plans.models import Plan, Phase, Task, TaskStatus
from ..plans.store import get_plan_store
from .context_builder import ContextBuilder, SubagentContext

logger = logging.getLogger(__name__)


class DelegationStatus(str, Enum):
	"""Status of a delegated task."""
	PENDING = "pending"
	DELEGATED = "delegated"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	FAILED = "failed"
	BLOCKED = "blocked"


@dataclass
class DelegatedTask:
	"""A task that has been delegated to a subagent."""
	id: str
	task: Task
	plan_id: str
	phase_id: str
	context: SubagentContext
	status: DelegationStatus
	session_id: Optional[str] = None
	result: Optional[dict] = None
	error: Optional[str] = None
	delegated_at: str = ""
	completed_at: Optional[str] = None


@dataclass
class DelegationResult:
	"""Result of a delegation attempt."""
	success: bool
	delegated_task: Optional[DelegatedTask] = None
	error: Optional[str] = None


class TaskDelegator:
	"""
	Delegates tasks to subagents with proper context.

	Handles:
	- Building context for each task
	- Spawning subagent sessions
	- Tracking delegated tasks
	- Resource locking
	"""

	def __init__(self, context_builder: Optional[ContextBuilder] = None):
		"""Initialize the delegator."""
		self.context_builder = context_builder or ContextBuilder()
		self._delegated_tasks: dict[str, DelegatedTask] = {}
		self._resource_locks: dict[str, str] = {}  # resource -> task_id
		self._lock = asyncio.Lock()

	async def delegate_task(
		self,
		task: Task,
		plan: Plan,
		phase: Phase,
		docs: list[dict] = None,
		history: list[dict] = None,
	) -> DelegationResult:
		"""
		Delegate a task to a subagent.

		Args:
			task: Task to delegate
			plan: Parent plan
			phase: Parent phase
			docs: Relevant documentation
			history: Prior work history

		Returns:
			DelegationResult with delegation status
		"""
		async with self._lock:
			# Check if task is already delegated
			if task.id in self._delegated_tasks:
				existing = self._delegated_tasks[task.id]
				if existing.status in [DelegationStatus.DELEGATED, DelegationStatus.IN_PROGRESS]:
					return DelegationResult(
						success=False,
						error=f"Task {task.id} already delegated",
					)

			# Check for resource conflicts
			if task.files:
				for file in task.files:
					if file in self._resource_locks:
						blocking_task = self._resource_locks[file]
						return DelegationResult(
							success=False,
							error=f"File {file} locked by task {blocking_task}",
						)

			# Build context
			context = self.context_builder.build_context(
				task=task,
				plan=plan,
				history=history,
				docs=docs,
			)

			# Lock resources
			for file in task.files:
				self._resource_locks[file] = task.id

			# Create delegated task record
			delegated = DelegatedTask(
				id=f"delegation-{task.id}-{datetime.now().strftime('%H%M%S')}",
				task=task,
				plan_id=plan.id,
				phase_id=phase.id,
				context=context,
				status=DelegationStatus.DELEGATED,
				delegated_at=datetime.now().isoformat(),
			)

			self._delegated_tasks[task.id] = delegated

			logger.info(f"Delegated task {task.id}: {task.description[:50]}...")

			return DelegationResult(
				success=True,
				delegated_task=delegated,
			)

	async def get_delegation_prompt(self, task_id: str) -> Optional[str]:
		"""
		Get the prompt to send to a subagent for a delegated task.

		Args:
			task_id: Task ID

		Returns:
			Prompt string or None if not found
		"""
		delegated = self._delegated_tasks.get(task_id)
		if not delegated:
			return None

		return delegated.context.to_prompt()

	async def mark_in_progress(self, task_id: str, session_id: str) -> bool:
		"""Mark a delegated task as in progress."""
		async with self._lock:
			if task_id not in self._delegated_tasks:
				return False

			delegated = self._delegated_tasks[task_id]
			delegated.status = DelegationStatus.IN_PROGRESS
			delegated.session_id = session_id

			return True

	async def mark_completed(
		self,
		task_id: str,
		result: dict,
		success: bool = True,
	) -> bool:
		"""
		Mark a delegated task as completed.

		Args:
			task_id: Task ID
			result: Result from subagent
			success: Whether task succeeded

		Returns:
			True if marked successfully
		"""
		async with self._lock:
			if task_id not in self._delegated_tasks:
				return False

			delegated = self._delegated_tasks[task_id]
			delegated.status = DelegationStatus.COMPLETED if success else DelegationStatus.FAILED
			delegated.result = result
			delegated.completed_at = datetime.now().isoformat()

			# Release resource locks
			for file in delegated.task.files:
				if file in self._resource_locks and self._resource_locks[file] == task_id:
					del self._resource_locks[file]

			# Update plan store
			try:
				store = await get_plan_store()
				plan = await store.get_plan(delegated.plan_id)
				if plan:
					await store.update_task_status(
						delegated.plan_id,
						delegated.phase_id,
						task_id,
						TaskStatus.COMPLETED if success else TaskStatus.BLOCKED,
						plan.version,
					)
			except Exception as e:
				logger.error(f"Failed to update plan: {e}")

			logger.info(f"Task {task_id} marked {'completed' if success else 'failed'}")

			return True

	async def mark_failed(self, task_id: str, error: str) -> bool:
		"""Mark a delegated task as failed."""
		async with self._lock:
			if task_id not in self._delegated_tasks:
				return False

			delegated = self._delegated_tasks[task_id]
			delegated.status = DelegationStatus.FAILED
			delegated.error = error
			delegated.completed_at = datetime.now().isoformat()

			# Release resource locks
			for file in delegated.task.files:
				if file in self._resource_locks and self._resource_locks[file] == task_id:
					del self._resource_locks[file]

			logger.warning(f"Task {task_id} failed: {error}")

			return True

	def get_delegated_task(self, task_id: str) -> Optional[DelegatedTask]:
		"""Get a delegated task by ID."""
		return self._delegated_tasks.get(task_id)

	def list_delegated_tasks(
		self,
		status: Optional[DelegationStatus] = None,
	) -> list[DelegatedTask]:
		"""List delegated tasks, optionally filtered by status."""
		tasks = list(self._delegated_tasks.values())
		if status:
			tasks = [t for t in tasks if t.status == status]
		return tasks

	def get_locked_resources(self) -> dict[str, str]:
		"""Get currently locked resources."""
		return self._resource_locks.copy()

	async def delegate_phase(
		self,
		phase: Phase,
		plan: Plan,
		docs: list[dict] = None,
		sequential: bool = True,
	) -> list[DelegationResult]:
		"""
		Delegate all tasks in a phase.

		Args:
			phase: Phase to delegate
			plan: Parent plan
			docs: Relevant documentation
			sequential: If True, delegate one at a time

		Returns:
			List of DelegationResults
		"""
		results = []

		for task in phase.tasks:
			if task.status in [TaskStatus.COMPLETED, TaskStatus.SKIPPED]:
				continue

			result = await self.delegate_task(
				task=task,
				plan=plan,
				phase=phase,
				docs=docs,
			)
			results.append(result)

			if sequential and result.success:
				# Wait for completion before next task
				# In practice, this would wait for the supervisor
				pass

		return results
