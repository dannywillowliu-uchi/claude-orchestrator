"""Tests for hooks module - task-specific permission profiles."""

import pytest

from claude_orchestrator.hooks import (
	HooksConfig,
	PROFILES,
	READ_ONLY,
	CODE_EDIT,
	TEST_RUN,
	FULL_ACCESS,
	get_profile,
	generate_hooks_for_task,
)
from claude_orchestrator.orchestrator.supervisor import Supervisor


class TestHooksConfig:
	"""Tests for HooksConfig dataclass."""

	def test_to_allowed_tools_list(self):
		"""allowed tools list should match allow_patterns."""
		config = HooksConfig(
			name="test",
			description="test",
			allow_patterns=["Read", "Glob", "Grep"],
		)
		assert config.to_allowed_tools_list() == ["Read", "Glob", "Grep"]

	def test_is_full_access_true(self):
		"""full_access profile should report is_full_access=True."""
		assert FULL_ACCESS.is_full_access is True

	def test_is_full_access_false(self):
		"""Non-full_access profiles should report is_full_access=False."""
		assert READ_ONLY.is_full_access is False
		assert CODE_EDIT.is_full_access is False
		assert TEST_RUN.is_full_access is False

	def test_empty_allow_patterns_for_full_access(self):
		"""full_access should have no allow_patterns (uses --dangerously-skip-permissions)."""
		assert FULL_ACCESS.to_allowed_tools_list() == []


class TestPredefinedProfiles:
	"""Tests for predefined profiles."""

	def test_all_profiles_registered(self):
		"""All predefined profiles should be in PROFILES dict."""
		assert "read_only" in PROFILES
		assert "code_edit" in PROFILES
		assert "test_run" in PROFILES
		assert "full_access" in PROFILES

	def test_read_only_has_read_tools(self):
		"""read_only should include Read, Glob, Grep."""
		tools = READ_ONLY.to_allowed_tools_list()
		assert "Read" in tools
		assert "Glob" in tools
		assert "Grep" in tools

	def test_code_edit_has_write_tools(self):
		"""code_edit should include Edit and Write."""
		tools = CODE_EDIT.to_allowed_tools_list()
		assert "Edit" in tools
		assert "Write" in tools

	def test_test_run_has_bash(self):
		"""test_run should include Bash."""
		tools = TEST_RUN.to_allowed_tools_list()
		assert "Bash" in tools

	def test_get_profile_valid(self):
		"""get_profile should return the correct profile."""
		assert get_profile("read_only") is READ_ONLY
		assert get_profile("full_access") is FULL_ACCESS

	def test_get_profile_invalid(self):
		"""get_profile should return None for unknown names."""
		assert get_profile("nonexistent") is None


class TestGenerateHooksForTask:
	"""Tests for keyword-based profile selection."""

	def test_read_task(self):
		"""'read' keyword should map to read_only."""
		config = generate_hooks_for_task("Read the configuration files")
		assert config.name == "read_only"

	def test_search_task(self):
		"""'search' keyword should map to read_only."""
		config = generate_hooks_for_task("Search for error patterns")
		assert config.name == "read_only"

	def test_test_task(self):
		"""'test' keyword should map to test_run."""
		config = generate_hooks_for_task("Run the test suite")
		assert config.name == "test_run"

	def test_implement_task(self):
		"""'implement' keyword should map to code_edit."""
		config = generate_hooks_for_task("Implement the new feature")
		assert config.name == "code_edit"

	def test_fix_task(self):
		"""'fix' keyword should map to code_edit."""
		config = generate_hooks_for_task("Fix the login bug")
		assert config.name == "code_edit"

	def test_delete_task(self):
		"""'delete' keyword should map to full_access."""
		config = generate_hooks_for_task("Delete deprecated modules")
		assert config.name == "full_access"

	def test_deploy_task(self):
		"""'deploy' keyword should map to full_access."""
		config = generate_hooks_for_task("Deploy to production")
		assert config.name == "full_access"

	def test_unknown_defaults_to_code_edit(self):
		"""Unrecognized tasks should default to code_edit."""
		config = generate_hooks_for_task("Do something completely unique and novel")
		assert config.name == "code_edit"

	def test_case_insensitive(self):
		"""Keyword matching should be case-insensitive."""
		config = generate_hooks_for_task("SEARCH for patterns")
		assert config.name == "read_only"


class TestSupervisorHooksIntegration:
	"""Tests for supervisor hooks profile selection."""

	def test_supervisor_select_hooks_profile(self):
		"""Supervisor should delegate to generate_hooks_for_task."""
		supervisor = Supervisor()
		profile = supervisor.select_hooks_profile("Read the docs")
		assert profile.name == "read_only"

	def test_supervisor_select_hooks_profile_code(self):
		"""Supervisor should select code_edit for implementation tasks."""
		supervisor = Supervisor()
		profile = supervisor.select_hooks_profile("Implement auth module")
		assert profile.name == "code_edit"
