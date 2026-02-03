"""Tests for the orchestrator tools module.

These tests cover gotcha derivation and verification-gotcha integration.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_orchestrator.orchestrator.verifier import CheckResult, CheckStatus
from claude_orchestrator.tools.orchestrator import (
	_derive_gotcha_from_failure,
	_should_recommend_consensus_review,
)

# ---------------------------------------------------------------------------
# _derive_gotcha_from_failure
# ---------------------------------------------------------------------------

class TestDeriveGotchaFromFailure:
	def test_ruff_extracts_unique_rule_codes(self):
		check = CheckResult(
			name="ruff",
			status=CheckStatus.FAILED,
			output=(
				"src/foo.py:1:1 E501 Line too long\n"
				"src/foo.py:5:1 E501 Line too long\n"  # duplicate
				"src/bar.py:3:1 F841 Local variable unused\n"
				"src/bar.py:7:1 I001 Import block unsorted"
			),
		)
		result = _derive_gotcha_from_failure(check)
		assert "E501" in result
		assert "F841" in result
		assert "I001" in result
		# Should be deduplicated
		assert result.count("E501") == 1

	def test_ruff_no_codes_still_produces_gotcha(self):
		check = CheckResult(
			name="ruff", status=CheckStatus.FAILED,
			output="error: invalid configuration",
		)
		result = _derive_gotcha_from_failure(check)
		assert result is not None
		assert "ruff" in result.lower()

	def test_pytest_extracts_test_names(self):
		check = CheckResult(
			name="pytest",
			status=CheckStatus.FAILED,
			output=(
				"FAILED tests/test_auth.py::test_login - AssertionError\n"
				"FAILED tests/test_auth.py::test_logout - KeyError\n"
				"FAILED tests/test_perms.py::test_admin - ValueError"
			),
		)
		result = _derive_gotcha_from_failure(check)
		assert "test_auth.py" in result
		assert "test_perms.py" in result

	def test_pytest_truncates_many_failures(self):
		# More than 3 failures should show "+N more"
		lines = [f"FAILED tests/test_{i}.py::test_fn - Error" for i in range(10)]
		check = CheckResult(
			name="pytest", status=CheckStatus.FAILED,
			output="\n".join(lines),
		)
		result = _derive_gotcha_from_failure(check)
		assert "+7 more" in result

	def test_mypy_extracts_error_count(self):
		check = CheckResult(
			name="mypy",
			status=CheckStatus.FAILED,
			output="src/auth.py:10: error: Incompatible types\nFound 5 errors in 2 files",
		)
		result = _derive_gotcha_from_failure(check)
		assert "5" in result

	def test_mypy_no_count_still_works(self):
		check = CheckResult(
			name="mypy", status=CheckStatus.FAILED,
			output="src/auth.py:10: error: Something wrong",
		)
		result = _derive_gotcha_from_failure(check)
		assert result is not None
		assert "mypy" in result.lower() or "type" in result.lower()

	def test_bandit_high_severity(self):
		check = CheckResult(
			name="bandit",
			status=CheckStatus.FAILED,
			output=(
				">> Issue: [B105:hardcoded_password_string]\n"
				"   Severity: High\n"
				"   Confidence: Medium\n"
				">> Issue: [B106:hardcoded_password_funcarg]\n"
				"   Severity: High\n"
			),
		)
		result = _derive_gotcha_from_failure(check)
		assert "2" in result  # 2 high-severity
		assert "high" in result.lower()

	def test_bandit_medium_only(self):
		check = CheckResult(
			name="bandit", status=CheckStatus.FAILED,
			output=">> Issue: [B101]\n   Severity: Medium\n   Confidence: High",
		)
		result = _derive_gotcha_from_failure(check)
		assert "medium" in result.lower()

	def test_unknown_checker_produces_generic_gotcha(self):
		check = CheckResult(
			name="eslint", status=CheckStatus.FAILED,
			output="3 problems found",
		)
		result = _derive_gotcha_from_failure(check)
		assert "eslint" in result

	def test_empty_output_returns_none(self):
		check = CheckResult(name="ruff", status=CheckStatus.FAILED, output="")
		assert _derive_gotcha_from_failure(check) is None

	def test_long_output_is_truncated_before_parsing(self):
		# Output > 2000 chars should still work
		check = CheckResult(
			name="ruff", status=CheckStatus.FAILED,
			output="src/x.py:1:1 E501 Line too long\n" * 500,
		)
		result = _derive_gotcha_from_failure(check)
		assert result is not None
		assert "E501" in result


# ---------------------------------------------------------------------------
# TestVerificationGotchaIntegration
# ---------------------------------------------------------------------------

class TestVerificationGotchaIntegration:
	"""Test that run_verification auto-logs gotchas on failure."""

	def _capture_orchestrator_tools(self):
		from claude_orchestrator.tools.orchestrator import register_orchestrator_tools

		captured = {}

		class MockMCP:
			def tool(self):
				def decorator(fn):
					captured[fn.__name__] = fn
					return fn
				return decorator

		register_orchestrator_tools(MockMCP(), MagicMock())
		return captured

	def _make_mock_verifier(self, checks: list[CheckResult], passed: bool = False):
		mock_result = MagicMock()
		mock_result.passed = passed
		mock_result.summary = f"{'all passed' if passed else 'failures found'}"
		mock_result.can_retry = not passed
		mock_result.verified_at = "2026-02-02T00:00:00"
		mock_result.checks = checks

		mock_cls = MagicMock()
		mock_cls.return_value.verify = AsyncMock(return_value=mock_result)
		return mock_cls

	@pytest.mark.asyncio
	async def test_failed_ruff_logs_gotcha_to_claude_md(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()
		claude_md = proj / "CLAUDE.md"
		claude_md.write_text("# Project\n\n## Gotchas & Learnings\n\n")

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier([
			CheckResult(name="ruff", status=CheckStatus.FAILED,
				output="src/foo.py:1:1 E501 Line too long\nsrc/bar.py:3:1 F841 Unused"),
		])

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](project_path=str(proj)))

		assert result["passed"] is False
		assert "gotchas_logged" in result
		assert any("E501" in g for g in result["gotchas_logged"])

		# Verify CLAUDE.md was actually modified
		content = claude_md.read_text()
		assert content != "# Project\n\n## Gotchas & Learnings\n\n"

	@pytest.mark.asyncio
	async def test_multiple_failures_log_multiple_gotchas(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()
		(proj / "CLAUDE.md").write_text("# P\n\n## Gotchas & Learnings\n\n")

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier([
			CheckResult(name="ruff", status=CheckStatus.FAILED,
				output="x.py:1:1 E501 too long"),
			CheckResult(name="mypy", status=CheckStatus.FAILED,
				output="x.py:1: error: Bad type\nFound 1 error in 1 file"),
			CheckResult(name="pytest", status=CheckStatus.PASSED, output="3 passed"),
		])

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](project_path=str(proj)))

		gotchas = result["gotchas_logged"]
		assert len(gotchas) == 2  # ruff + mypy, not pytest (it passed)

	@pytest.mark.asyncio
	async def test_passing_verification_logs_no_gotchas(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier(
			[CheckResult(name="pytest", status=CheckStatus.PASSED, output="5 passed")],
			passed=True,
		)

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](project_path=str(proj)))

		assert result["passed"] is True
		assert "gotchas_logged" not in result

	@pytest.mark.asyncio
	async def test_no_project_path_skips_gotcha_logging(self, tmp_path: Path):
		"""Gotchas require project_path to know where CLAUDE.md is."""
		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier([
			CheckResult(name="ruff", status=CheckStatus.FAILED,
				output="x.py:1:1 E501 too long"),
		])

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](project_path=""))

		assert result["passed"] is False
		assert "gotchas_logged" not in result


# ---------------------------------------------------------------------------
# _should_recommend_consensus_review
# ---------------------------------------------------------------------------

class TestConsensusReviewRecommendation:
	def test_empty_files_returns_false(self):
		recommend, reason = _should_recommend_consensus_review(None)
		assert recommend is False
		assert reason == ""

	def test_empty_list_returns_false(self):
		recommend, reason = _should_recommend_consensus_review([])
		assert recommend is False
		assert reason == ""

	def test_security_file_triggers_recommendation(self):
		files = ["src/auth.py"]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is True
		assert "security-sensitive" in reason
		assert "auth.py" in reason

	def test_security_patterns_case_insensitive(self):
		files = ["src/Authentication.py", "lib/CryptoUtils.js"]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is True
		assert "security-sensitive" in reason

	def test_architecture_file_triggers_recommendation(self):
		files = ["config.py"]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is True
		assert "architecture" in reason

	def test_multi_file_changes_triggers_recommendation(self):
		files = [f"src/file{i}.py" for i in range(6)]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is True
		assert "6 files changed" in reason

	def test_four_files_does_not_trigger(self):
		files = ["a.py", "b.py", "c.py", "d.py"]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is False

	def test_multiple_reasons_combined(self):
		files = ["auth.py", "config.py", "a.py", "b.py", "c.py", "d.py", "e.py"]
		recommend, reason = _should_recommend_consensus_review(files)
		assert recommend is True
		assert "security-sensitive" in reason
		assert "architecture" in reason
		assert "7 files" in reason


class TestRunVerificationConsensusReview(TestVerificationGotchaIntegration):
	"""Test that run_verification recommends consensus review for high-stakes changes."""

	@pytest.mark.asyncio
	async def test_passing_with_security_files_recommends_review(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier(
			[CheckResult(name="pytest", status=CheckStatus.PASSED, output="5 passed")],
			passed=True,
		)

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](
				project_path=str(proj),
				files_changed="src/auth.py,src/login.py",
			))

		assert result["passed"] is True
		assert result.get("recommend_consensus_review") is True
		assert "security-sensitive" in result.get("consensus_review_reason", "")

	@pytest.mark.asyncio
	async def test_failing_verification_does_not_recommend_review(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()
		(proj / "CLAUDE.md").write_text("# P\n\n## Gotchas & Learnings\n\n")

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier([
			CheckResult(name="pytest", status=CheckStatus.FAILED, output="FAILED test_auth"),
		])

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](
				project_path=str(proj),
				files_changed="src/auth.py",
			))

		assert result["passed"] is False
		assert "recommend_consensus_review" not in result

	@pytest.mark.asyncio
	async def test_no_files_changed_no_recommendation(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier(
			[CheckResult(name="pytest", status=CheckStatus.PASSED, output="5 passed")],
			passed=True,
		)

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](project_path=str(proj)))

		assert result["passed"] is True
		assert "recommend_consensus_review" not in result

	@pytest.mark.asyncio
	async def test_ordinary_files_no_recommendation(self, tmp_path: Path):
		proj = tmp_path / "proj"
		proj.mkdir()

		tools = self._capture_orchestrator_tools()
		verifier_cls = self._make_mock_verifier(
			[CheckResult(name="pytest", status=CheckStatus.PASSED, output="5 passed")],
			passed=True,
		)

		with patch("claude_orchestrator.tools.orchestrator.Verifier", verifier_cls):
			result = json.loads(await tools["run_verification"](
				project_path=str(proj),
				files_changed="utils.py,helpers.py",
			))

		assert result["passed"] is True
		assert "recommend_consensus_review" not in result
