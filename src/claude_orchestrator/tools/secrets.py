"""Secrets management tools."""

import json
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import Config


def _load_secrets(secrets_file: Path) -> dict:
	"""Load secrets from file."""
	if not secrets_file.exists():
		return {"keys": {}, "last_updated": None}
	try:
		with open(secrets_file, "r") as f:
			return json.load(f)
	except (json.JSONDecodeError, IOError):
		return {"keys": {}, "last_updated": None}


def _save_secrets(secrets_file: Path, data: dict) -> None:
	"""Save secrets to file."""
	data["last_updated"] = datetime.now().isoformat()
	secrets_file.parent.mkdir(parents=True, exist_ok=True)
	with open(secrets_file, "w") as f:
		json.dump(data, f, indent=2)


def register_secrets_tools(mcp: FastMCP, config: Config) -> None:
	"""Register secrets management tools."""

	@mcp.tool()
	async def get_secret(key_name: str) -> str:
		"""
		Get a secret value by name.

		Args:
			key_name: Name of the secret (e.g., "openai", "telegram_bot")

		Returns:
			The secret value or error if not found/inactive
		"""
		secrets = _load_secrets(config.secrets_file)
		keys = secrets.get("keys", {})

		if key_name not in keys:
			return json.dumps({
				"error": f"Secret '{key_name}' not found",
				"available": list(keys.keys()),
			})

		secret = keys[key_name]
		# Handle legacy format where value is a plain string
		if isinstance(secret, str):
			return json.dumps({"key": secret, "notes": ""})

		if not secret.get("active", True):
			return json.dumps({
				"error": f"Secret '{key_name}' is inactive",
				"notes": secret.get("notes", ""),
			})

		return json.dumps({
			"key": secret["key"],
			"notes": secret.get("notes", ""),
		})

	@mcp.tool()
	async def list_secrets() -> str:
		"""
		List all secrets with their status. Does NOT show actual values.

		Returns list of secret names, active status, and notes.
		"""
		secrets = _load_secrets(config.secrets_file)
		keys = secrets.get("keys", {})

		result = []
		for name, data in keys.items():
			# Handle legacy format where value is a plain string
			if isinstance(data, str):
				result.append({
					"name": name,
					"active": True,
					"notes": "",
					"has_value": bool(data),
				})
			else:
				result.append({
					"name": name,
					"active": data.get("active", True),
					"notes": data.get("notes", ""),
					"has_value": bool(data.get("key")),
				})

		return json.dumps({
			"secrets": result,
			"last_updated": secrets.get("last_updated"),
			"file": str(config.secrets_file),
		}, indent=2)

	@mcp.tool()
	async def set_secret(key_name: str, value: str, notes: str = "") -> str:
		"""
		Add or update a secret.

		Args:
			key_name: Name of the secret (e.g., "openai", "postgres_test")
			value: The secret value (API key, connection string, etc.)
			notes: Optional notes about this secret
		"""
		secrets = _load_secrets(config.secrets_file)

		if "keys" not in secrets:
			secrets["keys"] = {}

		secrets["keys"][key_name] = {
			"key": value,
			"active": True,
			"notes": notes,
		}

		_save_secrets(config.secrets_file, secrets)

		return json.dumps({
			"success": True,
			"message": f"Secret '{key_name}' saved",
		})

	@mcp.tool()
	async def deactivate_secret(key_name: str) -> str:
		"""
		Mark a secret as inactive (without deleting it).

		Args:
			key_name: Name of the secret to deactivate
		"""
		secrets = _load_secrets(config.secrets_file)
		keys = secrets.get("keys", {})

		if key_name not in keys:
			return json.dumps({"error": f"Secret '{key_name}' not found"})

		# Migrate legacy string format to dict
		if isinstance(keys[key_name], str):
			keys[key_name] = {"key": keys[key_name], "active": True, "notes": ""}

		keys[key_name]["active"] = False
		_save_secrets(config.secrets_file, secrets)

		return json.dumps({
			"success": True,
			"message": f"Secret '{key_name}' deactivated",
		})

	@mcp.tool()
	async def activate_secret(key_name: str) -> str:
		"""
		Reactivate a previously deactivated secret.

		Args:
			key_name: Name of the secret to activate
		"""
		secrets = _load_secrets(config.secrets_file)
		keys = secrets.get("keys", {})

		if key_name not in keys:
			return json.dumps({"error": f"Secret '{key_name}' not found"})

		# Migrate legacy string format to dict
		if isinstance(keys[key_name], str):
			keys[key_name] = {"key": keys[key_name], "active": True, "notes": ""}

		keys[key_name]["active"] = True
		_save_secrets(config.secrets_file, secrets)

		return json.dumps({
			"success": True,
			"message": f"Secret '{key_name}' activated",
		})
