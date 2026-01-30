"""CLI for claude-orchestrator: setup, serve, doctor, seed-docs, and viz commands."""

import argparse
import asyncio
import json
import os
import platform
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from importlib.metadata import version as pkg_version

from .config import load_config

def _get_bundled_claude_md() -> str:
	"""Read the bundled CLAUDE.md from the package."""
	import importlib.resources as resources
	ref = resources.files("claude_orchestrator").joinpath("CLAUDE.md")
	return ref.read_text(encoding="utf-8")


def _install_claude_md(target_dir: Path) -> tuple[bool, str]:
	"""Copy bundled CLAUDE.md to a target directory.

	Returns (created, message). If the file already exists, skips it.
	"""
	target = target_dir / "CLAUDE.md"
	if target.exists():
		return False, f"Already exists: {target}"
	content = _get_bundled_claude_md()
	target.write_text(content, encoding="utf-8")
	return True, f"Created: {target}"


DEFAULT_SEED_SOURCES = [
	{
		"name": "anthropic-docs",
		"url": "https://docs.anthropic.com/en/docs",
		"source_name": "anthropic-docs",
		"max_pages": 100,
	},
	{
		"name": "mcp-docs",
		"url": "https://modelcontextprotocol.io/docs",
		"source_name": "mcp-docs",
		"max_pages": 50,
	},
]


def _detect_claude_code_config() -> Path:
	"""Detect Claude Code MCP config file.

	Claude Code stores MCP servers in ~/.claude.json under the root-level
	"mcpServers" key. Returns the path to that file (creates if needed during
	injection).
	"""
	home = Path.home()
	path = home / ".claude.json"
	return path


def _detect_claude_desktop_config() -> Path | None:
	"""Detect Claude Desktop MCP settings file."""
	system = platform.system()
	home = Path.home()
	if system == "Darwin":
		path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
	elif system == "Linux":
		path = home / ".config" / "Claude" / "claude_desktop_config.json"
	elif system == "Windows":
		appdata = os.getenv("APPDATA", "")
		if appdata:
			path = Path(appdata) / "Claude" / "claude_desktop_config.json"
		else:
			return None
	else:
		return None
	return path if path.exists() else None


PERMISSION_RULE = "mcp__claude-orchestrator__*"

MCP_ENTRY = {
	"type": "stdio",
	"command": "claude-orchestrator",
	"args": ["serve"],
}


def _inject_claude_code_permissions() -> bool:
	"""Inject mcp__claude-orchestrator__* into Claude Code permissions.allow.

	Reads ~/.claude/settings.json (creates with default structure if missing),
	appends the permission rule if not already present, and writes back.
	Returns True if the rule was added or already existed.
	"""
	settings_path = Path.home() / ".claude" / "settings.json"
	try:
		if settings_path.exists():
			with open(settings_path) as f:
				data = json.load(f)
		else:
			data = {}

		if "permissions" not in data:
			data["permissions"] = {}
		if "allow" not in data["permissions"]:
			data["permissions"]["allow"] = []

		allow_list = data["permissions"]["allow"]
		if PERMISSION_RULE in allow_list:
			print(f"  Permission already configured: {PERMISSION_RULE}")
			return True

		allow_list.append(PERMISSION_RULE)
		settings_path.parent.mkdir(parents=True, exist_ok=True)
		with open(settings_path, "w") as f:
			json.dump(data, f, indent="\t")
			f.write("\n")
		print(f"  Added permission: {PERMISSION_RULE}")
		return True
	except (json.JSONDecodeError, IOError) as e:
		print(f"  Failed to update {settings_path}: {e}")
		return False


def _inject_mcp_config(config_path: Path) -> bool:
	"""Inject claude-orchestrator entry into an MCP config file."""
	try:
		if config_path.exists():
			with open(config_path) as f:
				data = json.load(f)
		else:
			data = {}

		if "mcpServers" not in data:
			data["mcpServers"] = {}

		if "claude-orchestrator" in data["mcpServers"]:
			print(f"  Already configured in {config_path}")
			return True

		data["mcpServers"]["claude-orchestrator"] = MCP_ENTRY
		config_path.parent.mkdir(parents=True, exist_ok=True)
		with open(config_path, "w") as f:
			json.dump(data, f, indent=2)
		print(f"  Added to {config_path}")
		return True
	except (json.JSONDecodeError, IOError) as e:
		print(f"  Failed to update {config_path}: {e}")
		return False


def cmd_setup(args: argparse.Namespace) -> None:
	"""Interactive setup wizard."""
	if args.check:
		cmd_setup_check()
		return

	print("claude-orchestrator setup")
	print(f"{'=' * 40}")
	print()

	# Step 1: Create directories + show extras status
	config = load_config()
	print("[1/7] Directories & extras")
	print(f"  Config: {config.config_dir}")
	print(f"  Data:   {config.data_dir}")
	print()
	print("  Installed extras:")
	extras_results = _check_optional_extras()
	missing_extras = []
	for extra_name, status in extras_results:
		print(f"    {extra_name:14s} {status}")
		if "NOT INSTALLED" in status:
			missing_extras.append(extra_name)
	print()

	# Step 2: Write default config.toml
	toml_path = config.config_dir / "config.toml"
	if not toml_path.exists():
		toml_path.write_text(
			'# claude-orchestrator configuration\n'
			'# See: https://github.com/dannywillowliu-uchi/claude-orchestrator\n'
			'\n'
			'# projects_path = "~/personal_projects"\n'
		)
		print(f"[2/7] Config file created: {toml_path}")
	else:
		print(f"[2/7] Config file exists: {toml_path}")
	print()

	# Step 3: Detect and inject MCP config
	print("[3/7] MCP configuration")

	claude_code = _detect_claude_code_config()
	exists_label = "" if claude_code.exists() else " (will be created)"
	print(f"  Claude Code config: {claude_code}{exists_label}")
	response = input("  Add claude-orchestrator to Claude Code? [Y/n] ").strip().lower()
	if response in ("", "y", "yes"):
		_inject_mcp_config(claude_code)

	claude_desktop = _detect_claude_desktop_config()
	if claude_desktop:
		print(f"  Claude Desktop config: {claude_desktop}")
		response = input("  Add claude-orchestrator to Claude Desktop? [Y/n] ").strip().lower()
		if response in ("", "y", "yes"):
			_inject_mcp_config(claude_desktop)
	else:
		print("  Claude Desktop config: not detected")

	print()
	print("  Auto-accepting MCP permissions in Claude Code...")
	_inject_claude_code_permissions()
	print()

	# Step 4: Install CLAUDE.md for Claude Code integration
	print("[4/7] Claude Code project instructions (CLAUDE.md)")
	print("  The orchestrator ships a CLAUDE.md that teaches Claude Code how to")
	print("  use planning sessions, verification gates, Telegram notifications,")
	print("  and other orchestrator tools automatically.")
	print()
	projects_path = config.projects_path
	cwd = Path.cwd()
	targets = []
	if cwd != Path.home() and (cwd / ".git").exists():
		targets.append(("current project", cwd))
	if projects_path.exists():
		targets.append(("projects root", projects_path))

	if targets:
		for label, target in targets:
			existing = (target / "CLAUDE.md").exists()
			default = "n" if existing else "Y"
			prompt_str = f"  Install CLAUDE.md to {label} ({target})? [{'y/N' if existing else 'Y/n'}] "
			response = input(prompt_str).strip().lower()
			should_install = response in ("y", "yes") if existing else response in ("", "y", "yes")
			if should_install:
				if existing:
					response = input("  File already exists. Overwrite? [y/N] ").strip().lower()
					if response not in ("y", "yes"):
						print(f"  Skipped: {target / 'CLAUDE.md'}")
						continue
					(target / "CLAUDE.md").unlink()
				created, msg = _install_claude_md(target)
				print(f"  {msg}")
			else:
				print(f"  Skipped: {target}")
	else:
		print(f"  No project directories found. Use 'claude-orchestrator init-project <path>'")
		print(f"  to install CLAUDE.md into any project later.")
	print()

	# Step 5: Seed knowledge base
	print("[5/7] Knowledge base seeding")
	try:
		from .knowledge import retriever as _  # noqa: F401
		response = input("  Seed documentation knowledge base? [y/N] ").strip().lower()
		if response in ("y", "yes"):
			print("  Run 'claude-orchestrator seed-docs' to seed the knowledge base.")
	except ImportError:
		print("  Skipped (install knowledge extras: pip install claude-orchestrator[knowledge])")
	print()

	# Step 6: Run doctor to verify
	print("[6/7] Verification")
	print()
	try:
		cmd_doctor(argparse.Namespace())
	except SystemExit:
		pass  # doctor may exit(1) on issues, don't propagate during setup
	print()

	# Step 7: Next steps
	print("[7/7] Next steps")
	next_steps = []
	if missing_extras:
		next_steps.append(f"  Install extras: pip install claude-orchestrator[all]")
	if "knowledge" not in missing_extras:
		# Knowledge is installed, check if seeded
		knowledge_dir = config.data_dir / "knowledge"
		if not knowledge_dir.exists() or not any(knowledge_dir.iterdir() if knowledge_dir.exists() else []):
			next_steps.append("  Seed docs: claude-orchestrator seed-docs")
	if not config.secrets_file.exists():
		next_steps.append("  Add API keys via the set_secret MCP tool")
	next_steps.append("  Restart Claude Code / Claude Desktop to load the MCP server")

	for step in next_steps:
		print(step)
	if not next_steps:
		print("  Everything looks good!")


def cmd_setup_check() -> None:
	"""Check current configuration status."""
	print("claude-orchestrator config check")
	print(f"{'=' * 40}")
	print()

	config = load_config()

	checks = [
		("Config dir", config.config_dir, config.config_dir.exists()),
		("Data dir", config.data_dir, config.data_dir.exists()),
		("Config file", config.config_dir / "config.toml", (config.config_dir / "config.toml").exists()),
		("Secrets file", config.secrets_file, config.secrets_file.exists()),
		("Plans DB", config.plans_db_path, config.plans_db_path.exists()),
	]

	all_ok = True
	for label, path, exists in checks:
		status = "OK" if exists else "MISSING"
		if not exists:
			all_ok = False
		print(f"  [{status:7s}] {label}: {path}")

	print()
	if not all_ok:
		print("  Some paths are missing. Run 'claude-orchestrator setup' to configure.")
	else:
		print("  All paths configured.")


def cmd_allow_permissions(args: argparse.Namespace) -> None:
	"""Add MCP permission rule to Claude Code settings."""
	print("claude-orchestrator allow-permissions")
	print(f"{'=' * 40}")
	print()
	_inject_claude_code_permissions()


def cmd_serve(args: argparse.Namespace) -> None:
	"""Run the MCP server (stdio transport)."""
	from .server import mcp
	mcp.run()


def _check_optional_extras() -> list[tuple[str, str]]:
	"""Check optional extras installation status.

	Returns list of (extra_name, status_string) tuples.
	"""
	extras = {
		"visual": ["playwright"],
		"knowledge": ["lancedb", "sentence-transformers", "aiohttp", "markdownify"],
		"web": ["starlette", "uvicorn"],
	}
	results = []
	for extra_name, packages in extras.items():
		installed = []
		for pkg in packages:
			try:
				ver = pkg_version(pkg)
				installed.append(f"{pkg} {ver}")
			except Exception:
				pass
		if installed:
			results.append((extra_name, ", ".join(installed)))
		else:
			results.append((extra_name, f"NOT INSTALLED (pip install claude-orchestrator[{extra_name}])"))
	return results


def _check_config_toml(config_dir: Path) -> tuple[str, str | None]:
	"""Validate config.toml. Returns (status, issue_or_none)."""
	import tomllib

	toml_path = config_dir / "config.toml"
	if not toml_path.exists():
		return "not found (optional)", None
	try:
		with open(toml_path, "rb") as f:
			tomllib.load(f)
		return "valid", None
	except tomllib.TOMLDecodeError as e:
		msg = f"config.toml parse error: {e}"
		return f"INVALID ({e})", msg


def _check_secrets_json(secrets_file: Path) -> tuple[str, str | None]:
	"""Validate secrets.json. Returns (status, issue_or_none)."""
	if not secrets_file.exists():
		return "not found (optional)", None
	try:
		with open(secrets_file) as f:
			data = json.load(f)
		keys = data.get("keys", {})
		if not isinstance(keys, dict):
			return "INVALID (keys is not a dict)", "secrets.json: 'keys' field is not a dict"
		active = sum(1 for v in keys.values() if isinstance(v, dict) and v.get("active", True))
		legacy = sum(1 for v in keys.values() if isinstance(v, str))
		status = f"{len(keys)} secrets ({active} active)"
		if legacy:
			status += f", {legacy} legacy string-format"
		issue = f"secrets.json has {legacy} legacy string-format entries" if legacy else None
		return status, issue
	except (json.JSONDecodeError, IOError) as e:
		return f"INVALID ({e})", f"secrets.json unreadable: {e}"


def _check_server_startup() -> tuple[str, str | None]:
	"""Try importing and counting registered tools. Returns (status, issue_or_none)."""
	try:
		from .server import mcp as server_instance
		# FastMCP stores tools internally - count them
		tools = server_instance._tool_manager._tools
		count = len(tools)
		return f"OK ({count} tools registered)", None
	except Exception as e:
		return f"FAILED ({e})", f"Server startup failed: {e}"


def cmd_doctor(args: argparse.Namespace) -> None:
	"""Health check - verify installation and configuration."""
	print("claude-orchestrator doctor")
	print(f"{'=' * 40}")

	config = load_config()
	issues: list[str] = []

	# System info
	py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
	print(f"  Python:       {py_ver}")
	print(f"  Platform:     {platform.system()} {platform.machine()}")
	print()

	# Core deps
	print("  Core deps:")
	core_deps = ["mcp", "aiosqlite", "platformdirs", "python-dotenv", "pexpect", "PyGithub", "rich"]
	for dep in core_deps:
		try:
			dep_ver = pkg_version(dep)
			print(f"    {dep:22s} {dep_ver}")
		except Exception:
			print(f"    {dep:22s} NOT INSTALLED")
			issues.append(f"{dep} package not installed")
	print()

	# Optional extras
	print("  Optional extras:")
	for extra_name, status in _check_optional_extras():
		print(f"    {extra_name:22s} {status}")
	print()

	# Config validation
	print("  Config:")
	toml_status, toml_issue = _check_config_toml(config.config_dir)
	print(f"    config.toml:         {toml_status}")
	if toml_issue:
		issues.append(toml_issue)

	secrets_status, secrets_issue = _check_secrets_json(config.secrets_file)
	print(f"    secrets.json:        {secrets_status}")
	if secrets_issue:
		issues.append(secrets_issue)
	print()

	# Server startup test
	print("  Server:")
	server_status, server_issue = _check_server_startup()
	print(f"    {server_status}")
	if server_issue:
		issues.append(server_issue)
	print()

	# MCP config injection
	claude_code = _detect_claude_code_config()
	if claude_code.exists():
		try:
			with open(claude_code) as f:
				data = json.load(f)
			has_entry = "claude-orchestrator" in data.get("mcpServers", {})
			status = "configured" if has_entry else "not configured"
			print(f"  Claude Code:  {status}")
			if not has_entry:
				issues.append("claude-orchestrator not in Claude Code MCP config")
		except (json.JSONDecodeError, IOError):
			print("  Claude Code:  config file unreadable")
	else:
		print(f"  Claude Code:  {claude_code} not found (run setup to create)")

	print()
	if issues:
		print(f"  {len(issues)} issue(s) found:")
		for issue in issues:
			print(f"    - {issue}")
		sys.exit(1)
	else:
		print("  All checks passed.")


def cmd_init_project(args: argparse.Namespace) -> None:
	"""Install CLAUDE.md into a project directory."""
	target = Path(args.path).resolve()
	if not target.is_dir():
		print(f"Error: {target} is not a directory.")
		sys.exit(1)

	target_file = target / "CLAUDE.md"
	if target_file.exists() and not args.force:
		print(f"CLAUDE.md already exists at {target_file}")
		print("Use --force to overwrite.")
		sys.exit(1)

	if target_file.exists():
		target_file.unlink()

	created, msg = _install_claude_md(target)
	print(msg)
	if created:
		print()
		print("Claude Code will now use orchestrator tools automatically in this project.")
		print("Commit CLAUDE.md to your repo so collaborators get the same setup.")


def cmd_seed_docs(args: argparse.Namespace) -> None:
	"""Seed the knowledge base by crawling and indexing documentation sources."""
	try:
		from .knowledge.retriever import crawl_and_index
	except ImportError:
		print("Error: knowledge extras not installed.")
		print("Install with: pip install -e '.[knowledge]'")
		sys.exit(1)

	source_filter = getattr(args, "source", None)

	sources = DEFAULT_SEED_SOURCES
	if source_filter:
		sources = [s for s in sources if s["name"] == source_filter]
		if not sources:
			available = ", ".join(s["name"] for s in DEFAULT_SEED_SOURCES)
			print(f"Unknown source: {source_filter}")
			print(f"Available: {available}")
			sys.exit(1)

	print("claude-orchestrator seed-docs")
	print(f"{'=' * 40}")
	print()

	for source in sources:
		print(f"  Crawling {source['name']} ({source['url']}, max {source['max_pages']} pages)...")
		try:
			result_json = asyncio.run(crawl_and_index(
				start_url=source["url"],
				source_name=source["source_name"],
				max_pages=source["max_pages"],
			))
			result = json.loads(result_json)
			if result.get("success"):
				crawl = result.get("crawl", {})
				index = result.get("index", {})
				print(f"    Crawled {crawl.get('successful', 0)} pages, indexed {index.get('total_chunks', 0)} chunks")
			else:
				print(f"    Error: {result.get('error', 'unknown')}")
		except Exception as e:
			print(f"    Failed: {e}")
		print()

	print("Done.")


def _parse_since(since_str: str) -> str:
	"""Parse a duration string like '1h', '24h', '7d' into an ISO timestamp."""
	match = re.match(r"^(\d+)([hmd])$", since_str)
	if not match:
		print(f"Invalid --since format: {since_str} (use e.g. 1h, 24h, 7d)")
		sys.exit(1)
	amount = int(match.group(1))
	unit = match.group(2)
	if unit == "h":
		delta = timedelta(hours=amount)
	elif unit == "m":
		delta = timedelta(minutes=amount)
	else:
		delta = timedelta(days=amount)
	return (datetime.now() - delta).isoformat()


def cmd_viz(args: argparse.Namespace) -> None:
	"""Visualizer subcommand - Rich terminal views for observability."""
	from .instrumentation import ToolCallStore
	from .visualizer.dashboard import render_dashboard
	from .visualizer.plan_progress import render_plan_progress, render_plan_summary
	from .visualizer.session_timeline import render_session_detail, render_session_list
	from .visualizer.tool_stats import render_tool_detail, render_tool_stats, render_tool_timeline

	store = ToolCallStore()
	since = _parse_since(args.since) if getattr(args, "since", None) else None
	limit = getattr(args, "limit", 50)

	viz_target = getattr(args, "viz_target", None)

	if viz_target == "web":
		cmd_viz_web(args)
		return

	if viz_target == "tools":
		if getattr(args, "name", None):
			render_tool_detail(store, args.name, limit=limit)
		elif getattr(args, "timeline", False):
			render_tool_timeline(store, limit=limit, since=since)
		else:
			render_tool_stats(store, since=since)

	elif viz_target == "sessions":
		session_id = getattr(args, "session_id", None)
		if session_id:
			render_session_detail(store, session_id)
		else:
			render_session_list(store)

	elif viz_target == "plan":
		plan_id = getattr(args, "plan_id", None)
		plan = asyncio.run(_load_plan(plan_id))
		if plan:
			if getattr(args, "summary", False):
				render_plan_summary(plan)
			else:
				render_plan_progress(plan)
		else:
			label = f"plan '{plan_id}'" if plan_id else "active plan"
			print(f"No {label} found.")

	elif viz_target == "dashboard":
		plan = asyncio.run(_load_plan(None))
		render_dashboard(store, plan=plan)

	else:
		print("Usage: claude-orchestrator viz {tools|sessions|plan|dashboard|web}")
		print("Run 'claude-orchestrator viz --help' for details.")
		sys.exit(1)


def cmd_viz_web(args: argparse.Namespace) -> None:
	"""Launch the web dashboard."""
	try:
		from .web import run_web_dashboard
	except ImportError:
		print("Web extras not installed.")
		print("Install with: pip install -e '.[web]'")
		sys.exit(1)

	port = getattr(args, "port", 8420)
	no_open = getattr(args, "no_open", False)
	run_web_dashboard(port=port, open_browser=not no_open)


async def _load_plan(plan_id: str | None):
	"""Load a plan by ID or get the most recent current plan."""
	try:
		from .plans.store import get_plan_store
		plan_store = await get_plan_store()
		if plan_id:
			return await plan_store.get_plan(plan_id)
		# Get most recent current plan across all projects
		plans = await plan_store.search_plans(current_only=True)
		return plans[0] if plans else None
	except Exception:
		return None


def main() -> None:
	"""CLI entry point."""
	parser = argparse.ArgumentParser(
		prog="claude-orchestrator",
		description="MCP server for Claude Code: planning, verification, and progress tracking",
	)
	subparsers = parser.add_subparsers(dest="command")

	# setup
	setup_parser = subparsers.add_parser("setup", help="Interactive setup wizard")
	setup_parser.add_argument("--check", action="store_true", help="Check current config")
	setup_parser.set_defaults(func=cmd_setup)

	# allow-permissions
	perms_parser = subparsers.add_parser("allow-permissions", help="Auto-accept MCP permissions in Claude Code")
	perms_parser.set_defaults(func=cmd_allow_permissions)

	# serve
	serve_parser = subparsers.add_parser("serve", help="Run MCP server (stdio)")
	serve_parser.set_defaults(func=cmd_serve)

	# doctor
	doctor_parser = subparsers.add_parser("doctor", help="Health check")
	doctor_parser.set_defaults(func=cmd_doctor)

	# init-project
	init_parser = subparsers.add_parser(
		"init-project",
		help="Install CLAUDE.md into a project for Claude Code integration",
	)
	init_parser.add_argument("path", nargs="?", default=".", help="Project directory (default: current)")
	init_parser.add_argument("--force", action="store_true", help="Overwrite existing CLAUDE.md")
	init_parser.set_defaults(func=cmd_init_project)

	# seed-docs
	seed_parser = subparsers.add_parser("seed-docs", help="Seed knowledge base with documentation")
	seed_parser.add_argument(
		"--source",
		type=str,
		default=None,
		help="Seed a single source (e.g., 'anthropic-docs', 'mcp-docs')",
	)
	seed_parser.set_defaults(func=cmd_seed_docs)

	# viz
	viz_parser = subparsers.add_parser("viz", help="Visualize tool calls, sessions, and plans")
	viz_subparsers = viz_parser.add_subparsers(dest="viz_target")

	# viz tools
	viz_tools = viz_subparsers.add_parser("tools", help="Tool call statistics")
	viz_tools.add_argument("--timeline", action="store_true", help="Show timeline instead of stats")
	viz_tools.add_argument("--name", type=str, default=None, help="Detail view for a specific tool")
	viz_tools.add_argument("--since", type=str, default=None, help="Filter by time (e.g. 1h, 24h, 7d)")
	viz_tools.add_argument("--limit", type=int, default=50, help="Max results")
	viz_tools.set_defaults(func=cmd_viz)

	# viz sessions
	viz_sessions = viz_subparsers.add_parser("sessions", help="Session timelines")
	viz_sessions.add_argument("session_id", nargs="?", default=None, help="Session ID for detail view")
	viz_sessions.set_defaults(func=cmd_viz)

	# viz plan
	viz_plan = viz_subparsers.add_parser("plan", help="Plan progress")
	viz_plan.add_argument("plan_id", nargs="?", default=None, help="Plan ID (default: latest)")
	viz_plan.add_argument("--summary", action="store_true", help="Show summary panel instead of tree")
	viz_plan.set_defaults(func=cmd_viz)

	# viz dashboard
	viz_dashboard = viz_subparsers.add_parser("dashboard", help="Combined dashboard")
	viz_dashboard.set_defaults(func=cmd_viz)

	# viz web
	viz_web = viz_subparsers.add_parser("web", help="Launch web dashboard")
	viz_web.add_argument("--port", type=int, default=8420, help="Server port (default: 8420)")
	viz_web.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
	viz_web.set_defaults(func=cmd_viz)

	viz_parser.set_defaults(func=cmd_viz)

	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		sys.exit(1)

	args.func(args)
