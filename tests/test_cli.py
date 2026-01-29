"""Tests for the CLI module."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from claude_orchestrator.cli import (
	_inject_mcp_config,
	DEFAULT_SEED_SOURCES,
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
	import argparse

	args = argparse.Namespace(source=None)

	with patch.dict("sys.modules", {"claude_orchestrator.knowledge": None, "claude_orchestrator.knowledge.retriever": None}):
		with patch("builtins.__import__", side_effect=ImportError("no knowledge")):
			try:
				cmd_seed_docs(args)
				assert False, "Should have called sys.exit"
			except SystemExit as e:
				assert e.code == 1
