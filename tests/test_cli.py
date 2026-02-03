"""Tests for the CLI module."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_orchestrator.cli import (
	DEFAULT_SEED_SOURCES,
	PERMISSION_RULE,
	_check_config_toml,
	_check_optional_extras,
	_check_secrets_json,
	_get_bundled_claude_md,
	_inject_claude_code_permissions,
	_inject_mcp_config,
	_install_agents,
	_install_claude_md,
	cmd_doctor,
	cmd_init_project,
	cmd_install_agents,
	cmd_seed_docs,
	main,
)


def test_inject_mcp_config_creates_entry(tmp_path: Path):
	"""MCP config injection should add the server entry."""
	config_file = tmp_path / "claude_code_config.json"
	config_file.write_text(json.dumps({"mcpServers": {}}))

	result = _inject_mcp_config(config_file)
	assert result is True

	data = json.loads(config_file.read_text())
	assert "claude-orchestrator" in data["mcpServers"]
	entry = data["mcpServers"]["claude-orchestrator"]
	assert entry["type"] == "stdio"
	assert entry["command"] == "claude-orchestrator"
	assert entry["args"] == ["serve"]


def test_inject_mcp_config_idempotent(tmp_path: Path):
	"""Injecting twice should not duplicate the entry."""
	config_file = tmp_path / "claude_code_config.json"
	config_file.write_text(json.dumps({"mcpServers": {}}))

	_inject_mcp_config(config_file)
	_inject_mcp_config(config_file)

	data = json.loads(config_file.read_text())
	assert len(data["mcpServers"]) == 1


def test_inject_mcp_config_creates_file(tmp_path: Path):
	"""Injection should work even if config file doesn't exist yet."""
	config_file = tmp_path / "new_config.json"
	assert not config_file.exists()

	result = _inject_mcp_config(config_file)
	assert result is True
	assert config_file.exists()

	data = json.loads(config_file.read_text())
	assert "claude-orchestrator" in data["mcpServers"]


def test_inject_mcp_config_preserves_existing(tmp_path: Path):
	"""Injection should not remove existing MCP entries."""
	config_file = tmp_path / "config.json"
	existing = {
		"mcpServers": {
			"other-server": {"type": "stdio", "command": "other"},
		},
		"someOtherKey": True,
	}
	config_file.write_text(json.dumps(existing))

	_inject_mcp_config(config_file)

	data = json.loads(config_file.read_text())
	assert "other-server" in data["mcpServers"]
	assert "claude-orchestrator" in data["mcpServers"]
	assert data["someOtherKey"] is True


def test_seed_docs_subparser_registered():
	"""seed-docs subparser should be registered in the CLI."""
	with patch("sys.argv", ["claude-orchestrator", "seed-docs", "--help"]):
		try:
			main()
		except SystemExit as e:
			# --help causes SystemExit(0)
			assert e.code == 0


def test_seed_docs_source_flag():
	"""seed-docs should accept --source flag."""
	with patch("sys.argv", ["claude-orchestrator", "seed-docs", "--source", "anthropic-docs", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def test_default_seed_sources_defined():
	"""DEFAULT_SEED_SOURCES should contain expected sources."""
	names = [s["name"] for s in DEFAULT_SEED_SOURCES]
	assert "anthropic-docs" in names
	assert "mcp-docs" in names


def test_seed_docs_graceful_import_error():
	"""seed-docs should exit gracefully when knowledge extras are missing."""
	args = argparse.Namespace(source=None)

	with patch.dict("sys.modules", {"claude_orchestrator.knowledge": None, "claude_orchestrator.knowledge.retriever": None}):
		with patch("builtins.__import__", side_effect=ImportError("no knowledge")):
			try:
				cmd_seed_docs(args)
				assert False, "Should have called sys.exit"
			except SystemExit as e:
				assert e.code == 1


# --- Doctor command tests ---

class TestCheckConfigToml:
	"""Tests for config.toml validation."""

	def test_missing_toml(self, tmp_path: Path):
		status, issue = _check_config_toml(tmp_path)
		assert "not found" in status
		assert issue is None

	def test_valid_toml(self, tmp_path: Path):
		(tmp_path / "config.toml").write_text('projects_path = "~/projects"\n')
		status, issue = _check_config_toml(tmp_path)
		assert status == "valid"
		assert issue is None

	def test_invalid_toml(self, tmp_path: Path):
		(tmp_path / "config.toml").write_text("this is [not valid toml\n")
		status, issue = _check_config_toml(tmp_path)
		assert "INVALID" in status
		assert issue is not None


class TestCheckSecretsJson:
	"""Tests for secrets.json validation."""

	def test_missing_secrets(self, tmp_path: Path):
		status, issue = _check_secrets_json(tmp_path / "secrets.json")
		assert "not found" in status
		assert issue is None

	def test_valid_secrets(self, tmp_path: Path):
		secrets_file = tmp_path / "secrets.json"
		secrets_file.write_text(json.dumps({
			"keys": {
				"openai": {"value": "sk-...", "active": True},
				"github": {"value": "ghp-...", "active": False},
			}
		}))
		status, issue = _check_secrets_json(secrets_file)
		assert "2 secrets" in status
		assert "1 active" in status
		assert issue is None

	def test_invalid_json(self, tmp_path: Path):
		secrets_file = tmp_path / "secrets.json"
		secrets_file.write_text("{broken json")
		status, issue = _check_secrets_json(secrets_file)
		assert "INVALID" in status
		assert issue is not None

	def test_legacy_string_format(self, tmp_path: Path):
		secrets_file = tmp_path / "secrets.json"
		secrets_file.write_text(json.dumps({
			"keys": {
				"openai": "sk-raw-string-value",
				"github": {"value": "ghp-...", "active": True},
			}
		}))
		status, issue = _check_secrets_json(secrets_file)
		assert "legacy" in status
		assert issue is not None


class TestCheckOptionalExtras:
	"""Tests for optional extras detection."""

	def test_returns_all_extras(self):
		results = _check_optional_extras()
		names = [name for name, _ in results]
		assert "visual" in names
		assert "knowledge" in names
		assert "web" in names

	def test_missing_extra_shows_install_command(self):
		"""Extras that aren't installed should show pip install command."""
		with patch("claude_orchestrator.cli.pkg_version", side_effect=Exception("not found")):
			results = _check_optional_extras()
			for name, status in results:
				assert "NOT INSTALLED" in status
				assert f"pip install claude-orchestrator[{name}]" in status


class TestInitProject:
	"""Tests for CLAUDE.md installation."""

	def test_bundled_claude_md_exists(self):
		"""Bundled CLAUDE.md should be readable from the package."""
		content = _get_bundled_claude_md()
		assert "claude-orchestrator" in content
		assert "run_verification" in content
		assert "telegram_notify" in content

	def test_install_creates_file(self, tmp_path: Path):
		"""install_claude_md should create CLAUDE.md in target dir."""
		created, msg = _install_claude_md(tmp_path)
		assert created is True
		assert (tmp_path / "CLAUDE.md").exists()
		content = (tmp_path / "CLAUDE.md").read_text()
		assert "claude-orchestrator" in content

	def test_install_skips_existing(self, tmp_path: Path):
		"""install_claude_md should not overwrite existing file."""
		(tmp_path / "CLAUDE.md").write_text("existing content")
		created, msg = _install_claude_md(tmp_path)
		assert created is False
		assert "Already exists" in msg
		assert (tmp_path / "CLAUDE.md").read_text() == "existing content"

	def test_cmd_init_project(self, tmp_path: Path):
		"""init-project command should install CLAUDE.md."""
		args = argparse.Namespace(path=str(tmp_path), force=False)
		cmd_init_project(args)
		assert (tmp_path / "CLAUDE.md").exists()

	def test_cmd_init_project_refuses_overwrite(self, tmp_path: Path):
		"""init-project should refuse to overwrite without --force."""
		(tmp_path / "CLAUDE.md").write_text("existing")
		args = argparse.Namespace(path=str(tmp_path), force=False)
		with pytest.raises(SystemExit) as exc_info:
			cmd_init_project(args)
		assert exc_info.value.code == 1

	def test_cmd_init_project_force_overwrites(self, tmp_path: Path):
		"""init-project --force should overwrite existing file."""
		(tmp_path / "CLAUDE.md").write_text("old content")
		args = argparse.Namespace(path=str(tmp_path), force=True)
		cmd_init_project(args)
		content = (tmp_path / "CLAUDE.md").read_text()
		assert "claude-orchestrator" in content

	def test_init_project_subparser_registered(self):
		"""init-project subparser should be registered in the CLI."""
		with patch("sys.argv", ["claude-orchestrator", "init-project", "--help"]):
			with pytest.raises(SystemExit) as exc_info:
				main()
			assert exc_info.value.code == 0


class TestInjectClaudeCodePermissions:
	"""Tests for Claude Code permission injection."""

	def test_creates_settings_file(self, tmp_path: Path):
		"""Should create settings.json if it doesn't exist."""
		settings = tmp_path / ".claude" / "settings.json"
		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			_inject_claude_code_permissions()
		assert settings.exists()
		data = json.loads(settings.read_text())
		assert PERMISSION_RULE in data["permissions"]["allow"]

	def test_adds_to_existing_file(self, tmp_path: Path):
		"""Should append permission to existing settings without clobbering."""
		settings_dir = tmp_path / ".claude"
		settings_dir.mkdir()
		settings = settings_dir / "settings.json"
		existing = {
			"permissions": {
				"allow": ["Bash(git:*)"],
				"deny": [],
			},
			"someOtherKey": True,
		}
		settings.write_text(json.dumps(existing))

		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			_inject_claude_code_permissions()

		data = json.loads(settings.read_text())
		assert "Bash(git:*)" in data["permissions"]["allow"]
		assert PERMISSION_RULE in data["permissions"]["allow"]
		assert data["someOtherKey"] is True

	def test_idempotent(self, tmp_path: Path):
		"""Should not duplicate the permission rule."""
		settings_dir = tmp_path / ".claude"
		settings_dir.mkdir()
		settings = settings_dir / "settings.json"
		existing = {"permissions": {"allow": [PERMISSION_RULE]}}
		settings.write_text(json.dumps(existing))

		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			_inject_claude_code_permissions()

		data = json.loads(settings.read_text())
		count = data["permissions"]["allow"].count(PERMISSION_RULE)
		assert count == 1

	def test_adds_missing_permissions_key(self, tmp_path: Path):
		"""Should handle settings file with no permissions key."""
		settings_dir = tmp_path / ".claude"
		settings_dir.mkdir()
		settings = settings_dir / "settings.json"
		settings.write_text(json.dumps({"hooks": {}}))

		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			_inject_claude_code_permissions()

		data = json.loads(settings.read_text())
		assert PERMISSION_RULE in data["permissions"]["allow"]
		assert data["hooks"] == {}

	def test_allow_permissions_subparser_registered(self):
		"""allow-permissions subparser should be registered in the CLI."""
		with patch("sys.argv", ["claude-orchestrator", "allow-permissions", "--help"]):
			with pytest.raises(SystemExit) as exc_info:
				main()
			assert exc_info.value.code == 0


class TestDoctorExitCode:
	"""Test that doctor returns proper exit codes."""

	def test_doctor_exits_1_on_issues(self):
		"""Doctor should exit(1) when there are issues."""
		args = argparse.Namespace()
		# Mock a core dep as missing to trigger an issue
		with patch("claude_orchestrator.cli.pkg_version", side_effect=Exception("nope")):
			with pytest.raises(SystemExit) as exc_info:
				cmd_doctor(args)
			assert exc_info.value.code == 1


class TestInstallAgents:
	"""Tests for custom agent installation."""

	def test_installs_agents_to_target(self, tmp_path: Path):
		"""Should copy bundled agent .md files to target directory."""
		agents_dir = tmp_path / ".claude" / "agents"
		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			results = _install_agents()

		assert agents_dir.exists()
		installed = [name for name, ok, _ in results if ok]
		assert len(installed) == 10
		# Verify actual files exist
		for name in installed:
			assert (agents_dir / name).exists()
			content = (agents_dir / name).read_text()
			assert len(content) > 0

	def test_skips_existing_files(self, tmp_path: Path):
		"""Should skip files that already exist without --force."""
		agents_dir = tmp_path / ".claude" / "agents"
		agents_dir.mkdir(parents=True)
		(agents_dir / "code-reviewer.md").write_text("custom content")

		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			results = _install_agents(force=False)

		skipped = [name for name, ok, _ in results if not ok]
		assert "code-reviewer.md" in skipped
		# Original content preserved
		assert (agents_dir / "code-reviewer.md").read_text() == "custom content"

	def test_force_overwrites_existing(self, tmp_path: Path):
		"""Should overwrite existing files when force=True."""
		agents_dir = tmp_path / ".claude" / "agents"
		agents_dir.mkdir(parents=True)
		(agents_dir / "code-reviewer.md").write_text("custom content")

		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			results = _install_agents(force=True)

		installed = [name for name, ok, _ in results if ok]
		assert "code-reviewer.md" in installed
		assert (agents_dir / "code-reviewer.md").read_text() != "custom content"

	def test_install_agents_subparser_registered(self):
		"""install-agents subparser should be registered in the CLI."""
		with patch("sys.argv", ["claude-orchestrator", "install-agents", "--help"]):
			with pytest.raises(SystemExit) as exc_info:
				main()
			assert exc_info.value.code == 0

	def test_cmd_install_agents(self, tmp_path: Path):
		"""cmd_install_agents should call _install_agents and print results."""
		args = argparse.Namespace(force=False)
		with patch("claude_orchestrator.cli.Path.home", return_value=tmp_path):
			cmd_install_agents(args)
