# Task Automation MCP - Orchestrator

A sophisticated orchestration system for Claude Code that enables autonomous multi-step task execution with human oversight.

## The Problem

Claude Code excels at single tasks but struggles with complex multi-step projects:

- **Context Loss**: Information scattered across conversations
- **No Progress Tracking**: Can't resume failed tasks
- **Self-Verification**: AI marking its own homework doesn't work
- **Permission Chaos**: Every operation needs approval, causing friction

**Solution**: 90% autonomous execution, 10% human guidance at critical decision points.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                            │
│                                                              │
│   ┌──────────┐    ┌───────────┐    ┌────────────┐          │
│   │ PLANNER  │ -> │ DELEGATOR │ -> │ SUPERVISOR │          │
│   │          │    │           │    │            │          │
│   │ Q&A ->   │    │ Break     │    │ Monitor    │          │
│   │ Plan     │    │ tasks,    │    │ progress,  │          │
│   │          │    │ lock      │    │ checkpoint │          │
│   │          │    │ files     │    │ retry      │          │
│   └──────────┘    └───────────┘    └────────────┘          │
│                                           │                 │
│                                           v                 │
│                                    ┌────────────┐          │
│                                    │  VERIFIER  │          │
│                                    │            │          │
│                                    │ pytest     │          │
│                                    │ ruff, mypy │          │
│                                    │ bandit     │          │
│                                    └────────────┘          │
│                                                              │
│   SUPPORT: Context Builder | Plan Store | Knowledge Base    │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### Planner

Interactive Q&A sessions that gather requirements before any code is written.

```python
session = await planner.start_planning_session(
    project="my-app",
    goal="Add user authentication"
)
# Asks 10-15 questions about requirements, constraints, success criteria
# Generates comprehensive plan with phases and tasks
plan_id = await planner.approve_plan(session.id)
```

**Phases**: GATHERING_REQUIREMENTS -> RESEARCHING -> DESIGNING -> REVIEWING -> APPROVED

### Context Builder

Assembles relevant context for subagents while staying under token budget.

- Filters relevant architectural decisions
- Includes related documentation
- Summarizes prior work history
- Enforces 150K token budget

```python
context = context_builder.build_context(
    task=task,
    plan=plan,
    history=prior_work,
    docs=relevant_docs
)
# Returns SubagentContext with estimated_tokens
```

### Delegator

Breaks tasks into subagent-sized chunks with resource locking.

```python
result = await delegator.delegate_task(
    task=task,
    plan=plan,
    phase=phase
)
# Locks files: src/auth.py, tests/test_auth.py
# Creates DelegatedTask record
# Status: PENDING -> DELEGATED -> IN_PROGRESS -> COMPLETED
```

**Key Feature**: File locking prevents race conditions when multiple subagents work simultaneously.

### Supervisor

Monitors subagent progress with checkpoints and smart approval routing.

```python
await supervisor.start_supervision(task_id, session_id)
# Monitors every 60 seconds
# Saves checkpoints every 2 hours
# Auto-approves: read, test, lint, grep
# Escalates: delete, install, curl, fetch
# Retries up to 5x, then escalates to user
```

### Verifier

Independent quality gate - tasks cannot self-verify.

```python
result = await verifier.verify(
    checks=["pytest", "ruff", "mypy", "bandit"],
    files_changed=["src/auth.py"]
)
# All checks must pass before task marked complete
```

| Check | Purpose |
|-------|---------|
| pytest | Unit tests pass |
| ruff | Code style/linting |
| mypy | Type checking |
| bandit | Security vulnerabilities |

## Workflow Example

```
USER: "Add authentication to my trading bot"

1. PLANNING
   Planner: "What auth method?" -> "OAuth2"
   Planner: "Session storage?" -> "Redis"
   Planner: "Success criteria?" -> "All endpoints protected"
   -> Generates: 3 phases, 8 tasks

2. DELEGATION
   Task 1: "Set up OAuth2 client"
   -> Locks: src/auth/oauth.py
   -> Builds context with relevant decisions
   -> Creates DelegatedTask

3. SUPERVISION
   -> Executes via Claude CLI
   -> Monitors progress
   -> Auto-approves file reads
   -> Escalates pip install requests

4. VERIFICATION
   -> pytest: 12 tests pass
   -> ruff: no issues
   -> mypy: types valid
   -> bandit: no vulnerabilities
   -> TASK COMPLETE

5. NEXT TASK...
```

## Installation

```bash
git clone https://github.com/dannywillowliu-uchi/task-automation-mcp
cd task-automation-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Create `.secrets.json` in your project root:

```json
{
  "keys": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

## Usage

### As MCP Server

```json
// claude_desktop_config.json
{
  "mcpServers": {
    "task-automation": {
      "command": "python",
      "args": ["-m", "claude_orchestrator.server"],
      "cwd": "/path/to/task-automation-mcp"
    }
  }
}
```

### Programmatic

```python
from claude_orchestrator.orchestrator.planner import Planner
from claude_orchestrator.orchestrator.delegator import TaskDelegator
from claude_orchestrator.orchestrator.supervisor import Supervisor
from claude_orchestrator.orchestrator.verifier import Verifier

# Initialize
planner = Planner()
delegator = TaskDelegator()
supervisor = Supervisor(delegator=delegator)
verifier = Verifier(project_path="./my-project")

# Plan
session = await planner.start_planning_session(
    project="my-project",
    goal="Add feature X"
)

# ... answer questions ...

plan_id = await planner.approve_plan(session.id)

# Execute
for phase in plan.phases:
    for task in phase.tasks:
        result = await delegator.delegate_task(task, plan, phase)
        await supervisor.start_supervision(task.id, f"session-{task.id}")
        # ... execute task ...
        verification = await verifier.verify()
        if verification.passed:
            await delegator.mark_completed(task.id, result)
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Per-task file locking | Prevents race conditions |
| Independent verification | Self-verification unreliable |
| 150K token budget | Leave room for response |
| Max 3 concurrent sessions | More causes chaos |
| 2-hour checkpoints | Balance recovery vs noise |
| Auto-approve safe ops | Reduce friction for reads |

## Project Structure

```
src/claude_orchestrator/
├── server.py              # MCP server (123 tools)
├── orchestrator/
│   ├── planner.py         # Q&A -> Plans
│   ├── context_builder.py # Token budgeting
│   ├── delegator.py       # Task breakdown
│   ├── supervisor.py      # Progress monitoring
│   └── verifier.py        # Quality gate
├── plans/
│   ├── models.py          # Pydantic models
│   └── store.py           # SQLite storage
├── knowledge/
│   ├── crawler.py         # Doc indexing
│   └── retriever.py       # Semantic search
└── skills/
    └── loader.py          # SKILL.md discovery
```

## Success Metrics

- **Task Success Rate**: >90% simple, >75% complex
- **Context Accuracy**: >95% project resolution
- **Test Coverage**: >80% new code
- **Unhandled Errors**: <5% of executions

## License

MIT
