"""
Tests for the Supervision phase of orchestration.

Tests:
- Supervision start/stop
- Approval request handling
- Checkpoint saving
- Failure handling and escalation
"""

import pytest
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from claude_orchestrator.orchestrator.supervisor import (
	Supervisor,
	SupervisionStatus,
	Checkpoint,
)
from claude_orchestrator.orchestrator.delegator import TaskDelegator


class TestSupervisionLifecycle:
	"""Tests for supervision start/stop."""

	@pytest.fixture
	def supervisor(self):
		return Supervisor()

	@pytest.mark.asyncio
	async def test_start_supervision_creates_state(self, supervisor):
		"""Test that starting supervision creates state."""
		state = await supervisor.start_supervision(
			task_id="task-1",
			session_id="session-1",
		)

		assert state is not None
		assert state.task_id == "task-1"
		assert state.session_id == "session-1"
		assert state.status == SupervisionStatus.MONITORING

	@pytest.mark.asyncio
	async def test_stop_supervision_updates_state(self, supervisor):
		"""Test that stopping supervision updates state."""
		await supervisor.start_supervision("task-1", "session-1")

		success = await supervisor.stop_supervision("task-1")

		assert success

		state = supervisor.get_state("task-1")
		assert state.status == SupervisionStatus.COMPLETED

	@pytest.mark.asyncio
	async def test_stop_supervision_invalid_task_returns_false(self, supervisor):
		"""Test that stopping non-existent task returns False."""
		success = await supervisor.stop_supervision("invalid-task")
		assert not success

	@pytest.mark.asyncio
	async def test_get_state_returns_correct_state(self, supervisor):
		"""Test getting supervision state."""
		await supervisor.start_supervision("task-1", "session-1")

		state = supervisor.get_state("task-1")

		assert state is not None
		assert state.task_id == "task-1"

	@pytest.mark.asyncio
	async def test_list_supervised_tasks(self, supervisor):
		"""Test listing all supervised tasks."""
		await supervisor.start_supervision("task-1", "session-1")
		await supervisor.start_supervision("task-2", "session-2")

		tasks = supervisor.list_supervised_tasks()

		assert len(tasks) == 2
		task_ids = [t["task_id"] for t in tasks]
		assert "task-1" in task_ids
		assert "task-2" in task_ids


class TestApprovalHandling:
	"""Tests for approval request handling."""

	@pytest.fixture
	def supervisor(self):
		return Supervisor()

	@pytest.mark.asyncio
	async def test_auto_approve_safe_operations(self, supervisor):
		"""Test that safe operations are auto-approved."""
		await supervisor.start_supervision("task-1", "session-1")

		# Safe operations
		safe_requests = [
			{"action": "read file"},
			{"action": "list directory"},
			{"action": "search for pattern"},
			{"action": "run tests"},
		]

		for request in safe_requests:
			approved = await supervisor.handle_approval_request("task-1", request)
			assert approved, f"Should auto-approve: {request['action']}"

	@pytest.mark.asyncio
	async def test_deny_unsafe_operations(self, supervisor):
		"""Test that unsafe operations are denied without callback."""
		await supervisor.start_supervision("task-1", "session-1")

		# Unsafe operations
		unsafe_requests = [
			{"action": "delete all files"},
			{"action": "curl external url"},
			{"action": "install package from url"},
		]

		for request in unsafe_requests:
			approved = await supervisor.handle_approval_request("task-1", request)
			assert not approved, f"Should deny: {request['action']}"

	@pytest.mark.asyncio
	async def test_approval_callback_is_called(self, supervisor):
		"""Test that approval callback is invoked."""
		callback_called = False
		callback_task_id = None
		callback_request = None

		async def approval_callback(task_id, request):
			nonlocal callback_called, callback_task_id, callback_request
			callback_called = True
			callback_task_id = task_id
			callback_request = request
			return True

		supervisor.on_approval_needed = approval_callback

		await supervisor.start_supervision("task-1", "session-1")
		await supervisor.handle_approval_request("task-1", {"action": "custom"})

		assert callback_called
		assert callback_task_id == "task-1"

	@pytest.mark.asyncio
	async def test_approval_status_changes(self, supervisor):
		"""Test that approval request changes supervision status."""
		await supervisor.start_supervision("task-1", "session-1")

		# Request should temporarily change status
		state = supervisor.get_state("task-1")
		initial_status = state.status

		await supervisor.handle_approval_request("task-1", {"action": "test"})

		# After handling, should be back to monitoring
		assert state.status == SupervisionStatus.MONITORING


class TestCheckpointSaving:
	"""Tests for checkpoint functionality."""

	@pytest.fixture
	def supervisor(self):
		return Supervisor()

	@pytest.mark.asyncio
	async def test_save_checkpoint_creates_checkpoint(self, supervisor):
		"""Test that saving checkpoint creates checkpoint object."""
		await supervisor.start_supervision("task-1", "session-1")

		checkpoint = await supervisor.save_checkpoint(
			task_id="task-1",
			state={"progress": 50},
			files_modified=["src/main.py"],
			output_summary="Halfway done",
		)

		assert checkpoint is not None
		assert checkpoint.task_id == "task-1"
		assert checkpoint.state == {"progress": 50}
		assert "src/main.py" in checkpoint.files_modified
		assert checkpoint.output_summary == "Halfway done"

	@pytest.mark.asyncio
	async def test_save_checkpoint_updates_state(self, supervisor):
		"""Test that saving checkpoint updates supervision state."""
		await supervisor.start_supervision("task-1", "session-1")

		checkpoint = await supervisor.save_checkpoint(
			task_id="task-1",
			state={"progress": 50},
		)

		state = supervisor.get_state("task-1")
		assert state.last_checkpoint == checkpoint
		assert len(state.checkpoints) == 1

	@pytest.mark.asyncio
	async def test_multiple_checkpoints_preserved(self, supervisor):
		"""Test that multiple checkpoints are preserved."""
		await supervisor.start_supervision("task-1", "session-1")

		await supervisor.save_checkpoint("task-1", {"progress": 25})
		await supervisor.save_checkpoint("task-1", {"progress": 50})
		await supervisor.save_checkpoint("task-1", {"progress": 75})

		state = supervisor.get_state("task-1")
		assert len(state.checkpoints) == 3

	@pytest.mark.asyncio
	async def test_checkpoint_callback_is_called(self, supervisor):
		"""Test that checkpoint callback is invoked."""
		callback_called = False
		callback_checkpoint = None

		async def checkpoint_callback(task_id, checkpoint):
			nonlocal callback_called, callback_checkpoint
			callback_called = True
			callback_checkpoint = checkpoint

		supervisor.on_checkpoint = checkpoint_callback

		await supervisor.start_supervision("task-1", "session-1")
		await supervisor.save_checkpoint("task-1", {"progress": 50})

		assert callback_called
		assert callback_checkpoint is not None

	@pytest.mark.asyncio
	async def test_get_last_checkpoint(self, supervisor):
		"""Test getting the last checkpoint."""
		await supervisor.start_supervision("task-1", "session-1")

		await supervisor.save_checkpoint("task-1", {"progress": 25})
		await supervisor.save_checkpoint("task-1", {"progress": 50})

		last = await supervisor.get_last_checkpoint("task-1")

		assert last is not None
		assert last.state == {"progress": 50}


class TestFailureHandling:
	"""Tests for failure handling and escalation."""

	@pytest.fixture
	def supervisor(self):
		return Supervisor()

	@pytest.mark.asyncio
	async def test_handle_failure_increments_retry(self, supervisor):
		"""Test that failure handling increments retry count."""
		await supervisor.start_supervision("task-1", "session-1")

		result = await supervisor.handle_failure("task-1", "Error occurred")

		assert result["action"] == "retry"
		assert result["retry_count"] == 1

		state = supervisor.get_state("task-1")
		assert state.retry_count == 1

	@pytest.mark.asyncio
	async def test_handle_failure_escalates_after_max_retries(self, supervisor):
		"""Test that failure escalates after max retries."""
		await supervisor.start_supervision("task-1", "session-1", max_retries=3)

		# Trigger failures up to max
		for i in range(3):
			result = await supervisor.handle_failure("task-1", f"Error {i}")

		assert result["action"] == "escalate"

		state = supervisor.get_state("task-1")
		assert state.status == SupervisionStatus.ESCALATED

	@pytest.mark.asyncio
	async def test_handle_failure_non_retryable_escalates_immediately(self, supervisor):
		"""Test that non-retryable failures escalate immediately."""
		await supervisor.start_supervision("task-1", "session-1")

		result = await supervisor.handle_failure(
			"task-1",
			"Critical error",
			can_retry=False,
		)

		assert result["action"] == "escalate"

	@pytest.mark.asyncio
	async def test_escalation_callback_is_called(self, supervisor):
		"""Test that escalation callback is invoked."""
		callback_called = False
		callback_reason = None

		async def escalate_callback(task_id, reason, context):
			nonlocal callback_called, callback_reason
			callback_called = True
			callback_reason = reason

		supervisor.on_escalate = escalate_callback

		await supervisor.start_supervision("task-1", "session-1", max_retries=1)

		await supervisor.handle_failure("task-1", "Critical error")

		assert callback_called
		assert callback_reason == "Critical error"

	@pytest.mark.asyncio
	async def test_escalation_preserves_reason(self, supervisor):
		"""Test that escalation preserves the error reason."""
		await supervisor.start_supervision("task-1", "session-1", max_retries=1)

		await supervisor.handle_failure("task-1", "Specific error message")

		state = supervisor.get_state("task-1")
		assert state.escalation_reason == "Specific error message"


class TestSupervisionWithDelegator:
	"""Tests for supervision integrated with delegator."""

	@pytest.mark.asyncio
	async def test_supervisor_uses_delegator(self):
		"""Test that supervisor can access delegator state."""
		delegator = TaskDelegator()
		supervisor = Supervisor(delegator=delegator)

		# The supervisor should be able to access delegator
		assert supervisor.delegator is delegator
