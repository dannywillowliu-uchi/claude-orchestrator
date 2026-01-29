"""Rich views for session timelines."""

from typing import Optional

from rich.console import Console
from rich.table import Table

from ..instrumentation import ToolCallStore
from .utils import format_duration, format_timestamp, status_style, status_text, truncate_args


def render_session_list(store: ToolCallStore, console: Optional[Console] = None) -> None:
	"""Render a table of sessions with call counts and time ranges."""
	console = console or Console()

	# Get all records grouped by session
	all_records = store.query(limit=10000)

	if not all_records:
		console.print("[dim]No sessions recorded yet.[/dim]")
		return

	sessions: dict[str, dict] = {}
	for r in all_records:
		sid = r.session_id or "(no session)"
		if sid not in sessions:
			sessions[sid] = {
				"count": 0,
				"first": r.timestamp,
				"last": r.timestamp,
				"successes": 0,
				"total_duration": 0.0,
			}
		s = sessions[sid]
		s["count"] += 1
		s["total_duration"] += r.duration_seconds
		if r.success:
			s["successes"] += 1
		if r.timestamp < s["first"]:
			s["first"] = r.timestamp
		if r.timestamp > s["last"]:
			s["last"] = r.timestamp

	table = Table(title="Sessions")
	table.add_column("Session ID", style="cyan")
	table.add_column("Calls", justify="right")
	table.add_column("Success %", justify="right")
	table.add_column("Total Time", justify="right")
	table.add_column("First Call")
	table.add_column("Last Call")

	for sid, info in sorted(sessions.items(), key=lambda x: x[1]["last"], reverse=True):
		rate = info["successes"] / info["count"] * 100 if info["count"] > 0 else 0
		rate_style = "green" if rate >= 90 else ("yellow" if rate >= 70 else "red")
		table.add_row(
			sid,
			str(info["count"]),
			f"[{rate_style}]{rate:.0f}%[/{rate_style}]",
			format_duration(info["total_duration"]),
			format_timestamp(info["first"]),
			format_timestamp(info["last"]),
		)

	console.print(table)


def render_session_detail(
	store: ToolCallStore,
	session_id: str,
	console: Optional[Console] = None,
) -> None:
	"""Render a chronological tool call timeline for a single session."""
	console = console or Console()
	records = store.query(session_id=session_id, limit=500)

	if not records:
		console.print(f"[dim]No calls found for session '{session_id}'.[/dim]")
		return

	# Records come newest-first; reverse for chronological
	records = list(reversed(records))

	console.print(f"\n[bold cyan]Session: {session_id}[/bold cyan]")
	console.print(f"  Calls: {len(records)}")
	console.print()

	table = Table(title=f"Timeline for {session_id}")
	table.add_column("#", justify="right", style="dim")
	table.add_column("Time")
	table.add_column("Tool", style="cyan")
	table.add_column("Args")
	table.add_column("Duration", justify="right")
	table.add_column("Status", justify="center")

	for i, r in enumerate(records, 1):
		style = status_style(r.success)
		table.add_row(
			str(i),
			format_timestamp(r.timestamp),
			r.tool_name,
			truncate_args(r.args_json),
			format_duration(r.duration_seconds),
			f"[{style}]{status_text(r.success)}[/{style}]",
		)

	console.print(table)
