"""Tests for the configuration system."""

import os
from pathlib import Path
from unittest.mock import patch

from claude_orchestrator.config import Config, _apply_env_overrides, load_config


def test_config_defaults():
	"""Config should have sensible defaults."""
	config = Config()
	assert config.config_dir.is_absolute()
	assert config.data_dir.is_absolute()
	assert config.projects_path.is_absolute()


def test_config_env_overrides():
	"""Environment variables should override defaults."""
	config = Config()
	with patch.dict(os.environ, {
		"CLAUDE_ORCHESTRATOR_DATA_DIR": "/tmp/test-data",
		"CLAUDE_ORCHESTRATOR_CONFIG_DIR": "/tmp/test-config",
	}):
		config = _apply_env_overrides(config)
		assert config.data_dir == Path("/tmp/test-data")
		assert config.config_dir == Path("/tmp/test-config")


def test_config_ensure_dirs(tmp_path: Path):
	"""ensure_dirs should create all required directories."""
	config = Config(
		config_dir=tmp_path / "config",
		data_dir=tmp_path / "data",
	)
	assert not config.config_dir.exists()
	assert not config.data_dir.exists()

	config.ensure_dirs()

	assert config.config_dir.exists()
	assert config.data_dir.exists()


def test_load_config_creates_dirs(tmp_path: Path):
	"""load_config should create directories."""
	with patch.dict(os.environ, {
		"CLAUDE_ORCHESTRATOR_DATA_DIR": str(tmp_path / "data"),
		"CLAUDE_ORCHESTRATOR_CONFIG_DIR": str(tmp_path / "config"),
	}):
		config = load_config()
		assert config.data_dir.exists()
		assert config.config_dir.exists()
