# claude-orchestrator - Claude Code Project Instructions

This file configures Claude Code to use the orchestrator's MCP tools effectively. It is loaded automatically when working in this project or any project where the orchestrator is available.

## Workflow

- Default to Plan mode for non-trivial tasks
- Phase large tasks into subtasks with commits at each phase
- Ask thorough questions during planning - build comprehensive one-shot plans
- Do NOT extrapolate or assume - ask until requirements are clear

## Verification Requirements

Before ANY commit, run the full verification suite automatically:
- Unit tests (pytest, jest, etc.)
- Linter (ruff)
- Type checker (mypy)
- Security scanner (bandit, npm audit)
- Dependency health check

Block the commit if any check fails. Use the `run_verification` tool to execute the gate.

## Telegram Communication (MCP Tools)

When working on tasks, use MCP tools to communicate with the user via Telegram:

### Notifications
- Use `telegram_notify` for status updates
- Include project name in all messages
- Use appropriate level (info/warning/error/success)

### Questions (Planning)
- Use `telegram_ask` for multiple choice questions
- Use `telegram_ask_freeform` for open-ended questions
- Number questions hierarchically when planning: Q1, Q1.1, Q1.2, Q2, etc.
- Always provide context for why you're asking
- Batch related questions when possible

### Phase Updates
- Call `telegram_phase_update` after each phase completion
- Include test results (passed/failed/skipped counts)
- List any concerns or issues encountered
- Describe what's coming in the next phase

### Approvals
- Use `telegram_request_approval` for destructive/irreversible actions
- Clearly state consequences
- Note if action is reversible

### Escalations
- After 5 failed attempts, use `telegram_escalate`
- Provide full context and what you tried
- Suggest possible solutions

### Multi-Project
- Always include project name in tool calls
- Messages will be prefixed with [project-name]

## Autonomy Boundaries

- Default iteration limit: 5 attempts on a failing approach, then escalate via Telegram
- Phase completion: Git commit at each phase
- Stop for errors that truly require human judgment (not solvable via reasoning)

## Project Memory

Update the project CLAUDE.md automatically:
- After each phase completion: Update Implementation Status section
- On significant architectural decisions: Append to Decisions Log
- When user says "avoid X" or similar: Append to Gotchas section
- After discovering issues: Append to Gotchas section

Use `log_project_decision`, `log_project_gotcha`, and `log_global_learning` tools to persist context across sessions.

## Planning Workflow

1. Use `start_planning_session` to begin structured Q&A
2. Gather requirements via `telegram_ask` / `telegram_ask_freeform`
3. Create a phased plan with `create_plan` and `add_phase_to_plan`
4. Get approval with `telegram_request_approval` before implementation
5. Execute phase-by-phase, calling `telegram_phase_update` after each
6. Run `run_verification` before every commit
