"""Tests for the CLI install command."""

from pathlib import Path

from claude_orchestrator.cli import _install_protocol


def test_install_adds_protocol(tmp_path: Path):
	"""install should create CLAUDE.md with protocol when file doesn't exist."""
	claude_md = tmp_path / "CLAUDE.md"
	_install_protocol(claude_md, force=False)

	assert claude_md.exists()
	content = claude_md.read_text(encoding="utf-8")
	assert "## Workflow Protocol" in content
	assert "### Session Start" in content


def test_install_replaces_existing_protocol(tmp_path: Path):
	"""install --force should replace existing Workflow Protocol section."""
	claude_md = tmp_path / "CLAUDE.md"
	claude_md.write_text(
		"# My Config\n\nSome stuff.\n\n## Workflow Protocol\n\nOld content here.\n\n## Other Section\n\nKeep this.\n",
		encoding="utf-8",
	)

	_install_protocol(claude_md, force=True)

	content = claude_md.read_text(encoding="utf-8")
	assert "# My Config" in content
	assert "## Other Section" in content
	assert "Keep this." in content
	assert "Old content here." not in content
	assert "### Session Start" in content


def test_install_preserves_other_sections(tmp_path: Path):
	"""install should append protocol without touching other sections."""
	claude_md = tmp_path / "CLAUDE.md"
	original = "# My Config\n\nSome custom content.\n\n## Custom Section\n\nImportant stuff.\n"
	claude_md.write_text(original, encoding="utf-8")

	_install_protocol(claude_md, force=False)

	content = claude_md.read_text(encoding="utf-8")
	assert "# My Config" in content
	assert "Some custom content." in content
	assert "## Custom Section" in content
	assert "Important stuff." in content
	assert "## Workflow Protocol" in content


def test_install_skips_existing_without_force(tmp_path: Path, capsys):
	"""install without --force should skip if protocol already exists."""
	claude_md = tmp_path / "CLAUDE.md"
	claude_md.write_text("## Workflow Protocol\n\nExisting.\n", encoding="utf-8")

	_install_protocol(claude_md, force=False)

	content = claude_md.read_text(encoding="utf-8")
	assert content == "## Workflow Protocol\n\nExisting.\n"
	captured = capsys.readouterr()
	assert "already exists" in captured.out
