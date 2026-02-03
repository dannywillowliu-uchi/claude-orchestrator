"""Orchestrator tools - planning sessions and verification."""

import json
import logging
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .. import project_memory
from ..config import Config
from ..orchestrator.planner import get_planner
from ..orchestrator.verifier import CheckResult, CheckStatus, Verifier

logger = logging.getLogger(__name__)

# Patterns that warrant multi-agent consensus review
SECURITY_PATTERNS = {"auth", "security", "crypt", "password", "token", "secret", "credential", "permission"}
ARCHITECTURE_PATTERNS = {"config", "settings", "init", "main", "core", "base", "registry"}


def _should_recommend_consensus_review(files_changed: list[str] | None) -> tuple[bool, str]:
	"""Determine if consensus review should be recommended based on changed files."""
	if not files_changed:
		return False, ""

	file_count = len(files_changed)
	reasons = []

	# Check for security-sensitive files
	security_files = []
	for f in files_changed:
		f_lower = f.lower()
		if any(pattern in f_lower for pattern in SECURITY_PATTERNS):
			security_files.append(f)
	if security_files:
		reasons.append(f"security-sensitive files: {', '.join(security_files[:3])}")

	# Check for architecture files
	arch_files = []
	for f in files_changed:
		f_lower = f.lower()
		if any(pattern in f_lower for pattern in ARCHITECTURE_PATTERNS):
			arch_files.append(f)
	if arch_files:
		reasons.append(f"architecture files: {', '.join(arch_files[:3])}")

	# Multi-file changes (threshold: 5+ files)
	if file_count >= 5:
		reasons.append(f"{file_count} files changed (multi-file refactor)")

	if reasons:
		return True, "; ".join(reasons)
	return False, ""


def _derive_gotcha_from_failure(check: CheckResult) -> str | None:
	"""Parse a verification failure into a concise gotcha string."""
	if not check.output:
		return None

	output = check.output[:2000]

	if check.name == "ruff":
		# Extract unique rule codes like E501, F841, I001
		codes = set(re.findall(r"\b([A-Z]\d{3,4})\b", output))
		if codes:
			return f"Linting: fix {', '.join(sorted(codes))} violations before committing"
		return "Linting: ruff check failed -- fix lint errors before committing"

	if check.name == "pytest":
		# Extract failed test names
		failed = re.findall(r"FAILED\s+(\S+)", output)
		if failed:
			names = ", ".join(f[:60] for f in failed[:3])
			suffix = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
			return f"Tests: fix failing tests before committing -- {names}{suffix}"
		return "Tests: pytest failed -- fix test failures before committing"

	if check.name == "mypy":
		# Extract error count
		error_match = re.search(r"Found (\d+) error", output)
		count = error_match.group(1) if error_match else "multiple"
		return f"Types: fix {count} mypy type error(s) before committing"

	if check.name == "bandit":
		# Extract severity levels
		severities = re.findall(r"Severity:\s+(High|Medium|Low)", output)
		if severities:
			high = severities.count("High")
			med = severities.count("Medium")
			if high:
				return f"Security: {high} high-severity bandit finding(s) -- fix before committing"
			return f"Security: {med} medium-severity bandit finding(s) -- review before committing"
		return "Security: bandit found issues -- review security findings before committing"

	return f"Verification: {check.name} failed -- review output and fix before committing"


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

		# Auto-log gotchas for verification failures
		gotchas_logged: list[str] = []
		if not result.passed and project_path:
			proj_dir = str(Path(project_path).expanduser())
			for check in result.checks:
				if check.status == CheckStatus.FAILED:
					gotcha = _derive_gotcha_from_failure(check)
					if gotcha:
						project_memory.log_gotcha(proj_dir, "dont", gotcha)
						gotchas_logged.append(gotcha)

		response = {
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
		}
		if gotchas_logged:
			response["gotchas_logged"] = gotchas_logged
			response["gotcha_note"] = "Verification failures have been logged as gotchas in CLAUDE.md"

		# Check if consensus review is recommended for high-stakes changes
		recommend_review, review_reason = _should_recommend_consensus_review(files_list)
		if recommend_review and result.passed:
			response["recommend_consensus_review"] = True
			response["consensus_review_reason"] = review_reason
			response["consensus_review_note"] = (
				"Consider running /verify-by-consensus for multi-agent review of these changes"
			)

		return json.dumps(response, indent=2)
