# claude-orchestrator

An MCP server that turns Claude Code into a structured, autonomous-capable development workflow.

## Why This Exists

Claude Code is powerful, but out of the box it has no persistent memory between sessions, no structured planning, no verification gates, and no way to track decisions across a multi-phase project. This means you spend time re-explaining context, re-discovering gotchas, and manually checking that code quality holds up.

**claude-orchestrator** solves this by giving Claude Code a set of MCP tools for:

- **Structured planning** -- Interactive Q&A sessions that front-load 90% of the thinking before a single line of code is written. The result is a versioned, phased plan that Claude follows autonomously with minimal back-and-forth.
- **Persistent project memory** -- Decisions, gotchas, and implementation status are written to each project's CLAUDE.md automatically. Cross-project learnings survive across sessions in a global learnings file. Context is never lost.
- **Verification gates** -- Every commit candidate runs through pytest, ruff, mypy, and bandit automatically. Claude doesn't ship broken code because it literally can't bypass the gate.
- **Sub-agent delegation** -- Spawn and supervise additional Claude CLI sessions for parallel workstreams, with output capture and approval routing.
- **Knowledge indexing** -- Crawl and semantically index documentation (SDK docs, internal wikis) so Claude can search them during implementation instead of hallucinating.

The net effect: you describe what you want, approve a plan, and Claude executes it phase-by-phase with quality checks at every step -- closer to a junior developer than a chat autocomplete.

## Quick Start

```bash
pip install claude-orchestrator
claude-orchestrator setup
```

The setup wizard creates config directories, writes a default config, and offers to inject the MCP server entry into Claude Code and/or Claude Desktop.

## What You Get

### Core
- **Interactive planning sessions** with thorough Q&A before implementation
- **Verification gate** (pytest, ruff, mypy, bandit) to enforce quality
- **Plan management** with phases, tasks, and versioned history
- **Skills system** (SKILL.md discovery and execution)
- **Project memory** (CLAUDE.md management, decisions log, gotchas)
- **Global learnings** (cross-project patterns and preferences)
- **Secrets management** (local key storage)
- **Personal context** (project registry, coding preferences)

### Optional Modules
- **GitHub integration** (`PyGithub`) - repos, issues, PRs, notifications
- **Sub-agent sessions** (`pexpect`) - spawn and manage Claude CLI sessions
- **Visual testing** (`playwright`) - screenshots, element verification, page content
- **Knowledge base** (`lancedb`, `sentence-transformers`) - semantic doc search, crawling, indexing

## Manual Setup

If you prefer not to use the setup wizard:

1. Install:
   ```bash
   pip install claude-orchestrator          # core only
   pip install claude-orchestrator[all]     # all optional modules
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

## Tools

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
| GitHub | `get_github_repos`, `get_github_issues`, `create_github_issue`, `get_github_prs`, `get_github_notifications`, `search_github_repos`, `get_github_file`, `comment_on_github_issue`, `get_github_rate_limit`, `check_github_security`, `setup_github` |
| Sessions | `list_claude_sessions`, `start_claude_session`, `stop_claude_session`, `send_to_claude_session`, `get_session_output`, `approve_session_action` |
| Visual | `take_screenshot`, `take_element_screenshot`, `verify_element`, `get_page_content`, `list_screenshots`, `delete_screenshot` |
| Knowledge | `search_docs`, `get_doc`, `list_doc_sources`, `index_docs`, `crawl_and_index_docs` |

## Development

```bash
git clone <repo-url>
cd claude-orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,all]"
pytest
ruff check src/
```

## License

MIT
