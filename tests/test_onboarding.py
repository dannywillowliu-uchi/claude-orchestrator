"""Tests for codebase onboarding module."""

from pathlib import Path

import pytest

from claude_orchestrator.orchestrator.onboarding import (
	CodebaseOnboarder,
)


@pytest.fixture
def onboarder():
	return CodebaseOnboarder()


@pytest.fixture
def python_project(tmp_path: Path) -> Path:
	"""Create a minimal Python project structure."""
	(tmp_path / "src").mkdir()
	(tmp_path / "src" / "main.py").write_text("print('hello')")
	(tmp_path / "src" / "utils.py").write_text("def helper(): pass")
	(tmp_path / "tests").mkdir()
	(tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass")
	(tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
	(tmp_path / "README.md").write_text("# Test Project")
	return tmp_path


@pytest.fixture
def js_project(tmp_path: Path) -> Path:
	"""Create a minimal JS project structure."""
	(tmp_path / "src").mkdir()
	(tmp_path / "src" / "index.js").write_text("console.log('hello')")
	(tmp_path / "package.json").write_text('{"name": "test"}')
	return tmp_path


class TestAnalyzeProject:
	"""Tests for analyze_project."""

	def test_analyze_python_project(self, onboarder, python_project):
		"""Should detect Python as primary language."""
		profile = onboarder.analyze_project(str(python_project))
		assert profile.primary_language == "python"
		assert "python" in profile.languages

	def test_analyze_project_name(self, onboarder, python_project):
		"""Should use directory name as project name."""
		profile = onboarder.analyze_project(str(python_project))
		assert profile.name == python_project.name

	def test_analyze_detects_entry_points(self, onboarder, python_project):
		"""Should detect main.py as entry point."""
		profile = onboarder.analyze_project(str(python_project))
		assert any("main.py" in ep for ep in profile.entry_points)

	def test_analyze_detects_key_files(self, onboarder, python_project):
		"""Should detect pyproject.toml and README.md."""
		profile = onboarder.analyze_project(str(python_project))
		assert "pyproject.toml" in profile.key_files
		assert "README.md" in profile.key_files

	def test_analyze_detects_tests(self, onboarder, python_project):
		"""Should detect tests directory."""
		profile = onboarder.analyze_project(str(python_project))
		assert profile.has_tests is True

	def test_analyze_no_tests(self, onboarder, tmp_path):
		"""Project without tests should report has_tests=False."""
		(tmp_path / "main.py").write_text("pass")
		profile = onboarder.analyze_project(str(tmp_path))
		assert profile.has_tests is False

	def test_analyze_counts_files(self, onboarder, python_project):
		"""Should count files in the project."""
		profile = onboarder.analyze_project(str(python_project))
		assert profile.file_count >= 4  # main.py, utils.py, test_main.py, pyproject.toml, README.md

	def test_analyze_js_project(self, onboarder, js_project):
		"""Should detect JavaScript project."""
		profile = onboarder.analyze_project(str(js_project))
		assert "javascript" in profile.languages

	def test_analyze_nonexistent_path(self, onboarder):
		"""Should raise FileNotFoundError for missing path."""
		with pytest.raises(FileNotFoundError):
			onboarder.analyze_project("/nonexistent/path")


class TestDetectLanguages:
	"""Tests for language detection."""

	def test_detect_multiple_languages(self, onboarder, tmp_path):
		"""Should detect multiple languages."""
		(tmp_path / "main.py").write_text("pass")
		(tmp_path / "script.js").write_text("//")
		profile = onboarder.analyze_project(str(tmp_path))
		assert len(profile.languages) >= 2

	def test_empty_project(self, onboarder, tmp_path):
		"""Empty project should have no languages."""
		profile = onboarder.analyze_project(str(tmp_path))
		assert profile.languages == []
		assert profile.primary_language is None


class TestDetectCapabilities:
	"""Tests for CI and Docker detection."""

	def test_detect_github_ci(self, onboarder, tmp_path):
		"""Should detect GitHub Actions CI."""
		workflows = tmp_path / ".github" / "workflows"
		workflows.mkdir(parents=True)
		(workflows / "ci.yml").write_text("name: CI")
		profile = onboarder.analyze_project(str(tmp_path))
		assert profile.has_ci is True

	def test_detect_docker(self, onboarder, tmp_path):
		"""Should detect Dockerfile."""
		(tmp_path / "Dockerfile").write_text("FROM python:3.11")
		profile = onboarder.analyze_project(str(tmp_path))
		assert profile.has_docker is True

	def test_no_ci_or_docker(self, onboarder, tmp_path):
		"""Should report False when no CI/Docker found."""
		(tmp_path / "main.py").write_text("pass")
		profile = onboarder.analyze_project(str(tmp_path))
		assert profile.has_ci is False
		assert profile.has_docker is False


class TestStubs:
	"""Tests for not-yet-implemented methods."""

	def test_generate_ast_summary_raises(self, onboarder):
		"""generate_ast_summary should raise NotImplementedError."""
		with pytest.raises(NotImplementedError):
			onboarder.generate_ast_summary("/some/path")

	def test_generate_onboarding_prompt_raises(self, onboarder):
		"""generate_onboarding_prompt should raise NotImplementedError."""
		with pytest.raises(NotImplementedError):
			onboarder.generate_onboarding_prompt("/some/path")
