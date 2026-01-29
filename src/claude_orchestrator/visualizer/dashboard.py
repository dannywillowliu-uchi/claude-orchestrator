"""Combined dashboard view."""

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..instrumentation import ToolCallStore
from ..plans.models import Plan
from .plan_progress import render_plan_progress
from .utils import format_duration, format_timestamp, status_style, status_text, truncate_args


def render_dashboard(
	store: ToolCallStore,
	plan: Optional[Plan] = None,
	console: Optional[Console] = None,
) -> None:
	"""Render a combined dashboard with stats, timeline, and plan progress."""
	console = console or Console()

	console.print()
	console.rule("[bold cyan]Orchestrator Dashboard[/bold cyan]")
	console.print()

	# Top: summary stats
	stats = store.get_stats()
	all_records = store.query(limit=10000)

	if not stats and not all_records:
		console.print("[dim]No data recorded yet. Use MCP tools to generate activity.[/dim]")
		console.print()
	else:
		total_calls = sum(s.call_count for s in stats)
		total_tools = len(stats)
		sessions = set(r.session_id for r in all_records if r.session_id)
		overall_success = (
			sum(1 for r in all_records if r.success) / len(all_records) * 100
			if all_records else 0
		)

		summary = (
			f"[bold]Total calls:[/bold] {total_calls}  |  "
			f"[bold]Tools used:[/bold] {total_tools}  |  "
			f"[bold]Sessions:[/bold] {len(sessions)}  |  "
			f"[bold]Success rate:[/bold] {overall_success:.1f}%"
		)
		console.print(Panel(summary, title="Summary", border_style="green"))
		console.print()

		# Middle: recent timeline (last 20)
		recent = store.query(limit=20)
		if recent:
			table = Table(title="Recent Tool Calls")
			table.add_column("Time")
			table.add_column("Tool", style="cyan")
			table.add_column("Args")
			table.add_column("Duration", justify="right")
			table.add_column("Status", justify="center")

			for r in recent:
				style = status_style(r.success)
				table.add_row(
					format_timestamp(r.timestamp),
					r.tool_name,
					truncate_args(r.args_json, 40),
					format_duration(r.duration_seconds),
					f"[{style}]{status_text(r.success)}[/{style}]",
				)
			console.print(table)
			console.print()

	# Bottom: plan progress
	if plan:
		render_plan_progress(plan, console=console)
		console.print()
	else:
		console.print("[dim]No active plan.[/dim]")
		console.print()
