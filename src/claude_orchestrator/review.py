"""Review artifact generation for checkpoint phases.

At checkpoint phases, generates a structured review artifact summarizing
what was accomplished, verification results, decisions made, and risks.
Stored in .claude-project/reviews/ for human review.
"""

import re
from datetime import datetime
from pathlib import Path

from .workflow import WORKFLOW_DIR

REVIEWS_DIR = "reviews"


def generate_review(
	project_path: str,
	phase_name: str,
	summary: str = "",
	changes: str = "",
	verification_passed: bool = True,
	verification_details: str = "",
	decisions: list[str] | None = None,
	risks: list[str] | None = None,
	next_steps: str = "",
	commit_hash: str = "",
) -> dict[str, object]:
	"""Generate a review artifact for a completed phase.

	Args:
		project_path: Path to the project directory.
		phase_name: Name of the completed phase (e.g., "Phase 1 - Core").
		summary: Brief description of what was accomplished.
		changes: Description of files modified/created.
		verification_passed: Whether verification suite passed.
		verification_details: Detailed verification output.
		decisions: List of key decisions made during this phase.
		risks: List of risks or concerns identified.
		next_steps: What's coming in the next phase.
		commit_hash: Git commit hash for this phase.

	Returns:
		dict with artifact path, content, and status.
	"""
	base = Path(project_path).expanduser().resolve()
	reviews_dir = base / WORKFLOW_DIR / REVIEWS_DIR
	reviews_dir.mkdir(parents=True, exist_ok=True)

	# Sanitize phase name for filename
	filename = _sanitize_filename(phase_name) + ".md"
	artifact_path = reviews_dir / filename

	# Build artifact content
	now = datetime.now().strftime("%Y-%m-%d %H:%M")
	decisions_list = decisions or []
	risks_list = risks or []

	decisions_block = (
		"\n".join(f"- {d}" for d in decisions_list)
		if decisions_list
		else "- None recorded"
	)

	risks_block = (
		"\n".join(f"- {r}" for r in risks_list)
		if risks_list
		else "- None identified"
	)

	verification_status = "PASSED" if verification_passed else "FAILED"

	content = f"""# Review: {phase_name}

**Date:** {now}
**Commit:** {commit_hash or "N/A"}
**Verification:** {verification_status}

## Summary

{summary or "No summary provided."}

## Changes

{changes or "No changes description provided."}

## Verification Results

{verification_details or f"Verification {verification_status.lower()}."}

## Decisions Made

{decisions_block}

## Risks & Concerns

{risks_block}

## Next Steps

{next_steps or "See plan.md for next phase."}
"""

	artifact_path.write_text(content, encoding="utf-8")

	# Build Telegram-friendly summary (concise, actionable)
	telegram_summary = _build_telegram_summary(
		phase_name, summary, verification_status, commit_hash,
		len(decisions_list), len(risks_list),
	)

	return {
		"success": True,
		"artifact_path": str(artifact_path),
		"phase": phase_name,
		"telegram_summary": telegram_summary,
	}


def list_reviews(project_path: str) -> list[dict[str, str]]:
	"""List all review artifacts for a project."""
	base = Path(project_path).expanduser().resolve()
	reviews_dir = base / WORKFLOW_DIR / REVIEWS_DIR

	if not reviews_dir.exists():
		return []

	return [
		{"name": f.stem, "path": str(f)}
		for f in sorted(reviews_dir.glob("*.md"))
	]


def _sanitize_filename(name: str) -> str:
	"""Convert phase name to a safe filename."""
	# Replace non-alphanumeric chars with hyphens, collapse multiples
	sanitized = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower())
	return sanitized.strip("-")


def _build_telegram_summary(
	phase_name: str,
	summary: str,
	verification_status: str,
	commit_hash: str,
	decision_count: int,
	risk_count: int,
) -> str:
	"""Build a concise Telegram-friendly summary."""
	lines = [
		f"Phase complete: {phase_name}",
		f"Verification: {verification_status}",
	]
	if commit_hash:
		lines.append(f"Commit: {commit_hash}")
	if summary:
		# Truncate to fit Telegram nicely
		short = summary[:200] + ("..." if len(summary) > 200 else "")
		lines.append(f"Summary: {short}")
	if decision_count > 0:
		lines.append(f"Decisions: {decision_count}")
	if risk_count > 0:
		lines.append(f"Risks: {risk_count} -- review recommended")
	return "\n".join(lines)
