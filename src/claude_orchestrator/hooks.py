"""
Task-specific permission hooks for Claude CLI sessions.

Replaces blanket --dangerously-skip-permissions with targeted --allowedTools
profiles based on task type. Each profile specifies which tool patterns
a subagent is allowed to use.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HooksConfig:
	"""Permission profile for a Claude CLI session."""

	name: str
	description: str
	allow_patterns: list[str] = field(default_factory=list)
	deny_patterns: list[str] = field(default_factory=list)
	task_type: str = "general"

	def to_allowed_tools_list(self) -> list[str]:
		"""Convert to a list of tool patterns for --allowedTools."""
		return list(self.allow_patterns)

	@property
	def is_full_access(self) -> bool:
		"""Check if this is a full-access profile (no restrictions)."""
		return self.name == "full_access"


# Predefined profiles

READ_ONLY = HooksConfig(
	name="read_only",
	description="Read-only access: file reading, search, listing",
	allow_patterns=[
		"Read",
		"Glob",
		"Grep",
		"WebSearch",
		"WebFetch",
	],
	task_type="research",
)

CODE_EDIT = HooksConfig(
	name="code_edit",
	description="Code editing: read, write, edit files",
	allow_patterns=[
		"Read",
		"Glob",
		"Grep",
		"Edit",
		"Write",
		"WebSearch",
		"WebFetch",
	],
	task_type="implementation",
)

TEST_RUN = HooksConfig(
	name="test_run",
	description="Test execution: read files, run test commands",
	allow_patterns=[
		"Read",
		"Glob",
		"Grep",
		"Bash",
	],
	task_type="testing",
)

FULL_ACCESS = HooksConfig(
	name="full_access",
	description="Full access: all tools allowed (uses --dangerously-skip-permissions)",
	allow_patterns=[],
	task_type="trusted",
)

PROFILES: dict[str, HooksConfig] = {
	"read_only": READ_ONLY,
	"code_edit": CODE_EDIT,
	"test_run": TEST_RUN,
	"full_access": FULL_ACCESS,
}

# Keywords that map task descriptions to profiles
_TASK_KEYWORDS: dict[str, str] = {
	"read": "read_only",
	"search": "read_only",
	"find": "read_only",
	"explore": "read_only",
	"research": "read_only",
	"analyze": "read_only",
	"review": "read_only",
	"test": "test_run",
	"verify": "test_run",
	"lint": "test_run",
	"check": "test_run",
	"implement": "code_edit",
	"create": "code_edit",
	"add": "code_edit",
	"fix": "code_edit",
	"refactor": "code_edit",
	"update": "code_edit",
	"write": "code_edit",
	"edit": "code_edit",
	"delete": "full_access",
	"deploy": "full_access",
	"install": "full_access",
	"migrate": "full_access",
}


def get_profile(name: str) -> Optional[HooksConfig]:
	"""Get a predefined hooks profile by name."""
	return PROFILES.get(name)


def generate_hooks_for_task(description: str) -> HooksConfig:
	"""
	Select the appropriate hooks profile based on task description.

	Scans the task description for keywords and returns the most
	appropriate permission profile. Defaults to code_edit for
	unrecognized tasks.
	"""
	description_lower = description.lower()

	for keyword, profile_name in _TASK_KEYWORDS.items():
		if keyword in description_lower:
			profile = PROFILES[profile_name]
			logger.info(f"Matched keyword '{keyword}' -> profile '{profile_name}' for task: {description[:80]}")
			return profile

	logger.info(f"No keyword match, defaulting to 'code_edit' for task: {description[:80]}")
	return CODE_EDIT
