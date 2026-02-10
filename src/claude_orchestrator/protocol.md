## Workflow Protocol

This protocol governs how you approach non-trivial tasks. It activates when `.claude-project/` exists or when the task warrants structured execution.

### Session Start

1. Check if `.claude-project/` exists in the project root
2. If it exists, read `progress.md` to understand current state
3. If the task is trivial (single-file fix, typo, < 3 steps), skip the workflow
4. If the task is non-trivial, `.claude-project/` MUST be initialized via `init_project_workflow` before proceeding

### Tool Disclosure

At each phase transition, call `get_phase_tools(phase)` to see which tools are relevant. Focus on the returned tools and ignore others to reduce noise.

| Phase | Key Tools | Purpose |
|-------|-----------|---------|
| discovery | `init_project_workflow`, `find_project`, `list_my_projects` | Set up workflow, understand project context |
| research | `check_tools`, `workflow_progress` | Verify toolchain, track progress |
| planning | `check_tools`, `workflow_progress`, `log_project_decision` | Plan phases, log architectural decisions |
| execution | `run_verification`, `suggest_fixes`, `workflow_progress`, `update_project_status`, `log_*` | Build, verify, fix, commit, record learnings |
| verification | `run_verification`, `suggest_fixes`, `log_project_gotcha` | Pre-commit gate, classify and fix issues |

`health_check` and `get_phase_tools` are available in all phases.

### Team vs Subagent Decision

Before spawning agents for research or review, decide whether to use individual subagents or an agent team:

| Use Subagents | Use Teams |
|---------------|-----------|
| Focused task, only result matters | Multiple perspectives needed |
| Sequential dependency between steps | Independent parallel exploration |
| Token cost matters | Agents should debate or challenge findings |
| Simple research lookup (1-2 topics) | Research with competing hypotheses (3+ topics) |
| Single verification pass | Multi-reviewer code review |

**Rule of thumb**: If agents would benefit from talking to each other, use a team. If you just need results back, use a subagent.

> **Note**: Agent teams are experimental. The protocol gracefully falls back to subagents if teams are unavailable or disabled.

### Parallel Decomposition

When splitting work across subagents or team members, avoid two failure modes:

- **Serial collapse**: Running tasks sequentially when they have no dependencies. Symptoms: one agent blocks while another's output sits unused; total time equals sum of all tasks instead of the longest.
- **Spurious parallelism**: Running tasks in parallel when they share mutable state or have ordering constraints. Symptoms: merge conflicts, race conditions, agents overwriting each other's work.

**Critical path rule**: Total latency = orchestration overhead + duration of the slowest parallel branch. Parallelism only helps when branches are roughly equal in effort and truly independent.

**Guidelines:**
- NEVER parallelize fewer than 3 independent tasks (overhead outweighs benefit)
- Identify the dependency graph BEFORE spawning agents -- draw it out in the plan if complex
- Each parallel branch MUST have a clear output artifact (file, result, report) that the orchestrator collects
- If two branches need to read/write the same file, they are NOT independent -- serialize them
- After parallel branches complete, always synthesize results before proceeding

### Discovery Phase

When starting a new feature or significant change:

1. Open `.claude-project/discover.md`
2. Fill in Problem Statement, Goals, Non-Goals, and Constraints through Q&A with the user
3. For complex problem spaces, consider generating a concept-map playground (`/playground`) to visually map the domain, identify knowledge gaps, and explore scope before committing to goals
4. Record every question and answer in the Q&A Log section
5. Discovery is complete when: problem is well-defined, goals are measurable, constraints are documented, and user confirms understanding
6. Update progress: `workflow_progress(phase_completed="Discovery", phase_started="Research")`

### Research Phase

When the task requires understanding unfamiliar domains or APIs:

#### Option A: Subagent Research (default, 1-2 topics)

1. Identify 2-4 research subtopics from discovery
2. For each topic, spawn a Sonnet-tier subagent (Task tool with `model: "sonnet"`) with specific research questions
3. Each subagent produces a markdown file saved to `.claude-project/research/<topic>.md`
4. After all research completes, synthesize findings into a summary
5. Use a two-pass approach: raw findings first, then structured synthesis

#### Option B: Team Research (3+ topics OR debate improves quality)

1. Create team: `TeamCreate(team_name="{project}-research")`
2. Create tasks: one `TaskCreate` per research topic with detailed description
3. Spawn 2-3 researcher teammates (Task tool with `team_name` and `name` parameters, `subagent_type: "researcher"`)
4. Teammates self-claim tasks via `TaskUpdate`, research independently, and message findings to the lead via `SendMessage`
5. Lead monitors progress via `TaskList` and synthesizes findings after all tasks complete
6. Shutdown team: `SendMessage(type: "shutdown_request")` to each teammate, then `TeamDelete`
7. Save synthesized findings to `.claude-project/research/synthesis.md`

**When to choose Option B**: The research involves competing approaches (e.g., "Redis vs Memcached vs in-memory"), requires cross-referencing between topics, or benefits from researchers challenging each other's findings.

6. Skip this phase if the domain is well-understood and no external APIs are involved
7. Update progress: `workflow_progress(phase_completed="Research", phase_started="Planning")`

### Planning Phase

Synthesize discovery + research into an actionable plan:

1. Write `.claude-project/plan.md` with phases, tasks, and verification criteria
2. For architecture-heavy plans, consider generating a code-map playground (`/playground`) to visualize component relationships, data flow, and layer dependencies before finalizing the plan
3. Each phase MUST specify:
   - `checkpoint: true/false` (whether to pause for user review)
   - `tools_required: [list]` (verify with `check_tools` before starting)
   - `verification_criteria: [list]` (what must pass before phase is complete)
4. No execution proceeds without user approval of the plan
5. Use `EnterPlanMode` for complex plans requiring user sign-off
6. Update progress: `workflow_progress(phase_completed="Planning", phase_started="Phase 1 - <name>")`

### Execution Phase

For each phase in the plan:

1. Read `progress.md` to confirm current phase and any blocked state
2. Run `check_tools` for any phase-specific tool requirements
3. Implement tasks sequentially within the phase
4. **Oracle-based task partitioning**: For large implementation phases, write failing tests FIRST that define the expected behavior (the "oracle"). Then partition work into the smallest chunks where each chunk flips one or more tests from red to green. Verify incrementally after each chunk. This provides continuous progress signal and catches regressions early.
5. After all tasks in a phase are complete:
   a. `run_verification` MUST execute before any commit
   b. If verification fails, fix issues (up to 3 attempts), then start a fresh session
   c. If verification passes, commit the changes
   d. Update progress: `workflow_progress(phase_completed="Phase N", phase_started="Phase N+1", commit_hash="...")`
6. If the phase has `checkpoint: true`:
   a. Call `generate_review_artifact` with phase summary, verification results, decisions, and risks
   b. The review artifact is saved to `.claude-project/reviews/`
   c. Send the `telegram_summary` from the response via Telegram notification
   d. Stop and wait for user confirmation

### Verification Gate (MANDATORY before every commit)

`run_verification` MUST execute before any commit.

**Error tiers:**

| Tier | Examples | Action | Limit |
|------|----------|--------|-------|
| Critical | pytest failures, mypy type errors, bandit security findings | Fix immediately | 3 attempts, then block commit and escalate |
| Non-critical | ruff style warnings, minor formatting | Log as follow-up task | No block -- commit proceeds, fix in next phase |

**Self-correction flow:**

1. Run `run_verification` -- if all pass, commit and proceed
2. If failures, call `suggest_fixes` with the verification JSON output
3. `suggest_fixes` classifies each issue and returns fix tasks:
   - **Critical fix tasks** (`should_block: true`): fix immediately, re-verify, up to 3 attempts
   - **Non-critical fix tasks** (`should_block: false`): log as follow-up, commit proceeds
4. **Circuit breaker**: if `circuit_breaker_triggered: true` (>5 non-critical issues), escalate -- do NOT attempt mass fixes
5. **Convergence tracking**: After 2+ fix attempts, call `track_convergence` with the array of previous `suggest_fixes` outputs. Follow its recommendation: `continue_fixing` (errors decreasing), `accept_and_commit` (stable non-critical only), `escalate` (errors increasing or stable-but-critical)

**Escalation criteria for blocking issues:**
- Error requires information not available in context (missing API keys, unclear requirements)
- Fix attempt changes the semantics of the original task
- Same error recurs after 3 fix attempts with different strategies
- Error is in code the current phase did not modify
- Circuit breaker triggered (>5 non-critical issues in one verification)

When blocked: update `progress.md` Blocked field with specific reason, notify via Telegram, and stop.

Use team-based verification for high-stakes changes (see below).

### Team-Based Verification

For high-stakes changes (security-sensitive code, architecture shifts, multi-file refactors):

1. Create team: `TeamCreate(team_name="{project}-review")`
2. Create review tasks from different angles:
   - **Security**: Check for vulnerabilities, injection risks, auth issues
   - **Architecture**: Evaluate design patterns, coupling, extensibility
   - **Correctness**: Verify logic, edge cases, error handling
3. Spawn 2-3 reviewer teammates (Task tool with `team_name`, `subagent_type: "code-reviewer"`)
4. Each reviewer independently analyzes the changes and messages findings to the lead
5. For large diffs, consider generating a diff-review playground (`/playground`) to enable visual line-by-line code review alongside team reviewer findings
6. Lead collates findings by consensus:
   - **Common** (found by all reviewers): high confidence, must address
   - **Majority** (found by 2+ reviewers): likely valid, investigate
   - **Exclusive** (found by one reviewer): cross-check before acting
6. Shutdown team after review is complete

This replaces independent subagent-based verification. The team approach lets reviewers challenge each other's findings and reduces false positives.

### Adaptive Replanning

Plans are mutable during execution via the `replan` tool. When execution diverges from the plan, adapt rather than force-fit.

**When to replan:**
- Blocked by an unanticipated dependency or external issue (`blocked_dependency`)
- Diverging errors from `track_convergence` suggest the approach is wrong (`verification_feedback`)
- A phase turns out to be too large and needs splitting (`phase_split`)
- A phase is unnecessary given what was learned during execution (`phase_skip`)
- New requirements or scope changes from the user (`scope_change`)

**How to replan:**
1. Call `replan` with trigger type, reason, and empty `new_plan_content` to get current context
2. Write new plan content incorporating completed phases and adjusting remaining phases
3. Call `replan` again with the new plan content to apply
4. Log the decision via `log_project_decision`

**Constraints (NEVER violate):**
- Max 3 replans per session -- if you need more, the task needs re-scoping
- MUST NOT remove completed phases from the plan (they are historical record)
- MUST NOT skip verification gates when replanning
- Every replan MUST be logged to progress.md Phase History (automatic)

### Auto-Continue Protocol

- After each phase completion, automatically proceed to the next phase
- Phase navigation follows **depth-first order**: sub-phases are completed before sibling phases
  - Example: `Phase 1 > Sub 1.1 > Sub 1.2 > Phase 2`
  - Use `>` as the path separator in `progress.md` phase strings (e.g., `Phase: Phase 1 > Sub-phase 1.1`)
- EXCEPT when:
  - The phase has `checkpoint: true` in the plan
  - Verification fails after retries
  - The user explicitly asks to stop
  - A blocking issue is encountered that requires human judgment
- `progress.md` MUST be updated before any phase transition

### Team Lifecycle

Standard lifecycle for agent teams within the workflow:

1. **Create** team with descriptive name: `{project}-{purpose}` (e.g., `myapp-research`, `myapp-review`)
2. **Create all tasks** before spawning teammates so they can self-claim work
3. **Spawn teammates** with clear prompts referencing the task list
4. **Monitor** via `TaskList` -- check for completed and blocked tasks
5. **Coordinate** via `SendMessage` -- prefer DM over broadcast (broadcasts are expensive)
6. **Shutdown** -- teams MUST NOT remain running after work completion: `SendMessage(type: "shutdown_request")` to each teammate, then `TeamDelete`
7. **Record** team outcomes in `progress.md` via `workflow_progress`

**Constraints (NEVER violate):**
- NO teams for < 3 parallel tasks
- NO broadcasts when DM suffices
- NO teams left running after completion
- NO teams for sequential dependencies (use subagents instead)

### Playground Integration

The `/playground` skill generates interactive single-file HTML explorers for visual exploration. Use playgrounds when visual/interactive output adds clarity over plain text.

| Template | Workflow Phase | Use Case |
|----------|---------------|----------|
| `concept-map` | Discovery | Map problem domains, identify knowledge gaps, explore scope |
| `code-map` | Planning | Visualize component relationships, data flow, dependencies |
| `diff-review` | Verification | Line-by-line visual code review for large changesets |
| `design-playground` | Any | Explore UI/design options interactively |
| `data-explorer` | Research | Visualize data structures or API response shapes |
| `document-critique` | Any | Review and annotate documents or specs |

Playgrounds are optional. Default to plain text unless the task involves complex relationships, large diffs, or visual design that benefit from interactive exploration.

### Session Reporting

Send structured Telegram notifications at key session events using the `telegram_notify` or `telegram_phase_update` MCP tools:

| Event | When | Content |
|-------|------|---------|
| Phase start | Beginning a new phase | Project name, phase name |
| Phase complete | After verification + commit | Phase name, verification status, commit hash |
| Checkpoint | Phase has `checkpoint: true` | Summary, risks, next phase, "awaiting approval" |
| Blocked | Cannot proceed | Phase name, reason, attempt count |
| Session complete | All phases done or stopping | Phases completed, commit count |

Report only at transitions -- do not send notifications during implementation.

### Continuous Improvement Loop

When the plan is fully executed and all phases are complete, don't stop. The cycle continues:

1. **Audit**: Run verification suite, scan for TODOs, check dependency health
2. **Discover**: Identify 1-3 improvement opportunities (regressions > bugs > quality > features > deps)
3. **Propose**: Present opportunities to the user or write as new plan phases with `checkpoint: true`
4. **Repeat**: Plan -> Execute -> Verify -> Discover -> Plan

Discovery phases are always advisory (`checkpoint: true`). The agent proposes, the human approves.

### Model Tier Guidance

- **Research subagents**: Use Sonnet (`model: "sonnet"`) for cost efficiency
- **Exploration/search**: Use Haiku (`model: "haiku"`) for quick lookups
- **Implementation/planning**: Use Opus (default) for complex reasoning
- **Verification runner**: Use Haiku for fast pass/fail checks
- **Team teammates**: Default Sonnet for cost-efficient parallel work
- **Team lead**: Opus for complex coordination and synthesis

### Context Recovery

If a session is compressed or restarted:
1. Read `.claude-project/progress.md` for current state
2. Read `.claude-project/plan.md` for the overall plan
3. Check git log for recent commits to understand what's been done
4. Resume from the current phase/task indicated in progress.md

### Context Freshness

Context degrades as it grows. Prefer rewriting over appending to keep working documents concise and high-signal.

| Document | Mutability | Rule |
|----------|-----------|------|
| `progress.md` Current State | Rewritten each phase | MUST reflect only current phase, not accumulate history |
| `progress.md` Phase History | Append-only | Collapsed `<details>` entries, one per completed phase |
| `discover.md` | Immutable after Discovery | NO modifications once Discovery phase is complete |
| `plan.md` | Rewritable during Planning | Mutable via `replan` tool only (max 3 per session). Direct edits during execution are forbidden. |
| `research/*.md` | Immutable after Research | Reference only; do not update during execution |

**Agent context management:**
- When approaching context limits, summarize and restart rather than continuing with degraded context
- Re-read `.claude-project/` files from disk rather than relying on in-context memory of their contents
- Scratchpad notes (comments, TODOs in progress.md "Next Up" section) should be rewritten each phase, not appended

### Output Discipline

Context pollution is the leading cause of agent degradation in long sessions. Every token of noise crowds out signal.

**Rules:**
- Pipe verbose command output to files; return only summaries (e.g., "12 passed, 0 failed" not the full pytest log)
- Read specific line ranges, not entire files, when looking for a single function or section
- Lead with decisions and conclusions, not with the reasoning chain that produced them
- Summarize research findings in 3-5 bullet points before elaborating

**NEVER do:**
- Dump full test output or raw stack traces into conversation context
- Read a 500-line file to find a 10-line function (use Grep or line ranges)
- Repeat prior context verbatim when a reference suffices
- Include build/install logs unless they contain an error
