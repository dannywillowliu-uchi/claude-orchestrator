"""Orchestrator tools - planning sessions and verification."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..orchestrator.planner import get_planner
from ..orchestrator.verifier import Verifier


def register_orchestrator_tools(mcp: FastMCP, config: Config) -> None:
	"""Register orchestrator tools (planning sessions + verification)."""

	@mcp.tool()
	async def start_planning_session(project: str, goal: str, context: str = "") -> str:
		"""
		Start a new interactive planning session.

		Planning sessions conduct thorough Q&A until complete clarity
		is achieved before any implementation begins.

		Args:
			project: Project name
			goal: What needs to be accomplished
			context: Optional additional context
		"""
		planner = get_planner()
		session = await planner.start_planning_session(project, goal, context or None)

		pending = session.get_pending_questions()

		return json.dumps({
			"session_id": session.id,
			"project": project,
			"goal": goal,
			"phase": session.phase.value,
			"questions": [
				{
					"id": q.id,
					"category": q.category,
					"question": q.question,
					"options": q.options,
				}
				for q in pending
			],
		}, indent=2)

	@mcp.tool()
	async def answer_planning_question(
		session_id: str,
		question_id: str,
		answer: str,
	) -> str:
		"""
		Answer a question in a planning session.

		Args:
			session_id: Planning session ID
			question_id: Question ID (e.g., "q1")
			answer: Your answer
		"""
		planner = get_planner()
		result = await planner.process_answer(session_id, question_id, answer)

		return json.dumps(result, indent=2)

	@mcp.tool()
	async def get_planning_session(session_id: str) -> str:
		"""
		Get the current state of a planning session.

		Args:
			session_id: Planning session ID
		"""
		planner = get_planner()
		session = planner.get_session(session_id)

		if not session:
			return json.dumps({"error": f"Session not found: {session_id}"})

		return json.dumps({
			"summary": session.get_summary(),
			"pending_questions": [
				{
					"id": q.id,
					"category": q.category,
					"question": q.question,
					"options": q.options,
				}
				for q in session.get_pending_questions()
			],
			"answered_questions": [
				{
					"id": q.id,
					"category": q.category,
					"question": q.question,
					"answer": q.answer,
				}
				for q in session.answered_questions
			],
			"has_draft_plan": session.draft_plan is not None,
		}, indent=2)

	@mcp.tool()
	async def approve_planning_session(session_id: str) -> str:
		"""
		Approve a planning session's draft plan and save it.

		Args:
			session_id: Planning session ID
		"""
		planner = get_planner()
		result = await planner.approve_plan(session_id)

		return json.dumps(result, indent=2)

	@mcp.tool()
	async def list_planning_sessions() -> str:
		"""
		List all active planning sessions.

		Returns JSON with list of session summaries.
		"""
		planner = get_planner()
		sessions = planner.list_sessions()

		return json.dumps({
			"sessions": sessions,
			"total": len(sessions),
		}, indent=2)

	@mcp.tool()
	async def run_verification(
		project_path: str = "",
		checks: str = "",
		files_changed: str = "",
	) -> str:
		"""
		Run verification suite (tests, lint, type check, security).

		Args:
			project_path: Path to project (default: current directory)
			checks: Comma-separated checks to run (default: pytest,ruff,mypy,bandit)
			files_changed: Comma-separated list of changed files for targeted checks
		"""
		verifier = Verifier(
			project_path=project_path if project_path else None,
			venv_path=".venv",
		)

		check_list = [c.strip() for c in checks.split(",")] if checks else None
		files_list = [f.strip() for f in files_changed.split(",")] if files_changed else None

		result = await verifier.verify(
			checks=check_list,
			files_changed=files_list,
		)

		return json.dumps({
			"passed": result.passed,
			"summary": result.summary,
			"can_retry": result.can_retry,
			"checks": [
				{
					"name": c.name,
					"status": c.status.value,
					"duration_seconds": round(c.duration_seconds, 2),
					"output_preview": c.output[:500] if c.output else "",
				}
				for c in result.checks
			],
			"verified_at": result.verified_at,
		}, indent=2)
