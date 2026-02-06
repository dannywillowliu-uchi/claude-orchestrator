# claude-orchestrator

A lightweight workflow system for Claude Code that adds structured project execution through a four-document lifecycle, verification gates, and persistent project memory.

## What It Does

Claude Code is powerful but has no built-in structure for multi-phase projects. **claude-orchestrator** adds:

- **Four-document workflow** -- Discovery, research, planning, and execution phases tracked in `.claude-project/` with progress persistence across sessions
- **Verification gates** -- pytest, ruff, mypy, and bandit run automatically before every commit. Failures are logged as gotchas in your project's CLAUDE.md
- **Persistent memory** -- Decisions, gotchas, and implementation status written to CLAUDE.md automatically. Cross-project learnings stored globally
- **Custom subagents** -- Researcher (Sonnet) and verifier (Haiku) agents for parallel research and fast checks
- **Agent teams** -- (Experimental) Team-based research and multi-perspective code review using Claude Code's native agent coordination

## Quick Start

```bash
# Install
pip install git+https://github.com/dannywillowliu-uchi/claude-orchestrator.git

# Install workflow protocol, agents, and hooks into Claude Code
claude-orchestrator install

# Add MCP server to Claude Code config (~/.claude.json)
# Under "mcpServers":
{
  "claude-orchestrator": {
    "type": "stdio",
    "command": "claude-orchestrator",
    "args": ["serve"]
  }
}
```

Restart Claude Code, then just run `claude` -- the workflow activates automatically for non-trivial tasks.

## The Four-Document Lifecycle

When you start a non-trivial task, the workflow creates `.claude-project/` with:

| Document | Purpose |
|----------|---------|
| `discover.md` | Problem statement, goals, constraints, Q&A log |
| `research/` | Subagent research findings per topic |
| `plan.md` | Phased plan with tasks, checkpoints, and verification criteria |
| `progress.md` | Current phase, active task, blocked state, commit history |

The protocol guides Claude through: Discovery -> Research -> Planning -> Execution, with verification gates at each commit.

## MCP Tools (11)

| Category | Tools |
|----------|-------|
| Core | `health_check` |
| Workflow | `init_project_workflow`, `workflow_progress`, `check_tools` |
| Verification | `run_verification` |
| Memory | `update_project_status`, `log_project_decision`, `log_project_gotcha`, `log_global_learning` |
| Context | `find_project`, `list_my_projects` |

## CLI Commands

```bash
claude-orchestrator serve     # Run MCP server (used by Claude Code)
claude-orchestrator install   # Install protocol, agents, and hooks
claude-orchestrator install --force  # Overwrite existing files
```

## Agent Teams (Experimental)

The workflow protocol supports Claude Code's native agent teams for richer multi-agent patterns:

- **Team research**: When 3+ research topics need parallel exploration with debate. A research lead coordinates researcher teammates who can challenge each other's findings.
- **Team-based verification**: Multi-perspective code review where reviewers independently analyze changes from security, architecture, and correctness angles. Findings are collated by consensus.

Teams are enabled automatically during `claude-orchestrator install` (sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in settings). To disable, remove the env var from `~/.claude/settings.json`.

The protocol gracefully falls back to individual subagents when teams are unavailable or when the task doesn't warrant the overhead.

## Playground Integration

The workflow protocol integrates with the `/playground` skill to generate interactive single-file HTML explorers at key phases:

| Template | Phase | Purpose |
|----------|-------|---------|
| `concept-map` | Discovery | Visually map problem domains and explore scope |
| `code-map` | Planning | Visualize architecture, data flow, and dependencies |
| `diff-review` | Verification | Line-by-line visual review for large changesets |

Playgrounds are optional -- the protocol suggests them when visual exploration adds value over plain text.

## Configuration

Config file location:
- **macOS**: `~/Library/Application Support/claude-orchestrator/config.toml`
- **Linux**: `~/.config/claude-orchestrator/config.toml`

```toml
projects_path = "~/my-projects"
```

Environment variable overrides:
- `CLAUDE_ORCHESTRATOR_CONFIG_DIR`
- `CLAUDE_ORCHESTRATOR_DATA_DIR`
- `CLAUDE_ORCHESTRATOR_PROJECTS_PATH`

## Development

```bash
git clone https://github.com/dannywillowliu-uchi/claude-orchestrator.git
cd claude-orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src/
```

## License

MIT
