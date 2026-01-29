# Architecture & Best Practices

A living guide to how claude-orchestrator works and how to use it well.

**Last updated**: 2026-01-28

---

## How It Works

claude-orchestrator is an MCP server that gives Claude Code structured tools for planning, delegating, and verifying work. It runs as a sidecar process: Claude Code talks to it via MCP tool calls, and it talks back to Claude Code via the CLI bridge.

### The Four Stages

Every non-trivial task flows through four stages:

```
1. PLAN  -->  2. DELEGATE  -->  3. SUPERVISE  -->  4. VERIFY
```

Each stage is handled by a separate module. They are loosely coupled -- you can use planning without delegation, or verification without supervision.

---

## Stage 1: Planning

**Module**: `orchestrator/planner.py`
**Tools**: `start_planning_session`, `answer_planning_question`, `approve_planning_session`

The planner conducts an interactive Q&A to build a comprehensive implementation plan before any code is written. The philosophy: spend 90% of the effort thinking, 10% implementing.

### How it works

1. `start_planning_session("my-project", "Add user auth")` creates a session with initial questions
2. Questions are grouped by category: requirements, architecture, verification, scope
3. Vague answers ("not sure") trigger follow-up questions
4. Once all questions are answered, a draft plan is generated
5. `approve_planning_session(session_id)` saves the plan with version tracking

### The Plan structure

```
Plan
├── overview (goal, success criteria, constraints)
├── phases[]
│   ├── name ("Phase 1: Core auth")
│   └── tasks[]
│       ├── description
│       ├── files to modify
│       ├── verification steps
│       └── status (pending → in_progress → completed)
├── decisions[] (what was decided, why, what was rejected)
└── version (increments on every change)
```

Plans are stored in SQLite with full version history. You can roll back or compare versions.

### Best practices

- **Answer planning questions thoroughly.** The planner builds task context from your answers. Shallow answers = shallow context = worse subagent output.
- **Use `add_decision_to_plan` when you make architectural choices.** These get injected into subagent context so they don't contradict your decisions.
- **Break work into phases of 3-5 tasks.** Smaller phases mean more frequent checkpoints and easier recovery.

---

## Stage 2: Delegation

**Module**: `orchestrator/delegator.py`, `orchestrator/context_builder.py`
**Data**: `DelegatedTask`, `SubagentContext`

The delegator takes a plan's tasks and prepares them for execution by subagent sessions.

### How it works

1. For each task, the `ContextBuilder` assembles:
   - Task description and files
   - Relevant decisions from the plan (keyword-matched)
   - Prior work summary from completed tasks
   - Documentation snippets (if knowledge base is indexed)
   - Constraints and verification requirements
2. The context is token-budgeted (default 150K tokens) -- if it's too large, docs are trimmed first, then history
3. Resources (files) are locked to prevent two subagents editing the same file
4. A `DelegatedTask` record tracks status: `PENDING → DELEGATED → IN_PROGRESS → COMPLETED/FAILED`

### Resource locking

When task A locks `src/auth.py`, task B cannot be delegated if it also needs `src/auth.py`. This prevents merge conflicts in parallel execution. Locks are released when a task completes or fails.

### Best practices

- **List files explicitly in task definitions.** The delegator uses file lists for resource locking and context prioritization.
- **Don't run more than 3 subagents concurrently.** The session manager enforces this, but plan accordingly.
- **Order tasks within a phase by dependency.** Independent tasks can run in parallel; dependent ones should be sequential.

---

## Stage 3: Supervision

**Module**: `orchestrator/supervisor.py`
**Data**: `SupervisionState`, `Checkpoint`

The supervisor monitors running subagent sessions and handles failures.

### How it works

1. `start_supervision(task_id, session_id)` begins a background monitoring loop
2. Every 60 seconds, the monitor checks session health
3. Every 2 hours, a checkpoint is saved (task state, files modified, output summary)
4. Permission requests are evaluated:
   - **Auto-approved**: read, list, search, grep, test, lint, type check
   - **Auto-denied**: delete, remove, curl, wget, install
   - **Escalated**: anything with a callback or unknown operations
5. On failure, the supervisor retries up to 5 times (configurable), then escalates

### Escalation

When a task hits max retries, the supervisor:
- Sets status to `ESCALATED`
- Builds a context string with: task ID, retry count, last checkpoint, files modified, error message
- Calls the `on_escalate` callback (which typically sends a Telegram notification)

### Best practices

- **Set `max_retries` based on task risk.** Low-risk refactoring: 5 retries. Database migrations: 1-2 retries.
- **Use checkpoints for long-running tasks.** If a session crashes at hour 3, the checkpoint at hour 2 tells you exactly what was done.
- **Don't skip the supervisor for important tasks.** Even if you trust the subagent, the checkpoint history is valuable for debugging.

---

## Stage 4: Verification

**Module**: `orchestrator/verifier.py`
**Tools**: `run_verification`

The verifier runs an independent quality gate before any commit.

### What it runs

| Check | Tool | What it catches |
|-------|------|-----------------|
| Tests | pytest | Regressions, broken logic |
| Lint | ruff | Style violations, unused imports |
| Types | mypy | Type errors, missing annotations |
| Security | bandit | SQL injection, hardcoded secrets, eval() |

### How it works

1. `run_verification(project_path, checks, files_changed)` runs all (or specific) checks
2. Each check returns `CheckResult(passed, output, details)`
3. The overall `VerificationResult` is `passed` only if ALL checks pass
4. If `files_changed` is provided, some checks can scope to those files

### Best practices

- **Never bypass verification.** The whole point is that subagents can't ship broken code.
- **Add custom verification steps for domain-specific requirements.** The verifier supports `run_custom_verification(command, description)`.
- **Fix verification failures before retrying.** If a subagent breaks tests, fix the tests or the code -- don't just retry and hope.

---

## The CLI Bridge

**Module**: `claude_cli_bridge.py`

This is the lowest-level component: it executes `claude --print` as a subprocess and captures the output.

### How it works

```
ClaudeCLIBridge
    ├── project_path   (working directory for Claude CLI)
    ├── hooks_config   (permission profile: read_only, code_edit, test_run, full_access)
    ├── send_prompt()  (runs claude --print with the prompt)
    └── output_schema  (optional: request JSON output + validate)
```

Each `send_prompt()` call is an independent subprocess. There is no persistent TUI session -- `--print` mode gives clean stdin/stdout.

### Permission model

The bridge uses **hooks profiles** to control what a subagent can do:

| Profile | Tools allowed | Use case |
|---------|--------------|----------|
| `read_only` | Read, Glob, Grep, WebSearch, WebFetch | Research, code review |
| `code_edit` | Read, Glob, Grep, Edit, Write, WebSearch, WebFetch | Implementation |
| `test_run` | Read, Glob, Grep, Bash | Running tests, linting |
| `full_access` | Everything (--dangerously-skip-permissions) | Trusted tasks |

The supervisor selects profiles automatically based on task description keywords:
- "read", "search", "explore", "review" → `read_only`
- "implement", "fix", "refactor", "write" → `code_edit`
- "test", "verify", "lint" → `test_run`
- "delete", "deploy", "install" → `full_access`

### Structured output

Pass `output_schema` to `send_prompt()` to request JSON output:

```python
from claude_orchestrator.schemas import TASK_RESULT_SCHEMA

response = await bridge.send_prompt(
    "Implement the login feature",
    output_schema=TASK_RESULT_SCHEMA,
)
# Bridge adds --output-format json to CLI args
# Validates response against schema (logs warning on mismatch, still returns raw)
```

Predefined schemas: `CODE_REVIEW_SCHEMA`, `TASK_RESULT_SCHEMA`, `PLAN_SCHEMA`.

### Best practices

- **Use the narrowest hooks profile that works.** `read_only` for research, `code_edit` for implementation. Only use `full_access` when you genuinely need Bash and network access.
- **Set reasonable timeouts.** Default is 300 seconds. Bump to 600+ for large codebases. Don't set to infinity.
- **Don't bypass the bridge for subagent work.** Going around it means no hooks, no schema validation, no output capture.

---

## Session Management

**Module**: `session_manager.py`
**Tools**: `start_claude_session`, `send_to_claude_session`, `get_session_output`

Sessions are persistent Claude CLI processes that can receive multiple prompts.

### Limits

- **Max 3 concurrent sessions** (enforced by session manager)
- **Output history**: last 500 lines per session
- **Health check**: every 5 seconds in background
- **State persistence**: saved to `data/sessions/session_state.json` for crash recovery

### Session states

```
STARTING → READY → BUSY → READY (loop)
                 ↘ WAITING_INPUT → READY (after approval)
                 ↘ FAILED / STOPPED
```

### Best practices

- **Reuse sessions for related tasks in the same project.** Starting a new session has overhead.
- **Check session health before sending prompts.** Use `list_claude_sessions()` to verify state is `READY`.
- **Stop sessions when done.** They consume resources.

---

## Batch Processing

**Module**: `orchestrator/batch.py`

For processing many similar items concurrently (e.g., migrate 50 files, fix lint errors across a codebase).

### How it works

```python
processor = BatchProcessor(max_concurrency=5)
summary = await processor.execute(
    items=[BatchItem(id="1", data=file) for file in files],
    handler=process_one_file,
    on_item_complete=log_progress,
)
# summary.succeeded, summary.failed, summary.success_rate
```

- Uses `asyncio.Semaphore` to cap concurrency
- Individual item failures don't abort the batch
- `on_item_complete` callback fires after each item (failures in the callback don't affect the batch)

### Best practices

- **Set `max_concurrency` to match your session limit (3).** No point fanning out to 10 if sessions cap at 3.
- **Make items idempotent.** If an item fails and gets retried, it should produce the same result.
- **Use `BatchSummary.success_rate` to decide whether to proceed.** If 80% failed, something systemic is wrong.

---

## Knowledge Base

**Modules**: `knowledge/crawler.py`, `knowledge/indexer.py`, `knowledge/retriever.py`
**CLI**: `claude-orchestrator seed-docs`

### How it works

1. **Crawl**: `DocCrawler` fetches HTML from doc sites, extracts content, converts to markdown
2. **Index**: `DocIndexer` chunks markdown into ~500-token pieces, generates embeddings with `all-MiniLM-L6-v2`, stores in LanceDB
3. **Search**: `search_docs("how to use tools")` performs semantic search over indexed chunks

### Seeding

```bash
# Seed all default sources
claude-orchestrator seed-docs

# Seed a single source
claude-orchestrator seed-docs --source anthropic-docs
```

Default sources: `anthropic-docs` (100 pages), `mcp-docs` (50 pages).

### Best practices

- **Seed the knowledge base before starting implementation work.** Claude searches it during context building.
- **Index project-specific docs too.** Use the `index_docs` MCP tool for internal wikis or READMEs.
- **Re-index after major doc updates.** The indexer tracks file modification times but doesn't auto-re-crawl.

---

## Codebase Onboarding

**Module**: `orchestrator/onboarding.py`

Analyzes a project directory to detect language, entry points, key files, and capabilities.

### What it detects

| Detection | How |
|-----------|-----|
| Language | File extensions + config files (pyproject.toml → Python, package.json → JS, etc.) |
| Entry points | Looks for main.py, index.js, app.py, server.py, etc. |
| Key files | README, CLAUDE.md, Dockerfile, CI configs, package manifests |
| Tests | `tests/` directory, `test_*.py` files, `*.test.js` files |
| CI | `.github/workflows/`, `.gitlab-ci.yml`, `.circleci/`, `Jenkinsfile` |
| Docker | `Dockerfile`, `docker-compose.yml` |

### Current limitations

- `generate_ast_summary()` and `generate_onboarding_prompt()` are not yet implemented (raise `NotImplementedError`)
- Detection is heuristic-based (filesystem patterns), not AST-based
- No dependency graph generation yet

---

## End-to-End Example

Here's the full flow for a multi-phase feature implementation:

```
1. User asks Claude: "Add OAuth login to my app"

2. PLAN
   Claude calls start_planning_session("my-app", "Add OAuth login")
   → Planner asks: "Which OAuth providers? What token storage? Session length?"
   → User answers questions
   → Planner generates a 3-phase plan
   → User approves

3. DELEGATE (Phase 1)
   Delegator builds context for task 1.1: "Add OAuth callback endpoint"
   → Context includes: task description, plan decisions, relevant docs
   → Resources locked: src/auth/oauth.py, src/routes/callback.py
   → DelegatedTask created with status DELEGATED

4. SUPERVISE
   Supervisor starts monitoring the subagent session
   → Hooks profile: code_edit (Edit, Write, Read, Glob, Grep)
   → Session sends prompts via CLI bridge
   → Supervisor auto-approves file reads, logs file writes
   → Checkpoint saved at 2-hour mark

5. VERIFY
   Subagent signals task complete
   → Verifier runs: pytest (pass), ruff (pass), mypy (1 error), bandit (pass)
   → mypy failure → subagent fixes the type error → re-verify → all pass
   → Resource locks released
   → Task marked COMPLETED

6. Repeat for Phase 2, Phase 3...

7. All phases complete → Plan status = COMPLETED
```

---

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|------------|
| Skip planning for "simple" tasks | Simple tasks often have hidden complexity | At minimum, create a plan with 1 phase |
| Use `full_access` by default | Defeats the permission model | Let the supervisor select the profile |
| Run 3 subagents on unrelated projects | Context switching kills quality | Focus subagents on one project at a time |
| Ignore verification failures | They exist for a reason | Fix the root cause, don't retry blindly |
| Put everything in one phase | No checkpoints, no recovery points | 3-5 tasks per phase maximum |
| Skip the knowledge base | Claude hallucinates API details | Seed docs before implementation |

---

## Module Map

```
src/claude_orchestrator/
├── cli.py                    # CLI: setup, serve, doctor, seed-docs
├── server.py                 # MCP server init
├── config.py                 # Platform-aware config paths
├── claude_cli_bridge.py      # Subprocess bridge to claude --print
├── hooks.py                  # Permission profiles for subagents
├── schemas.py                # Structured output validation
├── session_manager.py        # Multi-session lifecycle
├── orchestrator/
│   ├── planner.py            # Interactive planning Q&A
│   ├── delegator.py          # Task breakdown + resource locking
│   ├── context_builder.py    # Token-budgeted context assembly
│   ├── supervisor.py         # Monitoring + checkpoints + escalation
│   ├── verifier.py           # Quality gate (pytest/ruff/mypy/bandit)
│   ├── batch.py              # Fan-out/fan-in batch processing
│   └── onboarding.py         # Codebase analysis heuristics
├── knowledge/
│   ├── crawler.py            # Async web doc crawler
│   ├── indexer.py            # LanceDB vector indexing
│   └── retriever.py          # Semantic search
├── plans/
│   ├── models.py             # Pydantic plan/phase/task schemas
│   └── store.py              # SQLite plan persistence
├── skills/
│   ├── loader.py             # SKILL.md discovery
│   └── executor.py           # Skill execution
└── tools/                    # MCP tool definitions (one file per category)
    ├── core.py, plans.py, orchestrator.py, memory.py,
    ├── context.py, secrets.py, sessions.py, skills.py,
    ├── github.py, knowledge.py, visual.py
    └── __init__.py           # register_all_tools dispatcher
```

---

## Updating This Document

This is a living document. Update it when:

- A new module is added
- A workflow changes significantly
- A best practice is discovered or invalidated
- A new anti-pattern is encountered

Keep sections focused. If a section grows past ~40 lines, split it.
