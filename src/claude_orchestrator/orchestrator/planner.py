"""
Planner - Interactive planning sessions with thorough Q&A.

The planner conducts comprehensive Q&A until complete clarity is achieved
before any implementation begins. Plans are stored with versioning for
tracking and recovery.

Philosophy:
- Ask thorough questions during planning
- Build comprehensive one-shot plans
- Do NOT extrapolate or assume - ask until requirements are clear
- 90% planning, 10% guiding
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..plans.models import (
	Decision,
	Phase,
	Plan,
	PlanOverview,
	PlanStatus,
	Research,
	Task,
)
from ..plans.store import get_plan_store

logger = logging.getLogger(__name__)


class PlanningPhase(str, Enum):
	"""Current phase of the planning session."""
	GATHERING_REQUIREMENTS = "gathering_requirements"
	RESEARCHING = "researching"
	DESIGNING = "designing"
	REVIEWING = "reviewing"
	APPROVED = "approved"


@dataclass
class Question:
	"""A question to ask during planning."""
	id: str
	category: str  # requirements, architecture, verification, scope
	question: str
	options: list[str] = field(default_factory=list)  # For multiple choice
	answer: Optional[str] = None
	follow_ups: list[str] = field(default_factory=list)


@dataclass
class PlanningSession:
	"""
	An interactive planning session.

	Tracks questions asked, answers received, and builds toward
	a comprehensive implementation plan.
	"""
	id: str
	project: str
	goal: str
	phase: PlanningPhase = PlanningPhase.GATHERING_REQUIREMENTS
	questions: list[Question] = field(default_factory=list)
	answered_questions: list[Question] = field(default_factory=list)
	research_findings: list[str] = field(default_factory=list)
	decisions: list[Decision] = field(default_factory=list)
	draft_plan: Optional[Plan] = None
	created_at: str = field(default_factory=lambda: datetime.now().isoformat())
	updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

	def add_question(self, category: str, question: str, options: list[str] = None) -> Question:
		"""Add a question to the session."""
		q = Question(
			id=f"q{len(self.questions) + 1}",
			category=category,
			question=question,
			options=options or [],
		)
		self.questions.append(q)
		return q

	def answer_question(self, question_id: str, answer: str) -> bool:
		"""Record an answer to a question."""
		for q in self.questions:
			if q.id == question_id and q.answer is None:
				q.answer = answer
				self.answered_questions.append(q)
				self.updated_at = datetime.now().isoformat()
				return True
		return False

	def get_pending_questions(self) -> list[Question]:
		"""Get questions that haven't been answered yet."""
		return [q for q in self.questions if q.answer is None]

	def add_research_finding(self, finding: str):
		"""Add a research finding."""
		self.research_findings.append(finding)
		self.updated_at = datetime.now().isoformat()

	def add_decision(self, decision: str, rationale: str, alternatives: list[str] = None):
		"""Record a decision made during planning."""
		d = Decision(
			id=f"decision-{len(self.decisions) + 1}",
			decision=decision,
			rationale=rationale,
			alternatives=alternatives or [],
		)
		self.decisions.append(d)
		self.updated_at = datetime.now().isoformat()

	def get_summary(self) -> dict:
		"""Get a summary of the planning session."""
		return {
			"id": self.id,
			"project": self.project,
			"goal": self.goal,
			"phase": self.phase.value,
			"questions_total": len(self.questions),
			"questions_answered": len(self.answered_questions),
			"questions_pending": len(self.get_pending_questions()),
			"research_findings": len(self.research_findings),
			"decisions": len(self.decisions),
			"has_draft_plan": self.draft_plan is not None,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}


class Planner:
	"""
	Orchestrates planning sessions.

	Conducts thorough Q&A, researches domain knowledge,
	and builds comprehensive implementation plans.
	"""

	# Standard question categories
	REQUIREMENT_QUESTIONS = [
		"What is the primary goal of this task?",
		"What are the success criteria?",
		"Are there any constraints or limitations?",
		"What is explicitly out of scope?",
		"Who are the stakeholders?",
	]

	ARCHITECTURE_QUESTIONS = [
		"What existing code/systems does this interact with?",
		"What is the preferred technology stack?",
		"Are there any performance requirements?",
		"What are the security considerations?",
		"How should errors be handled?",
	]

	VERIFICATION_QUESTIONS = [
		"How will we verify this works correctly?",
		"What tests are needed?",
		"What manual verification is required?",
		"What are the acceptance criteria?",
	]

	def __init__(self):
		"""Initialize the planner."""
		self._sessions: dict[str, PlanningSession] = {}

	async def start_planning_session(
		self,
		project: str,
		goal: str,
		context: Optional[str] = None,
	) -> PlanningSession:
		"""
		Start a new planning session.

		Args:
			project: Project name
			goal: What needs to be accomplished
			context: Optional additional context

		Returns:
			PlanningSession for interactive Q&A
		"""
		session_id = f"plan-{project}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

		session = PlanningSession(
			id=session_id,
			project=project,
			goal=goal,
		)

		# Add initial requirement questions
		for q in self.REQUIREMENT_QUESTIONS:
			session.add_question("requirements", q)

		self._sessions[session_id] = session
		logger.info(f"Started planning session {session_id} for {project}")

		return session

	def get_session(self, session_id: str) -> Optional[PlanningSession]:
		"""Get a planning session by ID."""
		return self._sessions.get(session_id)

	def list_sessions(self) -> list[dict]:
		"""List all active planning sessions."""
		return [s.get_summary() for s in self._sessions.values()]

	async def process_answer(
		self,
		session_id: str,
		question_id: str,
		answer: str,
	) -> dict:
		"""
		Process an answer and potentially add follow-up questions.

		Args:
			session_id: Planning session ID
			question_id: Question being answered
			answer: The answer

		Returns:
			Dict with next steps (more questions, move to next phase, etc.)
		"""
		session = self._sessions.get(session_id)
		if not session:
			return {"error": f"Session not found: {session_id}"}

		if not session.answer_question(question_id, answer):
			return {"error": f"Question not found or already answered: {question_id}"}

		# Check if we need follow-up questions based on the answer
		follow_ups = self._generate_follow_ups(session, question_id, answer)
		for q in follow_ups:
			session.add_question(q["category"], q["question"], q.get("options"))

		# Check if we should move to the next phase
		pending = session.get_pending_questions()

		if not pending and session.phase == PlanningPhase.GATHERING_REQUIREMENTS:
			# Move to architecture questions
			session.phase = PlanningPhase.RESEARCHING
			for q in self.ARCHITECTURE_QUESTIONS:
				session.add_question("architecture", q)
			pending = session.get_pending_questions()

		if not pending and session.phase == PlanningPhase.RESEARCHING:
			# Move to verification questions
			session.phase = PlanningPhase.DESIGNING
			for q in self.VERIFICATION_QUESTIONS:
				session.add_question("verification", q)
			pending = session.get_pending_questions()

		if not pending and session.phase == PlanningPhase.DESIGNING:
			# Ready to review - generate draft plan
			session.phase = PlanningPhase.REVIEWING
			session.draft_plan = await self._generate_draft_plan(session)

		return {
			"session_id": session_id,
			"phase": session.phase.value,
			"pending_questions": [
				{
					"id": q.id,
					"category": q.category,
					"question": q.question,
					"options": q.options,
				}
				for q in pending
			],
			"has_draft_plan": session.draft_plan is not None,
		}

	def _generate_follow_ups(
		self,
		session: PlanningSession,
		question_id: str,
		answer: str,
	) -> list[dict]:
		"""Generate follow-up questions based on an answer."""
		# Disabled follow-ups for cleaner flow - the initial questions are comprehensive
		# Enable this for more thorough interactive planning sessions
		return []

	async def _generate_draft_plan(self, session: PlanningSession) -> Plan:
		"""Generate a draft plan using Claude CLI based on Q&A answers."""
		# Try to generate plan with Claude CLI
		try:
			plan = await self._generate_plan_with_claude(session)
			if plan:
				return plan
		except Exception as e:
			logger.warning(f"Claude plan generation failed: {e}, using fallback")

		# Fallback to template-based plan
		return self._generate_fallback_plan(session)

	async def _generate_plan_with_claude(self, session: PlanningSession) -> Plan | None:
		"""Use Claude CLI to generate a detailed implementation plan."""
		# Build the prompt with all Q&A context
		prompt = self._build_plan_generation_prompt(session)

		try:
			process = await asyncio.create_subprocess_exec(
				"claude",
				"--print",
				"--output-format", "text",
				stdin=asyncio.subprocess.PIPE,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
			)

			stdout, stderr = await asyncio.wait_for(
				process.communicate(input=prompt.encode()),
				timeout=120,  # 2 minute timeout for plan generation
			)

			if process.returncode != 0:
				logger.error(f"Claude CLI error: {stderr.decode()}")
				return None

			response = stdout.decode()
			return self._parse_claude_plan_response(session, response)

		except asyncio.TimeoutError:
			logger.error("Claude plan generation timed out")
			return None
		except FileNotFoundError:
			logger.error("Claude CLI not found")
			return None

	def _build_plan_generation_prompt(self, session: PlanningSession) -> str:
		"""Build a prompt for Claude to generate an implementation plan."""
		lines = [
			"# Generate Implementation Plan",
			"",
			"You are a software architect. Based on the requirements below, generate a detailed implementation plan.",
			"",
			"## Project Goal",
			session.goal,
			"",
			"## Requirements Gathered",
			"",
		]

		# Add all Q&A
		for q in session.answered_questions:
			if q.answer and q.answer != "Use default implementation":
				lines.append(f"**Q: {q.question}**")
				lines.append(f"A: {q.answer}")
				lines.append("")

		lines.extend([
			"## Output Format",
			"",
			"Generate a plan in the following JSON format."
			" Be specific about files to create and what each should contain.",
			"",
			"```json",
			"{",
			'  "overview": {',
			'    "goal": "string",',
			'    "success_criteria": ["string"],',
			'    "constraints": ["string"],',
			'    "out_of_scope": ["string"]',
			"  },",
			'  "decisions": [',
			'    {"decision": "string", "rationale": "string", "alternatives": ["string"]}',
			"  ],",
			'  "phases": [',
			"    {",
			'      "name": "string",',
			'      "description": "string",',
			'      "tasks": [',
			"        {",
			'          "description": "Specific task description",',
			'          "files": ["path/to/file.py"],',
			'          "verification": ["pytest tests/test_file.py"]',
			"        }",
			"      ]",
			"    }",
			"  ]",
			"}",
			"```",
			"",
			"IMPORTANT:",
			"- Be specific about file paths (e.g., src/motion_detection/detector.py)",
			"- Each task should be completable by an AI agent in one session",
			"- Include specific verification commands for each task",
			"- Create 3-5 phases with 2-4 tasks each",
			"- Tasks should build on each other logically",
			"",
			"Generate the JSON plan now:",
		])

		return "\n".join(lines)

	def _parse_claude_plan_response(self, session: PlanningSession, response: str) -> Plan | None:
		"""Parse Claude's response into a Plan object."""
		# Extract JSON from response
		json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
		if not json_match:
			# Try to find raw JSON
			json_match = re.search(r"\{[\s\S]*\"phases\"[\s\S]*\}", response)
			if json_match:
				json_str = json_match.group(0)
			else:
				logger.error("Could not find JSON in Claude response")
				return None
		else:
			json_str = json_match.group(1)

		try:
			data = json.loads(json_str)
		except json.JSONDecodeError as e:
			logger.error(f"Failed to parse plan JSON: {e}")
			return None

		# Build Plan from parsed data
		overview_data = data.get("overview", {})
		overview = PlanOverview(
			goal=overview_data.get("goal", session.goal),
			success_criteria=overview_data.get("success_criteria", []),
			constraints=overview_data.get("constraints", []),
			out_of_scope=overview_data.get("out_of_scope", []),
		)

		decisions = []
		for i, d in enumerate(data.get("decisions", [])):
			decisions.append(Decision(
				id=f"decision-{i+1}",
				decision=d.get("decision", ""),
				rationale=d.get("rationale", ""),
				alternatives=d.get("alternatives", []),
			))

		phases = []
		for i, p in enumerate(data.get("phases", [])):
			tasks = []
			for j, t in enumerate(p.get("tasks", [])):
				tasks.append(Task(
					id=f"phase-{i+1}-task-{j+1}",
					description=t.get("description", ""),
					files=t.get("files", []),
					verification=t.get("verification", []),
				))

			phases.append(Phase(
				id=f"phase-{i+1}",
				name=p.get("name", f"Phase {i+1}"),
				description=p.get("description", ""),
				tasks=tasks,
				dependencies=[f"phase-{i}"] if i > 0 else [],
			))

		plan = Plan(
			id="",
			project=session.project,
			status=PlanStatus.DRAFT,
			overview=overview,
			phases=phases,
			decisions=decisions or session.decisions,
			research=Research(findings=session.research_findings),
		)

		logger.info(f"Generated plan with {len(phases)} phases, {sum(len(p.tasks) for p in phases)} tasks")
		return plan

	def _generate_fallback_plan(self, session: PlanningSession) -> Plan:
		"""Generate a fallback template plan if Claude generation fails."""
		requirements = [q for q in session.answered_questions if q.category == "requirements"]

		overview = PlanOverview(
			goal=session.goal,
			success_criteria=[
				q.answer for q in requirements
				if "success" in q.question.lower() and q.answer
			],
			constraints=[
				q.answer for q in requirements
				if "constraint" in q.question.lower() and q.answer
			],
			out_of_scope=[
				q.answer for q in requirements
				if "scope" in q.question.lower() and q.answer
			],
		)

		research = Research(
			findings=session.research_findings,
			open_questions=[q.question for q in session.get_pending_questions()],
		)

		phases = [
			Phase(
				id="phase-1",
				name="Setup & Research",
				description="Prepare the environment and gather remaining context",
				tasks=[
					Task(id="phase-1-task-1", description="Review existing codebase"),
					Task(id="phase-1-task-2", description="Identify files to modify"),
					Task(id="phase-1-task-3", description="Set up development environment"),
				],
			),
			Phase(
				id="phase-2",
				name="Implementation",
				description="Implement the core functionality",
				tasks=[
					Task(id="phase-2-task-1", description="Implement core logic"),
					Task(id="phase-2-task-2", description="Add error handling"),
					Task(id="phase-2-task-3", description="Write unit tests"),
				],
				dependencies=["phase-1"],
			),
			Phase(
				id="phase-3",
				name="Verification & Cleanup",
				description="Verify implementation and clean up",
				tasks=[
					Task(id="phase-3-task-1", description="Run full test suite"),
					Task(id="phase-3-task-2", description="Run linter and type checker"),
					Task(id="phase-3-task-3", description="Update documentation"),
				],
				dependencies=["phase-2"],
			),
		]

		return Plan(
			id="",
			project=session.project,
			status=PlanStatus.DRAFT,
			overview=overview,
			phases=phases,
			decisions=session.decisions,
			research=research,
		)

	async def approve_plan(self, session_id: str) -> dict:
		"""
		Approve a draft plan and save it to the plan store.

		Args:
			session_id: Planning session ID

		Returns:
			Dict with plan_id and status
		"""
		session = self._sessions.get(session_id)
		if not session:
			return {"error": f"Session not found: {session_id}"}

		if not session.draft_plan:
			return {"error": "No draft plan to approve"}

		if session.phase != PlanningPhase.REVIEWING:
			return {"error": f"Cannot approve plan in phase: {session.phase.value}"}

		# Save to plan store
		store = await get_plan_store()
		plan = session.draft_plan
		plan.status = PlanStatus.APPROVED
		plan.approved_at = datetime.now().isoformat()

		plan_id = await store.create_plan(session.project, plan)

		session.phase = PlanningPhase.APPROVED
		session.draft_plan.id = plan_id

		logger.info(f"Approved plan {plan_id} for session {session_id}")

		return {
			"success": True,
			"plan_id": plan_id,
			"project": session.project,
			"phase_count": len(plan.phases),
			"task_count": sum(len(p.tasks) for p in plan.phases),
		}

	async def add_custom_phase(
		self,
		session_id: str,
		name: str,
		description: str,
		tasks: list[str],
		dependencies: list[str] = None,
	) -> dict:
		"""
		Add a custom phase to the draft plan.

		Args:
			session_id: Planning session ID
			name: Phase name
			description: Phase description
			tasks: List of task descriptions
			dependencies: List of phase IDs this depends on

		Returns:
			Dict with updated plan info
		"""
		session = self._sessions.get(session_id)
		if not session:
			return {"error": f"Session not found: {session_id}"}

		if not session.draft_plan:
			return {"error": "No draft plan yet - complete Q&A first"}

		phase_id = f"phase-{len(session.draft_plan.phases) + 1}"
		phase = Phase(
			id=phase_id,
			name=name,
			description=description,
			tasks=[
				Task(id=f"{phase_id}-task-{i+1}", description=t)
				for i, t in enumerate(tasks)
			],
			dependencies=dependencies or [],
		)

		session.draft_plan.phases.append(phase)
		session.updated_at = datetime.now().isoformat()

		return {
			"success": True,
			"phase_id": phase_id,
			"task_count": len(tasks),
			"total_phases": len(session.draft_plan.phases),
		}

	def end_session(self, session_id: str) -> bool:
		"""End a planning session."""
		if session_id in self._sessions:
			del self._sessions[session_id]
			logger.info(f"Ended planning session {session_id}")
			return True
		return False


# Global planner instance
_planner: Optional[Planner] = None


def get_planner() -> Planner:
	"""Get or create the global planner instance."""
	global _planner
	if _planner is None:
		_planner = Planner()
	return _planner
