"""Verification tools - pre-commit verification gate."""

import json
import logging
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .. import project_memory
from ..config import Config
from ..fixer import analyze_verification
from ..fixer import track_convergence as _track_convergence
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


def register_verification_tools(mcp: FastMCP, config: Config) -> None:
	"""Register verification tools."""

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

		response: dict[str, object] = {
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

	@mcp.tool()
	async def suggest_fixes(
		verification_json: str,
		circuit_breaker_threshold: int = 5,
	) -> str:
		"""
		Analyze verification results and suggest corrective fix tasks.

		Call this after run_verification when it reports failures. Classifies
		issues as critical (block commit) or non-critical (create fix tasks,
		commit proceeds). Includes a circuit breaker that triggers when too
		many non-critical issues accumulate.

		Args:
			verification_json: JSON string from run_verification output
			circuit_breaker_threshold: Max non-critical tasks before escalation (default 5)
		"""
		try:
			verification = json.loads(verification_json)
		except json.JSONDecodeError:
			return json.dumps({"error": "Invalid JSON input"})

		checks = verification.get("checks", [])
		result = analyze_verification(checks, circuit_breaker_threshold)

		response = {
			"should_block": result.should_block,
			"circuit_breaker_triggered": result.circuit_breaker_triggered,
			"critical_count": result.critical_count,
			"non_critical_count": result.non_critical_count,
			"summary": result.summary,
			"fix_tasks": [
				{
					"check": t.check_name,
					"severity": t.severity,
					"description": t.description,
					"file_path": t.file_path,
					"rule_code": t.rule_code,
					"action": t.suggested_action,
				}
				for t in result.fix_tasks
			],
		}
		return json.dumps(response, indent=2)

	@mcp.tool()
	async def track_convergence(
		verification_history_json: str,
		tolerance: int = 2,
	) -> str:
		"""
		Analyze error trends across multiple verification runs.

		Call this after 2+ fix attempts to determine whether errors are
		converging (decreasing), stable, or diverging (increasing). Returns
		a recommendation: continue_fixing, accept_and_commit, or escalate.

		Args:
			verification_history_json: JSON array of previous suggest_fixes outputs (chronological)
			tolerance: Number of stable runs before accepting non-critical-only state (default 2)
		"""
		try:
			history = json.loads(verification_history_json)
		except json.JSONDecodeError:
			return json.dumps({"error": "Invalid JSON input"})

		if not isinstance(history, list):
			return json.dumps({"error": "Expected a JSON array of verification results"})

		result = _track_convergence(history, tolerance)

		response = {
			"trend": result.trend,
			"runs_analyzed": result.runs_analyzed,
			"recommendation": result.recommendation,
			"errors_fixed": result.errors_fixed,
			"errors_new": result.errors_new,
			"errors_persistent": result.errors_persistent,
		}
		return json.dumps(response, indent=2)
