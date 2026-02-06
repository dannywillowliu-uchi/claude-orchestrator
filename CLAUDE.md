# claude-orchestrator - Claude Code Project Instructions

Lightweight workflow system for Claude Code with 11 MCP tools. Supports `/playground` skill for visual exploration during discovery, planning, and verification phases.

## Workflow

- Default to Plan mode for non-trivial tasks
- Phase large tasks into subtasks with commits at each phase
- Ask thorough questions during planning
- Do NOT extrapolate or assume - ask until requirements are clear

## Verification Requirements

Before ANY commit, run the full verification suite automatically:
- Unit tests (pytest)
- Linter (ruff)
- Type checker (mypy)
- Security scanner (bandit)

Block the commit if any check fails. Use the `run_verification` tool to execute the gate.

## Available MCP Tools (11)

### Workflow
- `init_project_workflow` -- Create .claude-project/ workflow structure
- `workflow_progress` -- Update phase progress in progress.md
- `check_tools` -- Verify tool availability before a phase

### Verification
- `run_verification` -- Pre-commit gate (pytest, ruff, mypy, bandit)

### Memory
- `update_project_status` -- Update CLAUDE.md implementation status
- `log_project_decision` -- Log decisions to CLAUDE.md
- `log_project_gotcha` -- Log gotchas to CLAUDE.md
- `log_global_learning` -- Log cross-project learnings

### Context
- `health_check` -- Server health status
- `find_project` -- Find project by name/alias
- `list_my_projects` -- List all projects

## Project Memory

Update the project CLAUDE.md automatically:
- After each phase completion: Update Implementation Status section
- On significant architectural decisions: Append to Decisions Log
- When user says "avoid X" or similar: Append to Gotchas section
- After discovering issues: Append to Gotchas section

## Agent Teams (Experimental)

The workflow protocol supports Claude Code's native agent teams for:
- **Team research**: 3+ topics explored in parallel with debate between researchers
- **Team-based verification**: Multi-perspective code review with consensus scoring

Teams are optional and additive. The protocol falls back to subagents when teams are unavailable. Enable via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (set automatically by `claude-orchestrator install`).

Custom team agents: `research-lead`, `review-lead` (coordinate teams); `researcher`, `code-reviewer` (team-aware teammates).

## Autonomy Boundaries

- Default iteration limit: 5 attempts on a failing approach, then escalate
- Phase completion: Git commit at each phase
- Stop for errors that truly require human judgment
