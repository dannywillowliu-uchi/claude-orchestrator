"""Core health check tool."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config


def register_core_tools(mcp: FastMCP, config: Config) -> None:
	"""Register core tools."""

	@mcp.tool()
	async def health_check() -> str:
		"""
		Check the health of the claude-orchestrator server.
		Returns status of all components.
		"""
		status = {
			"server": "running",
			"config_dir": str(config.config_dir),
			"data_dir": str(config.data_dir),
			"secrets_file_exists": config.secrets_file.exists(),
			"db_exists": config.db_path.exists(),
			"plans_db_exists": config.plans_db_path.exists(),
		}
		return json.dumps(status, indent=2)
