"""
Session Manager - Tracks and controls Claude Code CLI sessions.

Provides:
- List active sessions
- Start new session in project
- Kill session
- View session output/history
- Session state persistence
- Per-session locking for thread safety
- Health monitoring and crash recovery
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from .claude_cli_bridge import (
	ClaudeCLIBridge,
	CLIBridgeError,
	CLINotRunningError,
	CLIOutput,
	CLITimeoutError,
	OutputType,
)

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
	"""State of a Claude session."""
	STARTING = "starting"
	READY = "ready"
	BUSY = "busy"
	WAITING_INPUT = "waiting_input"
	STOPPED = "stopped"
	FAILED = "failed"


@dataclass
class Session:
	"""Represents a Claude Code session."""
	id: str
	project_path: str
	project_name: str
	state: SessionState
	created_at: str
	last_activity: str
	output_history: list[str] = field(default_factory=list)
	current_task: str = ""
	error: str = ""

	def to_dict(self) -> dict:
		"""Convert to dictionary for JSON serialization."""
		return {
			"id": self.id,
			"project_path": self.project_path,
			"project_name": self.project_name,
			"state": self.state.value,
			"created_at": self.created_at,
			"last_activity": self.last_activity,
			"output_lines": len(self.output_history),
			"current_task": self.current_task,
			"error": self.error,
		}


class SessionManager:
	"""
	Manages multiple Claude Code sessions.

	Tracks sessions, provides start/stop/list functionality,
	and maintains output history.

	Thread-safety: Uses per-session locks to prevent race conditions.
	Persistence: Saves session state for crash recovery.
	Health monitoring: Background loop checks session health.
	"""

	MAX_HISTORY_LINES = 500  # Per session
	MAX_CONCURRENT_SESSIONS = 3  # Limit concurrent sessions
	HEALTH_CHECK_INTERVAL = 5  # Seconds between health checks
	STATE_FILE = "data/sessions/session_state.json"

	def __init__(
		self,
		data_dir: str = "data/sessions",
		on_output: Callable[[str, str], Awaitable[None]] | None = None,
		on_permission: Callable[[str, str], Awaitable[bool]] | None = None,
		on_session_died: Callable[[str, str], Awaitable[None]] | None = None,
	):
		"""
		Initialize session manager.

		Args:
			data_dir: Directory for session state persistence
			on_output: Callback(session_id, output) for session output
			on_permission: Callback(session_id, prompt) -> bool for permissions
			on_session_died: Callback(session_id, reason) when session dies unexpectedly
		"""
		self.data_dir = Path(data_dir)
		self.data_dir.mkdir(parents=True, exist_ok=True)
		self.on_output = on_output
		self.on_permission = on_permission
		self.on_session_died = on_session_died

		self._sessions: dict[str, Session] = {}
		self._bridges: dict[str, ClaudeCLIBridge] = {}
		self._global_lock = asyncio.Lock()  # For session creation/deletion
		self._session_locks: dict[str, asyncio.Lock] = {}  # Per-session locks
		self._health_task: asyncio.Task | None = None
		self._running = False

	async def start_session(
		self,
		project_path: str,
		initial_prompt: str | None = None,
		timeout: int = 60,
	) -> tuple[str, str]:
		"""
		Start a new Claude session in a project directory.

		Args:
			project_path: Path to project directory
			initial_prompt: Optional initial prompt to start with
			timeout: Startup timeout in seconds

		Returns:
			Tuple of (session_id, message)
		"""
		async with self._global_lock:
			# Check session limit
			active_count = sum(
				1 for s in self._sessions.values()
				if s.state not in [SessionState.STOPPED, SessionState.FAILED]
			)
			if active_count >= self.MAX_CONCURRENT_SESSIONS:
				return "", f"Maximum concurrent sessions ({self.MAX_CONCURRENT_SESSIONS}) reached"

			# Generate session ID
			session_id = str(uuid.uuid4())[:8]
			project_path = str(Path(project_path).expanduser().resolve())
			project_name = Path(project_path).name

			# Check if project directory exists
			if not Path(project_path).is_dir():
				return "", f"Directory not found: {project_path}"

			# Create per-session lock
			self._session_locks[session_id] = asyncio.Lock()

			# Create session record
			now = datetime.now().isoformat()
			session = Session(
				id=session_id,
				project_path=project_path,
				project_name=project_name,
				state=SessionState.STARTING,
				created_at=now,
				last_activity=now,
			)
			self._sessions[session_id] = session

			# Create bridge with callbacks
			bridge = ClaudeCLIBridge(
				project_path=project_path,
				on_output=self._make_output_callback(session_id),
				on_permission=self._make_permission_callback(session_id),
				on_startup_message=self._make_startup_callback(session_id),
			)
			self._bridges[session_id] = bridge

			# Start the session
			result = await bridge.start(initial_prompt=initial_prompt, timeout=timeout)

			if result.success:
				session.state = SessionState.READY
				session.last_activity = datetime.now().isoformat()
				logger.info(f"Session {session_id} started for {project_name}")
				await self._persist_state()
				return session_id, f"Session started: {project_name} ({session_id})"
			else:
				session.state = SessionState.FAILED
				session.error = result.message
				# Clean up failed session
				del self._sessions[session_id]
				del self._bridges[session_id]
				del self._session_locks[session_id]
				return "", f"Failed to start session: {result.message}"

	async def stop_session(self, session_id: str) -> str:
		"""
		Stop a session.

		Args:
			session_id: ID of session to stop

		Returns:
			Status message
		"""
		async with self._global_lock:
			if session_id not in self._sessions:
				return f"Session not found: {session_id}"

			session = self._sessions[session_id]
			bridge = self._bridges.get(session_id)

			if bridge:
				await bridge.stop()

			session.state = SessionState.STOPPED
			session.last_activity = datetime.now().isoformat()

			# Clean up
			if session_id in self._bridges:
				del self._bridges[session_id]
			if session_id in self._session_locks:
				del self._session_locks[session_id]

			await self._persist_state()
			logger.info(f"Session {session_id} stopped")
			return f"Session {session_id} stopped"

	async def send_prompt(self, session_id: str, prompt: str) -> str:
		"""
		Send a prompt to a session.

		Args:
			session_id: ID of session
			prompt: Prompt to send

		Returns:
			Response from Claude
		"""
		if session_id not in self._sessions:
			return f"Session not found: {session_id}"

		# Get per-session lock to prevent concurrent access
		session_lock = self._session_locks.get(session_id)
		if not session_lock:
			return f"Session {session_id} lock not found"

		async with session_lock:
			session = self._sessions[session_id]
			bridge = self._bridges.get(session_id)

			if not bridge or not bridge.is_ready:
				return f"Session {session_id} is not ready"

			session.state = SessionState.BUSY
			session.current_task = prompt[:100]
			session.last_activity = datetime.now().isoformat()

			try:
				response = await bridge.send_prompt(prompt)
			except CLINotRunningError as e:
				session.state = SessionState.FAILED
				session.error = str(e)
				logger.error(f"Session {session_id} CLI not running: {e}")
				return f"Error: {e}"
			except CLITimeoutError as e:
				# Timeout doesn't necessarily mean failed - CLI may still be running
				session.error = str(e)
				logger.warning(f"Session {session_id} prompt timed out: {e}")
				return f"Error: {e}"
			except CLIBridgeError as e:
				session.state = SessionState.FAILED
				session.error = str(e)
				logger.error(f"Session {session_id} CLI error: {e}")
				return f"Error: {e}"
			except Exception as e:
				session.state = SessionState.FAILED
				session.error = str(e)
				logger.error(f"Session {session_id} unexpected error: {e}")
				return f"Error: {e}"
			finally:
				if session.state == SessionState.BUSY:
					session.state = SessionState.READY
				session.current_task = ""
				session.last_activity = datetime.now().isoformat()

			return response

	def list_sessions(self) -> list[dict]:
		"""List all sessions with their status."""
		sessions = []
		for session in self._sessions.values():
			# Update state based on bridge status
			bridge = self._bridges.get(session.id)
			if bridge:
				if bridge.is_ready:
					if session.state not in [SessionState.BUSY]:
						session.state = SessionState.READY
				elif not bridge.is_running:
					session.state = SessionState.STOPPED

			sessions.append(session.to_dict())

		return sorted(sessions, key=lambda s: s["last_activity"], reverse=True)

	def get_session(self, session_id: str) -> dict | None:
		"""Get details for a specific session."""
		session = self._sessions.get(session_id)
		if session:
			return session.to_dict()
		return None

	def get_session_output(
		self,
		session_id: str,
		lines: int = 50,
		offset: int = 0,
	) -> list[str]:
		"""
		Get output history for a session.

		Args:
			session_id: Session ID
			lines: Number of lines to return
			offset: Number of lines to skip from end

		Returns:
			List of output lines
		"""
		session = self._sessions.get(session_id)
		if not session:
			return []

		history = session.output_history
		if offset > 0:
			history = history[:-offset] if offset < len(history) else []

		return history[-lines:] if lines < len(history) else history

	async def send_input(self, session_id: str, text: str) -> str:
		"""Send raw input to a session (for approvals, etc.)."""
		bridge = self._bridges.get(session_id)
		if not bridge:
			return f"Session not found: {session_id}"

		await bridge.send_input(text)
		return "Input sent"

	def _make_output_callback(
		self, session_id: str
	) -> Callable[[CLIOutput], Awaitable[None]]:
		"""Create output callback for a session."""
		async def callback(output: CLIOutput):
			session = self._sessions.get(session_id)
			if session:
				# Add to history
				session.output_history.append(output.content)
				# Trim history if too long
				if len(session.output_history) > self.MAX_HISTORY_LINES:
					session.output_history = session.output_history[-self.MAX_HISTORY_LINES:]

				# Update state based on output type
				if output.type == OutputType.PERMISSION_REQUEST:
					session.state = SessionState.WAITING_INPUT

				# Forward to external callback
				if self.on_output:
					await self.on_output(session_id, output.content)

		return callback

	def _make_permission_callback(
		self, session_id: str
	) -> Callable[[str], Awaitable[bool]]:
		"""Create permission callback for a session."""
		async def callback(prompt: str) -> bool:
			session = self._sessions.get(session_id)
			if session:
				session.state = SessionState.WAITING_INPUT

			# Forward to external callback
			if self.on_permission:
				return await self.on_permission(session_id, prompt)

			# Default: auto-approve
			return True

		return callback

	def _make_startup_callback(
		self, session_id: str
	) -> Callable[[str], Awaitable[None]]:
		"""Create startup message callback for a session."""
		async def callback(message: str):
			session = self._sessions.get(session_id)
			if session:
				session.output_history.append(f"[startup] {message}")

		return callback

	async def cleanup(self):
		"""Stop all sessions and clean up."""
		self._running = False
		if self._health_task:
			self._health_task.cancel()
			try:
				await self._health_task
			except asyncio.CancelledError:
				pass

		async with self._global_lock:
			for session_id in list(self._sessions.keys()):
				bridge = self._bridges.get(session_id)
				if bridge:
					await bridge.stop()

			self._sessions.clear()
			self._bridges.clear()
			self._session_locks.clear()

	async def start(self):
		"""Start the session manager (health monitoring)."""
		self._running = True
		await self._load_state()
		self._health_task = asyncio.create_task(self._health_check_loop())
		logger.info("Session manager started")

	async def stop(self):
		"""Stop the session manager."""
		await self.cleanup()
		logger.info("Session manager stopped")

	async def _persist_state(self):
		"""Save session state to disk for crash recovery."""
		state_file = self.data_dir / "session_state.json"
		state = {}
		for session_id, session in self._sessions.items():
			bridge = self._bridges.get(session_id)
			state[session_id] = {
				"id": session.id,
				"project_path": session.project_path,
				"project_name": session.project_name,
				"state": session.state.value,
				"created_at": session.created_at,
				"last_activity": session.last_activity,
				"current_task": session.current_task,
				"pid": bridge.process.pid if bridge and bridge.process else None,
			}
		try:
			state_file.write_text(json.dumps(state, indent=2))
			logger.debug(f"Persisted state for {len(state)} sessions")
		except Exception as e:
			logger.error(f"Failed to persist state: {e}")

	async def _load_state(self):
		"""Load session state from disk (for recovery)."""
		state_file = self.data_dir / "session_state.json"
		if not state_file.exists():
			return

		try:
			state = json.loads(state_file.read_text())
			for session_id, info in state.items():
				pid = info.get("pid")
				if pid and self._process_running(pid):
					logger.info(f"Found orphaned session {session_id} (PID {pid})")
					# For now, just log - reconnection requires more work
					# TODO: Implement reconnection to orphaned processes
				else:
					logger.debug(f"Session {session_id} no longer running")
		except Exception as e:
			logger.error(f"Failed to load state: {e}")

	def _process_running(self, pid: int) -> bool:
		"""Check if a process is still running."""
		try:
			os.kill(pid, 0)
			return True
		except (OSError, ProcessLookupError):
			return False

	async def _health_check_loop(self):
		"""Background loop to monitor session health."""
		while self._running:
			try:
				await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
				await self._check_session_health()
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Health check error: {e}")

	async def _check_session_health(self):
		"""Check health of all active sessions."""
		async with self._global_lock:
			for session_id in list(self._sessions.keys()):
				session = self._sessions[session_id]
				bridge = self._bridges.get(session_id)

				if session.state in [SessionState.STOPPED, SessionState.FAILED]:
					continue

				if bridge and not bridge.is_running:
					# Session died unexpectedly
					reason = "Process terminated unexpectedly"
					session.state = SessionState.FAILED
					session.error = reason
					session.last_activity = datetime.now().isoformat()

					logger.warning(f"Session {session_id} died: {reason}")

					if self.on_session_died:
						try:
							await self.on_session_died(session_id, reason)
						except Exception as e:
							logger.error(f"on_session_died callback failed: {e}")

					await self._persist_state()


# Global instance
_manager: SessionManager | None = None


async def get_session_manager() -> SessionManager:
	"""Get or create the global session manager."""
	global _manager
	if _manager is None:
		_manager = SessionManager()
	return _manager
