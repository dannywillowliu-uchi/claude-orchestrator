"""
Tests for the Delegation phase of orchestration.

Tests:
- Context building and budgeting
- Task delegation
- Resource locking
- Delegation prompt generation
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from claude_orchestrator.orchestrator.context_builder import ContextBuilder, SubagentContext
from claude_orchestrator.orchestrator.delegator import (
	TaskDelegator,
	DelegationStatus,
	DelegatedTask,
)
from claude_orchestrator.plans.models import (
	Plan,
	Phase,
	Task,
	PlanOverview,
	PlanStatus,
	TaskStatus,
)


@pytest.fixture
def sample_task():
	"""Create a sample task for testing."""
	return Task(
		id="task-1",
		description="Implement core functionality",
		files=["src/core.py", "src/utils.py"],
		verification=["pytest", "ruff"],
	)


@pytest.fixture
def sample_plan():
	"""Create a sample plan for testing."""
	return Plan(
		id="plan-1",
		project="test-project",
		status=PlanStatus.APPROVED,
		overview=PlanOverview(
			goal="Test goal",
			success_criteria=["Tests pass"],
			constraints=["Python only"],
		),
		phases=[
			Phase(
				id="phase-1",
				name="Implementation",
				description="Implement features",
				tasks=[
					Task(id="task-1", description="Task 1", files=["src/a.py"]),
					Task(id="task-2", description="Task 2", files=["src/b.py"]),
				],
			),
		],
	)


@pytest.fixture
def sample_phase(sample_plan):
	"""Get the first phase from sample plan."""
	return sample_plan.phases[0]


class TestContextBuilder:
	"""Tests for ContextBuilder."""

	def test_build_context_creates_valid_context(self, sample_task, sample_plan):
		"""Test that build_context creates a valid SubagentContext."""
		builder = ContextBuilder()

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
		)

		assert context is not None
		assert isinstance(context, SubagentContext)
		assert context.task["id"] == "task-1"
		assert context.task["description"] == "Implement core functionality"

	def test_build_context_includes_constraints(self, sample_task, sample_plan):
		"""Test that context includes plan constraints."""
		builder = ContextBuilder()

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
		)

		assert "Python only" in context.constraints

	def test_build_context_includes_verification(self, sample_task, sample_plan):
		"""Test that context includes verification requirements."""
		builder = ContextBuilder()

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
		)

		assert "pytest" in context.verification_required
		assert "ruff" in context.verification_required

	def test_build_context_estimates_tokens(self, sample_task, sample_plan):
		"""Test that context estimates token count."""
		builder = ContextBuilder()

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
		)

		assert context.estimated_tokens > 0

	def test_context_to_prompt(self, sample_task, sample_plan):
		"""Test that context can be converted to a prompt string."""
		builder = ContextBuilder()

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
		)

		prompt = context.to_prompt()

		assert "# Task Assignment" in prompt
		assert "Implement core functionality" in prompt
		assert "src/core.py" in prompt

	def test_build_context_with_docs(self, sample_task, sample_plan):
		"""Test building context with documentation."""
		builder = ContextBuilder()

		docs = [
			{"title": "Core API", "content": "The core API handles..."},
			{"title": "Utils", "content": "Utility functions for..."},
		]

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
			docs=docs,
		)

		# Should have filtered relevant docs
		assert len(context.relevant_docs) <= len(docs)

	def test_build_context_with_history(self, sample_task, sample_plan):
		"""Test building context with prior work history."""
		builder = ContextBuilder()

		history = [
			{"type": "task_completed", "task": "Set up project"},
			{"type": "file_modified", "file": "setup.py"},
		]

		context = builder.build_context(
			task=sample_task,
			plan=sample_plan,
			history=history,
		)

		assert context.prior_work_summary != ""

	def test_context_budget_enforcement(self):
		"""Test that context respects token budget."""
		builder = ContextBuilder(max_tokens=1000)  # Small budget

		task = Task(
			id="task-1",
			description="Test task",
			files=["test.py"],
		)

		plan = Plan(
			id="plan-1",
			project="test",
			status=PlanStatus.APPROVED,
			overview=PlanOverview(goal="Test"),
			phases=[],
		)

		# Large docs that would exceed budget
		docs = [
			{"title": f"Doc {i}", "content": "x" * 10000}
			for i in range(10)
		]

		context = builder.build_context(
			task=task,
			plan=plan,
			docs=docs,
		)

		# Should have truncated to fit budget
		assert context.estimated_tokens <= builder.max_tokens


class TestTaskDelegator:
	"""Tests for TaskDelegator."""

	@pytest.mark.asyncio
	async def test_delegate_task_success(self, sample_task, sample_plan, sample_phase):
		"""Test successful task delegation."""
		delegator = TaskDelegator()

		result = await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		assert result.success
		assert result.delegated_task is not None
		assert result.delegated_task.status == DelegationStatus.DELEGATED

	@pytest.mark.asyncio
	async def test_delegate_task_locks_resources(self, sample_task, sample_plan, sample_phase):
		"""Test that delegation locks task files."""
		delegator = TaskDelegator()

		await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		locked = delegator.get_locked_resources()

		for file in sample_task.files:
			assert file in locked

	@pytest.mark.asyncio
	async def test_delegate_task_detects_conflict(self, sample_plan, sample_phase):
		"""Test that delegation detects resource conflicts."""
		delegator = TaskDelegator()

		task1 = Task(id="task-1", description="Task 1", files=["shared.py"])
		task2 = Task(id="task-2", description="Task 2", files=["shared.py"])

		# Delegate first task
		result1 = await delegator.delegate_task(
			task=task1,
			plan=sample_plan,
			phase=sample_phase,
		)
		assert result1.success

		# Second task should fail due to conflict
		result2 = await delegator.delegate_task(
			task=task2,
			plan=sample_plan,
			phase=sample_phase,
		)

		assert not result2.success
		assert "locked" in result2.error.lower()

	@pytest.mark.asyncio
	async def test_delegate_task_prevents_double_delegation(self, sample_task, sample_plan, sample_phase):
		"""Test that same task cannot be delegated twice."""
		delegator = TaskDelegator()

		result1 = await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)
		assert result1.success

		result2 = await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		assert not result2.success
		assert "already delegated" in result2.error.lower()

	@pytest.mark.asyncio
	async def test_get_delegation_prompt(self, sample_task, sample_plan, sample_phase):
		"""Test getting the delegation prompt."""
		delegator = TaskDelegator()

		await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		prompt = await delegator.get_delegation_prompt(sample_task.id)

		assert prompt is not None
		assert "Task Assignment" in prompt

	@pytest.mark.asyncio
	async def test_mark_in_progress(self, sample_task, sample_plan, sample_phase):
		"""Test marking task as in progress."""
		delegator = TaskDelegator()

		await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		success = await delegator.mark_in_progress(sample_task.id, "session-123")

		assert success

		delegated = delegator.get_delegated_task(sample_task.id)
		assert delegated.status == DelegationStatus.IN_PROGRESS
		assert delegated.session_id == "session-123"

	@pytest.mark.asyncio
	async def test_mark_completed_releases_locks(self, sample_task, sample_plan, sample_phase):
		"""Test that completing a task releases resource locks."""
		delegator = TaskDelegator()

		await delegator.delegate_task(
			task=sample_task,
			plan=sample_plan,
			phase=sample_phase,
		)

		# Locks should be held
		assert len(delegator.get_locked_resources()) > 0

		await delegator.mark_completed(sample_task.id, {"output": "Done"})

		# Locks should be released
		for file in sample_task.files:
			assert file not in delegator.get_locked_resources()

	@pytest.mark.asyncio
	async def test_list_delegated_tasks(self, sample_plan, sample_phase):
		"""Test listing delegated tasks."""
		delegator = TaskDelegator()

		task1 = Task(id="task-1", description="Task 1", files=["a.py"])
		task2 = Task(id="task-2", description="Task 2", files=["b.py"])

		await delegator.delegate_task(task1, sample_plan, sample_phase)
		await delegator.delegate_task(task2, sample_plan, sample_phase)

		all_tasks = delegator.list_delegated_tasks()
		assert len(all_tasks) == 2

		# Filter by status
		delegated_tasks = delegator.list_delegated_tasks(status=DelegationStatus.DELEGATED)
		assert len(delegated_tasks) == 2


class TestDelegatePhase:
	"""Tests for phase delegation."""

	@pytest.mark.asyncio
	async def test_delegate_phase_delegates_all_tasks(self, sample_plan, sample_phase):
		"""Test that delegate_phase delegates all tasks in a phase."""
		delegator = TaskDelegator()

		results = await delegator.delegate_phase(
			phase=sample_phase,
			plan=sample_plan,
		)

		assert len(results) == len(sample_phase.tasks)
		assert all(r.success for r in results)

	@pytest.mark.asyncio
	async def test_delegate_phase_skips_completed_tasks(self, sample_plan):
		"""Test that delegate_phase skips completed tasks."""
		# Create phase with one completed task
		phase = Phase(
			id="phase-1",
			name="Test",
			description="Test",
			tasks=[
				Task(id="task-1", description="Task 1", status=TaskStatus.COMPLETED),
				Task(id="task-2", description="Task 2", status=TaskStatus.PENDING),
			],
		)

		delegator = TaskDelegator()

		results = await delegator.delegate_phase(
			phase=phase,
			plan=sample_plan,
		)

		# Should only delegate the pending task
		assert len(results) == 1
