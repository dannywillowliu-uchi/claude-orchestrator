# claude-orchestrator

MCP server for Claude Code: planning, verification, TDD, and progress tracking.

## Quick Start

```bash
pip install claude-orchestrator
claude-orchestrator setup
```

The setup wizard creates config directories, writes a default config, and offers to inject the MCP server entry into Claude Code and/or Claude Desktop.

## What You Get

- **Interactive planning sessions** with thorough Q&A before implementation
- **Verification gate** (pytest, ruff, mypy, bandit) to enforce quality
- **Plan management** with phases, tasks, and versioned history
- **Skills system** (SKILL.md discovery and execution)
- **Project memory** (CLAUDE.md management, decisions log, gotchas)
- **Global learnings** (cross-project patterns and preferences)
- **Secrets management** (local encrypted key storage)
- **Personal context** (project registry, coding preferences)

## Manual Setup

If you prefer not to use the setup wizard:

1. Install:
   ```bash
   pip install claude-orchestrator
   ```

2. Add to your Claude Code MCP config (`~/.claude/claude_code_config.json`):
   ```json
   {
     "mcpServers": {
       "claude-orchestrator": {
         "type": "stdio",
         "command": "claude-orchestrator",
         "args": ["serve"]
       }
     }
   }
   ```

3. Restart Claude Code.

## Configuration

Config file location:
- **macOS**: `~/Library/Application Support/claude-orchestrator/config.toml`
- **Linux**: `~/.config/claude-orchestrator/config.toml`

```toml
# Override default projects path
projects_path = "~/my-projects"
```

Environment variable overrides (`CLAUDE_ORCHESTRATOR_*`):
- `CLAUDE_ORCHESTRATOR_CONFIG_DIR`
- `CLAUDE_ORCHESTRATOR_DATA_DIR`
- `CLAUDE_ORCHESTRATOR_PROJECTS_PATH`

## CLI Commands

```bash
claude-orchestrator setup          # Interactive setup wizard
claude-orchestrator setup --check  # Verify current config
claude-orchestrator serve          # Run MCP server (used by Claude)
claude-orchestrator doctor         # Health check
```

## Tools (34)

| Category | Tools |
|----------|-------|
| Core | `health_check` |
| Planning Sessions | `start_planning_session`, `answer_planning_question`, `get_planning_session`, `approve_planning_session`, `list_planning_sessions` |
| Plans | `create_plan`, `get_plan`, `get_project_plan`, `add_phase_to_plan`, `update_task_status`, `add_decision_to_plan`, `list_plans`, `get_plan_history` |
| Verification | `run_verification` |
| Memory | `update_project_status`, `log_project_decision`, `log_project_gotcha`, `log_global_learning` |
| Context | `get_my_context`, `find_project`, `list_my_projects`, `update_context_notes` |
| Secrets | `get_secret`, `list_secrets`, `set_secret`, `deactivate_secret`, `activate_secret` |
| Skills | `list_skills`, `get_skill_details`, `create_skill_template`, `execute_skill`, `list_skill_executions` |

## Development

```bash
git clone https://github.com/dannywillowliu-uchi/claude-orchestrator
cd claude-orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src/
mypy src/
```

## License

MIT
