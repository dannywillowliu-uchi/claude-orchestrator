"""
End-to-end tests for the full orchestration flow.

These tests run the complete orchestration pipeline:
Planning → Delegation → Supervision → Verification

Note: Tests marked with @pytest.mark.slow run real Claude CLI sessions
and may take several minutes to complete.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.framework import (
	OrchestrationPhase,
	OrchestrationResult,
	OrchestrationTestFramework,
	create_simple_test_framework,
)
from tests.visualizer import Visualizer

# Sample planning answers for tests
SIMPLE_PLANNING_ANSWERS = {
	"q1": "Simple test project",
	"q2": "Code runs without errors",
	"q3": "Python only",
	"q4": "Nothing out of scope",
	"q5": "Test project",
}


class TestOrchestrationFramework:
	"""Tests for the orchestration test framework itself."""

	@pytest.fixture
	def temp_dir(self):
		"""Create a temporary directory for tests."""
		with tempfile.TemporaryDirectory() as tmpdir:
			yield Path(tmpdir)

	def test_framework_initialization(self, temp_dir):
		"""Test that framework initializes correctly."""
		framework = OrchestrationTestFramework(
			project_name="test-project",
			working_dir=temp_dir / "test",
			use_mocks=True,
		)

		assert framework.project_name == "test-project"
		assert framework.use_mocks
		assert framework.planner is not None
		assert framework.delegator is not None
		assert framework.supervisor is not None

	def test_framework_with_callbacks(self, temp_dir):
		"""Test that callbacks can be registered."""
		framework = OrchestrationTestFramework(
			project_name="test",
			working_dir=temp_dir / "test",
			use_mocks=True,
		)

		phases_seen = []

		async def phase_callback(phase):
			phases_seen.append(phase)

		framework.on_phase_change(phase_callback)

		# Verify callback was registered
		assert len(framework._on_phase_change) == 1


class TestMockedOrchestration:
	"""Tests using mocked Claude CLI execution."""

	@pytest.mark.asyncio
	async def test_full_orchestration_mocked(self):
		"""Test complete orchestration with mocked execution."""
		framework = await create_simple_test_framework(
			project_name="mocked-test",
			use_mocks=True,
		)

		result = await framework.run_full_orchestration(
			project_goal="Create a simple test project",
			planning_answers=SIMPLE_PLANNING_ANSWERS,
		)

		assert isinstance(result, OrchestrationResult)
		assert result.project_path.exists()

	@pytest.mark.asyncio
	async def test_orchestration_creates_project_structure(self):
		"""Test that orchestration creates expected project structure."""
		framework = await create_simple_test_framework(use_mocks=True)

		result = await framework.run_full_orchestration(
			project_goal="Test project",
			planning_answers=SIMPLE_PLANNING_ANSWERS,
		)

		# Check project structure was created
		assert (result.project_path / "src").exists()
		assert (result.project_path / "tests").exists()
		assert (result.project_path / "requirements.txt").exists()
		assert (result.project_path / "README.md").exists()

	@pytest.mark.asyncio
	async def test_orchestration_generates_plan(self):
		"""Test that orchestration generates a valid plan."""
		framework = await create_simple_test_framework(use_mocks=True)

		result = await framework.run_full_orchestration(
			project_goal="Test project",
			planning_answers=SIMPLE_PLANNING_ANSWERS,
		)

		# Plan should have been generated
		assert framework.plan is not None
		assert len(framework.plan.phases) > 0

	@pytest.mark.asyncio
	async def test_orchestration_tracks_events(self):
		"""Test that orchestration tracks events."""
		framework = await create_simple_test_framework(use_mocks=True)

		result = await framework.run_full_orchestration(
			project_goal="Test project",
			planning_answers=SIMPLE_PLANNING_ANSWERS,
		)

		# Should have logged events
		assert len(result.events) > 0

		# Should have events from different phases
		components = set(e["component"] for e in result.events)
		assert len(components) > 1

	@pytest.mark.asyncio
	async def test_orchestration_phase_transitions(self):
		"""Test that orchestration transitions through all phases."""
		framework = await create_simple_test_framework(use_mocks=True)

		phases_seen = []

		async def track_phase(phase):
			phases_seen.append(phase)

		framework.on_phase_change(track_phase)

		await framework.run_full_orchestration(
			project_goal="Test project",
			planning_answers=SIMPLE_PLANNING_ANSWERS,
		)

		# Should have gone through all phases
		assert OrchestrationPhase.SETUP in phases_seen
		assert OrchestrationPhase.PLANNING in phases_seen
		assert OrchestrationPhase.DELEGATION in phases_seen
		assert OrchestrationPhase.SUPERVISION in phases_seen
		assert OrchestrationPhase.VERIFICATION in phases_seen

	@pytest.mark.asyncio
	async def test_orchestration_handles_planning_failure(self):
		"""Test graceful handling when planning fails."""
		framework = await create_simple_test_framework(use_mocks=True)

		# Provide empty answers to potentially cause issues
		result = await framework.run_full_orchestration(
			project_goal="",  # Empty goal
			planning_answers={},  # No answers
		)

		# Should still complete (with default answers)
		assert isinstance(result, OrchestrationResult)


class TestOrchestrationResult:
	"""Tests for OrchestrationResult data class."""

	def test_result_to_dict(self):
		"""Test converting result to dictionary."""
		result = OrchestrationResult(
			success=True,
			project_path=Path("/test/path"),
			plan_id="plan-123",
			tasks_completed=5,
			tasks_total=5,
			verification_passed=True,
			duration_seconds=10.5,
		)

		d = result.to_dict()

		assert d["success"] is True
		assert d["plan_id"] == "plan-123"
		assert d["tasks_completed"] == 5
		assert d["duration_seconds"] == 10.5

	def test_result_with_error(self):
		"""Test result with error."""
		result = OrchestrationResult(
			success=False,
			project_path=Path("/test"),
			error="Something went wrong",
		)

		assert not result.success
		assert result.error == "Something went wrong"


@pytest.mark.slow
class TestRealCLIOrchestration:
	"""
	Tests that use real Claude CLI sessions.

	These tests are slow and require Claude CLI to be installed.
	Run with: pytest -m slow
	Skip with: pytest -m "not slow"
	"""

	@pytest.mark.asyncio
	async def test_full_orchestration_real_cli(self):
		"""
		End-to-end test with real Claude CLI.

		This test:
		1. Creates a real project
		2. Runs planning with Q&A
		3. Delegates tasks to Claude CLI
		4. Supervises execution
		5. Runs verification
		"""
		import subprocess

		# Check if claude CLI is available
		try:
			result = subprocess.run(
				["claude", "--version"],
				capture_output=True,
				timeout=5,
			)
			if result.returncode != 0:
				pytest.skip("Claude CLI not available")
		except (FileNotFoundError, subprocess.TimeoutExpired):
			pytest.skip("Claude CLI not available")

		with tempfile.TemporaryDirectory() as tmpdir:
			framework = OrchestrationTestFramework(
				project_name="real-cli-test",
				working_dir=Path(tmpdir) / "project",
				use_mocks=False,  # Real CLI
				verbose=True,
				cleanup_on_exit=False,
			)

			result = await framework.run_full_orchestration(
				project_goal="Create a simple Python function that adds two numbers",
				planning_answers={
					"q1": "Simple addition function",
					"q2": "Function correctly adds numbers",
					"q3": "Python only, no dependencies",
					"q4": "No advanced math",
					"q5": "Test project",
				},
			)

			assert result.project_path.exists()
			# Note: May or may not succeed depending on Claude CLI behavior


class TestVisualizerIntegration:
	"""Tests for visualizer integration with framework."""

	def test_visualizer_captures_events(self):
		"""Test that visualizer captures events during orchestration."""
		visualizer = Visualizer(verbose=False)

		visualizer.show_phase("planning", "Starting planning")
		visualizer.show_component("Planner", "Processing question")
		visualizer.show_result(True, "Complete")

		events = visualizer.get_event_log()

		assert len(events) == 3
		assert events[0]["component"] == "Phase"
		assert events[1]["component"] == "Planner"
		assert events[2]["component"] == "Result"


class TestOrchestrationConcurrency:
	"""Tests for concurrent orchestration behavior."""

	@pytest.mark.asyncio
	async def test_multiple_orchestrations_isolated(self):
		"""Test that multiple orchestrations don't interfere."""
		framework1 = await create_simple_test_framework(
			project_name="project-1",
			use_mocks=True,
		)
		framework2 = await create_simple_test_framework(
			project_name="project-2",
			use_mocks=True,
		)

		# Run concurrently
		results = await asyncio.gather(
			framework1.run_full_orchestration(
				project_goal="Project 1",
				planning_answers=SIMPLE_PLANNING_ANSWERS,
			),
			framework2.run_full_orchestration(
				project_goal="Project 2",
				planning_answers=SIMPLE_PLANNING_ANSWERS,
			),
		)

		# Both should succeed
		assert len(results) == 2
		assert results[0].project_path != results[1].project_path
