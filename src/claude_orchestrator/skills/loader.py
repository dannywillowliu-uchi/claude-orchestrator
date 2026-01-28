"""
Skill Loader - Discovers and parses skills from SKILL.md files.

Skills are discovered from:
- Global: ~/.claude/skills/
- Project: .claude/skills/
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
	"""A parsed skill definition."""
	name: str
	description: str
	instructions: str
	allowed_tools: list[str] = field(default_factory=list)
	auto_invoke: bool = False
	source_path: str = ""

	# Optional metadata
	tags: list[str] = field(default_factory=list)
	version: str = "1.0.0"
	author: str = ""


class SkillLoader:
	"""
	Discovers and loads skills from SKILL.md files.

	Skills can be defined in:
	- ~/.claude/skills/<skill-name>/SKILL.md (global)
	- .claude/skills/<skill-name>/SKILL.md (project)

	Project skills take precedence over global skills with the same name.
	"""

	SKILL_FILENAME = "SKILL.md"

	def __init__(self, project_path: str | None = None):
		"""
		Initialize the skill loader.

		Args:
			project_path: Path to the project root (for project-specific skills)
		"""
		self.project_path = Path(project_path) if project_path else Path.cwd()
		self._skills_cache: dict[str, Skill] = {}
		self._loaded = False

	@property
	def global_skills_path(self) -> Path:
		"""Path to global skills directory."""
		return Path.home() / ".claude" / "skills"

	@property
	def project_skills_path(self) -> Path:
		"""Path to project-specific skills directory."""
		return self.project_path / ".claude" / "skills"

	def discover_skills(self, reload: bool = False) -> dict[str, Skill]:
		"""
		Discover all available skills.

		Args:
			reload: Force reload even if already cached

		Returns:
			Dict mapping skill name to Skill object
		"""
		if self._loaded and not reload:
			return self._skills_cache

		self._skills_cache = {}

		# Load global skills first
		if self.global_skills_path.exists():
			for skill_dir in self.global_skills_path.iterdir():
				if skill_dir.is_dir():
					skill = self._load_skill(skill_dir)
					if skill:
						self._skills_cache[skill.name] = skill
						logger.debug(f"Loaded global skill: {skill.name}")

		# Load project skills (overrides global)
		if self.project_skills_path.exists():
			for skill_dir in self.project_skills_path.iterdir():
				if skill_dir.is_dir():
					skill = self._load_skill(skill_dir)
					if skill:
						if skill.name in self._skills_cache:
							logger.info(f"Project skill '{skill.name}' overrides global")
						self._skills_cache[skill.name] = skill
						logger.debug(f"Loaded project skill: {skill.name}")

		self._loaded = True
		logger.info(f"Discovered {len(self._skills_cache)} skills")

		return self._skills_cache

	def get_skill(self, name: str) -> Skill | None:
		"""
		Get a skill by name.

		Args:
			name: Skill name

		Returns:
			Skill object or None if not found
		"""
		if not self._loaded:
			self.discover_skills()

		return self._skills_cache.get(name)

	def list_skills(self) -> list[dict]:
		"""
		List all available skills with basic info.

		Returns:
			List of skill summaries
		"""
		if not self._loaded:
			self.discover_skills()

		return [
			{
				"name": skill.name,
				"description": skill.description,
				"auto_invoke": skill.auto_invoke,
				"allowed_tools": skill.allowed_tools,
				"source": "project" if ".claude/skills" in skill.source_path else "global",
			}
			for skill in self._skills_cache.values()
		]

	def _load_skill(self, skill_dir: Path) -> Skill | None:
		"""
		Load a skill from a directory.

		Args:
			skill_dir: Path to skill directory

		Returns:
			Skill object or None if invalid
		"""
		skill_file = skill_dir / self.SKILL_FILENAME

		if not skill_file.exists():
			logger.warning(f"No {self.SKILL_FILENAME} in {skill_dir}")
			return None

		try:
			content = skill_file.read_text(encoding="utf-8")
			return self._parse_skill_file(content, str(skill_file))
		except Exception as e:
			logger.error(f"Failed to load skill from {skill_dir}: {e}")
			return None

	def _parse_skill_file(self, content: str, source_path: str) -> Skill | None:
		"""
		Parse a SKILL.md file.

		Expected format:
		```
		---
		name: skill-name
		description: Brief description
		allowed-tools: Read, Grep, Glob, Bash
		auto-invoke: false
		---

		# Skill Title
		[Instructions markdown...]
		```

		Args:
			content: File content
			source_path: Path to the source file

		Returns:
			Skill object or None if parsing fails
		"""
		# Extract YAML frontmatter
		frontmatter_match = re.match(
			r"^---\s*\n(.*?)\n---\s*\n(.*)$",
			content,
			re.DOTALL
		)

		if not frontmatter_match:
			logger.warning(f"No frontmatter found in {source_path}")
			return None

		frontmatter_text = frontmatter_match.group(1)
		instructions = frontmatter_match.group(2).strip()

		try:
			frontmatter = yaml.safe_load(frontmatter_text)
		except yaml.YAMLError as e:
			logger.error(f"Invalid YAML frontmatter in {source_path}: {e}")
			return None

		if not frontmatter:
			logger.warning(f"Empty frontmatter in {source_path}")
			return None

		# Required fields
		name = frontmatter.get("name")
		if not name:
			logger.warning(f"Missing 'name' in {source_path}")
			return None

		description = frontmatter.get("description", "")

		# Optional fields
		allowed_tools_raw = frontmatter.get("allowed-tools", "")
		if isinstance(allowed_tools_raw, str):
			allowed_tools = [t.strip() for t in allowed_tools_raw.split(",") if t.strip()]
		elif isinstance(allowed_tools_raw, list):
			allowed_tools = allowed_tools_raw
		else:
			allowed_tools = []

		auto_invoke = frontmatter.get("auto-invoke", False)
		tags_raw = frontmatter.get("tags", [])
		if isinstance(tags_raw, str):
			tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
		else:
			tags = tags_raw or []

		return Skill(
			name=name,
			description=description,
			instructions=instructions,
			allowed_tools=allowed_tools,
			auto_invoke=auto_invoke,
			source_path=source_path,
			tags=tags,
			version=frontmatter.get("version", "1.0.0"),
			author=frontmatter.get("author", ""),
		)

	def create_skill_template(self, name: str, global_skill: bool = False) -> Path:
		"""
		Create a skill template directory.

		Args:
			name: Skill name
			global_skill: Create in global vs project directory

		Returns:
			Path to created SKILL.md file
		"""
		base_path = self.global_skills_path if global_skill else self.project_skills_path
		skill_dir = base_path / name
		skill_dir.mkdir(parents=True, exist_ok=True)

		skill_file = skill_dir / self.SKILL_FILENAME

		template = f"""---
name: {name}
description: Brief description of what this skill does
allowed-tools: Read, Grep, Glob
auto-invoke: false
tags: []
version: 1.0.0
---

# {name.replace("-", " ").title()} Skill

## Overview
[Describe what this skill accomplishes]

## Instructions
[Step-by-step instructions for Claude to follow]

## Constraints
- [Any constraints or limitations]

## Examples
[Example usage or outputs]
"""

		skill_file.write_text(template, encoding="utf-8")
		logger.info(f"Created skill template at {skill_file}")

		# Invalidate cache
		self._loaded = False

		return skill_file


# Global loader instance
_loader: SkillLoader | None = None


def get_skill_loader(project_path: str | None = None) -> SkillLoader:
	"""Get or create the global skill loader instance."""
	global _loader
	if _loader is None:
		_loader = SkillLoader(project_path)
	return _loader
