"""
Supervisor - Monitors subagent progress and handles checkpoints.

Responsibilities:
- Monitor subagent session status
- Handle permission requests
- Save checkpoints for recovery
- Escalate on failures after N retries
- Time-based checkpoints (every 2 hours)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable, Awaitable

from ..hooks import HooksConfig, generate_hooks_for_task
from .delegator import TaskDelegator, DelegatedTask, DelegationStatus

logger = logging.getLogger(__name__)


class SupervisionStatus(str, Enum):
	"""Current supervision status."""
	IDLE = "idle"
	MONITORING = "monitoring"
	AWAITING_APPROVAL = "awaiting_approval"
	ESCALATED = "escalated"
	COMPLETED = "completed"


@dataclass
class Checkpoint:
	"""A checkpoint of task progress."""
	task_id: str
	timestamp: str
	state: dict
	files_modified: list[str] = field(default_factory=list)
	output_summary: str = ""


@dataclass
class SupervisionState:
	"""State of supervision for a task."""
	task_id: str
	status: SupervisionStatus
	session_id: Optional[str]
	started_at: str
	last_checkpoint: Optional[Checkpoint] = None
	retry_count: int = 0
	max_retries: int = 5
	checkpoints: list[Checkpoint] = field(default_factory=list)
	approval_pending: Optional[dict] = None
	escalation_reason: Optional[str] = None


class Supervisor:
	"""
	Supervises subagent task execution.

	Monitors progress, handles approvals, saves checkpoints,
	and escalates when tasks fail repeatedly.
	"""

	CHECKPOINT_INTERVAL = 7200  # 2 hours in seconds
	DEFAULT_MAX_RETRIES = 5

	def __init__(
		self,
		delegator: Optional[TaskDelegator] = None,
		on_approval_needed: Optional[Callable[[str, dict], Awaitable[bool]]] = None,
		on_escalate: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
		on_checkpoint: Optional[Callable[[str, Checkpoint], Awaitable[None]]] = None,
	):
		"""
		Initialize the supervisor.

		Args:
			delegator: Task delegator instance
			on_approval_needed: Callback(task_id, request) -> approved
			on_escalate: Callback(task_id, reason, context)
			on_checkpoint: Callback(task_id, checkpoint)
		"""
		self.delegator = delegator or TaskDelegator()
		self.on_approval_needed = on_approval_needed
		self.on_escalate = on_escalate
		self.on_checkpoint = on_checkpoint

		self._states: dict[str, SupervisionState] = {}
		self._monitoring_tasks: dict[str, asyncio.Task] = {}
		self._lock = asyncio.Lock()

	async def start_supervision(
		self,
		task_id: str,
		session_id: str,
		max_retries: int = DEFAULT_MAX_RETRIES,
	) -> SupervisionState:
		"""
		Start supervising a task.

		Args:
			task_id: Task being supervised
			session_id: Subagent session ID
			max_retries: Max retry attempts before escalation

		Returns:
			SupervisionState
		"""
		async with self._lock:
			state = SupervisionState(
				task_id=task_id,
				status=SupervisionStatus.MONITORING,
				session_id=session_id,
				started_at=datetime.now().isoformat(),
				max_retries=max_retries,
			)
			self._states[task_id] = state

			# Start monitoring loop
			monitor_task = asyncio.create_task(
				self._monitor_task(task_id)
			)
			self._monitoring_tasks[task_id] = monitor_task

			logger.info(f"Started supervision for task {task_id}")

			return state

	async def stop_supervision(self, task_id: str) -> bool:
		"""Stop supervising a task."""
		async with self._lock:
			if task_id in self._monitoring_tasks:
				self._monitoring_tasks[task_id].cancel()
				try:
					await self._monitoring_tasks[task_id]
				except asyncio.CancelledError:
					pass
				del self._monitoring_tasks[task_id]

			if task_id in self._states:
				self._states[task_id].status = SupervisionStatus.COMPLETED
				return True

			return False

	async def handle_approval_request(
		self,
		task_id: str,
		request: dict,
	) -> bool:
		"""
		Handle an approval request from a subagent.

		Args:
			task_id: Task ID
			request: Approval request details

		Returns:
			True if approved, False if denied
		"""
		state = self._states.get(task_id)
		if not state:
			logger.warning(f"Approval request for unknown task: {task_id}")
			return False

		state.status = SupervisionStatus.AWAITING_APPROVAL
		state.approval_pending = request

		# Call approval callback if set
		if self.on_approval_needed:
			try:
				approved = await self.on_approval_needed(task_id, request)
				state.approval_pending = None
				state.status = SupervisionStatus.MONITORING
				return approved
			except Exception as e:
				logger.error(f"Approval callback failed: {e}")
				state.approval_pending = None
				state.status = SupervisionStatus.MONITORING
				return False

		# Default: auto-approve safe operations
		return self._is_safe_operation(request)

	def _is_safe_operation(self, request: dict) -> bool:
		"""Check if an operation is safe to auto-approve."""
		action = request.get("action", "").lower()

		# Safe operations
		safe_patterns = [
			"read",
			"list",
			"search",
			"grep",
			"glob",
			"test",
			"lint",
			"type check",
		]

		for pattern in safe_patterns:
			if pattern in action:
				return True

		# Unsafe operations that need manual approval
		unsafe_patterns = [
			"delete",
			"remove",
			"drop",
			"curl",
			"wget",
			"fetch",
			"install",
			"execute",
			"run script",
		]

		for pattern in unsafe_patterns:
			if pattern in action:
				return False

		# Default: approve edit/write operations in project files
		return True

	async def save_checkpoint(
		self,
		task_id: str,
		state: dict,
		files_modified: list[str] = None,
		output_summary: str = "",
	) -> Checkpoint:
		"""
		Save a checkpoint for a task.

		Args:
			task_id: Task ID
			state: Current task state
			files_modified: Files modified so far
			output_summary: Summary of output

		Returns:
			Checkpoint object
		"""
		checkpoint = Checkpoint(
			task_id=task_id,
			timestamp=datetime.now().isoformat(),
			state=state,
			files_modified=files_modified or [],
			output_summary=output_summary,
		)

		supervision_state = self._states.get(task_id)
		if supervision_state:
			supervision_state.last_checkpoint = checkpoint
			supervision_state.checkpoints.append(checkpoint)

		# Notify checkpoint callback
		if self.on_checkpoint:
			try:
				await self.on_checkpoint(task_id, checkpoint)
			except Exception as e:
				logger.error(f"Checkpoint callback failed: {e}")

		logger.debug(f"Saved checkpoint for task {task_id}")

		return checkpoint

	async def handle_failure(
		self,
		task_id: str,
		error: str,
		can_retry: bool = True,
	) -> dict:
		"""
		Handle a task failure.

		Args:
			task_id: Task ID
			error: Error message
			can_retry: Whether this failure is retryable

		Returns:
			Dict with action to take (retry, escalate, etc.)
		"""
		state = self._states.get(task_id)
		if not state:
			return {"action": "abort", "reason": "Unknown task"}

		state.retry_count += 1

		if not can_retry or state.retry_count >= state.max_retries:
			# Escalate
			state.status = SupervisionStatus.ESCALATED
			state.escalation_reason = error

			if self.on_escalate:
				try:
					context = self._build_escalation_context(state)
					await self.on_escalate(task_id, error, context)
				except Exception as e:
					logger.error(f"Escalation callback failed: {e}")

			logger.warning(
				f"Task {task_id} escalated after {state.retry_count} retries: {error}"
			)

			return {
				"action": "escalate",
				"reason": error,
				"retry_count": state.retry_count,
			}

		# Retry
		logger.info(
			f"Task {task_id} retry {state.retry_count}/{state.max_retries}: {error}"
		)

		return {
			"action": "retry",
			"retry_count": state.retry_count,
			"max_retries": state.max_retries,
		}

	def _build_escalation_context(self, state: SupervisionState) -> str:
		"""Build context string for escalation."""
		lines = [
			f"Task ID: {state.task_id}",
			f"Session ID: {state.session_id}",
			f"Started: {state.started_at}",
			f"Retry count: {state.retry_count}",
			f"Reason: {state.escalation_reason}",
		]

		if state.last_checkpoint:
			lines.append(f"Last checkpoint: {state.last_checkpoint.timestamp}")
			lines.append(f"Files modified: {', '.join(state.last_checkpoint.files_modified)}")
			if state.last_checkpoint.output_summary:
				lines.append(f"Output summary: {state.last_checkpoint.output_summary}")

		return "\n".join(lines)

	async def _monitor_task(self, task_id: str):
		"""Background task to monitor progress and save periodic checkpoints."""
		state = self._states.get(task_id)
		if not state:
			return

		last_checkpoint_time = datetime.now()

		while state.status == SupervisionStatus.MONITORING:
			try:
				await asyncio.sleep(60)  # Check every minute

				# Check if time for periodic checkpoint
				elapsed = (datetime.now() - last_checkpoint_time).total_seconds()
				if elapsed >= self.CHECKPOINT_INTERVAL:
					# Get current state from delegator
					delegated = self.delegator.get_delegated_task(task_id)
					if delegated:
						await self.save_checkpoint(
							task_id,
							{"status": delegated.status.value},
							output_summary="Periodic checkpoint",
						)
					last_checkpoint_time = datetime.now()

			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Monitor error for task {task_id}: {e}")

	def get_state(self, task_id: str) -> Optional[SupervisionState]:
		"""Get supervision state for a task."""
		return self._states.get(task_id)

	def list_supervised_tasks(self) -> list[dict]:
		"""List all supervised tasks with their status."""
		return [
			{
				"task_id": state.task_id,
				"status": state.status.value,
				"session_id": state.session_id,
				"started_at": state.started_at,
				"retry_count": state.retry_count,
				"has_checkpoint": state.last_checkpoint is not None,
			}
			for state in self._states.values()
		]

	async def get_last_checkpoint(self, task_id: str) -> Optional[Checkpoint]:
		"""Get the last checkpoint for a task."""
		state = self._states.get(task_id)
		if state:
			return state.last_checkpoint
		return None

	def select_hooks_profile(self, task_description: str) -> HooksConfig:
		"""Select the appropriate hooks profile for a task description."""
		return generate_hooks_for_task(task_description)
