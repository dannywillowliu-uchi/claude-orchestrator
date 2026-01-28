"""
Plan Models - Pydantic schemas for structured plan storage.

Defines the structure of implementation plans with phases, tasks,
decisions, and research findings.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlanStatus(str, Enum):
	"""Status of a plan."""
	DRAFT = "draft"
	APPROVED = "approved"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	ARCHIVED = "archived"


class TaskStatus(str, Enum):
	"""Status of a task within a phase."""
	PENDING = "pending"
	IN_PROGRESS = "in_progress"
	COMPLETED = "completed"
	BLOCKED = "blocked"
	SKIPPED = "skipped"


class Task(BaseModel):
	"""A single task within a phase."""
	id: str = Field(description="Unique task identifier")
	description: str = Field(description="What needs to be done")
	status: TaskStatus = Field(default=TaskStatus.PENDING)
	files: list[str] = Field(default_factory=list, description="Files to be modified")
	verification: list[str] = Field(default_factory=list, description="How to verify completion")
	notes: str = Field(default="", description="Additional notes or context")
	completed_at: Optional[str] = Field(default=None)


class Phase(BaseModel):
	"""A phase of implementation."""
	id: str = Field(description="Phase identifier (e.g., 'phase-1')")
	name: str = Field(description="Phase name (e.g., 'Knowledge Base Foundation')")
	description: str = Field(description="What this phase accomplishes")
	tasks: list[Task] = Field(default_factory=list)
	dependencies: list[str] = Field(default_factory=list, description="Phase IDs this depends on")
	status: TaskStatus = Field(default=TaskStatus.PENDING)
	started_at: Optional[str] = Field(default=None)
	completed_at: Optional[str] = Field(default=None)


class Decision(BaseModel):
	"""An architectural or implementation decision."""
	id: str = Field(description="Decision identifier")
	decision: str = Field(description="What was decided")
	rationale: str = Field(description="Why this decision was made")
	alternatives: list[str] = Field(default_factory=list, description="Rejected alternatives")
	made_at: str = Field(default_factory=lambda: datetime.now().isoformat())
	phase_id: Optional[str] = Field(default=None, description="Related phase if any")


class Research(BaseModel):
	"""Research findings during planning."""
	findings: list[str] = Field(default_factory=list)
	references: list[str] = Field(default_factory=list)
	open_questions: list[str] = Field(default_factory=list)


class PlanOverview(BaseModel):
	"""High-level plan overview."""
	goal: str = Field(description="What the plan achieves")
	success_criteria: list[str] = Field(default_factory=list)
	constraints: list[str] = Field(default_factory=list)
	out_of_scope: list[str] = Field(default_factory=list)


class Plan(BaseModel):
	"""
	A complete implementation plan.

	Plans are versioned - each update creates a new version while
	preserving the history.
	"""
	id: str = Field(description="Unique plan identifier")
	project: str = Field(description="Project this plan belongs to")
	version: int = Field(default=1, description="Version number (increments on each update)")
	status: PlanStatus = Field(default=PlanStatus.DRAFT)

	# Timestamps
	created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
	updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
	approved_at: Optional[str] = Field(default=None)

	# Parent version for history tracking
	parent_version: Optional[int] = Field(default=None)

	# Plan content
	overview: PlanOverview = Field(default_factory=PlanOverview)
	phases: list[Phase] = Field(default_factory=list)
	decisions: list[Decision] = Field(default_factory=list)
	research: Research = Field(default_factory=Research)

	# Metadata
	tags: list[str] = Field(default_factory=list)
	notes: str = Field(default="")

	def get_current_phase(self) -> Optional[Phase]:
		"""Get the currently active phase."""
		for phase in self.phases:
			if phase.status == TaskStatus.IN_PROGRESS:
				return phase
		return None

	def get_next_phase(self) -> Optional[Phase]:
		"""Get the next pending phase."""
		for phase in self.phases:
			if phase.status == TaskStatus.PENDING:
				return phase
		return None

	def get_progress(self) -> dict:
		"""Calculate overall progress."""
		total_tasks = sum(len(p.tasks) for p in self.phases)
		completed_tasks = sum(
			len([t for t in p.tasks if t.status == TaskStatus.COMPLETED])
			for p in self.phases
		)
		completed_phases = len([p for p in self.phases if p.status == TaskStatus.COMPLETED])

		return {
			"total_phases": len(self.phases),
			"completed_phases": completed_phases,
			"total_tasks": total_tasks,
			"completed_tasks": completed_tasks,
			"percent_complete": round(completed_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0,
		}

	def to_markdown(self) -> str:
		"""Convert plan to markdown format."""
		lines = [
			f"# {self.overview.goal}",
			"",
			f"**Project:** {self.project}",
			f"**Status:** {self.status.value}",
			f"**Version:** {self.version}",
			f"**Created:** {self.created_at}",
			"",
		]

		# Overview
		if self.overview.success_criteria:
			lines.append("## Success Criteria")
			for c in self.overview.success_criteria:
				lines.append(f"- {c}")
			lines.append("")

		# Phases
		lines.append("## Phases")
		for phase in self.phases:
			status_icon = {
				TaskStatus.PENDING: "⬜",
				TaskStatus.IN_PROGRESS: "🔄",
				TaskStatus.COMPLETED: "✅",
				TaskStatus.BLOCKED: "🚫",
				TaskStatus.SKIPPED: "⏭️",
			}.get(phase.status, "⬜")

			lines.append(f"### {status_icon} {phase.name}")
			lines.append(f"_{phase.description}_")
			lines.append("")

			for task in phase.tasks:
				task_icon = {
					TaskStatus.PENDING: "[ ]",
					TaskStatus.IN_PROGRESS: "[~]",
					TaskStatus.COMPLETED: "[x]",
					TaskStatus.BLOCKED: "[!]",
					TaskStatus.SKIPPED: "[-]",
				}.get(task.status, "[ ]")

				lines.append(f"- {task_icon} {task.description}")
			lines.append("")

		# Decisions
		if self.decisions:
			lines.append("## Decisions")
			for d in self.decisions:
				lines.append(f"### {d.decision}")
				lines.append(f"**Rationale:** {d.rationale}")
				if d.alternatives:
					lines.append(f"**Alternatives rejected:** {', '.join(d.alternatives)}")
				lines.append("")

		return "\n".join(lines)
