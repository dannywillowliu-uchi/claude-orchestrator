"""Plan parser for recursive sub-plan trees.

Parses plan.md to extract a tree of phases and sub-phases.
Sub-phases are represented as ### (h3) under ## (h2) phases,
or #### (h4) under ### (h3) phases.

Phase path convention: "Phase 2 > Sub-phase 2.1 > Task 2.1.1"
Uses > as the nesting separator in progress tracking.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .workflow import WORKFLOW_DIR

PHASE_PATH_SEPARATOR = " > "


@dataclass
class PlanPhase:
	"""A phase in the plan tree."""

	name: str
	depth: int  # 0 = top-level, 1 = sub-phase, 2 = sub-sub-phase
	checkpoint: bool = False
	tasks: list[str] = field(default_factory=list)
	children: list["PlanPhase"] = field(default_factory=list)

	@property
	def full_path(self) -> str:
		"""Full path is just the name for top-level phases."""
		return self.name

	def flatten(self, parent_path: str = "") -> list[tuple[str, "PlanPhase"]]:
		"""Flatten tree into (path, phase) pairs in depth-first order."""
		path = (
			f"{parent_path}{PHASE_PATH_SEPARATOR}{self.name}"
			if parent_path
			else self.name
		)
		result = [(path, self)]
		for child in self.children:
			result.extend(child.flatten(path))
		return result


@dataclass
class PlanTree:
	"""Parsed plan with phase hierarchy."""

	phases: list[PlanPhase] = field(default_factory=list)

	def flatten(self) -> list[tuple[str, PlanPhase]]:
		"""Flatten all phases depth-first into (path, phase) pairs."""
		result = []
		for phase in self.phases:
			result.extend(phase.flatten())
		return result

	def next_phase(self, current_path: str) -> str | None:
		"""Find the next phase path after current_path in depth-first order."""
		flat = self.flatten()
		paths = [p for p, _ in flat]
		if current_path not in paths:
			return paths[0] if paths else None
		idx = paths.index(current_path)
		if idx + 1 < len(paths):
			return paths[idx + 1]
		return None

	def get_phase(self, path: str) -> PlanPhase | None:
		"""Get a phase by its full path."""
		for p, phase in self.flatten():
			if p == path:
				return phase
		return None


def parse_plan(project_path: str) -> PlanTree:
	"""Parse plan.md into a PlanTree.

	Recognizes phases at heading levels:
	- ## Phase N - Name (depth 0)
	- ### Sub-phase N.M - Name (depth 1)
	- #### Sub-sub-phase N.M.K (depth 2)

	Checkpoint and task lines are parsed within each phase.
	"""
	base = Path(project_path).expanduser().resolve()
	plan_file = base / WORKFLOW_DIR / "plan.md"

	if not plan_file.exists():
		return PlanTree()

	content = plan_file.read_text(encoding="utf-8")
	return _parse_plan_content(content)


def _parse_plan_content(content: str) -> PlanTree:
	"""Parse plan markdown content into a PlanTree."""
	tree = PlanTree()
	stack: list[PlanPhase] = []  # Current nesting stack

	for line in content.splitlines():
		stripped = line.strip()

		# Detect phase headings (## through ####)
		heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
		if heading_match:
			level = len(heading_match.group(1))
			name = heading_match.group(2).strip()

			# Skip non-phase headings (Overview, Success Criteria, etc.)
			if not _looks_like_phase(name):
				continue

			depth = level - 2  # ## = 0, ### = 1, #### = 2
			phase = PlanPhase(name=name, depth=depth)

			# Place in tree based on depth
			if depth == 0:
				tree.phases.append(phase)
				stack = [phase]
			elif stack:
				# Find parent at correct depth
				while len(stack) > depth:
					stack.pop()
				if stack:
					stack[-1].children.append(phase)
					stack.append(phase)
			continue

		# Detect checkpoint line within a phase
		if stripped.lower().startswith("checkpoint:") and stack:
			value = stripped.split(":", 1)[1].strip().lower()
			stack[-1].checkpoint = value == "true"
			continue

		# Detect task lines within a phase
		task_match = re.match(r"^- \[[ x]\] (.+)$", stripped)
		if task_match and stack:
			stack[-1].tasks.append(task_match.group(1))

	return tree


def _looks_like_phase(name: str) -> bool:
	"""Heuristic: does this heading look like a phase name?"""
	lower = name.lower()
	# Match "Phase N", "Sub-phase N.M", or anything with a dash separator
	if re.match(r"phase\s+\d", lower):
		return True
	if re.match(r"sub-?phase\s+\d", lower):
		return True
	# Also match "Step N" or numbered headings like "1. Something"
	if re.match(r"step\s+\d", lower):
		return True
	# Match headings that contain " - " (phase name separator)
	if " - " in name and any(c.isdigit() for c in name):
		return True
	return False


def parse_phase_path(phase_string: str) -> list[str]:
	"""Split a phase path into its components.

	Example: "Phase 2 > Sub-phase 2.1" -> ["Phase 2", "Sub-phase 2.1"]
	"""
	return [p.strip() for p in phase_string.split(PHASE_PATH_SEPARATOR)]


def get_phase_depth(phase_string: str) -> int:
	"""Get the nesting depth of a phase path (0 = top-level)."""
	return len(parse_phase_path(phase_string)) - 1


def get_parent_phase(phase_string: str) -> str:
	"""Get the parent phase path, or empty string if top-level."""
	parts = parse_phase_path(phase_string)
	if len(parts) <= 1:
		return ""
	return PHASE_PATH_SEPARATOR.join(parts[:-1])
