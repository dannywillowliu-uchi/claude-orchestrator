"""Tests for bundled agent definitions."""

import re
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent / "src" / "claude_orchestrator" / "agents"

# Agents that must have valid frontmatter (new workflow agents)
WORKFLOW_AGENTS = ["researcher.md", "verifier.md"]


def test_researcher_agent_exists():
	"""researcher.md should be present."""
	assert (AGENTS_DIR / "researcher.md").exists()


def test_verifier_agent_exists():
	"""verifier.md should be present."""
	assert (AGENTS_DIR / "verifier.md").exists()


def test_researcher_has_valid_frontmatter():
	"""researcher.md should have valid YAML frontmatter with required fields."""
	content = (AGENTS_DIR / "researcher.md").read_text(encoding="utf-8")
	_assert_valid_frontmatter(content, "researcher.md")


def test_verifier_has_valid_frontmatter():
	"""verifier.md should have valid YAML frontmatter with required fields."""
	content = (AGENTS_DIR / "verifier.md").read_text(encoding="utf-8")
	_assert_valid_frontmatter(content, "verifier.md")


def _assert_valid_frontmatter(content: str, filename: str) -> None:
	"""Assert that content has valid frontmatter with required fields."""
	assert content.startswith("---"), f"{filename} should start with ---"
	end_idx = content.index("---", 3)
	assert end_idx > 3, f"{filename} should have closing ---"

	frontmatter = content[3:end_idx]
	assert re.search(r"^name:\s+\S+", frontmatter, re.MULTILINE), \
		f"{filename} missing 'name' field"
	assert re.search(r"^model:\s+\S+", frontmatter, re.MULTILINE), \
		f"{filename} missing 'model' field"
	assert re.search(r"^description:\s+\S+", frontmatter, re.MULTILINE), \
		f"{filename} missing 'description' field"
