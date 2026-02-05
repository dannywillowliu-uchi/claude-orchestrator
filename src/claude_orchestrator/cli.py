"""CLI for claude-orchestrator."""

import argparse
import sys


def cmd_serve(args: argparse.Namespace) -> None:
	"""Run the MCP server (stdio transport)."""
	from .server import mcp
	mcp.run()


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

	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		sys.exit(1)

	args.func(args)
