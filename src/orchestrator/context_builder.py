"""
Context Builder - Builds and budgets context for subagents.

Responsible for:
- Assembling relevant context for a task
- Token budgeting to prevent overflow
- Prioritizing important context
- Summarizing history when needed
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..plans.models import Plan, Phase, Task, Decision

logger = logging.getLogger(__name__)


@dataclass
class SubagentContext:
	"""Context package for a subagent."""
	task: dict
	plan_reference: str
	relevant_decisions: list[dict]
	relevant_docs: list[dict]
	prior_work_summary: str
	constraints: list[str]
	verification_required: list[str]
	estimated_tokens: int

	def to_prompt(self) -> str:
		"""Convert context to a prompt string for the subagent."""
		lines = [
			"# Task Assignment",
			"",
			f"## Task: {self.task.get('description', 'No description')}",
			"",
		]

		if self.task.get("files"):
			lines.append("### Files to modify:")
			for f in self.task["files"]:
				lines.append(f"- {f}")
			lines.append("")

		if self.constraints:
			lines.append("### Constraints:")
			for c in self.constraints:
				lines.append(f"- {c}")
			lines.append("")

		if self.relevant_decisions:
			lines.append("### Relevant Decisions:")
			for d in self.relevant_decisions:
				lines.append(f"- **{d.get('decision')}**: {d.get('rationale')}")
			lines.append("")

		if self.prior_work_summary:
			lines.append("### Prior Work Summary:")
			lines.append(self.prior_work_summary)
			lines.append("")

		if self.verification_required:
			lines.append("### Verification Required:")
			for v in self.verification_required:
				lines.append(f"- {v}")
			lines.append("")

		lines.append(f"Plan Reference: {self.plan_reference}")

		return "\n".join(lines)


class ContextBuilder:
	"""
	Builds context packages for subagents.

	Handles:
	- Context assembly from plan, decisions, docs
	- Token budgeting (default 150K max)
	- Priority-based context selection
	- History summarization
	"""

	MAX_TOKENS = 150_000  # Leave room for response
	CHARS_PER_TOKEN = 4  # Rough estimate

	def __init__(self, max_tokens: int = MAX_TOKENS):
		"""Initialize the context builder."""
		self.max_tokens = max_tokens

	def build_context(
		self,
		task: Task,
		plan: Plan,
		history: list[dict] = None,
		docs: list[dict] = None,
	) -> SubagentContext:
		"""
		Build a context package for a subagent.

		Args:
			task: The task to perform
			plan: The parent plan
			history: Optional prior work history
			docs: Optional relevant documentation

		Returns:
			SubagentContext ready for subagent
		"""
		history = history or []
		docs = docs or []

		# Start with task info
		task_dict = {
			"id": task.id,
			"description": task.description,
			"files": task.files,
			"verification": task.verification,
			"notes": task.notes,
		}

		# Filter relevant decisions
		relevant_decisions = self._filter_relevant_decisions(task, plan.decisions)

		# Get constraints from plan overview
		constraints = plan.overview.constraints.copy()

		# Add task-specific verification
		verification = task.verification.copy() if task.verification else []
		# Add default verification if not specified
		if not verification:
			verification = ["pytest", "ruff", "mypy"]

		# Summarize history if provided
		prior_summary = self._summarize_history(history) if history else ""

		# Filter docs by relevance and budget
		relevant_docs = self._filter_relevant_docs(task, docs)

		# Calculate token usage
		estimated_tokens = self._estimate_tokens(
			task_dict, relevant_decisions, relevant_docs, prior_summary
		)

		# Apply budget if over limit
		if estimated_tokens > self.max_tokens:
			relevant_docs, prior_summary = self._apply_budget(
				task_dict, relevant_decisions, relevant_docs, prior_summary
			)
			estimated_tokens = self._estimate_tokens(
				task_dict, relevant_decisions, relevant_docs, prior_summary
			)

		return SubagentContext(
			task=task_dict,
			plan_reference=f"{plan.project}:{plan.id}:v{plan.version}",
			relevant_decisions=[d.model_dump() for d in relevant_decisions],
			relevant_docs=relevant_docs,
			prior_work_summary=prior_summary,
			constraints=constraints,
			verification_required=verification,
			estimated_tokens=estimated_tokens,
		)

	def _filter_relevant_decisions(
		self,
		task: Task,
		decisions: list[Decision],
	) -> list[Decision]:
		"""Filter decisions relevant to the task."""
		relevant = []

		task_keywords = set(task.description.lower().split())

		for decision in decisions:
			# Check if decision mentions any task files
			if task.files:
				for f in task.files:
					if f.lower() in decision.decision.lower():
						relevant.append(decision)
						break
				else:
					# Check keyword overlap
					decision_keywords = set(decision.decision.lower().split())
					if task_keywords & decision_keywords:
						relevant.append(decision)
			else:
				# No files specified, use keyword matching
				decision_keywords = set(decision.decision.lower().split())
				if task_keywords & decision_keywords:
					relevant.append(decision)

		return relevant

	def _filter_relevant_docs(
		self,
		task: Task,
		docs: list[dict],
	) -> list[dict]:
		"""Filter documentation by relevance to task."""
		if not docs:
			return []

		# Simple relevance: check title/content overlap with task
		task_keywords = set(task.description.lower().split())

		scored_docs = []
		for doc in docs:
			title = doc.get("title", "").lower()
			content = doc.get("content", "")[:500].lower()

			title_keywords = set(title.split())
			content_keywords = set(content.split())

			score = len(task_keywords & title_keywords) * 3  # Title match worth more
			score += len(task_keywords & content_keywords)

			if score > 0:
				scored_docs.append((score, doc))

		# Sort by score and return top 5
		scored_docs.sort(key=lambda x: x[0], reverse=True)
		return [doc for _, doc in scored_docs[:5]]

	def _summarize_history(self, history: list[dict]) -> str:
		"""Summarize prior work history."""
		if not history:
			return ""

		summaries = []
		for item in history[-10:]:  # Last 10 items
			if item.get("type") == "task_completed":
				summaries.append(f"- Completed: {item.get('task', 'Unknown task')}")
			elif item.get("type") == "file_modified":
				summaries.append(f"- Modified: {item.get('file', 'Unknown file')}")
			elif item.get("type") == "test_result":
				status = "passed" if item.get("passed") else "failed"
				summaries.append(f"- Tests {status}: {item.get('summary', '')}")

		if summaries:
			return "Prior work:\n" + "\n".join(summaries)
		return ""

	def _estimate_tokens(
		self,
		task: dict,
		decisions: list,
		docs: list,
		summary: str,
	) -> int:
		"""Estimate token count for context."""
		total_chars = 0

		# Task
		total_chars += len(str(task))

		# Decisions
		for d in decisions:
			total_chars += len(str(d))

		# Docs
		for doc in docs:
			total_chars += len(doc.get("content", ""))

		# Summary
		total_chars += len(summary)

		return total_chars // self.CHARS_PER_TOKEN

	def _apply_budget(
		self,
		task: dict,
		decisions: list,
		docs: list,
		summary: str,
	) -> tuple[list, str]:
		"""Apply token budget by reducing docs and summary."""
		# First, truncate docs
		truncated_docs = []
		for doc in docs[:3]:  # Max 3 docs
			truncated = doc.copy()
			if len(truncated.get("content", "")) > 2000:
				truncated["content"] = truncated["content"][:2000] + "..."
			truncated_docs.append(truncated)

		# Truncate summary if still over
		if len(summary) > 1000:
			summary = summary[:1000] + "\n[Summary truncated]"

		return truncated_docs, summary

	def build_verification_context(
		self,
		task: Task,
		result: dict,
	) -> dict:
		"""
		Build context for the verifier.

		Args:
			task: The completed task
			result: Result from subagent

		Returns:
			Context dict for verification
		"""
		return {
			"task": {
				"id": task.id,
				"description": task.description,
				"verification": task.verification,
			},
			"result": result,
			"checks_required": [
				"pytest",
				"ruff",
				"mypy",
				"bandit",
			],
		}
