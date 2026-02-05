"""Project Discovery - Auto-discovers projects for find_project and list_my_projects."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProjectInfo:
	"""Information about a personal project."""
	name: str
	path: str
	description: str
	technologies: list[str] = field(default_factory=list)
	aliases: list[str] = field(default_factory=list)


@dataclass
class ProjectRegistry:
	"""Lightweight project registry."""
	projects: list["ProjectInfo"] = field(default_factory=list)


class ContextManager:
	"""Discovers and searches personal projects."""

	def __init__(self, projects_path: str = ""):
		from .config import get_config
		config = get_config()
		self._projects_path = projects_path or str(config.projects_path)
		self._registry: Optional[ProjectRegistry] = None

	def load(self) -> ProjectRegistry:
		"""Load project registry via auto-discovery."""
		if self._registry:
			return self._registry

		self._registry = ProjectRegistry(
			projects=self._discover_projects()
		)
		return self._registry

	def _discover_projects(self) -> list[ProjectInfo]:
		"""Auto-discover projects from the projects folder."""
		projects: list[ProjectInfo] = []
		projects_path = Path(self._projects_path)

		if not projects_path.exists():
			return projects

		for item in projects_path.iterdir():
			if not item.is_dir():
				continue
			if item.name.startswith(".") or item.name in ["venv", "__pycache__", "node_modules"]:
				continue

			projects.append(ProjectInfo(
				name=item.name,
				path=str(item),
				description=f"Project: {item.name}",
			))

		return projects

	def find_project(self, query: str) -> Optional[ProjectInfo]:
		"""Find a project by name or alias."""
		registry = self.load()
		query_lower = query.lower()

		for project in registry.projects:
			# Exact name match
			if project.name.lower() == query_lower:
				return project

			# Partial name match
			if query_lower in project.name.lower():
				return project

			# Alias match
			for alias in project.aliases:
				if query_lower in alias.lower() or alias.lower() in query_lower:
					return project

		return None
