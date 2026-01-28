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
	assert config.secrets_file == config.config_dir / "secrets.json"
	assert config.db_path == config.data_dir / "orchestrator.db"
	assert config.plans_db_path == config.data_dir / "plans.db"
	assert config.context_file == config.data_dir / "personal_context.json"
	assert config.log_dir == config.data_dir / "logs"


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
		# Derived paths should be recomputed
		assert config.db_path == Path("/tmp/test-data/orchestrator.db")
		assert config.secrets_file == Path("/tmp/test-config/secrets.json")


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
	assert config.log_dir.exists()


def test_load_config_creates_dirs(tmp_path: Path):
	"""load_config should create directories."""
	with patch.dict(os.environ, {
		"CLAUDE_ORCHESTRATOR_DATA_DIR": str(tmp_path / "data"),
		"CLAUDE_ORCHESTRATOR_CONFIG_DIR": str(tmp_path / "config"),
	}):
		config = load_config()
		assert config.data_dir.exists()
		assert config.config_dir.exists()
