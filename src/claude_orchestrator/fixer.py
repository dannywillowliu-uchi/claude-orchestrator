"""Self-correcting fixer: analyzes verification results and creates fix tasks.

The fixer is a post-verification step that classifies issues into critical
(block commit) vs non-critical (create fix tasks, commit proceeds). Includes
a circuit breaker to escalate when too many issues accumulate.

Error tiers (from protocol):
- Critical: pytest failures, mypy type errors, bandit security findings
- Non-critical: ruff style warnings, minor formatting
"""

import re
from dataclasses import dataclass, field

CRITICAL_CHECKS = {"pytest", "mypy", "bandit"}
NON_CRITICAL_CHECKS = {"ruff"}

# Circuit breaker threshold: escalate if more than this many fix tasks
CIRCUIT_BREAKER_THRESHOLD = 5


@dataclass
class FixTask:
	"""A single corrective task created by the fixer."""

	check_name: str
	severity: str  # "critical" or "non-critical"
	description: str
	file_path: str = ""
	rule_code: str = ""
	suggested_action: str = ""


@dataclass
class FixerResult:
	"""Result of fixer analysis on verification output."""

	fix_tasks: list[FixTask] = field(default_factory=list)
	critical_count: int = 0
	non_critical_count: int = 0
	should_block: bool = False
	circuit_breaker_triggered: bool = False
	summary: str = ""


def analyze_verification(
	checks: list[dict[str, object]],
	circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD,
) -> FixerResult:
	"""Analyze verification check results and produce fix tasks.

	Args:
		checks: List of check result dicts with keys:
			name (str), status (str), output_preview (str)
		circuit_breaker_threshold: Max non-critical tasks before escalation.

	Returns:
		FixerResult with classified fix tasks and action recommendations.
	"""
	result = FixerResult()

	for check in checks:
		name = str(check.get("name", ""))
		status = str(check.get("status", ""))
		output = str(check.get("output_preview", ""))

		if status in ("passed", "skipped"):
			continue

		if name in CRITICAL_CHECKS:
			tasks = _extract_critical_tasks(name, output)
			result.fix_tasks.extend(tasks)
			result.critical_count += len(tasks)
		elif name in NON_CRITICAL_CHECKS:
			tasks = _extract_non_critical_tasks(name, output)
			result.fix_tasks.extend(tasks)
			result.non_critical_count += len(tasks)
		else:
			# Unknown check type -- treat as non-critical
			result.fix_tasks.append(FixTask(
				check_name=name,
				severity="non-critical",
				description=f"{name} check failed",
				suggested_action=f"Review {name} output and fix issues",
			))
			result.non_critical_count += 1

	result.should_block = result.critical_count > 0
	result.circuit_breaker_triggered = (
		result.non_critical_count > circuit_breaker_threshold
	)

	# Build summary
	parts = []
	if result.critical_count:
		parts.append(f"{result.critical_count} critical")
	if result.non_critical_count:
		parts.append(f"{result.non_critical_count} non-critical")
	if not parts:
		result.summary = "No issues found"
	else:
		result.summary = f"{', '.join(parts)} issue(s) found"
		if result.should_block:
			result.summary += " -- commit BLOCKED (fix critical issues first)"
		elif result.circuit_breaker_triggered:
			result.summary += (
				f" -- ESCALATE (>{circuit_breaker_threshold} non-critical issues)"
			)
		else:
			result.summary += " -- commit may proceed, fix tasks created"

	return result


def _extract_critical_tasks(check_name: str, output: str) -> list[FixTask]:
	"""Extract fix tasks from critical check failures."""
	tasks: list[FixTask] = []

	if check_name == "pytest":
		# Extract FAILED test::name patterns
		failed = re.findall(r"FAILED\s+(\S+)", output)
		if failed:
			for test in failed[:10]:
				tasks.append(FixTask(
					check_name="pytest",
					severity="critical",
					description=f"Test failure: {test}",
					file_path=test.split("::")[0] if "::" in test else "",
					suggested_action="Fix the failing test or the code it tests",
				))
		else:
			tasks.append(FixTask(
				check_name="pytest",
				severity="critical",
				description="pytest failed (could not parse specific failures)",
				suggested_action="Run pytest locally and fix failures",
			))

	elif check_name == "mypy":
		# Extract file:line: error patterns
		errors = re.findall(r"(\S+\.py):(\d+):\s*error:\s*(.+?)(?:\s+\[|$)", output)
		if errors:
			for filepath, _line, msg in errors[:10]:
				tasks.append(FixTask(
					check_name="mypy",
					severity="critical",
					description=f"Type error: {msg.strip()}",
					file_path=filepath,
					suggested_action="Fix the type annotation or value",
				))
		else:
			tasks.append(FixTask(
				check_name="mypy",
				severity="critical",
				description="mypy type check failed",
				suggested_action="Run mypy locally and fix type errors",
			))

	elif check_name == "bandit":
		# Extract severity indicators
		findings = re.findall(
			r"Severity:\s+(High|Medium)\s+.*?Confidence:\s+\w+",
			output,
			re.DOTALL,
		)
		if findings:
			for severity in findings[:10]:
				tasks.append(FixTask(
					check_name="bandit",
					severity="critical",
					description=f"Security finding ({severity} severity)",
					suggested_action="Review and fix security vulnerability",
				))
		else:
			tasks.append(FixTask(
				check_name="bandit",
				severity="critical",
				description="bandit security scan found issues",
				suggested_action="Review bandit output for security findings",
			))

	return tasks


def _extract_non_critical_tasks(check_name: str, output: str) -> list[FixTask]:
	"""Extract fix tasks from non-critical check failures."""
	tasks: list[FixTask] = []

	if check_name == "ruff":
		# Extract file:line: CODE description patterns
		violations = re.findall(
			r"(\S+\.py):(\d+):\d+:\s+([A-Z]\d{3,4})\s+(.+)",
			output,
		)
		if violations:
			# Group by rule code to avoid duplicate tasks
			seen_codes: dict[str, FixTask] = {}
			for filepath, _line, code, msg in violations:
				if code not in seen_codes:
					seen_codes[code] = FixTask(
						check_name="ruff",
						severity="non-critical",
						description=f"Style: {code} {msg.strip()}",
						file_path=filepath,
						rule_code=code,
						suggested_action=f"Fix {code} violation or run `ruff check --fix`",
					)
			tasks.extend(seen_codes.values())
		else:
			tasks.append(FixTask(
				check_name="ruff",
				severity="non-critical",
				description="ruff style check failed",
				suggested_action="Run `ruff check --fix` to auto-fix style issues",
			))

	return tasks
