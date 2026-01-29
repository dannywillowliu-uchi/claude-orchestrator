"""Tests for the viz CLI subcommand."""

import argparse
from pathlib import Path
from unittest.mock import patch

from claude_orchestrator.cli import cmd_viz, main


def test_viz_subparser_registered():
	"""viz subparser should be registered in the CLI."""
	with patch("sys.argv", ["claude-orchestrator", "viz", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def test_viz_tools_subparser_registered():
	"""viz tools subparser should be registered."""
	with patch("sys.argv", ["claude-orchestrator", "viz", "tools", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def test_viz_sessions_subparser_registered():
	"""viz sessions subparser should be registered."""
	with patch("sys.argv", ["claude-orchestrator", "viz", "sessions", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def test_viz_plan_subparser_registered():
	"""viz plan subparser should be registered."""
	with patch("sys.argv", ["claude-orchestrator", "viz", "plan", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def test_viz_dashboard_subparser_registered():
	"""viz dashboard subparser should be registered."""
	with patch("sys.argv", ["claude-orchestrator", "viz", "dashboard", "--help"]):
		try:
			main()
		except SystemExit as e:
			assert e.code == 0


def _make_args(**kwargs) -> argparse.Namespace:
	"""Create an argparse Namespace with defaults."""
	defaults = {
		"viz_target": None,
		"name": None,
		"timeline": False,
		"since": None,
		"limit": 50,
		"session_id": None,
		"plan_id": None,
		"summary": False,
	}
	defaults.update(kwargs)
	return argparse.Namespace(**defaults)


def _run_viz(tmp_path: Path, **kwargs):
	"""Run cmd_viz with a temp DB so it doesn't touch real data."""
	from claude_orchestrator.instrumentation import ToolCallStore
	store = ToolCallStore(str(tmp_path / "test.db"))
	args = _make_args(**kwargs)

	# Patch ToolCallStore constructor to return our temp store
	with patch("claude_orchestrator.instrumentation.ToolCallStore", return_value=store):
		cmd_viz(args)


def test_cmd_viz_tools_stats(tmp_path: Path):
	"""viz tools should render stats without crashing on empty store."""
	_run_viz(tmp_path, viz_target="tools")


def test_cmd_viz_tools_timeline(tmp_path: Path):
	"""viz tools --timeline should render without crashing."""
	_run_viz(tmp_path, viz_target="tools", timeline=True)


def test_cmd_viz_tools_name(tmp_path: Path):
	"""viz tools --name should render without crashing."""
	_run_viz(tmp_path, viz_target="tools", name="get_plan")


def test_cmd_viz_sessions_list(tmp_path: Path):
	"""viz sessions should render without crashing."""
	_run_viz(tmp_path, viz_target="sessions")


def test_cmd_viz_sessions_detail(tmp_path: Path):
	"""viz sessions <id> should render without crashing."""
	_run_viz(tmp_path, viz_target="sessions", session_id="nonexistent")


def test_cmd_viz_dashboard(tmp_path: Path):
	"""viz dashboard should render without crashing."""
	with patch("claude_orchestrator.cli._load_plan", return_value=None):
		with patch("asyncio.run", return_value=None):
			_run_viz(tmp_path, viz_target="dashboard")


def test_cmd_viz_plan_no_plan(tmp_path: Path):
	"""viz plan should handle no plan gracefully."""
	with patch("asyncio.run", return_value=None):
		_run_viz(tmp_path, viz_target="plan")


def test_cmd_viz_no_target(tmp_path: Path):
	"""viz with no target should exit with code 1."""
	try:
		_run_viz(tmp_path, viz_target=None)
		assert False, "Should have called sys.exit"
	except SystemExit as e:
		assert e.code == 1
