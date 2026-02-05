"""Configuration system using platformdirs for cross-platform paths."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

APP_NAME = "claude-orchestrator"
APP_AUTHOR = "claude-orchestrator"


@dataclass
class Config:
	"""Central configuration with XDG/platform conventions."""

	config_dir: Path = field(default_factory=lambda: Path(platformdirs.user_config_dir(APP_NAME)))
	data_dir: Path = field(default_factory=lambda: Path(platformdirs.user_data_dir(APP_NAME)))

	# User-configurable
	projects_path: Path = field(
		default_factory=lambda: Path(
			os.getenv("PROJECTS_PATH", str(Path.home() / "personal_projects"))
		)
	)

	def ensure_dirs(self) -> None:
		"""Create all required directories."""
		self.config_dir.mkdir(parents=True, exist_ok=True)
		self.data_dir.mkdir(parents=True, exist_ok=True)


def _apply_env_overrides(config: Config) -> Config:
	"""Apply CLAUDE_ORCHESTRATOR_* environment variable overrides."""
	env_map = {
		"CLAUDE_ORCHESTRATOR_CONFIG_DIR": "config_dir",
		"CLAUDE_ORCHESTRATOR_DATA_DIR": "data_dir",
		"CLAUDE_ORCHESTRATOR_PROJECTS_PATH": "projects_path",
	}
	for env_key, attr in env_map.items():
		val = os.getenv(env_key)
		if val:
			setattr(config, attr, Path(val))
	return config


def _apply_toml(config: Config) -> Config:
	"""Apply config.toml overrides if file exists."""
	toml_path = config.config_dir / "config.toml"
	if not toml_path.exists():
		return config

	with open(toml_path, "rb") as f:
		data = tomllib.load(f)

	path_fields = {"config_dir", "data_dir", "projects_path"}
	for key, val in data.items():
		if hasattr(config, key):
			if key in path_fields:
				setattr(config, key, Path(os.path.expanduser(val)))
			else:
				setattr(config, key, val)

	return config


def load_config() -> Config:
	"""Load config with precedence: env vars > config.toml > defaults."""
	config = Config()
	config = _apply_toml(config)
	config = _apply_env_overrides(config)
	config.ensure_dirs()
	return config


# Singleton
_config: Config | None = None


def get_config() -> Config:
	"""Get or create the global config instance."""
	global _config
	if _config is None:
		_config = load_config()
	return _config
