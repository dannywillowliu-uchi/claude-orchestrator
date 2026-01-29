"""Rich views for plan progress visualization."""

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

from ..plans.models import Plan, TaskStatus

STATUS_ICONS = {
	TaskStatus.PENDING: "[dim][ ][/dim]",
	TaskStatus.IN_PROGRESS: "[yellow][~][/yellow]",
	TaskStatus.COMPLETED: "[green][x][/green]",
	TaskStatus.BLOCKED: "[red][!][/red]",
	TaskStatus.SKIPPED: "[dim][-][/dim]",
}


def render_plan_progress(plan: Plan, console: Optional[Console] = None) -> None:
	"""Render a plan as a Rich Tree with phases and tasks."""
	console = console or Console()

	progress = plan.get_progress()
	pct = progress["percent_complete"]

	tree = Tree(
		f"[bold]{plan.overview.goal}[/bold]  "
		f"[dim]({progress['completed_tasks']}/{progress['total_tasks']} tasks, {pct:.0f}%)[/dim]"
	)

	for phase in plan.phases:
		icon = STATUS_ICONS.get(phase.status, "[ ]")
		phase_branch = tree.add(f"{icon} [bold]{phase.name}[/bold] [dim]- {phase.description}[/dim]")

		for task in phase.tasks:
			task_icon = STATUS_ICONS.get(task.status, "[ ]")
			phase_branch.add(f"{task_icon} {task.description}")

	console.print(tree)


def render_plan_summary(plan: Plan, console: Optional[Console] = None) -> None:
	"""Render a summary panel for a plan."""
	console = console or Console()

	progress = plan.get_progress()
	pct = progress["percent_complete"]

	lines = []
	lines.append(f"[bold]Goal:[/bold] {plan.overview.goal}")
	lines.append(f"[bold]Project:[/bold] {plan.project}")
	lines.append(f"[bold]Status:[/bold] {plan.status.value}")
	lines.append(f"[bold]Version:[/bold] {plan.version}")
	lines.append("")
	lines.append(f"[bold]Progress:[/bold] {progress['completed_tasks']}/{progress['total_tasks']} tasks ({pct:.0f}%)")
	lines.append(
		f"[bold]Phases:[/bold] {progress['completed_phases']}/{progress['total_phases']} complete"
	)

	if plan.overview.success_criteria:
		lines.append("")
		lines.append("[bold]Success Criteria:[/bold]")
		for c in plan.overview.success_criteria:
			lines.append(f"  - {c}")

	if plan.overview.constraints:
		lines.append("")
		lines.append("[bold]Constraints:[/bold]")
		for c in plan.overview.constraints:
			lines.append(f"  - {c}")

	if plan.decisions:
		lines.append("")
		lines.append(f"[bold]Decisions:[/bold] {len(plan.decisions)}")
		for d in plan.decisions[-3:]:
			lines.append(f"  - {d.decision}")

	console.print(Panel("\n".join(lines), title=f"Plan: {plan.id}", border_style="cyan"))
