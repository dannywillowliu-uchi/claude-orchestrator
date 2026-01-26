"""
Telegram bot for Claude Code CLI equivalence.

Full bi-directional control:
- Session management (list, switch, new, kill)
- Prompt forwarding to active session
- Permission approvals
- Detailed notifications
"""

import os
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable, Dict, List
from dataclasses import dataclass, field
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
	Application,
	CommandHandler,
	CallbackQueryHandler,
	MessageHandler,
	ContextTypes,
	filters,
)

from .claude_cli_bridge import ClaudeCLIBridge, CLIOutput, OutputType, StartupResult


class SessionStatus(str, Enum):
	RUNNING = "running"
	WAITING = "waiting"
	DONE = "done"
	ERROR = "error"


class ApprovalStatus(str, Enum):
	APPROVED = "approved"
	DENIED = "denied"
	TIMEOUT = "timeout"


@dataclass
class ClaudeSession:
	"""Represents an active Claude Code session."""
	id: str  # Format: project-name-YYYY-MM-DD-HH:MM
	project_name: str
	project_path: str
	status: SessionStatus = SessionStatus.RUNNING
	cli_bridge: Optional[ClaudeCLIBridge] = None
	created_at: datetime = field(default_factory=datetime.now)
	last_activity: datetime = field(default_factory=datetime.now)
	output_buffer: List[str] = field(default_factory=list)

	@classmethod
	def generate_id(cls, project_name: str) -> str:
		"""Generate session ID: project-name-YYYY-MM-DD-HH:MM"""
		timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M")
		return f"{project_name}-{timestamp}"


@dataclass
class ApprovalRequest:
	"""Pending approval request."""
	id: str
	session_id: str
	action: str
	context: str
	future: asyncio.Future


@dataclass
class ApprovalResponse:
	"""Response to an approval request."""
	request_id: str
	status: ApprovalStatus
	message: Optional[str] = None


@dataclass
class PendingQuestion:
	"""Pending question awaiting response."""
	id: str
	project: str
	question: str
	options: Optional[List[str]]
	allow_other: bool
	message_id: int  # Telegram message ID for reply tracking
	future: asyncio.Future


class TelegramBot:
	"""
	Telegram bot providing full Claude Code CLI equivalence.

	Commands:
		/start - Initialize bot and capture chat ID
		/sessions - List all active Claude sessions
		/session <id> - Switch to a specific session
		/new <project> - Start a new Claude session
		/kill <id> - Kill a session
		/status - Show bot and session status
		/help - Show available commands

	Messages:
		Any non-command message is forwarded to the active session as a prompt.
	"""

	def __init__(self, token: str, chat_id: Optional[str] = None):
		self.token = token
		self.chat_id = chat_id
		self.app: Optional[Application] = None
		self._running = False

		# Session management
		self.sessions: Dict[str, ClaudeSession] = {}
		self.active_session_id: Optional[str] = None

		# Approval management
		self.pending_approvals: Dict[str, ApprovalRequest] = {}

		# Question management (for MCP tools)
		self.pending_questions: Dict[str, PendingQuestion] = {}
		self.message_to_question: Dict[int, str] = {}  # message_id -> question_id

		# Callbacks
		self._on_prompt_callback: Optional[Callable[[str, str], Awaitable[str]]] = None
		self._on_approval_callback: Optional[Callable[[ApprovalResponse], Awaitable[None]]] = None

	# ==================== Lifecycle ====================

	async def start(self):
		"""Initialize and start the bot."""
		self.app = Application.builder().token(self.token).build()

		# Command handlers
		self.app.add_handler(CommandHandler("start", self._cmd_start))
		self.app.add_handler(CommandHandler("help", self._cmd_help))
		self.app.add_handler(CommandHandler("sessions", self._cmd_sessions))
		self.app.add_handler(CommandHandler("session", self._cmd_session))
		self.app.add_handler(CommandHandler("new", self._cmd_new))
		self.app.add_handler(CommandHandler("kill", self._cmd_kill))
		self.app.add_handler(CommandHandler("status", self._cmd_status))
		self.app.add_handler(CommandHandler("create", self._cmd_create))

		# Callback handler for inline buttons
		self.app.add_handler(CallbackQueryHandler(self._handle_callback))

		# Message handler for prompts
		self.app.add_handler(
			MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
		)

		await self.app.initialize()
		await self.app.start()

		self._running = True
		asyncio.create_task(self._poll_updates())

	async def stop(self):
		"""Stop the bot and clean up sessions."""
		self._running = False

		# Kill all active sessions
		for session in self.sessions.values():
			if session.cli_bridge:
				await session.cli_bridge.stop()

		if self.app:
			if self.app.updater and self.app.updater.running:
				await self.app.updater.stop()
			await self.app.stop()
			await self.app.shutdown()

	async def _poll_updates(self):
		"""Poll for Telegram updates."""
		if not self.app or not self.app.updater:
			return

		await self.app.updater.start_polling(drop_pending_updates=True)
		while self._running:
			await asyncio.sleep(0.1)

	# ==================== Command Handlers ====================

	async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /start - Initialize bot."""
		if update.effective_chat:
			self.chat_id = str(update.effective_chat.id)
			await update.message.reply_text(
				"*Claude Code Telegram Interface*\n\n"
				f"Chat ID: `{self.chat_id}`\n\n"
				"Commands:\n"
				"/sessions - List active sessions\n"
				"/session <id> - Switch session\n"
				"/new <project> - New session\n"
				"/kill <id> - Kill session\n"
				"/status - Bot status\n"
				"/help - Show help\n\n"
				"Send any message to prompt the active session.",
				parse_mode="Markdown",
			)

	async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /help - Show commands."""
		await update.message.reply_text(
			"*Claude Code Commands*\n\n"
			"`/create <name>` - Create new project and start session\n"
			"`/new <project>` - Start session in existing project\n"
			"`/sessions` - List all active sessions\n"
			"`/session <id>` - Switch to a session\n"
			"`/kill <id>` - Kill a session\n"
			"`/status` - Show bot status\n\n"
			"*Prompting*\n"
			"Any message not starting with / is sent to the active session.\n\n"
			"*Approvals*\n"
			"Use inline buttons to approve/deny permission requests.",
			parse_mode="Markdown",
		)

	async def _cmd_sessions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /sessions - List active sessions."""
		if not self.sessions:
			await update.message.reply_text("No active sessions.")
			return

		lines = ["*Active Sessions*\n"]
		for sid, session in self.sessions.items():
			active = " (active)" if sid == self.active_session_id else ""
			status_icon = {
				SessionStatus.RUNNING: "🟢",
				SessionStatus.WAITING: "🟡",
				SessionStatus.DONE: "✅",
				SessionStatus.ERROR: "🔴",
			}.get(session.status, "⚪")

			lines.append(f"{status_icon} `{sid}`{active}")
			lines.append(f"   {session.project_path}")

		await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

	async def _cmd_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /session <id> - Switch to session."""
		if not context.args:
			if self.active_session_id:
				session = self.sessions.get(self.active_session_id)
				if session:
					await update.message.reply_text(
						f"*Active Session*\n\n"
						f"ID: `{self.active_session_id}`\n"
						f"Project: {session.project_name}\n"
						f"Path: {session.project_path}\n"
						f"Status: {session.status.value}",
						parse_mode="Markdown",
					)
					return
			await update.message.reply_text("No active session. Use `/session <id>` to switch.")
			return

		session_id = context.args[0]

		# Allow partial matching
		matches = [s for s in self.sessions.keys() if session_id in s]

		if not matches:
			await update.message.reply_text(f"Session not found: {session_id}")
			return

		if len(matches) > 1:
			await update.message.reply_text(
				f"Multiple matches:\n" + "\n".join(f"- `{m}`" for m in matches),
				parse_mode="Markdown",
			)
			return

		self.active_session_id = matches[0]
		session = self.sessions[self.active_session_id]
		await update.message.reply_text(
			f"Switched to: `{self.active_session_id}`\n"
			f"Project: {session.project_name}",
			parse_mode="Markdown",
		)

	async def _cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /new <project> - Start new session in existing project."""
		if not context.args:
			await update.message.reply_text(
				"Usage: /new <project_path_or_name>\n\n"
				"Examples:\n"
				"/new geoguessr-ai\n"
				"/new ~/personal_projects/my-app",
			)
			return

		project = " ".join(context.args)

		# Resolve project path
		if project.startswith("~") or project.startswith("/"):
			project_path = os.path.expanduser(project)
		else:
			# Assume it's in personal_projects
			project_path = os.path.expanduser(f"~/personal_projects/{project}")

		if not os.path.isdir(project_path):
			await update.message.reply_text(f"Directory not found: {project_path}")
			return

		project_name = os.path.basename(project_path)
		session_id = ClaudeSession.generate_id(project_name)

		await update.message.reply_text(f"Starting Claude CLI for {project_name}...")

		# Create startup message handler
		async def on_startup(msg: str):
			try:
				await update.message.reply_text(f"[Startup] {msg}")
			except Exception:
				pass

		# Create CLI bridge with callbacks
		cli_bridge = ClaudeCLIBridge(
			project_path=project_path,
			on_output=lambda output: self._handle_cli_output(session_id, output),
			on_permission=lambda prompt: self._handle_permission_request(session_id, prompt),
			on_startup_message=on_startup,
		)

		# Wait for Claude to be ready
		result: StartupResult = await cli_bridge.start(timeout=60)

		if not result.success:
			await update.message.reply_text(
				f"Failed to start Claude CLI:\n{result.message}\n\n"
				f"Startup output:\n" + "\n".join(result.startup_output[-5:])
			)
			return

		# Create session
		session = ClaudeSession(
			id=session_id,
			project_name=project_name,
			project_path=project_path,
			cli_bridge=cli_bridge,
		)

		self.sessions[session_id] = session
		self.active_session_id = session_id

		await update.message.reply_text(
			f"Claude Session Ready!\n\n"
			f"ID: {session_id}\n"
			f"Project: {project_name}\n"
			f"Path: {project_path}\n\n"
			f"Send a message to prompt Claude.",
		)

	async def _cmd_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /kill <id> - Kill session."""
		if not context.args:
			await update.message.reply_text("Usage: `/kill <session_id>`", parse_mode="Markdown")
			return

		session_id = context.args[0]

		# Allow partial matching
		matches = [s for s in self.sessions.keys() if session_id in s]

		if not matches:
			await update.message.reply_text(f"Session not found: {session_id}")
			return

		if len(matches) > 1:
			await update.message.reply_text(
				f"Multiple matches:\n" + "\n".join(f"- `{m}`" for m in matches),
				parse_mode="Markdown",
			)
			return

		target_id = matches[0]
		session = self.sessions.pop(target_id)

		if session.cli_bridge:
			await session.cli_bridge.stop()

		if self.active_session_id == target_id:
			self.active_session_id = None

		await update.message.reply_text(f"Killed session: `{target_id}`", parse_mode="Markdown")

	async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /status - Show bot status."""
		active = self.sessions.get(self.active_session_id) if self.active_session_id else None

		status_text = (
			"*Bot Status*\n\n"
			f"Sessions: {len(self.sessions)}\n"
			f"Pending approvals: {len(self.pending_approvals)}\n"
		)

		if active:
			status_text += (
				f"\n*Active Session*\n"
				f"ID: `{self.active_session_id}`\n"
				f"Project: {active.project_name}\n"
				f"Status: {active.status.value}"
			)
		else:
			status_text += "\nNo active session."

		await update.message.reply_text(status_text, parse_mode="Markdown")

	async def _cmd_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle /create <name> - Create a new project and start session."""
		if not context.args:
			await update.message.reply_text(
				"Usage: /create <project_name>\n\n"
				"Creates a new project in ~/personal_projects/ and starts a Claude session.\n\n"
				"Example: /create my-new-app",
			)
			return

		project_name = context.args[0]
		# Sanitize project name
		project_name = "".join(c for c in project_name if c.isalnum() or c in "-_")

		if not project_name:
			await update.message.reply_text("Invalid project name.")
			return

		project_path = os.path.expanduser(f"~/personal_projects/{project_name}")

		if os.path.exists(project_path):
			await update.message.reply_text(
				f"Project already exists: {project_name}\n"
				f"Use /new {project_name} to start a session in it.",
			)
			return

		await update.message.reply_text(f"Creating project: {project_name}...")

		try:
			# Create directory
			os.makedirs(project_path, exist_ok=True)

			# Initialize git
			import subprocess
			subprocess.run(["git", "init"], cwd=project_path, capture_output=True)

			await update.message.reply_text(
				f"Project Created\n\n"
				f"Name: {project_name}\n"
				f"Path: {project_path}\n"
				f"Git: Initialized\n\n"
				f"Starting Claude CLI...",
			)

			# Now start a Claude session in the new project
			session_id = ClaudeSession.generate_id(project_name)

			# Create startup message handler
			async def on_startup(msg: str):
				try:
					await update.message.reply_text(f"[Startup] {msg}")
				except Exception:
					pass

			cli_bridge = ClaudeCLIBridge(
				project_path=project_path,
				on_output=lambda output: self._handle_cli_output(session_id, output),
				on_permission=lambda prompt: self._handle_permission_request(session_id, prompt),
				on_startup_message=on_startup,
			)

			# Wait for Claude to actually be ready
			result: StartupResult = await cli_bridge.start(timeout=60)

			if not result.success:
				await update.message.reply_text(
					f"Failed to start Claude CLI:\n{result.message}\n\n"
					f"Startup output:\n" + "\n".join(result.startup_output[-5:])
				)
				return

			session = ClaudeSession(
				id=session_id,
				project_name=project_name,
				project_path=project_path,
				cli_bridge=cli_bridge,
			)

			self.sessions[session_id] = session
			self.active_session_id = session_id

			await update.message.reply_text(
				f"Claude Session Ready!\n\n"
				f"ID: {session_id}\n"
				f"Project: {project_name}\n\n"
				f"Send a message to describe what you want to build.",
			)

		except Exception as e:
			import traceback
			await update.message.reply_text(f"Error creating project: {e}\n\n{traceback.format_exc()[:500]}")

	# ==================== Message Handlers ====================

	async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle non-command messages as prompts to active session or replies to questions."""
		# Check if this is a reply to a pending question
		if update.message.reply_to_message:
			reply_to_id = update.message.reply_to_message.message_id
			if reply_to_id in self.message_to_question:
				question_id = self.message_to_question.pop(reply_to_id)
				if question_id in self.pending_questions:
					question = self.pending_questions.pop(question_id)
					response_text = update.message.text
					try:
						question.future.set_result(response_text)
					except asyncio.InvalidStateError:
						pass  # Already resolved by another path (CLI input)
					await update.message.reply_text("✅ Response received")
					return

		# Not a reply to a question - handle as session prompt
		if not self.active_session_id:
			await update.message.reply_text(
				"No active session. Use `/new <project>` or `/session <id>`",
				parse_mode="Markdown",
			)
			return

		session = self.sessions.get(self.active_session_id)
		if not session:
			await update.message.reply_text("Active session not found.")
			return

		if not session.cli_bridge or not session.cli_bridge.is_running:
			await update.message.reply_text("Session CLI not running. Use `/new` to start a new session.")
			return

		prompt = update.message.text
		session.last_activity = datetime.now()
		session.status = SessionStatus.RUNNING

		# Send acknowledgment
		await update.message.reply_text(
			f"[{session.project_name}] Sending prompt...",
		)

		try:
			# Send prompt to CLI bridge
			response = await session.cli_bridge.send_prompt(prompt)
			session.status = SessionStatus.DONE
			await self._send_response(session, response)
		except Exception as e:
			session.status = SessionStatus.ERROR
			await update.message.reply_text(f"Error: {e}")

	async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Handle inline keyboard callbacks (approvals and question options)."""
		query = update.callback_query
		await query.answer()

		data = query.data
		if ":" not in data:
			return

		parts = data.split(":")

		# Handle question option selection (qopt:question_id:option_index)
		if parts[0] == "qopt" and len(parts) == 3:
			question_id = parts[1]
			option_index = int(parts[2])

			if question_id not in self.pending_questions:
				await query.edit_message_text(
					f"{query.message.text}\n\n⚠️ Question expired or already answered.",
				)
				return

			question = self.pending_questions.pop(question_id)
			if question.options and 0 <= option_index < len(question.options):
				selected = question.options[option_index]
				await query.edit_message_text(
					f"{query.message.text}\n\n✅ Selected: {selected}",
				)
				try:
					question.future.set_result(selected)
				except asyncio.InvalidStateError:
					pass  # Already resolved by another path (CLI input)
			return

		# Handle approval callbacks (approve:id or deny:id)
		action, request_id = parts[0], parts[1]

		if request_id not in self.pending_approvals:
			await query.edit_message_text(
				f"{query.message.text}\n\n⚠️ Request expired or already handled.",
			)
			return

		request = self.pending_approvals.pop(request_id)

		if action == "approve":
			response = ApprovalResponse(request_id=request_id, status=ApprovalStatus.APPROVED)
			await query.edit_message_text(
				f"{query.message.text}\n\n✅ APPROVED",
			)
		elif action == "deny":
			response = ApprovalResponse(request_id=request_id, status=ApprovalStatus.DENIED)
			await query.edit_message_text(
				f"{query.message.text}\n\n❌ DENIED",
			)
		else:
			return

		# Resolve the future
		try:
			request.future.set_result(response)
		except asyncio.InvalidStateError:
			pass  # Already resolved by another path

		# Call callback if set
		if self._on_approval_callback:
			await self._on_approval_callback(response)

	# ==================== CLI Bridge Handlers ====================

	async def _handle_cli_output(self, session_id: str, output: CLIOutput):
		"""Handle output from Claude CLI."""
		if not self.chat_id or not self.app:
			return

		session = self.sessions.get(session_id)
		if not session:
			return

		# Only send significant output (not thinking indicators)
		if output.type in [OutputType.RESPONSE, OutputType.ERROR]:
			# Buffer the output - it will be sent as a complete response
			session.output_buffer.append(output.content)

	async def _handle_permission_request(self, session_id: str, prompt: str) -> bool:
		"""
		Handle permission request from Claude CLI.

		Sends approval request to Telegram and waits for response.
		Returns True if approved, False if denied.
		"""
		session = self.sessions.get(session_id)
		if session:
			session.status = SessionStatus.WAITING

		request_id = str(uuid.uuid4())[:8]
		response = await self.request_approval(
			session_id=session_id,
			request_id=request_id,
			action="Permission requested",
			context=prompt,
			timeout=300,  # 5 minute timeout
		)

		if session:
			session.status = SessionStatus.RUNNING

		return response.status == ApprovalStatus.APPROVED

	# ==================== Notifications ====================

	async def _send_response(self, session: ClaudeSession, response: str):
		"""Send Claude's response to Telegram."""
		if not self.chat_id or not self.app:
			return

		# Truncate if too long
		if len(response) > 4000:
			response = response[:4000] + "\n\n... (truncated)"

		message = (
			f"*[{session.project_name}]*\n"
			f"Status: {session.status.value}\n\n"
			f"{response}"
		)

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=message,
				parse_mode="Markdown",
			)
		except Exception as e:
			# Try without markdown if it fails
			try:
				await self.app.bot.send_message(
					chat_id=int(self.chat_id),
					text=message.replace("*", ""),
				)
			except Exception:
				print(f"Failed to send response: {e}")

	async def send_notification(
		self,
		session_id: str,
		status: str,
		message: str,
		needs_input: bool = False,
	):
		"""
		Send a detailed notification.

		Format:
			[SESSION: project-name]
			[STATUS: running/waiting/done/error]

			<message content>

			[Action buttons if needs_input]
		"""
		if not self.chat_id or not self.app:
			return

		session = self.sessions.get(session_id)
		project_name = session.project_name if session else "unknown"

		status_icon = {
			"running": "🟢",
			"waiting": "🟡",
			"done": "✅",
			"error": "🔴",
		}.get(status, "ℹ️")

		text = (
			f"*[SESSION: {project_name}]*\n"
			f"*[STATUS: {status_icon} {status}]*\n\n"
			f"{message}"
		)

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
				parse_mode="Markdown",
			)
		except Exception as e:
			print(f"Failed to send notification: {e}")

	async def request_approval(
		self,
		session_id: str,
		request_id: str,
		action: str,
		context: str,
		timeout: int = 3600,
	) -> ApprovalResponse:
		"""
		Request approval for an action.

		Args:
			session_id: The session requesting approval
			request_id: Unique ID for this request
			action: What action needs approval (e.g., "pip install requests")
			context: Additional context (e.g., files affected)
			timeout: Seconds to wait for response

		Returns:
			ApprovalResponse with status
		"""
		if not self.chat_id or not self.app:
			return ApprovalResponse(request_id=request_id, status=ApprovalStatus.TIMEOUT)

		session = self.sessions.get(session_id)
		project_name = session.project_name if session else "unknown"

		# Update session status
		if session:
			session.status = SessionStatus.WAITING

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		request = ApprovalRequest(
			id=request_id,
			session_id=session_id,
			action=action,
			context=context,
			future=future,
		)
		self.pending_approvals[request_id] = request

		# Build message
		text = (
			f"*Permission Request*\n\n"
			f"*Session:* {project_name}\n"
			f"*Action:* `{action}`\n\n"
			f"*Context:*\n{context}"
		)

		keyboard = InlineKeyboardMarkup([
			[
				InlineKeyboardButton("✅ Approve", callback_data=f"approve:{request_id}"),
				InlineKeyboardButton("❌ Deny", callback_data=f"deny:{request_id}"),
			]
		])

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
				parse_mode="Markdown",
				reply_markup=keyboard,
			)
		except Exception as e:
			self.pending_approvals.pop(request_id, None)
			return ApprovalResponse(request_id=request_id, status=ApprovalStatus.TIMEOUT)

		# Wait for response
		try:
			response = await asyncio.wait_for(future, timeout=timeout)
			if session:
				session.status = SessionStatus.RUNNING
			return response
		except asyncio.TimeoutError:
			self.pending_approvals.pop(request_id, None)
			if session:
				session.status = SessionStatus.RUNNING
			return ApprovalResponse(request_id=request_id, status=ApprovalStatus.TIMEOUT)

	# ==================== Callbacks ====================

	def set_prompt_callback(self, callback: Callable[[str, str], Awaitable[str]]):
		"""
		Set callback for handling prompts.

		Callback signature: async def callback(session_id: str, prompt: str) -> str
		"""
		self._on_prompt_callback = callback

	def set_approval_callback(self, callback: Callable[[ApprovalResponse], Awaitable[None]]):
		"""Set callback for when approval is received."""
		self._on_approval_callback = callback

	# ==================== Session Management ====================

	def get_session(self, session_id: str) -> Optional[ClaudeSession]:
		"""Get a session by ID."""
		return self.sessions.get(session_id)

	def get_active_session(self) -> Optional[ClaudeSession]:
		"""Get the currently active session."""
		if self.active_session_id:
			return self.sessions.get(self.active_session_id)
		return None

	def update_session_status(self, session_id: str, status: SessionStatus):
		"""Update a session's status."""
		if session_id in self.sessions:
			self.sessions[session_id].status = status
			self.sessions[session_id].last_activity = datetime.now()

	# ==================== MCP Tool Support ====================

	@staticmethod
	def _escape_markdown(text: str) -> str:
		"""Escape special Markdown characters for Telegram."""
		# Characters that need escaping in Telegram Markdown
		special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
		for char in special_chars:
			text = text.replace(char, f'\\{char}')
		return text

	@staticmethod
	def _level_icon(level: str) -> str:
		"""Get icon for notification level."""
		return {
			"info": "ℹ️",
			"warning": "⚠️",
			"error": "🚨",
			"success": "✅",
		}.get(level.lower(), "ℹ️")

	async def send_simple_notification(
		self,
		message: str,
		project: str = "",
		level: str = "info",
	) -> bool:
		"""
		Send a one-way notification (fire-and-forget).
		Used by telegram_notify MCP tool.

		Args:
			message: The message to send
			project: Project name for header (optional)
			level: Notification level (info/warning/error/success)

		Returns:
			True if sent successfully
		"""
		if not self.chat_id or not self.app:
			return False

		icon = self._level_icon(level)
		header = f"[{project}] " if project else ""
		text = f"{header}{icon} {level.upper()}\n\n{message}"

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
			)
			return True
		except Exception as e:
			print(f"Failed to send notification: {e}")
			return False

	async def send_question_with_options(
		self,
		question: str,
		options: List[str],
		project: str = "",
		context: str = "",
		allow_other: bool = True,
	) -> str:
		"""
		Send a question with predefined options as inline buttons.
		Blocks until user selects an option or types a custom response.

		Args:
			question: The question to ask
			options: List of option strings (shown as buttons)
			project: Project name for header
			context: Additional context for the question
			allow_other: Allow free-text "Other" option

		Returns:
			Selected option or custom text
		"""
		if not self.chat_id or not self.app:
			return "Error: Bot not initialized"

		question_id = str(uuid.uuid4())[:8]

		# Build message text
		header = f"[{project}] " if project else ""
		text = f"{header}🤔 QUESTION\n\n{question}"
		if context:
			text += f"\n\nContext: {context}"
		if allow_other:
			text += "\n\n(Reply to this message to provide a custom answer)"

		# Build inline keyboard - one button per row for clarity
		keyboard_rows = []
		for i, option in enumerate(options):
			callback_data = f"qopt:{question_id}:{i}"
			keyboard_rows.append([InlineKeyboardButton(option, callback_data=callback_data)])

		keyboard = InlineKeyboardMarkup(keyboard_rows)

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		try:
			sent_message = await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
				reply_markup=keyboard,
			)

			# Store pending question
			pending = PendingQuestion(
				id=question_id,
				project=project,
				question=question,
				options=options,
				allow_other=allow_other,
				message_id=sent_message.message_id,
				future=future,
			)
			self.pending_questions[question_id] = pending
			self.message_to_question[sent_message.message_id] = question_id

			# Wait indefinitely for response
			response = await future
			return response

		except Exception as e:
			return f"Error: {e}"
		finally:
			# Cleanup
			self.pending_questions.pop(question_id, None)
			# Don't remove message_to_question here - might be needed for cleanup

	async def send_question_freeform(
		self,
		question: str,
		project: str = "",
		context: str = "",
		hint: str = "",
	) -> str:
		"""
		Send an open-ended question and wait for text response.
		Uses Telegram's reply-to feature for tracking.

		Args:
			question: The question to ask
			project: Project name for header
			context: Additional context
			hint: Example of expected response format

		Returns:
			User's text response
		"""
		if not self.chat_id or not self.app:
			return "Error: Bot not initialized"

		question_id = str(uuid.uuid4())[:8]

		# Build message text
		header = f"[{project}] " if project else ""
		text = f"{header}💬 QUESTION\n\n{question}"
		if context:
			text += f"\n\nContext: {context}"
		if hint:
			text += f"\n\nHint: {hint}"
		text += "\n\n👆 Reply to this message with your answer"

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		try:
			sent_message = await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
			)

			# Store pending question
			pending = PendingQuestion(
				id=question_id,
				project=project,
				question=question,
				options=None,
				allow_other=True,
				message_id=sent_message.message_id,
				future=future,
			)
			self.pending_questions[question_id] = pending
			self.message_to_question[sent_message.message_id] = question_id

			# Wait indefinitely for response
			response = await future
			return response

		except Exception as e:
			return f"Error: {e}"
		finally:
			# Cleanup
			self.pending_questions.pop(question_id, None)

	async def send_phase_update(
		self,
		project: str,
		phase_number: int,
		total_phases: int,
		phase_name: str,
		summary: str,
		test_results: Optional[Dict[str, int]] = None,
		commit_hash: str = "",
		concerns: Optional[List[str]] = None,
		next_phase: str = "",
	) -> bool:
		"""
		Send structured phase completion update.

		Args:
			project: Project name
			phase_number: Current phase (1-indexed)
			total_phases: Total phases planned
			phase_name: Name of completed phase
			summary: What was implemented
			test_results: Test pass/fail/skip counts
			commit_hash: Git commit hash if committed
			concerns: Any implementation concerns
			next_phase: Description of next phase

		Returns:
			True if sent successfully
		"""
		if not self.chat_id or not self.app:
			return False

		# Build message
		lines = [f"[{project}] ✅ PHASE {phase_number}/{total_phases} COMPLETE"]
		lines.append("")
		lines.append(f"Phase: {phase_name}")
		lines.append("")
		lines.append(f"Summary:\n{summary}")

		if test_results:
			passed = test_results.get("passed", 0)
			failed = test_results.get("failed", 0)
			skipped = test_results.get("skipped", 0)
			test_icon = "✅" if failed == 0 else "❌"
			lines.append("")
			lines.append(f"{test_icon} Tests: {passed} passed, {failed} failed, {skipped} skipped")

		if commit_hash:
			lines.append(f"Commit: {commit_hash[:7]}")

		if concerns:
			lines.append("")
			lines.append("Concerns:")
			for concern in concerns:
				lines.append(f"  - {concern}")

		if next_phase:
			lines.append("")
			lines.append(f"Next: {next_phase}")

		text = "\n".join(lines)

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
			)
			return True
		except Exception as e:
			print(f"Failed to send phase update: {e}")
			return False

	async def send_escalation(
		self,
		error_type: str,
		description: str,
		context: str,
		attempts: int,
		project: str = "",
		suggestions: Optional[List[str]] = None,
	) -> str:
		"""
		Send escalation message and wait for user guidance.

		Args:
			error_type: Category of error
			description: What went wrong
			context: Full context including stack traces
			attempts: How many times Claude tried to fix it
			project: Project name
			suggestions: Claude's suggestions for resolution

		Returns:
			User's guidance/instructions
		"""
		if not self.chat_id or not self.app:
			return "Error: Bot not initialized"

		question_id = str(uuid.uuid4())[:8]

		# Build message
		header = f"[{project}] " if project else ""
		lines = [f"{header}🚨 ESCALATION"]
		lines.append("")
		lines.append(f"Type: {error_type}")
		lines.append(f"Attempts: {attempts}")
		lines.append("")
		lines.append(f"Description:\n{description}")
		lines.append("")
		lines.append(f"Context:\n{context}")

		if suggestions:
			lines.append("")
			lines.append("Suggestions:")
			for i, suggestion in enumerate(suggestions, 1):
				lines.append(f"  {i}. {suggestion}")

		lines.append("")
		lines.append("What should I do?")
		lines.append("👆 Reply to this message with instructions")

		text = "\n".join(lines)

		# Truncate if too long
		if len(text) > 4000:
			text = text[:3950] + "\n\n... (truncated)"

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		try:
			sent_message = await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
			)

			# Store pending question
			pending = PendingQuestion(
				id=question_id,
				project=project,
				question="escalation",
				options=None,
				allow_other=True,
				message_id=sent_message.message_id,
				future=future,
			)
			self.pending_questions[question_id] = pending
			self.message_to_question[sent_message.message_id] = question_id

			# Wait indefinitely for response
			response = await future
			return response

		except Exception as e:
			return f"Error: {e}"
		finally:
			self.pending_questions.pop(question_id, None)

	async def send_approval_request(
		self,
		action: str,
		context: str,
		project: str = "",
		consequences: str = "",
		reversible: bool = True,
	) -> bool:
		"""
		Request yes/no approval for an action.

		Args:
			action: What action needs approval
			context: Why this action is needed
			project: Project name for header
			consequences: What happens if approved
			reversible: Whether action can be undone

		Returns:
			True if approved, False if denied
		"""
		if not self.chat_id or not self.app:
			return False

		request_id = str(uuid.uuid4())[:8]

		# Build message
		header = f"[{project}] " if project else ""
		lines = [f"{header}⚠️ APPROVAL NEEDED"]
		lines.append("")
		lines.append(f"Action: {action}")
		lines.append("")
		lines.append(f"Context: {context}")

		if consequences:
			lines.append("")
			lines.append(f"Consequences: {consequences}")

		reversible_text = "Yes (can be undone)" if reversible else "No (irreversible)"
		lines.append(f"Reversible: {reversible_text}")

		text = "\n".join(lines)

		keyboard = InlineKeyboardMarkup([
			[
				InlineKeyboardButton("✅ Approve", callback_data=f"approve:{request_id}"),
				InlineKeyboardButton("❌ Deny", callback_data=f"deny:{request_id}"),
			]
		])

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		request = ApprovalRequest(
			id=request_id,
			session_id=project,  # Use project as session_id for MCP tools
			action=action,
			context=context,
			future=future,
		)
		self.pending_approvals[request_id] = request

		try:
			await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
				reply_markup=keyboard,
			)

			# Wait indefinitely
			response = await future
			return response.status == ApprovalStatus.APPROVED

		except Exception as e:
			print(f"Failed to send approval request: {e}")
			return False
		finally:
			self.pending_approvals.pop(request_id, None)

	# =========================================================================
	# Dual-Input Methods (Terminal + Telegram)
	# =========================================================================

	async def send_question_non_blocking(
		self,
		question: str,
		options: List[str],
		project: str = "",
		context: str = "",
		allow_other: bool = True,
	) -> str:
		"""
		Send a question to Telegram but return immediately with question_id.
		Does NOT block - use check_question_status or answer_question to handle response.

		Args:
			question: The question to ask
			options: List of option strings (shown as buttons)
			project: Project name for header
			context: Additional context for the question
			allow_other: Allow free-text "Other" option

		Returns:
			question_id for tracking
		"""
		if not self.chat_id or not self.app:
			return ""

		question_id = str(uuid.uuid4())[:8]

		# Build message text
		header = f"[{project}] " if project else ""
		text = f"{header}🤔 QUESTION\n\n{question}"
		if context:
			text += f"\n\nContext: {context}"
		text += "\n\n(You can also respond in Claude Code terminal)"

		# Build inline keyboard - one button per row for clarity
		keyboard_rows = []
		for i, option in enumerate(options):
			callback_data = f"qopt:{question_id}:{i}"
			keyboard_rows.append([InlineKeyboardButton(option, callback_data=callback_data)])

		keyboard = InlineKeyboardMarkup(keyboard_rows)

		# Create future for response
		future = asyncio.get_event_loop().create_future()

		try:
			sent_message = await self.app.bot.send_message(
				chat_id=int(self.chat_id),
				text=text,
				reply_markup=keyboard,
			)

			# Store pending question
			pending = PendingQuestion(
				id=question_id,
				project=project,
				question=question,
				options=options,
				allow_other=allow_other,
				message_id=sent_message.message_id,
				future=future,
			)
			self.pending_questions[question_id] = pending
			self.message_to_question[sent_message.message_id] = question_id

			return question_id

		except Exception as e:
			print(f"Failed to send question: {e}")
			return ""

	async def answer_question(self, question_id: str, answer: str) -> bool:
		"""
		Answer a pending question programmatically (from CLI input).

		Args:
			question_id: The question ID returned by send_question_non_blocking
			answer: The answer to submit

		Returns:
			True if question was found and answered, False otherwise
		"""
		if question_id not in self.pending_questions:
			return False

		pending = self.pending_questions[question_id]

		# Resolve the future (use try/except to handle race with Telegram callback)
		try:
			pending.future.set_result(answer)
		except asyncio.InvalidStateError:
			# Already resolved by Telegram callback - that's fine
			pass

		# Update Telegram message to show it was answered
		if self.app and self.chat_id:
			try:
				await self.app.bot.edit_message_text(
					chat_id=int(self.chat_id),
					message_id=pending.message_id,
					text=f"✅ Answered via terminal: {answer}",
				)
			except Exception:
				pass  # Message may have been deleted

		# Cleanup
		self.pending_questions.pop(question_id, None)
		self.message_to_question.pop(pending.message_id, None)

		return True

	def check_question_status(self, question_id: str) -> dict:
		"""
		Check if a question has been answered via Telegram.

		Args:
			question_id: The question ID to check

		Returns:
			Dict with 'answered' bool and 'response' if answered
		"""
		if question_id not in self.pending_questions:
			return {"answered": False, "error": "Question not found"}

		pending = self.pending_questions[question_id]

		if pending.future.done():
			try:
				response = pending.future.result()
				# Cleanup
				self.pending_questions.pop(question_id, None)
				self.message_to_question.pop(pending.message_id, None)
				return {"answered": True, "response": response}
			except Exception as e:
				return {"answered": False, "error": str(e)}

		return {"answered": False, "pending": True}

	async def cancel_question(self, question_id: str) -> bool:
		"""
		Cancel a pending question.

		Args:
			question_id: The question ID to cancel

		Returns:
			True if cancelled, False if not found
		"""
		if question_id not in self.pending_questions:
			return False

		pending = self.pending_questions[question_id]

		# Cancel the future if not done
		if not pending.future.done():
			pending.future.cancel()

		# Update Telegram message
		if self.app and self.chat_id:
			try:
				await self.app.bot.edit_message_text(
					chat_id=int(self.chat_id),
					message_id=pending.message_id,
					text=f"❌ Question cancelled",
				)
			except Exception:
				pass

		# Cleanup
		self.pending_questions.pop(question_id, None)
		self.message_to_question.pop(pending.message_id, None)

		return True
