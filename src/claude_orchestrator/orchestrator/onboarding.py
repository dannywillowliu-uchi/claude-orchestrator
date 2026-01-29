"""
Codebase Onboarding - Analyze a project to generate context for Claude sessions.

Detects language, entry points, key files, and project structure
to build onboarding context for new sessions.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# File patterns for language detection
_LANGUAGE_INDICATORS: dict[str, list[str]] = {
	"python": ["*.py", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt"],
	"javascript": ["*.js", "package.json", "*.mjs"],
	"typescript": ["*.ts", "*.tsx", "tsconfig.json"],
	"rust": ["*.rs", "Cargo.toml"],
	"go": ["*.go", "go.mod"],
	"java": ["*.java", "pom.xml", "build.gradle"],
	"ruby": ["*.rb", "Gemfile"],
	"c": ["*.c", "*.h", "Makefile"],
	"cpp": ["*.cpp", "*.hpp", "CMakeLists.txt"],
}

# Common entry point patterns
_ENTRY_POINT_PATTERNS: list[str] = [
	"main.py",
	"app.py",
	"cli.py",
	"__main__.py",
	"index.js",
	"index.ts",
	"main.rs",
	"main.go",
	"Main.java",
	"server.py",
	"server.js",
	"server.ts",
]

# Key file patterns
_KEY_FILE_PATTERNS: list[str] = [
	"README.md",
	"README.rst",
	"CLAUDE.md",
	"pyproject.toml",
	"package.json",
	"Cargo.toml",
	"go.mod",
	"Makefile",
	"Dockerfile",
	"docker-compose.yml",
	"docker-compose.yaml",
	".github/workflows/*.yml",
	".github/workflows/*.yaml",
]


@dataclass
class ProjectProfile:
	"""Profile of an analyzed project."""

	path: str
	name: str
	languages: list[str] = field(default_factory=list)
	primary_language: Optional[str] = None
	entry_points: list[str] = field(default_factory=list)
	key_files: list[str] = field(default_factory=list)
	has_tests: bool = False
	has_ci: bool = False
	has_docker: bool = False
	file_count: int = 0
	directory_count: int = 0


class CodebaseOnboarder:
	"""
	Analyzes a project directory to build an onboarding profile.

	Detects language, entry points, key files, and project structure
	using filesystem heuristics (no AST parsing yet).
	"""

	def analyze_project(self, path: str) -> ProjectProfile:
		"""
		Analyze a project directory and return its profile.

		Args:
			path: Path to the project root

		Returns:
			ProjectProfile with detected information

		Raises:
			FileNotFoundError: If path does not exist
		"""
		project_path = Path(path).expanduser().resolve()
		if not project_path.is_dir():
			raise FileNotFoundError(f"Not a directory: {path}")

		profile = ProjectProfile(
			path=str(project_path),
			name=project_path.name,
		)

		# Detect languages
		profile.languages = self._detect_languages(project_path)
		if profile.languages:
			profile.primary_language = profile.languages[0]

		# Detect entry points
		profile.entry_points = self._detect_entry_points(project_path)

		# Detect key files
		profile.key_files = self._detect_key_files(project_path)

		# Detect capabilities
		profile.has_tests = self._has_tests(project_path)
		profile.has_ci = self._has_ci(project_path)
		profile.has_docker = self._has_docker(project_path)

		# Count files and directories (top-level, skip hidden)
		profile.file_count = sum(
			1 for f in project_path.rglob("*")
			if f.is_file()
			and not any(
				p.name.startswith(".") for p in f.relative_to(project_path).parents if p != Path(".")
			)
		)
		profile.directory_count = sum(
			1 for d in project_path.rglob("*")
			if d.is_dir() and not d.name.startswith(".")
		)

		lang = profile.primary_language or "unknown"
		logger.info(f"Analyzed project: {profile.name} ({lang}, {profile.file_count} files)")

		return profile

	def _detect_languages(self, path: Path) -> list[str]:
		"""Detect programming languages used in the project."""
		detected: dict[str, int] = {}

		for language, patterns in _LANGUAGE_INDICATORS.items():
			count = 0
			for pattern in patterns:
				count += len(list(path.glob(f"**/{pattern}")))
			if count > 0:
				detected[language] = count

		# Sort by file count (most files = primary language)
		return sorted(detected.keys(), key=lambda k: detected[k], reverse=True)

	def _detect_entry_points(self, path: Path) -> list[str]:
		"""Detect likely entry point files."""
		found = []
		for pattern in _ENTRY_POINT_PATTERNS:
			for match in path.rglob(pattern):
				# Skip files in hidden dirs, node_modules, venvs
				rel = str(match.relative_to(path))
				skip_dirs = ("node_modules", "venv", ".venv", "__pycache__")
				if not any(part.startswith(".") or part in skip_dirs for part in rel.split("/")):
					found.append(rel)
		return sorted(found)

	def _detect_key_files(self, path: Path) -> list[str]:
		"""Detect key project files (configs, docs, CI)."""
		found = []
		for pattern in _KEY_FILE_PATTERNS:
			for match in path.glob(pattern):
				found.append(str(match.relative_to(path)))
		return sorted(found)

	def _has_tests(self, path: Path) -> bool:
		"""Check if project has a tests directory or test files."""
		if (path / "tests").is_dir() or (path / "test").is_dir():
			return True
		return bool(list(path.glob("**/test_*.py"))) or bool(list(path.glob("**/*.test.js")))

	def _has_ci(self, path: Path) -> bool:
		"""Check if project has CI configuration."""
		ci_paths = [
			path / ".github" / "workflows",
			path / ".gitlab-ci.yml",
			path / ".circleci",
			path / "Jenkinsfile",
		]
		return any(p.exists() for p in ci_paths)

	def _has_docker(self, path: Path) -> bool:
		"""Check if project has Docker configuration."""
		docker_paths = [
			path / "Dockerfile",
			path / "docker-compose.yml",
			path / "docker-compose.yaml",
		]
		return any(p.exists() for p in docker_paths)

	def generate_ast_summary(self, path: str) -> str:
		"""
		Generate an AST-based summary of the codebase.

		Not yet implemented. Will parse source files to extract
		class/function signatures and module structure.

		Raises:
			NotImplementedError
		"""
		raise NotImplementedError("AST summary generation is not yet implemented")

	def generate_onboarding_prompt(self, path: str) -> str:
		"""
		Generate a comprehensive onboarding prompt for a Claude session.

		Not yet implemented. Will combine project profile, AST summary,
		and documentation into a structured prompt.

		Raises:
			NotImplementedError
		"""
		raise NotImplementedError("Onboarding prompt generation is not yet implemented")
