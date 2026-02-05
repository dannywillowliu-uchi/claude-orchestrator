"""CLI for claude-orchestrator."""

import argparse
import importlib.resources as resources
import json
import re
import sys
from pathlib import Path


def _get_bundled_file(filename: str) -> str:
	"""Read a bundled file from the package."""
	ref = resources.files("claude_orchestrator").joinpath(filename)
	return ref.read_text(encoding="utf-8")


def _get_bundled_agent_files() -> list[tuple[str, str]]:
	"""Get all bundled agent .md files as (name, content) tuples."""
	agents_pkg = resources.files("claude_orchestrator").joinpath("agents")
	results = []
	for item in agents_pkg.iterdir():
		if item.name.endswith(".md"):
			results.append((item.name, item.read_text(encoding="utf-8")))
	return results


def _get_bundled_hook(filename: str) -> str:
	"""Read a bundled hook script from the package."""
	ref = resources.files("claude_orchestrator").joinpath(f"hooks/{filename}")
	return ref.read_text(encoding="utf-8")


def cmd_serve(args: argparse.Namespace) -> None:
	"""Run the MCP server (stdio transport)."""
	from .server import mcp
	mcp.run()


def cmd_install(args: argparse.Namespace) -> None:
	"""Install workflow protocol, agents, and hooks into Claude Code."""
	force = getattr(args, "force", False)
	print("claude-orchestrator install")
	print("=" * 40)
	print()

	claude_dir = Path.home() / ".claude"
	claude_dir.mkdir(parents=True, exist_ok=True)

	# 1. Install workflow protocol into ~/.claude/CLAUDE.md
	print("[1/3] Workflow protocol")
	_install_protocol(claude_dir / "CLAUDE.md", force)
	print()

	# 2. Install custom agents to ~/.claude/agents/
	print("[2/3] Custom agents")
	_install_agents(claude_dir / "agents", force)
	print()

	# 3. Install session-start hook
	print("[3/3] Session hook")
	_install_hook(claude_dir, force)
	print()

	print("Done. Restart Claude Code to pick up changes.")


def _install_protocol(claude_md_path: Path, force: bool) -> None:
	"""Install or update the Workflow Protocol section in CLAUDE.md."""
	protocol_content = _get_bundled_file("protocol.md")

	if not claude_md_path.exists():
		claude_md_path.write_text(protocol_content + "\n", encoding="utf-8")
		print(f"  Created: {claude_md_path}")
		return

	existing = claude_md_path.read_text(encoding="utf-8")

	# Check if section already exists
	section_pattern = r"## Workflow Protocol.*?(?=\n## |\Z)"
	match = re.search(section_pattern, existing, re.DOTALL)

	if match and not force:
		print(f"  Workflow Protocol section already exists in {claude_md_path}")
		print("  Use --force to replace it.")
		return

	if match:
		# Replace existing section
		new_content = existing[:match.start()] + protocol_content.strip() + "\n" + existing[match.end():]
		claude_md_path.write_text(new_content, encoding="utf-8")
		print(f"  Replaced Workflow Protocol section in {claude_md_path}")
	else:
		# Append new section
		separator = "\n\n" if not existing.endswith("\n\n") else "\n" if not existing.endswith("\n") else ""
		claude_md_path.write_text(existing + separator + protocol_content.strip() + "\n", encoding="utf-8")
		print(f"  Appended Workflow Protocol section to {claude_md_path}")


def _install_agents(agents_dir: Path, force: bool) -> None:
	"""Install bundled agent .md files to agents directory."""
	agents_dir.mkdir(parents=True, exist_ok=True)

	installed = 0
	skipped = 0
	for filename, content in _get_bundled_agent_files():
		target = agents_dir / filename
		if target.exists() and not force:
			skipped += 1
			continue
		target.write_text(content, encoding="utf-8")
		installed += 1

	print(f"  {installed} installed, {skipped} skipped in {agents_dir}")
	if skipped and not force:
		print("  Use --force to overwrite existing files.")


def _install_hook(claude_dir: Path, force: bool) -> None:
	"""Install session-start hook script and update settings.json."""
	scripts_dir = claude_dir / "scripts"
	scripts_dir.mkdir(parents=True, exist_ok=True)

	hook_target = scripts_dir / "workflow-session-start.sh"
	hook_content = _get_bundled_hook("session-start.sh")

	if hook_target.exists() and not force:
		print(f"  Hook already exists: {hook_target}")
		print("  Use --force to overwrite.")
	else:
		hook_target.write_text(hook_content, encoding="utf-8")
		hook_target.chmod(0o755)
		action = "Replaced" if hook_target.exists() else "Installed"
		print(f"  {action}: {hook_target}")

	# Update settings.json with hook config
	settings_path = claude_dir / "settings.json"
	_update_hook_settings(settings_path, str(hook_target))


def _update_hook_settings(settings_path: Path, hook_script: str) -> None:
	"""Add SessionStart hook to settings.json."""
	try:
		if settings_path.exists():
			data = json.loads(settings_path.read_text(encoding="utf-8"))
		else:
			data = {}

		if "hooks" not in data:
			data["hooks"] = {}

		hook_entry = {
			"type": "command",
			"command": hook_script,
		}

		# Check if our hook is already configured
		session_hooks = data["hooks"].get("SessionStart", [])
		already_configured = any(
			h.get("command") == hook_script
			for h in session_hooks
			if isinstance(h, dict)
		)

		if already_configured:
			print(f"  SessionStart hook already configured in {settings_path}")
			return

		session_hooks.append(hook_entry)
		data["hooks"]["SessionStart"] = session_hooks

		settings_path.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")
		print(f"  Added SessionStart hook to {settings_path}")

	except (json.JSONDecodeError, IOError) as e:
		print(f"  Failed to update {settings_path}: {e}")


def main() -> None:
	"""CLI entry point."""
	parser = argparse.ArgumentParser(
		prog="claude-orchestrator",
		description="Lightweight workflow system for Claude Code",
	)
	subparsers = parser.add_subparsers(dest="command")

	# serve
	serve_parser = subparsers.add_parser("serve", help="Run MCP server (stdio)")
	serve_parser.set_defaults(func=cmd_serve)

	# install
	install_parser = subparsers.add_parser(
		"install",
		help="Install workflow protocol, agents, and hooks into Claude Code",
	)
	install_parser.add_argument("--force", action="store_true", help="Overwrite existing files")
	install_parser.set_defaults(func=cmd_install)

	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		sys.exit(1)

	args.func(args)
