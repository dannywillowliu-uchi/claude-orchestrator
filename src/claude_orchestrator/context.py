"""Personal Context System - Stores and retrieves user context for personalization."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
class PersonalContext:
    """User's personal context for personalization."""
    name: str = ""
    email: str = ""
    university: str = ""

    # Preferences
    coding_style: dict = field(default_factory=lambda: {
        "language": "Python",
        "formatter": "black",
        "test_framework": "pytest",
    })

    communication_style: dict = field(default_factory=lambda: {
        "tone": "professional",
        "email_signature": "",
    })

    # Projects registry
    projects: list[ProjectInfo] = field(default_factory=list)

    # Recent interactions (for continuity)
    recent_tasks: list[str] = field(default_factory=list)

    # Custom notes
    notes: str = ""

    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ContextManager:
    """Manages personal context storage and retrieval."""

    def __init__(self, context_file: str = "", projects_path: str = ""):
        from .config import get_config
        config = get_config()
        self.context_file = Path(context_file) if context_file else config.context_file
        self.context_file.parent.mkdir(parents=True, exist_ok=True)
        self._projects_path = projects_path or str(config.projects_path)
        self._context: Optional[PersonalContext] = None

    def load(self) -> PersonalContext:
        """Load context from file or create default."""
        if self._context:
            return self._context

        if self.context_file.exists():
            try:
                with open(self.context_file) as f:
                    data = json.load(f)

                # Convert projects list
                projects = []
                for p in data.get("projects", []):
                    projects.append(ProjectInfo(**p))
                data["projects"] = projects

                self._context = PersonalContext(**data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Error loading context: {e}")
                self._context = self._create_default_context()
        else:
            self._context = self._create_default_context()
            self.save()

        return self._context

    def save(self):
        """Save context to file."""
        if not self._context:
            return

        self._context.updated_at = datetime.now().isoformat()

        # Convert to dict, handling nested dataclasses
        data = asdict(self._context)

        with open(self.context_file, "w") as f:
            json.dump(data, f, indent=2)

    def _create_default_context(self) -> PersonalContext:
        """Create default context with auto-discovered projects."""
        context = PersonalContext(
            name=os.getenv("USER_NAME", ""),
            email=os.getenv("USER_EMAIL", ""),
            university=os.getenv("USER_UNIVERSITY", ""),
        )
        context.projects = self._discover_projects()
        return context

    def _discover_projects(self) -> list[ProjectInfo]:
        """Auto-discover projects from the projects folder."""
        projects = []
        projects_path = Path(self._projects_path)

        if not projects_path.exists():
            return projects

        # Scan projects directory
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
        context = self.load()
        query_lower = query.lower()

        for project in context.projects:
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

    def get_project_context(self, project_name: str) -> str:
        """Get context string for a specific project."""
        project = self.find_project(project_name)
        if not project:
            return f"Project '{project_name}' not found."

        return (
            f"Project: {project.name}\n"
            f"Path: {project.path}\n"
            f"Description: {project.description}\n"
            f"Technologies: {', '.join(project.technologies)}"
        )

    def get_full_context(self) -> str:
        """Get full context as a string for Claude."""
        context = self.load()

        parts = [
            f"# Personal Context for {context.name}",
            f"Email: {context.email}",
            f"University: {context.university}",
            "",
            "## Coding Preferences",
        ]

        for key, value in context.coding_style.items():
            parts.append(f"- {key}: {value}")

        parts.extend([
            "",
            "## Communication Style",
        ])

        for key, value in context.communication_style.items():
            parts.append(f"- {key}: {value}")

        parts.extend([
            "",
            "## Projects",
        ])

        for project in context.projects:
            parts.append(f"- **{project.name}**: {project.description}")

        if context.notes:
            parts.extend([
                "",
                "## Notes",
                context.notes,
            ])

        return "\n".join(parts)

    def add_recent_task(self, task_description: str):
        """Add a task to recent history."""
        context = self.load()
        context.recent_tasks.insert(0, task_description)
        context.recent_tasks = context.recent_tasks[:20]  # Keep last 20
        self.save()

    def update_notes(self, notes: str):
        """Update custom notes."""
        context = self.load()
        context.notes = notes
        self.save()
