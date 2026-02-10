"""Session event reporting for structured Telegram notifications.

Provides formatting functions for session lifecycle events. The formatted
messages are designed to be sent via telegram_notify or telegram_phase_update
MCP tools. Protocol guidance tells agents when to call these formatters.

Event types:
- phase_start: Beginning work on a new phase
- phase_complete: Phase finished with verification results
- checkpoint: Pausing for human review
- blocked: Cannot proceed, needs human intervention
- session_complete: All phases done or session ending
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionEvent:
	"""A structured session event for reporting."""

	event_type: str
	project_name: str
	phase_name: str = ""
	session_id: str = ""
	timestamp: str = ""
	details: dict[str, str] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if not self.timestamp:
			self.timestamp = datetime.now().strftime("%H:%M")


def format_phase_start(
	phase_name: str,
	project_name: str,
	session_id: str = "",
) -> str:
	"""Format a phase start notification."""
	header = f"[{project_name}]"
	if session_id:
		header += f" Session {session_id}"
	return f"{header}\nStarting: {phase_name}"


def format_phase_complete(
	phase_name: str,
	project_name: str,
	verification_passed: bool = True,
	verification_summary: str = "",
	commit_hash: str = "",
) -> str:
	"""Format a phase completion notification."""
	status = "PASS" if verification_passed else "FAIL"
	lines = [f"[{project_name}] Phase complete: {phase_name}"]
	lines.append(f"Verification: {status}")
	if verification_summary:
		lines.append(f"Details: {verification_summary}")
	if commit_hash:
		lines.append(f"Commit: {commit_hash[:7]}")
	return "\n".join(lines)


def format_checkpoint(
	phase_name: str,
	project_name: str,
	summary: str = "",
	risks: list[str] | None = None,
	next_phase: str = "",
) -> str:
	"""Format a checkpoint review notification."""
	lines = [f"[{project_name}] CHECKPOINT: {phase_name}"]
	if summary:
		lines.append(f"Summary: {summary}")
	if risks:
		lines.append(f"Risks: {', '.join(risks)}")
	if next_phase:
		lines.append(f"Next: {next_phase}")
	lines.append("Awaiting approval to continue.")
	return "\n".join(lines)


def format_blocked(
	phase_name: str,
	project_name: str,
	reason: str,
	attempts: int = 0,
) -> str:
	"""Format a blocked notification."""
	lines = [f"[{project_name}] BLOCKED: {phase_name}"]
	lines.append(f"Reason: {reason}")
	if attempts:
		lines.append(f"Attempts: {attempts}")
	lines.append("Human intervention required.")
	return "\n".join(lines)


def format_session_complete(
	project_name: str,
	phases_completed: list[str],
	session_id: str = "",
	total_commits: int = 0,
) -> str:
	"""Format a session completion notification."""
	header = f"[{project_name}]"
	if session_id:
		header += f" Session {session_id}"
	lines = [f"{header} SESSION COMPLETE"]
	lines.append(f"Phases: {len(phases_completed)} completed")
	for phase in phases_completed:
		lines.append(f"  - {phase}")
	if total_commits:
		lines.append(f"Commits: {total_commits}")
	return "\n".join(lines)
