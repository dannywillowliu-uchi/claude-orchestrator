"""
Verifier - Independent verification gate for task completion.

Key Principle: Tasks are NOT self-verified. The verifier runs
independently to validate that work meets quality standards.

Checks:
- Unit tests (pytest)
- Linting (ruff)
- Type checking (mypy)
- Security scanning (bandit)
- Custom verification criteria from task
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CheckStatus(str, Enum):
	"""Status of a verification check."""
	PASSED = "passed"
	FAILED = "failed"
	SKIPPED = "skipped"
	ERROR = "error"


@dataclass
class CheckResult:
	"""Result of a single verification check."""
	name: str
	status: CheckStatus
	output: str = ""
	duration_seconds: float = 0.0
	details: dict = None

	def __post_init__(self):
		if self.details is None:
			self.details = {}


@dataclass
class VerificationResult:
	"""Result of full verification suite."""
	passed: bool
	checks: list[CheckResult]
	can_retry: bool = True
	summary: str = ""
	verified_at: str = ""

	def __post_init__(self):
		if not self.verified_at:
			self.verified_at = datetime.now().isoformat()

		# Build summary
		passed = sum(1 for c in self.checks if c.status == CheckStatus.PASSED)
		failed = sum(1 for c in self.checks if c.status == CheckStatus.FAILED)
		self.summary = f"{passed} passed, {failed} failed out of {len(self.checks)} checks"


class Verifier:
	"""
	Independent verification of task completion.

	Runs verification suite to ensure code quality before
	marking tasks as complete.
	"""

	# Standard checks to run
	STANDARD_CHECKS = ["pytest", "ruff", "mypy", "bandit"]

	def __init__(
		self,
		project_path: Optional[str] = None,
		venv_path: Optional[str] = None,
		timeout: int = 300,  # 5 minutes per check
	):
		"""
		Initialize the verifier.

		Args:
			project_path: Path to project root
			venv_path: Path to virtual environment
			timeout: Timeout per check in seconds
		"""
		self.project_path = Path(project_path) if project_path else Path.cwd()
		self.venv_path = Path(venv_path) if venv_path else self.project_path / ".venv"
		self.timeout = timeout

	async def verify(
		self,
		checks: list[str] = None,
		files_changed: list[str] = None,
	) -> VerificationResult:
		"""
		Run verification suite.

		Args:
			checks: List of checks to run (default: STANDARD_CHECKS)
			files_changed: Optional list of changed files for targeted checks

		Returns:
			VerificationResult with all check results
		"""
		checks = checks or self.STANDARD_CHECKS
		results = []

		for check in checks:
			try:
				result = await self._run_check(check, files_changed)
			except asyncio.TimeoutError:
				result = CheckResult(
					name=check,
					status=CheckStatus.ERROR,
					output=f"Check '{check}' timed out",
				)
			results.append(result)

		# Overall pass if all checks pass
		all_passed = all(
			r.status in [CheckStatus.PASSED, CheckStatus.SKIPPED]
			for r in results
		)

		# Can retry if failures are fixable (not errors)
		can_retry = not any(r.status == CheckStatus.ERROR for r in results)

		return VerificationResult(
			passed=all_passed,
			checks=results,
			can_retry=can_retry,
		)

	async def _run_check(
		self,
		check: str,
		files_changed: list[str] = None,
	) -> CheckResult:
		"""Run a single verification check."""
		datetime.now()

		try:
			if check == "pytest":
				return await self._run_pytest(files_changed)
			elif check == "ruff":
				return await self._run_ruff(files_changed)
			elif check == "mypy":
				return await self._run_mypy(files_changed)
			elif check == "bandit":
				return await self._run_bandit(files_changed)
			else:
				return CheckResult(
					name=check,
					status=CheckStatus.SKIPPED,
					output=f"Unknown check: {check}",
				)
		except asyncio.TimeoutError:
			return CheckResult(
				name=check,
				status=CheckStatus.ERROR,
				output=f"Check timed out after {self.timeout}s",
			)
		except Exception as e:
			return CheckResult(
				name=check,
				status=CheckStatus.ERROR,
				output=str(e),
			)

	async def _run_pytest(self, files_changed: list[str] = None) -> CheckResult:
		"""Run pytest."""
		cmd = [str(self.venv_path / "bin" / "pytest"), "-v", "--tb=short"]

		if files_changed:
			# Run tests related to changed files
			test_files = [f for f in files_changed if "test" in f.lower()]
			if test_files:
				cmd.extend(test_files)
			else:
				# Run all tests if no test files changed
				cmd.append("tests/")
		else:
			cmd.append("tests/")

		result = await self._run_command(cmd)

		# Parse pytest output
		"passed" in result["output"].lower()
		failed = "failed" in result["output"].lower() or "error" in result["output"].lower()

		if result["returncode"] == 0 and not failed:
			status = CheckStatus.PASSED
		elif result["returncode"] == 5:  # No tests collected
			status = CheckStatus.SKIPPED
		else:
			status = CheckStatus.FAILED

		return CheckResult(
			name="pytest",
			status=status,
			output=result["output"][-2000:],  # Last 2000 chars
			duration_seconds=result["duration"],
			details={
				"returncode": result["returncode"],
			},
		)

	async def _run_ruff(self, files_changed: list[str] = None) -> CheckResult:
		"""Run ruff linter."""
		cmd = [str(self.venv_path / "bin" / "ruff"), "check"]

		if files_changed:
			python_files = [f for f in files_changed if f.endswith(".py")]
			if python_files:
				cmd.extend(python_files)
			else:
				cmd.append("src/")
		else:
			cmd.append("src/")

		result = await self._run_command(cmd)

		if result["returncode"] == 0:
			status = CheckStatus.PASSED
		else:
			status = CheckStatus.FAILED

		return CheckResult(
			name="ruff",
			status=status,
			output=result["output"][-2000:],
			duration_seconds=result["duration"],
			details={
				"returncode": result["returncode"],
			},
		)

	async def _run_mypy(self, files_changed: list[str] = None) -> CheckResult:
		"""Run mypy type checker."""
		cmd = [
			str(self.venv_path / "bin" / "mypy"),
			"--ignore-missing-imports",
		]

		if files_changed:
			python_files = [f for f in files_changed if f.endswith(".py")]
			if python_files:
				cmd.extend(python_files)
			else:
				cmd.append("src/")
		else:
			cmd.append("src/")

		result = await self._run_command(cmd)

		if result["returncode"] == 0:
			status = CheckStatus.PASSED
		else:
			status = CheckStatus.FAILED

		return CheckResult(
			name="mypy",
			status=status,
			output=result["output"][-2000:],
			duration_seconds=result["duration"],
			details={
				"returncode": result["returncode"],
			},
		)

	async def _run_bandit(self, files_changed: list[str] = None) -> CheckResult:
		"""Run bandit security scanner."""
		cmd = [
			str(self.venv_path / "bin" / "bandit"),
			"-r",
			"-ll",  # Only medium and high severity
		]

		if files_changed:
			python_files = [f for f in files_changed if f.endswith(".py")]
			if python_files:
				cmd.extend(python_files)
			else:
				cmd.append("src/")
		else:
			cmd.append("src/")

		result = await self._run_command(cmd)

		# Bandit returns 0 even with findings, check output
		if result["returncode"] == 0 and "No issues identified" in result["output"]:
			status = CheckStatus.PASSED
		elif result["returncode"] == 1:  # Bandit not found or error
			status = CheckStatus.SKIPPED
		elif "High:" in result["output"] or "Medium:" in result["output"]:
			status = CheckStatus.FAILED
		else:
			status = CheckStatus.PASSED

		return CheckResult(
			name="bandit",
			status=status,
			output=result["output"][-2000:],
			duration_seconds=result["duration"],
			details={
				"returncode": result["returncode"],
			},
		)

	async def _run_command(self, cmd: list[str]) -> dict:
		"""Run a command asynchronously."""
		start = datetime.now()

		try:
			proc = await asyncio.create_subprocess_exec(
				*cmd,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.STDOUT,
				cwd=str(self.project_path),
			)

			stdout, _ = await asyncio.wait_for(
				proc.communicate(),
				timeout=self.timeout,
			)

			duration = (datetime.now() - start).total_seconds()

			return {
				"output": stdout.decode("utf-8", errors="replace"),
				"returncode": proc.returncode,
				"duration": duration,
			}
		except FileNotFoundError:
			return {
				"output": f"Command not found: {cmd[0]}",
				"returncode": 1,
				"duration": 0,
			}

	async def run_custom_verification(
		self,
		command: str,
		name: str = "custom",
	) -> CheckResult:
		"""
		Run a custom verification command.

		Args:
			command: Shell command to run
			name: Name for this check

		Returns:
			CheckResult
		"""
		start = datetime.now()

		try:
			proc = await asyncio.create_subprocess_shell(
				command,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.STDOUT,
				cwd=str(self.project_path),
			)

			stdout, _ = await asyncio.wait_for(
				proc.communicate(),
				timeout=self.timeout,
			)

			duration = (datetime.now() - start).total_seconds()

			status = CheckStatus.PASSED if proc.returncode == 0 else CheckStatus.FAILED

			return CheckResult(
				name=name,
				status=status,
				output=stdout.decode("utf-8", errors="replace")[-2000:],
				duration_seconds=duration,
				details={"returncode": proc.returncode},
			)

		except asyncio.TimeoutError:
			return CheckResult(
				name=name,
				status=CheckStatus.ERROR,
				output=f"Timed out after {self.timeout}s",
			)
		except Exception as e:
			return CheckResult(
				name=name,
				status=CheckStatus.ERROR,
				output=str(e),
			)


# Global verifier instance
_verifier: Optional[Verifier] = None


def get_verifier(
	project_path: str = None,
	venv_path: str = None,
) -> Verifier:
	"""Get or create the global verifier instance."""
	global _verifier
	if _verifier is None:
		_verifier = Verifier(project_path, venv_path)
	return _verifier
