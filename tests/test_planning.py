"""
Tests for the Planning phase of orchestration.

Tests:
- Planning session creation
- Question processing and answer handling
- Phase transitions
- Plan generation and approval
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from claude_orchestrator.orchestrator.planner import (
	Planner,
	PlanningPhase,
	PlanningSession,
)


class TestPlannerSessionCreation:
	"""Tests for planning session creation."""

	@pytest.fixture
	def planner(self):
		return Planner()

	@pytest.mark.asyncio
	async def test_start_planning_session_creates_session(self, planner):
		"""Test that starting a planning session creates a valid session."""
		session = await planner.start_planning_session(
			project="test-project",
			goal="Build a test application",
		)

		assert session is not None
		assert session.project == "test-project"
		assert session.goal == "Build a test application"
		assert session.phase == PlanningPhase.GATHERING_REQUIREMENTS
		assert len(session.questions) > 0

	@pytest.mark.asyncio
	async def test_session_has_initial_questions(self, planner):
		"""Test that a new session has initial requirement questions."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test goal",
		)

		questions = session.questions
		assert len(questions) >= 5  # Should have standard requirement questions

		# Check question format
		for q in questions:
			assert q.id is not None
			assert q.category == "requirements"
			assert q.question is not None
			assert q.answer is None  # Not yet answered

	@pytest.mark.asyncio
	async def test_get_session_returns_correct_session(self, planner):
		"""Test retrieving a session by ID."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		retrieved = planner.get_session(session.id)
		assert retrieved is not None
		assert retrieved.id == session.id

	@pytest.mark.asyncio
	async def test_get_session_returns_none_for_invalid_id(self, planner):
		"""Test that invalid session ID returns None."""
		retrieved = planner.get_session("invalid-id")
		assert retrieved is None


class TestPlannerAnswerProcessing:
	"""Tests for answer processing."""

	@pytest.fixture
	def planner(self):
		return Planner()

	@pytest.mark.asyncio
	async def test_process_answer_records_answer(self, planner):
		"""Test that processing an answer records it correctly."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		question = session.questions[0]
		result = await planner.process_answer(
			session.id,
			question.id,
			"My answer",
		)

		assert result.get("error") is None
		assert question.answer == "My answer"
		assert question in session.answered_questions

	@pytest.mark.asyncio
	async def test_process_answer_generates_follow_ups(self, planner):
		"""Test that vague answers generate follow-up questions."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		initial_count = len(session.questions)
		question = session.questions[0]

		# Answer with "not sure" to trigger follow-up
		await planner.process_answer(
			session.id,
			question.id,
			"I'm not sure about this",
		)

		# Should have generated follow-up questions
		assert len(session.questions) > initial_count

	@pytest.mark.asyncio
	async def test_process_answer_invalid_session_returns_error(self, planner):
		"""Test that invalid session ID returns error."""
		result = await planner.process_answer(
			"invalid-session",
			"q1",
			"answer",
		)

		assert "error" in result
		assert "not found" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_process_answer_invalid_question_returns_error(self, planner):
		"""Test that invalid question ID returns error."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		result = await planner.process_answer(
			session.id,
			"invalid-question",
			"answer",
		)

		assert "error" in result


class TestPlannerPhaseTransitions:
	"""Tests for phase transitions during planning."""

	@pytest.fixture
	def planner(self):
		return Planner()

	@pytest.mark.asyncio
	async def test_phase_transitions_to_researching(self, planner):
		"""Test transition from GATHERING_REQUIREMENTS to RESEARCHING."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		# Answer all requirement questions
		for q in list(session.questions):  # Copy list to avoid modification during iteration
			if q.answer is None:
				await planner.process_answer(session.id, q.id, "Test answer")

		# Should have transitioned to researching (or beyond)
		assert session.phase != PlanningPhase.GATHERING_REQUIREMENTS

	@pytest.mark.asyncio
	async def test_full_qa_generates_draft_plan(self, planner):
		"""Test that completing all Q&A generates a draft plan."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		# Keep answering until we have a draft plan or hit reviewing phase
		max_iterations = 50  # Safety limit
		iterations = 0

		while session.phase != PlanningPhase.REVIEWING and iterations < max_iterations:
			pending = session.get_pending_questions()
			if not pending:
				break

			for q in pending:
				await planner.process_answer(session.id, q.id, "Test answer")

			iterations += 1

		# Should have generated a draft plan
		assert session.draft_plan is not None or session.phase == PlanningPhase.REVIEWING


class TestPlannerPlanApproval:
	"""Tests for plan approval."""

	@pytest.fixture
	def planner(self):
		return Planner()

	@pytest.mark.asyncio
	async def test_approve_plan_without_draft_returns_error(self, planner):
		"""Test that approving without a draft plan returns error."""
		session = await planner.start_planning_session(
			project="test",
			goal="Test",
		)

		result = await planner.approve_plan(session.id)

		assert "error" in result
		assert "no draft" in result["error"].lower()

	@pytest.mark.asyncio
	async def test_approve_plan_invalid_session_returns_error(self, planner):
		"""Test that invalid session ID returns error."""
		result = await planner.approve_plan("invalid-session")

		assert "error" in result
		assert "not found" in result["error"].lower()


class TestPlanningSessionMethods:
	"""Tests for PlanningSession helper methods."""

	def test_get_pending_questions(self):
		"""Test getting pending questions."""
		session = PlanningSession(
			id="test",
			project="test",
			goal="test",
		)

		session.add_question("requirements", "Question 1")
		session.add_question("requirements", "Question 2")

		pending = session.get_pending_questions()
		assert len(pending) == 2

		session.answer_question("q1", "Answer 1")

		pending = session.get_pending_questions()
		assert len(pending) == 1

	def test_add_question_returns_question(self):
		"""Test adding a question returns the question object."""
		session = PlanningSession(
			id="test",
			project="test",
			goal="test",
		)

		q = session.add_question("requirements", "Test question?", ["opt1", "opt2"])

		assert q.id == "q1"
		assert q.category == "requirements"
		assert q.question == "Test question?"
		assert q.options == ["opt1", "opt2"]

	def test_add_research_finding(self):
		"""Test adding a research finding."""
		session = PlanningSession(
			id="test",
			project="test",
			goal="test",
		)

		session.add_research_finding("Found relevant documentation")

		assert len(session.research_findings) == 1
		assert session.research_findings[0] == "Found relevant documentation"

	def test_add_decision(self):
		"""Test adding a decision."""
		session = PlanningSession(
			id="test",
			project="test",
			goal="test",
		)

		session.add_decision(
			decision="Use Python",
			rationale="Standard for ML",
			alternatives=["JavaScript", "Go"],
		)

		assert len(session.decisions) == 1
		assert session.decisions[0].decision == "Use Python"

	def test_get_summary(self):
		"""Test getting session summary."""
		session = PlanningSession(
			id="test",
			project="test-project",
			goal="Test goal",
		)

		session.add_question("requirements", "Q1")
		session.answer_question("q1", "A1")

		summary = session.get_summary()

		assert summary["id"] == "test"
		assert summary["project"] == "test-project"
		assert summary["questions_total"] == 1
		assert summary["questions_answered"] == 1
		assert summary["questions_pending"] == 0
