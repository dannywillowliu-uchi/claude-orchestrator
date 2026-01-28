"""
Claude CLI Bridge - Executes Claude Code CLI in print mode for programmatic use.

Uses `claude --print` for clean stdin/stdout communication without TUI complexity.

Handles:
- Executing Claude CLI with prompts
- Working directory context
- Timeout management
- Error handling
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Awaitable, List

logger = logging.getLogger(__name__)

# Load API key from secrets
SECRETS_PATH = Path.home() / "personal_projects" / ".secrets.json"


def _get_api_key() -> str:
	"""Load API key from secrets file."""
	if SECRETS_PATH.exists():
		with open(SECRETS_PATH) as f:
			secrets = json.load(f)
			return secrets.get("keys", {}).get("ANTHROPIC_API_KEY", "")
	return os.environ.get("ANTHROPIC_API_KEY", "")


class CLIBridgeError(Exception):
	"""Base exception for CLI bridge errors."""
	pass


class CLINotRunningError(CLIBridgeError):
	"""Raised when CLI process is not running."""
	pass


class CLIStartupError(CLIBridgeError):
	"""Raised when CLI fails to start."""
	pass


class CLITimeoutError(CLIBridgeError):
	"""Raised when CLI operation times out."""
	pass


class OutputType(str, Enum):
	"""Type of output from Claude CLI."""
	RESPONSE = "response"
	PERMISSION_REQUEST = "permission"
	THINKING = "thinking"
	TOOL_USE = "tool_use"
	ERROR = "error"
	COMPLETE = "complete"
	STARTUP = "startup"
	READY = "ready"


class StartupState(str, Enum):
	"""State during Claude CLI startup."""
	SPAWNING = "spawning"
	WAITING_FOR_READY = "waiting"
	HANDLING_PROMPT = "handling_prompt"
	READY = "ready"
	FAILED = "failed"


@dataclass
class CLIOutput:
	"""Parsed output from Claude CLI."""
	type: OutputType
	content: str
	raw: str = ""


@dataclass
class StartupResult:
	"""Result of CLI startup."""
	success: bool
	message: str
	startup_output: List[str] = field(default_factory=list)


class ClaudeCLIBridge:
	"""
	Bridge to Claude Code CLI using --print mode.

	Uses subprocess with --print flag for clean programmatic interaction.
	Much simpler than TUI automation - just stdin/stdout.
	"""

	def __init__(
		self,
		project_path: str,
		on_output: Optional[Callable[[CLIOutput], Awaitable[None]]] = None,
		on_permission: Optional[Callable[[str], Awaitable[bool]]] = None,
		on_startup_message: Optional[Callable[[str], Awaitable[None]]] = None,
	):
		self.project_path = os.path.expanduser(project_path)
		self.on_output = on_output
		self.on_permission = on_permission  # Not used in print mode
		self.on_startup_message = on_startup_message
		self._api_key = _get_api_key()
		self._ready = False
		self._startup_buffer: List[str] = []

		# For compatibility with session_manager
		self.process = None

	async def start(self, initial_prompt: Optional[str] = None, timeout: int = 60) -> StartupResult:
		"""
		Initialize the bridge. With --print mode, we just verify the setup.

		Args:
			initial_prompt: Optional prompt to run immediately
			timeout: Timeout for initial prompt (if provided)

		Returns:
			StartupResult with success status
		"""
		if not os.path.isdir(self.project_path):
			return StartupResult(
				success=False,
				message=f"Directory not found: {self.project_path}"
			)

		if not self._api_key:
			return StartupResult(
				success=False,
				message="No API key found. Set ANTHROPIC_API_KEY or add to ~/.secrets.json"
			)

		await self._notify_startup(f"Claude CLI Bridge initialized for: {self.project_path}")
		await self._notify_startup("Using --print mode with API key")

		# If initial prompt provided, run it
		if initial_prompt:
			try:
				await self._notify_startup(f"Running initial prompt...")
				response = await self.send_prompt(initial_prompt, timeout=timeout)
				await self._notify_startup(f"Initial prompt complete ({len(response)} chars)")
			except Exception as e:
				return StartupResult(
					success=False,
					message=f"Initial prompt failed: {e}",
					startup_output=self._startup_buffer.copy()
				)

		self._ready = True
		await self._notify_startup("Ready!")

		return StartupResult(
			success=True,
			message="Claude CLI Bridge ready",
			startup_output=self._startup_buffer.copy()
		)

	async def _notify_startup(self, message: str):
		"""Send startup status message."""
		self._startup_buffer.append(message)
		logger.info(f"STARTUP: {message}")
		if self.on_startup_message:
			await self.on_startup_message(message)

	async def stop(self):
		"""Stop the bridge. No-op for print mode since each call is independent."""
		self._ready = False
		logger.info("Claude CLI Bridge stopped")

	async def send_prompt(self, prompt: str, timeout: int = 300) -> str:
		"""
		Send a prompt to Claude CLI and get response.

		Args:
			prompt: The prompt to send
			timeout: Seconds to wait for response (default 5 min)

		Returns:
			Claude's response text

		Raises:
			CLITimeoutError: If response times out
			CLIBridgeError: If execution fails
		"""
		if not self._api_key:
			raise CLIBridgeError("No API key configured")

		logger.info(f"Sending prompt ({len(prompt)} chars): {prompt[:100]}...")

		try:
			# Build environment with API key
			env = os.environ.copy()
			env["ANTHROPIC_API_KEY"] = self._api_key

			# Run claude --print with the prompt, using Opus 4.5
			# --dangerously-skip-permissions allows tool execution without interactive prompts
			process = await asyncio.create_subprocess_exec(
				"claude",
				"--print",
				"--model", "opus",
				"--dangerously-skip-permissions",
				prompt,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				cwd=self.project_path,
				env=env,
			)

			try:
				stdout, stderr = await asyncio.wait_for(
					process.communicate(),
					timeout=timeout,
				)
			except asyncio.TimeoutError:
				process.kill()
				await process.wait()
				raise CLITimeoutError(f"Response timed out after {timeout} seconds")

			stdout_text = stdout.decode() if stdout else ""
			stderr_text = stderr.decode() if stderr else ""

			if process.returncode != 0:
				error_msg = stderr_text or f"Exit code {process.returncode}"
				logger.error(f"Claude CLI error: {error_msg}")
				raise CLIBridgeError(f"Claude CLI failed: {error_msg}")

			logger.info(f"Response received ({len(stdout_text)} chars)")

			# Notify callback if set
			if self.on_output:
				await self.on_output(CLIOutput(
					type=OutputType.COMPLETE,
					content=stdout_text,
					raw=stdout_text,
				))

			return stdout_text

		except CLITimeoutError:
			raise
		except CLIBridgeError:
			raise
		except FileNotFoundError:
			raise CLIBridgeError("Claude CLI not found. Is it installed?")
		except Exception as e:
			raise CLIBridgeError(f"Unexpected error: {e}")

	async def send_approval(self, approved: bool):
		"""Not used in print mode - permissions handled via --dangerously-skip-permissions if needed."""
		pass

	async def send_input(self, text: str):
		"""Not used in print mode."""
		pass

	@property
	def is_running(self) -> bool:
		"""Check if bridge is ready."""
		return self._ready

	@property
	def is_ready(self) -> bool:
		"""Check if bridge is ready for prompts."""
		return self._ready and bool(self._api_key)
