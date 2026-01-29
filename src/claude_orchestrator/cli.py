"""CLI for claude-orchestrator: setup, serve, doctor, and seed-docs commands."""

import argparse
import asyncio
import json
import os
import platform
import sys
from pathlib import Path

from .config import load_config


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


def _detect_claude_code_config() -> Path | None:
	"""Detect Claude Code MCP settings file."""
	home = Path.home()
	candidates = [
		home / ".claude" / "claude_code_config.json",
		home / ".claude.json",
	]
	for path in candidates:
		if path.exists():
			return path
	# Default location even if it doesn't exist yet
	return home / ".claude" / "claude_code_config.json"


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


MCP_ENTRY = {
	"type": "stdio",
	"command": "claude-orchestrator",
	"args": ["serve"],
}


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

	# Step 1: Create directories
	config = load_config()
	print("[1/5] Directories")
	print(f"  Config: {config.config_dir}")
	print(f"  Data:   {config.data_dir}")
	print()

	# Step 2: Write default config.toml
	toml_path = config.config_dir / "config.toml"
	if not toml_path.exists():
		toml_path.write_text(
			'# claude-orchestrator configuration\n'
			'# See: https://github.com/YOUR_USERNAME/claude-orchestrator\n'
			'\n'
			'# projects_path = "~/personal_projects"\n'
		)
		print(f"[2/5] Config file created: {toml_path}")
	else:
		print(f"[2/5] Config file exists: {toml_path}")
	print()

	# Step 3: Detect and inject MCP config
	print("[3/5] MCP configuration")

	claude_code = _detect_claude_code_config()
	if claude_code:
		print(f"  Claude Code config: {claude_code}")
		response = input("  Add claude-orchestrator to Claude Code? [Y/n] ").strip().lower()
		if response in ("", "y", "yes"):
			_inject_mcp_config(claude_code)
	else:
		print("  Claude Code config: not found")

	claude_desktop = _detect_claude_desktop_config()
	if claude_desktop:
		print(f"  Claude Desktop config: {claude_desktop}")
		response = input("  Add claude-orchestrator to Claude Desktop? [Y/n] ").strip().lower()
		if response in ("", "y", "yes"):
			_inject_mcp_config(claude_desktop)
	else:
		print("  Claude Desktop config: not detected")
	print()

	# Step 4: Seed knowledge base
	print("[4/5] Knowledge base seeding")
	try:
		from .knowledge import retriever as _  # noqa: F401
		response = input("  Seed documentation knowledge base? [y/N] ").strip().lower()
		if response in ("y", "yes"):
			print("  Run 'claude-orchestrator seed-docs' to seed the knowledge base.")
	except ImportError:
		print("  Skipped (install knowledge extras: pip install -e '.[knowledge]')")
	print()

	# Step 5: Summary
	print("[5/5] Setup complete")
	print()
	print("  Restart Claude Code / Claude Desktop to load the MCP server.")
	print("  Run 'claude-orchestrator doctor' to verify.")


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


def cmd_serve(args: argparse.Namespace) -> None:
	"""Run the MCP server (stdio transport)."""
	from .server import mcp
	mcp.run()


def cmd_doctor(args: argparse.Namespace) -> None:
	"""Health check - verify installation and configuration."""
	print("claude-orchestrator doctor")
	print(f"{'=' * 40}")
	print()

	config = load_config()

	# Check Python version
	py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
	print(f"  Python:    {py_ver}")
	print(f"  Platform:  {platform.system()} {platform.machine()}")
	print(f"  Config:    {config.config_dir}")
	print(f"  Data:      {config.data_dir}")
	print()

	# Check dependencies
	issues = []
	try:
		from importlib.metadata import version as pkg_version
		mcp_ver = pkg_version("mcp")
		print(f"  mcp:         {mcp_ver}")
	except Exception:
		print("  mcp:         NOT INSTALLED")
		issues.append("mcp package not installed")

	for dep in ["aiosqlite", "platformdirs", "python-dotenv"]:
		try:
			dep_ver = pkg_version(dep)
			print(f"  {dep:14s} {dep_ver}")
		except Exception:
			print(f"  {dep:14s} NOT INSTALLED")
			issues.append(f"{dep} package not installed")

	print()

	# Check MCP config injection
	claude_code = _detect_claude_code_config()
	if claude_code and claude_code.exists():
		try:
			with open(claude_code) as f:
				data = json.load(f)
			has_entry = "claude-orchestrator" in data.get("mcpServers", {})
			status = "configured" if has_entry else "not configured"
			print(f"  Claude Code: {status}")
			if not has_entry:
				issues.append("claude-orchestrator not in Claude Code MCP config")
		except (json.JSONDecodeError, IOError):
			print("  Claude Code: config file unreadable")
	else:
		print("  Claude Code: config not found")

	print()
	if issues:
		print(f"  {len(issues)} issue(s) found:")
		for issue in issues:
			print(f"    - {issue}")
	else:
		print("  All checks passed.")


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

	# serve
	serve_parser = subparsers.add_parser("serve", help="Run MCP server (stdio)")
	serve_parser.set_defaults(func=cmd_serve)

	# doctor
	doctor_parser = subparsers.add_parser("doctor", help="Health check")
	doctor_parser.set_defaults(func=cmd_doctor)

	# seed-docs
	seed_parser = subparsers.add_parser("seed-docs", help="Seed knowledge base with documentation")
	seed_parser.add_argument(
		"--source",
		type=str,
		default=None,
		help="Seed a single source (e.g., 'anthropic-docs', 'mcp-docs')",
	)
	seed_parser.set_defaults(func=cmd_seed_docs)

	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		sys.exit(1)

	args.func(args)
