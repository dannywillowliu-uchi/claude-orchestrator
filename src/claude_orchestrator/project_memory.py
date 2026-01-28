"""
Project Memory - Tools for updating project CLAUDE.md files and global learnings.

Handles:
- Updating implementation status sections
- Appending to decisions log
- Appending to gotchas/learnings
- Updating global learnings file
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional


def find_project_claude_md(project_path: str) -> Optional[Path]:
	"""Find CLAUDE.md file in project directory."""
	path = Path(project_path)
	claude_md = path / "CLAUDE.md"
	if claude_md.exists():
		return claude_md
	return None


def read_file(path: Path) -> str:
	"""Read file contents."""
	return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str):
	"""Write content to file."""
	path.write_text(content, encoding="utf-8")


def update_implementation_status(
	project_path: str,
	phase_completed: str = "",
	phase_started: str = "",
	commit_hash: str = "",
) -> dict:
	"""
	Update the Implementation Status section of a project CLAUDE.md.

	Args:
		project_path: Path to the project directory
		phase_completed: Phase that was just completed (e.g., "Phase 3: Vision Pipeline")
		phase_started: Phase that is now starting
		commit_hash: Git commit hash for the completed phase

	Returns:
		dict with success status and message
	"""
	claude_md = find_project_claude_md(project_path)
	if not claude_md:
		return {"success": False, "error": f"No CLAUDE.md found in {project_path}"}

	content = read_file(claude_md)

	# Find Implementation Status section
	status_pattern = r"(## Implementation Status.*?)((?=\n## )|$)"
	match = re.search(status_pattern, content, re.DOTALL)

	if not match:
		return {"success": False, "error": "No Implementation Status section found"}

	status_section = match.group(1)

	# Update completed phase: change [ ] to [x] and add commit hash
	if phase_completed:
		# Match the phase in "Remaining" or as unchecked
		phase_pattern = rf"- \[ \] {re.escape(phase_completed)}"
		commit_suffix = f" (commit: {commit_hash})" if commit_hash else ""
		replacement = f"- [x] {phase_completed}{commit_suffix}"
		status_section = re.sub(phase_pattern, replacement, status_section)

	# Update current phase
	if phase_started:
		# Update "Current Phase" subsection
		current_pattern = r"(### Current Phase\n).*?(\n### |\n## |$)"
		current_replacement = rf"\1- {phase_started} (in progress)\n- Current focus: Starting phase\n\2"
		status_section = re.sub(current_pattern, current_replacement, status_section, flags=re.DOTALL)

	# Replace in original content
	new_content = content[:match.start()] + status_section + content[match.end():]
	write_file(claude_md, new_content)

	return {"success": True, "message": "Implementation status updated"}


def log_decision(
	project_path: str,
	decision: str,
	rationale: str,
	alternatives: str = "",
) -> dict:
	"""
	Append a decision to the Decisions Log section.

	Args:
		project_path: Path to the project directory
		decision: What was decided
		rationale: Why this decision was made
		alternatives: What alternatives were rejected

	Returns:
		dict with success status
	"""
	claude_md = find_project_claude_md(project_path)
	if not claude_md:
		return {"success": False, "error": f"No CLAUDE.md found in {project_path}"}

	content = read_file(claude_md)

	# Find Decisions Log section
	log_pattern = r"(## Decisions Log.*?\n\|.*?\|.*?\|.*?\|.*?\|\n)"
	match = re.search(log_pattern, content, re.DOTALL)

	if not match:
		return {"success": False, "error": "No Decisions Log section found"}

	# Create new row
	today = datetime.now().strftime("%Y-%m-%d")
	new_row = f"| {today} | {decision} | {rationale} | {alternatives or 'N/A'} |\n"

	# Insert after header row
	insert_pos = match.end()
	new_content = content[:insert_pos] + new_row + content[insert_pos:]
	write_file(claude_md, new_content)

	return {"success": True, "message": f"Decision logged: {decision}"}


def log_gotcha(
	project_path: str,
	gotcha_type: str,
	description: str,
) -> dict:
	"""
	Append a gotcha/learning to the Gotchas & Learnings section.

	Args:
		project_path: Path to the project directory
		gotcha_type: Type of gotcha - "dont", "do", or "note"
		description: Description of the gotcha

	Returns:
		dict with success status
	"""
	claude_md = find_project_claude_md(project_path)
	if not claude_md:
		return {"success": False, "error": f"No CLAUDE.md found in {project_path}"}

	content = read_file(claude_md)

	# Find Gotchas section
	gotcha_pattern = r"(## Gotchas & Learnings\n)"
	match = re.search(gotcha_pattern, content)

	if not match:
		return {"success": False, "error": "No Gotchas & Learnings section found"}

	# Format based on type
	type_prefix = {
		"dont": "**Don't**",
		"do": "**Do**",
		"note": "**Note**",
	}.get(gotcha_type.lower(), "**Note**")

	new_line = f"- {type_prefix}: {description}\n"

	# Find the end of the section (next ## or end of file)
	section_end = content.find("\n## ", match.end())
	if section_end == -1:
		section_end = len(content)

	# Insert before the next section
	new_content = content[:section_end] + new_line + content[section_end:]
	write_file(claude_md, new_content)

	return {"success": True, "message": f"Gotcha logged: {description[:50]}..."}


def log_global_learning(
	category: str,
	content_to_add: str,
) -> dict:
	"""
	Append a learning to the global learnings file.

	Args:
		category: Category - "preference", "pattern", "gotcha", "decision"
		content_to_add: The learning content to add

	Returns:
		dict with success status
	"""
	global_file = Path.home() / ".claude" / "global-learnings.md"

	if not global_file.exists():
		return {"success": False, "error": "Global learnings file not found"}

	content = read_file(global_file)

	# Map category to section
	section_map = {
		"preference": "## Danny's Preferences",
		"pattern": "## Technical Patterns That Work",
		"gotcha": "## Common Gotchas Across Projects",
		"decision": "## Decision Patterns",
	}

	section_header = section_map.get(category.lower())
	if not section_header:
		return {"success": False, "error": f"Unknown category: {category}"}

	# Find section
	section_pattern = rf"({re.escape(section_header)}\n)"
	match = re.search(section_pattern, content)

	if not match:
		return {"success": False, "error": f"Section not found: {section_header}"}

	# Find end of section (next ## or ---)
	section_end = content.find("\n## ", match.end())
	if section_end == -1:
		section_end = content.find("\n---", match.end())
	if section_end == -1:
		section_end = len(content)

	# Format the new entry
	new_entry = f"- {content_to_add}\n"

	# Insert at end of section (before next section)
	new_content = content[:section_end] + new_entry + content[section_end:]
	write_file(global_file, new_content)

	# Update timestamp
	new_content = re.sub(
		r"\*Last updated:.*\*",
		f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*",
		new_content
	)
	write_file(global_file, new_content)

	return {"success": True, "message": f"Global learning added to {category}"}
