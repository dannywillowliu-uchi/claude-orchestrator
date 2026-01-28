"""Claude Code session management tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..session_manager import get_session_manager


def register_session_tools(mcp: FastMCP, config: Config) -> None:
	"""Register session management tools."""

	@mcp.tool()
	async def list_claude_sessions() -> str:
		"""
		List all active Claude Code sessions.

		Returns information about each session including:
		- Session ID
		- Project name and path
		- Current state (ready, busy, waiting_input, stopped)
		- Last activity timestamp
		- Current task (if busy)
		"""
		manager = await get_session_manager()
		sessions = manager.list_sessions()
		return json.dumps({"success": True, "count": len(sessions), "sessions": sessions})

	@mcp.tool()
	async def start_claude_session(project_path: str, initial_prompt: str = "") -> str:
		"""
		Start a new Claude Code session in a project directory.

		This creates a new Claude CLI process in the specified project.
		The session can then be controlled via other MCP tools.

		Args:
			project_path: Path to project directory (e.g., "~/personal_projects/my-app")
			initial_prompt: Optional initial prompt to start working on
		"""
		manager = await get_session_manager()
		session_id, message = await manager.start_session(
			project_path=project_path,
			initial_prompt=initial_prompt if initial_prompt else None,
		)
		if session_id:
			return json.dumps({"success": True, "session_id": session_id, "message": message})
		else:
			return json.dumps({"success": False, "error": message})

	@mcp.tool()
	async def stop_claude_session(session_id: str) -> str:
		"""
		Stop a Claude Code session.

		Args:
			session_id: The session ID to stop (from list_claude_sessions)
		"""
		manager = await get_session_manager()
		message = await manager.stop_session(session_id)
		return json.dumps({"success": True, "message": message})

	@mcp.tool()
	async def send_to_claude_session(session_id: str, prompt: str) -> str:
		"""
		Send a prompt to a Claude session.

		Args:
			session_id: The session ID to send to
			prompt: The prompt or command to send
		"""
		manager = await get_session_manager()
		response = await manager.send_prompt(session_id, prompt)
		return json.dumps({"success": True, "response": response})

	@mcp.tool()
	async def get_session_output(session_id: str, lines: int = 50) -> str:
		"""
		Get recent output from a Claude session.

		Args:
			session_id: The session ID
			lines: Number of output lines to retrieve (default: 50)
		"""
		manager = await get_session_manager()
		session = manager.get_session(session_id)
		if not session:
			return json.dumps({"success": False, "error": f"Session not found: {session_id}"})
		output = manager.get_session_output(session_id, lines=lines)
		return json.dumps({"success": True, "session": session, "output": output, "line_count": len(output)})

	@mcp.tool()
	async def approve_session_action(session_id: str, approved: bool = True) -> str:
		"""
		Approve or deny a pending action in a Claude session.

		Use this when a session is in 'waiting_input' state and needs
		approval for a permission request.

		Args:
			session_id: The session ID
			approved: True to approve, False to deny
		"""
		manager = await get_session_manager()
		response = "y" if approved else "n"
		message = await manager.send_input(session_id, response)
		return json.dumps({"success": True, "message": message, "approved": approved})
