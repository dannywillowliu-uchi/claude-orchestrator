"""
Visualizer - Rich console output showing orchestration flow.

Provides beautiful console output that shows:
- Phase transitions
- Component actions
- Data flow between components
- Progress bars for multi-step operations
- Final results with pass/fail styling
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

try:
	from rich import box
	from rich.console import Console
	from rich.panel import Panel
	from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
	from rich.table import Table
	from rich.tree import Tree
	RICH_AVAILABLE = True
except ImportError:
	RICH_AVAILABLE = False


class OutputLevel(str, Enum):
	"""Output verbosity level."""
	MINIMAL = "minimal"
	NORMAL = "normal"
	VERBOSE = "verbose"


@dataclass
class Event:
	"""An event in the orchestration flow."""
	timestamp: str
	component: str
	action: str
	details: dict
	level: str = "info"


class Visualizer:
	"""
	Rich console visualization of orchestration flow.

	Provides formatted output showing what each component is doing
	at each step of the orchestration.
	"""

	PHASE_EMOJIS = {
		"planning": "📋",
		"delegation": "🚀",
		"supervision": "👁️",
		"verification": "✅",
		"complete": "🎉",
		"error": "❌",
	}

	COMPONENT_COLORS = {
		"Planner": "cyan",
		"ContextBuilder": "yellow",
		"TaskDelegator": "green",
		"Supervisor": "blue",
		"Verifier": "magenta",
	}

	def __init__(
		self,
		verbose: bool = True,
		output_level: OutputLevel = OutputLevel.NORMAL,
		log_file: str | None = None,
	):
		"""
		Initialize the visualizer.

		Args:
			verbose: Enable verbose output
			output_level: How much detail to show
			log_file: Optional file to log events
		"""
		self.verbose = verbose
		self.output_level = output_level
		self.events: list[Event] = []

		if RICH_AVAILABLE:
			self.console = Console()
		else:
			self.console = None

		# Setup file logging if requested
		self.logger = None
		if log_file:
			self.logger = logging.getLogger("orchestration.visualizer")
			handler = logging.FileHandler(log_file)
			handler.setFormatter(logging.Formatter(
				"%(asctime)s - %(levelname)s - %(message)s"
			))
			self.logger.addHandler(handler)
			self.logger.setLevel(logging.DEBUG if verbose else logging.INFO)

	def show_phase(self, phase: str, description: str):
		"""
		Display a phase header.

		Args:
			phase: Phase name (planning, delegation, supervision, verification)
			description: Description of what's happening
		"""
		emoji = self.PHASE_EMOJIS.get(phase.lower(), "▶")
		header = f"{emoji} PHASE: {phase.upper()}"

		self._log_event("Phase", "start", {"phase": phase, "description": description})

		if self.console:
			self.console.print()
			self.console.rule(header, style="bold white")
			self.console.print(f"[dim]{description}[/dim]")
			self.console.print()
		else:
			print(f"\n{'=' * 60}")
			print(f"{header}")
			print(f"{'=' * 60}")
			print(description)
			print()

	def show_component(self, component: str, action: str, details: dict | None = None):
		"""
		Show what a component is doing.

		Args:
			component: Component name (Planner, Delegator, etc.)
			action: What it's doing
			details: Additional details
		"""
		self._log_event(component, action, details or {})

		color = self.COMPONENT_COLORS.get(component, "white")

		if self.console:
			self.console.print(f"[{color}][{component}][/{color}] {action}")

			if details and self.output_level != OutputLevel.MINIMAL:
				for key, value in details.items():
					if isinstance(value, list):
						for item in value[:5]:  # Max 5 items
							self.console.print(f"  → {item}")
					else:
						self.console.print(f"  → {key}: {value}")
		else:
			print(f"[{component}] {action}")
			if details and self.output_level != OutputLevel.MINIMAL:
				for key, value in details.items():
					print(f"  -> {key}: {value}")

	def show_data_flow(self, from_: str, to: str, data_summary: str):
		"""
		Show data flowing between components.

		Args:
			from_: Source component
			to: Destination component
			data_summary: Summary of what's being passed
		"""
		self._log_event("DataFlow", f"{from_} -> {to}", {"summary": data_summary})

		if self.output_level == OutputLevel.MINIMAL:
			return

		if self.console:
			self.console.print(
				f"  [dim]{from_}[/dim] → [dim]{to}[/dim]: {data_summary}"
			)
		else:
			print(f"  {from_} -> {to}: {data_summary}")

	def show_progress(self, current: int, total: int, label: str):
		"""
		Show progress for multi-step operations.

		Args:
			current: Current step
			total: Total steps
			label: What's being processed
		"""
		if self.output_level == OutputLevel.MINIMAL:
			return

		pct = (current / total) * 100 if total > 0 else 0
		bar_width = 20
		filled = int(bar_width * current / total) if total > 0 else 0
		bar = "█" * filled + "░" * (bar_width - filled)

		if self.console:
			self.console.print(
				f"  [{bar}] {current}/{total} ({pct:.0f}%) - {label}",
				end="\r" if current < total else "\n"
			)
		else:
			print(f"  [{bar}] {current}/{total} ({pct:.0f}%) - {label}")

	def show_question(self, question_id: str, question: str, options: list[str] | None = None):
		"""
		Show a planning question.

		Args:
			question_id: Question ID (e.g., "q1")
			question: The question text
			options: Optional list of choices
		"""
		if self.console:
			self.console.print(f"\n[bold cyan]Q{question_id}:[/bold cyan] {question}")
			if options:
				for i, opt in enumerate(options, 1):
					self.console.print(f"    {i}. {opt}")
		else:
			print(f"\nQ{question_id}: {question}")
			if options:
				for i, opt in enumerate(options, 1):
					print(f"    {i}. {opt}")

	def show_answer(self, question_id: str, answer: str):
		"""
		Show an answer to a planning question.

		Args:
			question_id: Question ID
			answer: The answer
		"""
		if self.console:
			self.console.print(f"  [green]→ {answer[:100]}{'...' if len(answer) > 100 else ''}[/green]")
		else:
			print(f"  -> {answer[:100]}{'...' if len(answer) > 100 else ''}")

	def show_plan_summary(self, plan_summary: dict):
		"""
		Show a summary of the generated plan.

		Args:
			plan_summary: Dict with plan details
		"""
		self._log_event("Plan", "generated", plan_summary)

		if self.console:
			tree = Tree("[bold]Plan Structure[/bold]")

			for phase in plan_summary.get("phases", []):
				phase_branch = tree.add(f"[cyan]{phase['name']}[/cyan] ({len(phase.get('tasks', []))} tasks)")
				for task in phase.get("tasks", [])[:3]:  # Max 3 tasks shown
					phase_branch.add(f"[dim]{task}[/dim]")
				if len(phase.get("tasks", [])) > 3:
					phase_branch.add(f"[dim]... and {len(phase['tasks']) - 3} more[/dim]")

			self.console.print(tree)
		else:
			print("\nPlan Structure:")
			for phase in plan_summary.get("phases", []):
				print(f"├─ {phase['name']} ({len(phase.get('tasks', []))} tasks)")
				for task in phase.get("tasks", [])[:3]:
					print(f"│  └─ {task}")

	def show_delegation(self, task_id: str, description: str, context_tokens: int):
		"""
		Show a task being delegated.

		Args:
			task_id: Task ID
			description: Task description
			context_tokens: Token count in context
		"""
		self._log_event("TaskDelegator", "delegate", {
			"task_id": task_id,
			"description": description,
			"context_tokens": context_tokens,
		})

		if self.console:
			self.console.print(
				f"  [green]Delegating:[/green] {task_id}"
			)
			self.console.print(f"    Description: {description[:60]}...")
			self.console.print(f"    Context: {context_tokens:,} tokens")
		else:
			print(f"  Delegating: {task_id}")
			print(f"    Description: {description[:60]}...")
			print(f"    Context: {context_tokens:,} tokens")

	def show_verification_result(self, check: str, status: str, duration: float):
		"""
		Show a verification check result.

		Args:
			check: Check name (pytest, ruff, mypy, bandit)
			status: passed, failed, skipped, error
			duration: Time taken in seconds
		"""
		status_colors = {
			"passed": "green",
			"failed": "red",
			"skipped": "yellow",
			"error": "red",
		}
		status_icons = {
			"passed": "✓",
			"failed": "✗",
			"skipped": "○",
			"error": "!",
		}

		color = status_colors.get(status, "white")
		icon = status_icons.get(status, "?")

		if self.console:
			self.console.print(
				f"  [{color}]{icon}[/{color}] {check:12} [{color}]{status.upper():8}[/{color}] ({duration:.1f}s)"
			)
		else:
			print(f"  {icon} {check:12} {status.upper():8} ({duration:.1f}s)")

	def show_result(self, success: bool, summary: str, details: dict | None = None):
		"""
		Show final result with pass/fail styling.

		Args:
			success: Whether orchestration succeeded
			summary: Summary message
			details: Optional additional details
		"""
		self._log_event("Result", "success" if success else "failure", {
			"summary": summary,
			**(details or {}),
		})

		emoji = "🎉" if success else "❌"
		status = "COMPLETE" if success else "FAILED"

		if self.console:
			style = "bold green" if success else "bold red"
			self.console.print()
			self.console.rule(f"{emoji} ORCHESTRATION {status}", style=style)
			self.console.print()

			if details:
				table = Table(box=box.SIMPLE)
				table.add_column("Metric", style="cyan")
				table.add_column("Value")

				for key, value in details.items():
					table.add_row(key, str(value))

				self.console.print(table)

			self.console.print(f"\n[{'green' if success else 'red'}]{summary}[/]")
		else:
			print(f"\n{'=' * 60}")
			print(f"{emoji} ORCHESTRATION {status}")
			print(f"{'=' * 60}")
			if details:
				for key, value in details.items():
					print(f"  {key}: {value}")
			print(f"\n{summary}")

	def show_error(self, component: str, error: str, recoverable: bool = True):
		"""
		Show an error.

		Args:
			component: Component that errored
			error: Error message
			recoverable: Whether this is recoverable
		"""
		self._log_event(component, "error", {"error": error, "recoverable": recoverable}, "error")

		if self.console:
			style = "yellow" if recoverable else "red"
			self.console.print(
				f"[{style}][ERROR][/{style}] [{component}] {error}"
			)
		else:
			print(f"[ERROR] [{component}] {error}")

	def _log_event(self, component: str, action: str, details: dict, level: str = "info"):
		"""Log an event internally."""
		event = Event(
			timestamp=datetime.now().isoformat(),
			component=component,
			action=action,
			details=details,
			level=level,
		)
		self.events.append(event)

		if self.logger:
			log_msg = f"{component} - {action}: {details}"
			if level == "error":
				self.logger.error(log_msg)
			elif level == "warning":
				self.logger.warning(log_msg)
			else:
				self.logger.info(log_msg)

	def get_event_log(self) -> list[dict]:
		"""Get all logged events."""
		return [
			{
				"timestamp": e.timestamp,
				"component": e.component,
				"action": e.action,
				"details": e.details,
				"level": e.level,
			}
			for e in self.events
		]
