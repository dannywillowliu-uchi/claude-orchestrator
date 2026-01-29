"""Rich views for tool call statistics and timelines."""

from typing import Optional

from rich.console import Console
from rich.table import Table

from ..instrumentation import ToolCallStore
from .utils import format_duration, format_timestamp, status_style, status_text, truncate_args


def render_tool_stats(store: ToolCallStore, console: Optional[Console] = None, since: Optional[str] = None) -> None:
	"""Render a table of aggregate tool stats."""
	console = console or Console()
	stats = store.get_stats()

	if not stats:
		console.print("[dim]No tool call data recorded yet.[/dim]")
		return

	table = Table(title="Tool Call Statistics")
	table.add_column("Tool", style="cyan")
	table.add_column("Calls", justify="right")
	table.add_column("Avg Duration", justify="right")
	table.add_column("Success %", justify="right")
	table.add_column("Last Called")

	for s in stats:
		success_style = "green" if s.success_rate >= 90 else ("yellow" if s.success_rate >= 70 else "red")
		table.add_row(
			s.tool_name,
			str(s.call_count),
			format_duration(s.avg_duration),
			f"[{success_style}]{s.success_rate:.1f}%[/{success_style}]",
			format_timestamp(s.last_called),
		)

	console.print(table)


def render_tool_timeline(
	store: ToolCallStore,
	console: Optional[Console] = None,
	limit: int = 50,
	since: Optional[str] = None,
) -> None:
	"""Render a chronological timeline of recent tool calls."""
	console = console or Console()
	records = store.query(since=since, limit=limit)

	if not records:
		console.print("[dim]No tool calls recorded yet.[/dim]")
		return

	table = Table(title=f"Tool Call Timeline (last {len(records)})")
	table.add_column("Time")
	table.add_column("Tool", style="cyan")
	table.add_column("Args")
	table.add_column("Duration", justify="right")
	table.add_column("Status", justify="center")

	for r in records:
		style = status_style(r.success)
		table.add_row(
			format_timestamp(r.timestamp),
			r.tool_name,
			truncate_args(r.args_json),
			format_duration(r.duration_seconds),
			f"[{style}]{status_text(r.success)}[/{style}]",
		)

	console.print(table)


def render_tool_detail(
	store: ToolCallStore,
	tool_name: str,
	console: Optional[Console] = None,
	limit: int = 20,
) -> None:
	"""Render detailed view for a specific tool."""
	console = console or Console()
	records = store.query(tool_name=tool_name, limit=limit)

	if not records:
		console.print(f"[dim]No calls recorded for tool '{tool_name}'.[/dim]")
		return

	# Summary
	total = len(records)
	successes = sum(1 for r in records if r.success)
	durations = [r.duration_seconds for r in records]
	avg_dur = sum(durations) / len(durations)

	console.print(f"\n[bold cyan]{tool_name}[/bold cyan]")
	console.print(f"  Calls: {total}  |  Success: {successes}/{total}  |  Avg: {format_duration(avg_dur)}")
	console.print()

	table = Table(title=f"Recent calls to {tool_name}")
	table.add_column("Time")
	table.add_column("Args")
	table.add_column("Result")
	table.add_column("Duration", justify="right")
	table.add_column("Status", justify="center")

	for r in records:
		style = status_style(r.success)
		table.add_row(
			format_timestamp(r.timestamp),
			truncate_args(r.args_json, 40),
			truncate_args(r.result_summary, 40),
			format_duration(r.duration_seconds),
			f"[{style}]{status_text(r.success)}[/{style}]",
		)

	console.print(table)
