"""
Tests for the Verification phase of orchestration.

Tests:
- Verification suite execution
- Individual check results
- Custom verification commands
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from claude_orchestrator.orchestrator.verifier import (
	Verifier,
	CheckStatus,
	CheckResult,
	VerificationResult,
)


class TestVerifierInitialization:
	"""Tests for Verifier initialization."""

	def test_default_initialization(self):
		"""Test default verifier initialization."""
		verifier = Verifier()

		assert verifier.project_path == Path.cwd()
		assert verifier.timeout == 300

	def test_custom_initialization(self, tmp_path):
		"""Test verifier with custom paths."""
		verifier = Verifier(
			project_path=str(tmp_path),
			venv_path=str(tmp_path / "venv"),
			timeout=60,
		)

		assert verifier.project_path == tmp_path
		assert verifier.venv_path == tmp_path / "venv"
		assert verifier.timeout == 60


class TestCheckResult:
	"""Tests for CheckResult dataclass."""

	def test_check_result_creation(self):
		"""Test creating a check result."""
		result = CheckResult(
			name="pytest",
			status=CheckStatus.PASSED,
			output="All tests passed",
			duration_seconds=1.5,
		)

		assert result.name == "pytest"
		assert result.status == CheckStatus.PASSED
		assert result.output == "All tests passed"
		assert result.duration_seconds == 1.5
		assert result.details == {}  # Default empty dict

	def test_check_result_with_details(self):
		"""Test check result with details."""
		result = CheckResult(
			name="ruff",
			status=CheckStatus.FAILED,
			output="Found issues",
			details={"error_count": 5},
		)

		assert result.details["error_count"] == 5


class TestVerificationResult:
	"""Tests for VerificationResult dataclass."""

	def test_verification_result_passed(self):
		"""Test verification result when all checks pass."""
		checks = [
			CheckResult(name="pytest", status=CheckStatus.PASSED),
			CheckResult(name="ruff", status=CheckStatus.PASSED),
		]

		result = VerificationResult(passed=True, checks=checks)

		assert result.passed
		assert "2 passed, 0 failed" in result.summary
		assert result.can_retry

	def test_verification_result_failed(self):
		"""Test verification result with failures."""
		checks = [
			CheckResult(name="pytest", status=CheckStatus.PASSED),
			CheckResult(name="ruff", status=CheckStatus.FAILED),
		]

		result = VerificationResult(passed=False, checks=checks)

		assert not result.passed
		assert "1 passed, 1 failed" in result.summary

	def test_verification_result_with_skipped(self):
		"""Test verification result with skipped checks."""
		checks = [
			CheckResult(name="pytest", status=CheckStatus.PASSED),
			CheckResult(name="bandit", status=CheckStatus.SKIPPED),
		]

		# Skipped counts as passed
		result = VerificationResult(passed=True, checks=checks)

		assert result.passed


class TestVerifierChecks:
	"""Tests for individual verification checks."""

	@pytest.fixture
	def verifier(self, tmp_path):
		"""Create a verifier with a temp directory."""
		return Verifier(
			project_path=str(tmp_path),
			venv_path=str(tmp_path / ".venv"),
		)

	@pytest.mark.asyncio
	async def test_verify_runs_all_standard_checks(self, verifier):
		"""Test that verify runs all standard checks."""
		# Mock _run_command to simulate check outputs
		async def mock_run_command(cmd):
			return {
				"output": "All checks passed",
				"returncode": 0,
				"duration": 0.1,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier.verify()

		# Should have run all standard checks
		check_names = [c.name for c in result.checks]
		assert "pytest" in check_names
		assert "ruff" in check_names
		assert "mypy" in check_names
		assert "bandit" in check_names

	@pytest.mark.asyncio
	async def test_verify_with_specific_checks(self, verifier):
		"""Test running only specific checks."""
		async def mock_run_command(cmd):
			return {
				"output": "Passed",
				"returncode": 0,
				"duration": 0.1,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier.verify(checks=["pytest", "ruff"])

		check_names = [c.name for c in result.checks]
		assert len(check_names) == 2
		assert "pytest" in check_names
		assert "ruff" in check_names
		assert "mypy" not in check_names

	@pytest.mark.asyncio
	async def test_verify_skips_unknown_checks(self, verifier):
		"""Test that unknown checks are skipped."""
		async def mock_run_command(cmd):
			return {
				"output": "Passed",
				"returncode": 0,
				"duration": 0.1,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier.verify(checks=["unknown_check"])

		assert len(result.checks) == 1
		assert result.checks[0].status == CheckStatus.SKIPPED

	@pytest.mark.asyncio
	async def test_verify_handles_timeout(self, verifier):
		"""Test that verification handles timeouts."""
		async def mock_run_check(check, files=None):
			raise asyncio.TimeoutError()

		with patch.object(verifier, "_run_check", mock_run_check):
			result = await verifier.verify(checks=["pytest"])

		assert result.checks[0].status == CheckStatus.ERROR
		assert "timed out" in result.checks[0].output.lower()

	@pytest.mark.asyncio
	async def test_verify_with_files_changed(self, verifier):
		"""Test verification with specific changed files."""
		command_received = []

		async def mock_run_command(cmd):
			command_received.append(cmd)
			return {
				"output": "Passed",
				"returncode": 0,
				"duration": 0.1,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			await verifier.verify(
				checks=["ruff"],
				files_changed=["src/main.py", "src/utils.py"],
			)

		# Command should include the specific files
		assert any("src/main.py" in str(cmd) for cmd in command_received)


class TestIndividualChecks:
	"""Tests for individual check implementations."""

	@pytest.fixture
	def verifier(self, tmp_path):
		return Verifier(
			project_path=str(tmp_path),
			venv_path=str(tmp_path / ".venv"),
		)

	@pytest.mark.asyncio
	async def test_pytest_passed(self, verifier):
		"""Test pytest check when tests pass."""
		async def mock_run_command(cmd):
			return {
				"output": "5 passed in 1.0s",
				"returncode": 0,
				"duration": 1.0,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_pytest()

		assert result.status == CheckStatus.PASSED

	@pytest.mark.asyncio
	async def test_pytest_failed(self, verifier):
		"""Test pytest check when tests fail."""
		async def mock_run_command(cmd):
			return {
				"output": "2 passed, 1 failed in 1.0s",
				"returncode": 1,
				"duration": 1.0,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_pytest()

		assert result.status == CheckStatus.FAILED

	@pytest.mark.asyncio
	async def test_pytest_no_tests(self, verifier):
		"""Test pytest check when no tests found."""
		async def mock_run_command(cmd):
			return {
				"output": "no tests ran",
				"returncode": 5,  # pytest exit code for no tests
				"duration": 0.1,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_pytest()

		assert result.status == CheckStatus.SKIPPED

	@pytest.mark.asyncio
	async def test_ruff_passed(self, verifier):
		"""Test ruff check when lint passes."""
		async def mock_run_command(cmd):
			return {
				"output": "",
				"returncode": 0,
				"duration": 0.3,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_ruff()

		assert result.status == CheckStatus.PASSED

	@pytest.mark.asyncio
	async def test_ruff_failed(self, verifier):
		"""Test ruff check when lint fails."""
		async def mock_run_command(cmd):
			return {
				"output": "Found 5 errors",
				"returncode": 1,
				"duration": 0.3,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_ruff()

		assert result.status == CheckStatus.FAILED

	@pytest.mark.asyncio
	async def test_mypy_passed(self, verifier):
		"""Test mypy check when type check passes."""
		async def mock_run_command(cmd):
			return {
				"output": "Success: no issues found",
				"returncode": 0,
				"duration": 1.2,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_mypy()

		assert result.status == CheckStatus.PASSED

	@pytest.mark.asyncio
	async def test_bandit_no_issues(self, verifier):
		"""Test bandit check when no security issues found."""
		async def mock_run_command(cmd):
			return {
				"output": "No issues identified",
				"returncode": 0,
				"duration": 0.8,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_bandit()

		assert result.status == CheckStatus.PASSED

	@pytest.mark.asyncio
	async def test_bandit_high_severity(self, verifier):
		"""Test bandit check when high severity issue found."""
		async def mock_run_command(cmd):
			return {
				"output": "High: Possible hardcoded password",
				"returncode": 0,
				"duration": 0.8,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier._run_bandit()

		assert result.status == CheckStatus.FAILED


class TestCustomVerification:
	"""Tests for custom verification commands."""

	@pytest.fixture
	def verifier(self, tmp_path):
		return Verifier(
			project_path=str(tmp_path),
			venv_path=str(tmp_path / ".venv"),
		)

	@pytest.mark.asyncio
	async def test_run_custom_verification_success(self, verifier, tmp_path):
		"""Test running a custom verification command."""
		# Create a simple script to run
		script = tmp_path / "check.sh"
		script.write_text("#!/bin/bash\necho 'All good'\nexit 0")
		script.chmod(0o755)

		result = await verifier.run_custom_verification(
			command=f"bash {script}",
			name="custom-check",
		)

		assert result.name == "custom-check"
		assert result.status == CheckStatus.PASSED

	@pytest.mark.asyncio
	async def test_run_custom_verification_failure(self, verifier, tmp_path):
		"""Test custom verification that fails."""
		result = await verifier.run_custom_verification(
			command="exit 1",
			name="failing-check",
		)

		assert result.status == CheckStatus.FAILED

	@pytest.mark.asyncio
	async def test_run_custom_verification_timeout(self, verifier):
		"""Test custom verification timeout."""
		verifier.timeout = 1  # 1 second timeout

		result = await verifier.run_custom_verification(
			command="sleep 10",
			name="slow-check",
		)

		assert result.status == CheckStatus.ERROR
		assert "timed out" in result.output.lower()


class TestVerificationIntegration:
	"""Integration tests for verification flow."""

	@pytest.mark.asyncio
	async def test_full_verification_flow(self, tmp_path):
		"""Test a complete verification flow."""
		# Create project structure
		src_dir = tmp_path / "src"
		src_dir.mkdir()
		(src_dir / "main.py").write_text("def hello(): return 'world'")

		tests_dir = tmp_path / "tests"
		tests_dir.mkdir()
		(tests_dir / "test_main.py").write_text(
			"def test_hello(): assert True"
		)

		verifier = Verifier(
			project_path=str(tmp_path),
			timeout=30,
		)

		# Mock the command runner since we don't have a real venv
		async def mock_run_command(cmd):
			return {
				"output": "All passed",
				"returncode": 0,
				"duration": 0.5,
			}

		with patch.object(verifier, "_run_command", mock_run_command):
			result = await verifier.verify()

		assert result.passed
		assert all(c.status in [CheckStatus.PASSED, CheckStatus.SKIPPED] for c in result.checks)
