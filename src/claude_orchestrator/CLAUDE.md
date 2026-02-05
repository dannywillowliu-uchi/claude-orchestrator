# claude-orchestrator - Claude Code Project Instructions

This file configures Claude Code to use the orchestrator's MCP tools.

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

## Project Memory

Update the project CLAUDE.md automatically:
- After each phase completion: Update Implementation Status section
- On significant architectural decisions: Append to Decisions Log
- When user says "avoid X" or similar: Append to Gotchas section
- After discovering issues: Append to Gotchas section

Use `log_project_decision`, `log_project_gotcha`, and `log_global_learning` tools to persist context across sessions.

## Available MCP Tools

- `health_check` -- Server health status
- `init_project_workflow` -- Create .claude-project/ workflow structure
- `workflow_progress` -- Update phase progress
- `check_tools` -- Verify tool availability before a phase
- `run_verification` -- Pre-commit verification gate (pytest, ruff, mypy, bandit)
- `update_project_status` -- Update CLAUDE.md implementation status
- `log_project_decision` -- Log decisions to CLAUDE.md
- `log_project_gotcha` -- Log gotchas to CLAUDE.md
- `log_global_learning` -- Log cross-project learnings
- `find_project` -- Find project by name/alias
- `list_my_projects` -- List all projects
