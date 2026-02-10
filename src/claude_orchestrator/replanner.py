"""Adaptive replanning: plans become mutable during execution.

Allows the agent to modify plan.md when execution diverges from
expectations. Every replan is logged to progress.md for auditability.
Max 3 replans per session to prevent infinite plan churn.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .workflow import WORKFLOW_DIR

REPLAN_TRIGGERS = {
	"scope_change",
	"blocked_dependency",
	"verification_feedback",
	"phase_split",
	"phase_skip",
}

MAX_REPLANS = 3


@dataclass
class ReplanEvent:
	"""A single replan operation."""

	trigger: str
	reason: str
	phases_added: list[str] = field(default_factory=list)
	phases_removed: list[str] = field(default_factory=list)
	phases_modified: list[str] = field(default_factory=list)
	timestamp: str = ""


@dataclass
class ReplanResult:
	"""Result of a replan attempt."""

	success: bool
	event: ReplanEvent | None = None
	replan_count: int = 0
	error: str = ""


def evaluate_replan_trigger(project_path: str, trigger: str, reason: str) -> dict[str, object]:
	"""Return context for the agent to write new plan content.

	Returns current plan content, completed phases, remaining phases.
	"""
	base = Path(project_path).expanduser().resolve()
	workflow_dir = base / WORKFLOW_DIR

	plan_path = workflow_dir / "plan.md"
	progress_path = workflow_dir / "progress.md"

	if not plan_path.exists():
		return {"error": "No plan.md found"}

	if trigger not in REPLAN_TRIGGERS:
		return {"error": f"Invalid trigger: {trigger}. Valid: {sorted(REPLAN_TRIGGERS)}"}

	plan_content = plan_path.read_text(encoding="utf-8")
	progress_content = progress_path.read_text(encoding="utf-8") if progress_path.exists() else ""

	# Extract current replan count
	replan_count = _parse_replan_count(progress_content)

	if replan_count >= MAX_REPLANS:
		return {
			"error": f"Replan limit reached ({MAX_REPLANS}). Cannot replan further.",
			"replan_count": replan_count,
		}

	return {
		"trigger": trigger,
		"reason": reason,
		"current_plan": plan_content,
		"progress": progress_content,
		"replan_count": replan_count,
		"replans_remaining": MAX_REPLANS - replan_count,
	}


def apply_replan(
	project_path: str,
	trigger: str,
	reason: str,
	new_plan_content: str,
	phases_added: list[str] | None = None,
	phases_removed: list[str] | None = None,
	phases_modified: list[str] | None = None,
) -> ReplanResult:
	"""Replace plan.md and log replan event to progress.md.

	Args:
		project_path: Path to the project directory.
		trigger: One of REPLAN_TRIGGERS.
		reason: Human-readable reason for the replan.
		new_plan_content: Full replacement content for plan.md.
		phases_added: Names of phases added in this replan.
		phases_removed: Names of phases removed in this replan.
		phases_modified: Names of phases modified in this replan.

	Returns:
		ReplanResult with success status and updated replan count.
	"""
	base = Path(project_path).expanduser().resolve()
	workflow_dir = base / WORKFLOW_DIR

	plan_path = workflow_dir / "plan.md"
	progress_path = workflow_dir / "progress.md"

	if not plan_path.exists():
		return ReplanResult(success=False, error="No plan.md found")

	if trigger not in REPLAN_TRIGGERS:
		return ReplanResult(
			success=False,
			error=f"Invalid trigger: {trigger}. Valid: {sorted(REPLAN_TRIGGERS)}",
		)

	# Check replan limit
	progress_content = progress_path.read_text(encoding="utf-8") if progress_path.exists() else ""
	current_count = _parse_replan_count(progress_content)

	if current_count >= MAX_REPLANS:
		return ReplanResult(
			success=False,
			replan_count=current_count,
			error=f"Replan limit reached ({MAX_REPLANS}). Cannot replan further.",
		)

	# Write new plan
	plan_path.write_text(new_plan_content, encoding="utf-8")

	# Build replan event
	now = datetime.now().strftime("%Y-%m-%d %H:%M")
	event = ReplanEvent(
		trigger=trigger,
		reason=reason,
		phases_added=phases_added or [],
		phases_removed=phases_removed or [],
		phases_modified=phases_modified or [],
		timestamp=now,
	)

	# Log to progress.md Phase History
	new_count = current_count + 1
	_log_replan_event(progress_path, event, new_count)

	return ReplanResult(
		success=True,
		event=event,
		replan_count=new_count,
	)


def _parse_replan_count(content: str) -> int:
	"""Extract replan count from progress.md."""
	for line in content.splitlines():
		stripped = line.strip()
		if stripped.startswith("Replan Count:"):
			try:
				return int(stripped[len("Replan Count:"):].strip())
			except ValueError:
				return 0
	return 0


def _log_replan_event(progress_path: Path, event: ReplanEvent, new_count: int) -> None:
	"""Append replan event to progress.md and update replan count."""
	if not progress_path.exists():
		return

	content = progress_path.read_text(encoding="utf-8")

	# Update or insert Replan Count field
	if "Replan Count:" in content:
		lines = content.splitlines()
		for i, line in enumerate(lines):
			if line.strip().startswith("Replan Count:"):
				lines[i] = f"Replan Count: {new_count}"
				break
		content = "\n".join(lines)
	else:
		# Insert after Last Commit line
		lines = content.splitlines()
		for i, line in enumerate(lines):
			if line.strip().startswith("Last Commit:"):
				lines.insert(i + 1, f"Replan Count: {new_count}")
				break
		content = "\n".join(lines)

	# Build history entry
	changes = []
	if event.phases_added:
		changes.append(f"Added: {', '.join(event.phases_added)}")
	if event.phases_removed:
		changes.append(f"Removed: {', '.join(event.phases_removed)}")
	if event.phases_modified:
		changes.append(f"Modified: {', '.join(event.phases_modified)}")

	history_entry = (
		f"\n<details>\n<summary>Replan #{new_count} ({event.trigger}) - {event.timestamp}</summary>\n\n"
		f"Reason: {event.reason}\n"
	)
	if changes:
		history_entry += "\n".join(changes) + "\n"
	history_entry += "\n</details>\n"

	# Insert into Phase History
	history_marker = "## Phase History"
	idx = content.find(history_marker)
	if idx != -1:
		insert_at = content.find("\n", idx) + 1
		content = content[:insert_at] + history_entry + content[insert_at:]

	progress_path.write_text(content, encoding="utf-8")
