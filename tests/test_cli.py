"""Tests for the CLI module."""

import json
from pathlib import Path

from claude_orchestrator.cli import _inject_mcp_config


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
