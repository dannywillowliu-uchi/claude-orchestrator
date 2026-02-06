## Workflow Protocol

This protocol governs how you approach non-trivial tasks. It activates when `.claude-project/` exists or when the task warrants structured execution.

### Session Start

1. Check if `.claude-project/` exists in the project root
2. If it exists, read `progress.md` to understand current state
3. If the task is trivial (single-file fix, typo, < 3 steps), skip the workflow
4. If the task is non-trivial, ensure `.claude-project/` is initialized via `init_project_workflow`

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
3. Each phase should specify:
   - `checkpoint: true/false` (whether to pause for user review)
   - `tools_required: [list]` (verify with `check_tools` before starting)
   - `verification_criteria: [list]` (what must pass before phase is complete)
4. Present the plan to the user for review and iterate until approved
5. Use `EnterPlanMode` for complex plans requiring user sign-off
6. Update progress: `workflow_progress(phase_completed="Planning", phase_started="Phase 1 - <name>")`

### Execution Phase

For each phase in the plan:

1. Read `progress.md` to confirm current phase and any blocked state
2. Run `check_tools` for any phase-specific tool requirements
3. Implement tasks sequentially within the phase
4. After all tasks in a phase are complete:
   a. Run `run_verification` with the project path
   b. If verification fails, fix issues (up to 3 attempts), then start a fresh session
   c. If verification passes, commit the changes
   d. Update progress: `workflow_progress(phase_completed="Phase N", phase_started="Phase N+1", commit_hash="...")`
5. If the phase has `checkpoint: true`, stop and wait for user confirmation

### Verification Gate

Before every commit:

1. Run `run_verification(project_path, files_changed=<changed files>)`
2. If it fails:
   - Attempt to fix (max 3 tries per check type)
   - After 3 failures, do NOT commit - report the issue
3. If it passes and consensus review is recommended:
   - Note it in the commit message or progress update
   - Use team-based verification for high-stakes changes (see below)

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

### Auto-Continue Protocol

- After each phase completion, automatically proceed to the next phase
- EXCEPT when:
  - The phase has `checkpoint: true` in the plan
  - Verification fails after retries
  - The user explicitly asks to stop
  - A blocking issue is encountered that requires human judgment
- Always update `progress.md` before transitioning phases

### Team Lifecycle

Standard lifecycle for agent teams within the workflow:

1. **Create** team with descriptive name: `{project}-{purpose}` (e.g., `myapp-research`, `myapp-review`)
2. **Create all tasks** before spawning teammates so they can self-claim work
3. **Spawn teammates** with clear prompts referencing the task list
4. **Monitor** via `TaskList` -- check for completed and blocked tasks
5. **Coordinate** via `SendMessage` -- prefer DM over broadcast (broadcasts are expensive)
6. **Shutdown** after all tasks complete: `SendMessage(type: "shutdown_request")` to each teammate, then `TeamDelete`
7. **Record** team outcomes in `progress.md` via `workflow_progress`

**Anti-patterns to avoid:**
- Don't create teams for trivial work (fewer than 3 parallel tasks)
- Don't broadcast when a DM suffices
- Don't leave teams running after work is done
- Don't use teams when tasks have sequential dependencies (use subagents instead)

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
