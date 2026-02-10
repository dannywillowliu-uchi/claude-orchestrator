"""Project bootstrapping -- detect project type and configure environment.

Implements the Initializer Agent pattern: before starting work on a project,
detect its type, verify the toolchain, and generate a starter CLAUDE.md with
appropriate verification configuration.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectProfile:
	"""Detected project profile."""

	project_type: str  # python, node, rust, go, unknown
	manifest_file: str  # pyproject.toml, package.json, etc.
	package_manager: str  # uv, pip, npm, yarn, cargo, go
	test_command: str
	lint_command: str
	type_check_command: str
	security_command: str
	verification_commands: list[str] = field(default_factory=list)
	detected_tools: dict[str, bool] = field(default_factory=dict)
	has_claude_md: bool = False


# Manifest file -> project type mapping (checked in order)
MANIFEST_MAP: list[tuple[str, str]] = [
	("pyproject.toml", "python"),
	("setup.py", "python"),
	("setup.cfg", "python"),
	("requirements.txt", "python"),
	("package.json", "node"),
	("Cargo.toml", "rust"),
	("go.mod", "go"),
]

# Per-type verification defaults
TYPE_DEFAULTS: dict[str, dict[str, str]] = {
	"python": {
		"test_command": "pytest",
		"lint_command": "ruff check .",
		"type_check_command": "mypy . --ignore-missing-imports",
		"security_command": "bandit -r src/",
		"package_manager": "pip",
	},
	"node": {
		"test_command": "npm test",
		"lint_command": "npx eslint .",
		"type_check_command": "npx tsc --noEmit",
		"security_command": "npm audit",
		"package_manager": "npm",
	},
	"rust": {
		"test_command": "cargo test",
		"lint_command": "cargo clippy",
		"type_check_command": "cargo check",
		"security_command": "cargo audit",
		"package_manager": "cargo",
	},
	"go": {
		"test_command": "go test ./...",
		"lint_command": "golangci-lint run",
		"type_check_command": "go vet ./...",
		"security_command": "gosec ./...",
		"package_manager": "go",
	},
}


def detect_project_type(project_path: str) -> ProjectProfile:
	"""Detect project type from manifest files and configure verification."""
	base = Path(project_path).expanduser().resolve()

	# Detect project type
	project_type = "unknown"
	manifest_file = ""
	for manifest, ptype in MANIFEST_MAP:
		if (base / manifest).exists():
			project_type = ptype
			manifest_file = manifest
			break

	if project_type == "unknown":
		return ProjectProfile(
			project_type="unknown",
			manifest_file="",
			package_manager="",
			test_command="",
			lint_command="",
			type_check_command="",
			security_command="",
			has_claude_md=(base / "CLAUDE.md").exists(),
		)

	defaults = TYPE_DEFAULTS[project_type]
	package_manager = defaults["package_manager"]

	# Refine package manager detection for Python
	if project_type == "python":
		if (base / "uv.lock").exists() or (base / ".python-version").exists():
			package_manager = "uv"
		elif (base / "poetry.lock").exists():
			package_manager = "poetry"
		elif (base / "Pipfile").exists():
			package_manager = "pipenv"

	# Refine package manager for Node
	if project_type == "node":
		if (base / "yarn.lock").exists():
			package_manager = "yarn"
		elif (base / "pnpm-lock.yaml").exists():
			package_manager = "pnpm"
		elif (base / "bun.lockb").exists():
			package_manager = "bun"

	# Build run prefix
	run_prefix = _get_run_prefix(package_manager)

	# Build verification commands
	test_cmd = f"{run_prefix}{defaults['test_command']}"
	lint_cmd = f"{run_prefix}{defaults['lint_command']}"
	type_cmd = f"{run_prefix}{defaults['type_check_command']}"
	security_cmd = f"{run_prefix}{defaults['security_command']}"

	# Detect which config files exist for refinements
	detected_tools: dict[str, bool] = {}

	if project_type == "python":
		detected_tools["ruff"] = (
			(base / "ruff.toml").exists() or _pyproject_has(base, "ruff")
		)
		detected_tools["mypy"] = (
			(base / "mypy.ini").exists()
			or (base / ".mypy.ini").exists()
			or _pyproject_has(base, "mypy")
		)
		detected_tools["pytest"] = (
			(base / "pytest.ini").exists()
			or (base / "conftest.py").exists()
			or _pyproject_has(base, "pytest")
		)
		# Refine lint source path if src/ layout
		if (base / "src").is_dir():
			lint_cmd = f"{run_prefix}ruff check src/ tests/"
			security_cmd = f"{run_prefix}bandit -r src/"

	if project_type == "node":
		detected_tools["eslint"] = (
			(base / ".eslintrc.js").exists()
			or (base / ".eslintrc.json").exists()
			or (base / "eslint.config.js").exists()
		)
		detected_tools["typescript"] = (base / "tsconfig.json").exists()
		if not detected_tools["typescript"]:
			type_cmd = ""  # No TypeScript, skip type checking

	verification_commands = [c for c in [test_cmd, lint_cmd, type_cmd, security_cmd] if c]

	return ProjectProfile(
		project_type=project_type,
		manifest_file=manifest_file,
		package_manager=package_manager,
		test_command=test_cmd,
		lint_command=lint_cmd,
		type_check_command=type_cmd,
		security_command=security_cmd,
		verification_commands=verification_commands,
		detected_tools=detected_tools,
		has_claude_md=(base / "CLAUDE.md").exists(),
	)


def generate_claude_md(profile: ProjectProfile, project_name: str = "") -> str:
	"""Generate a starter CLAUDE.md based on the detected project profile."""
	name = project_name or "Project"
	verification_block = "\n".join(f"- {cmd}" for cmd in profile.verification_commands)

	return f"""# {name}

## Verification Requirements

Before ANY commit, run the full verification suite:
{verification_block}

Block the commit if any critical check fails (tests, type errors, security findings).

## Tech Stack

- Type: {profile.project_type}
- Package manager: {profile.package_manager}
- Manifest: {profile.manifest_file}

## Project Memory

Update the project CLAUDE.md automatically:
- After each phase completion: Update Implementation Status section
- On significant architectural decisions: Append to Decisions Log
- When discovering issues: Append to Gotchas section
"""


def _get_run_prefix(package_manager: str) -> str:
	"""Get the command prefix for running tools through the package manager."""
	prefixes = {
		"uv": "uv run ",
		"poetry": "poetry run ",
		"pipenv": "pipenv run ",
		"pip": "",
		"npm": "",
		"yarn": "yarn ",
		"pnpm": "pnpm ",
		"bun": "bun ",
		"cargo": "",
		"go": "",
	}
	return prefixes.get(package_manager, "")


def _pyproject_has(base: Path, tool: str) -> bool:
	"""Check if pyproject.toml references a tool."""
	pyproject = base / "pyproject.toml"
	if not pyproject.exists():
		return False
	content = pyproject.read_text(encoding="utf-8")
	return f"[tool.{tool}" in content
