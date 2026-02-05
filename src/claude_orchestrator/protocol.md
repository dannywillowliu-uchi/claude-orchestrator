## Workflow Protocol

This protocol governs how you approach non-trivial tasks. It activates when `.claude-project/` exists or when the task warrants structured execution.

### Session Start

1. Check if `.claude-project/` exists in the project root
2. If it exists, read `progress.md` to understand current state
3. If the task is trivial (single-file fix, typo, < 3 steps), skip the workflow
4. If the task is non-trivial, ensure `.claude-project/` is initialized via `init_project_workflow`

### Discovery Phase

When starting a new feature or significant change:

1. Open `.claude-project/discover.md`
2. Fill in Problem Statement, Goals, Non-Goals, and Constraints through Q&A with the user
3. Record every question and answer in the Q&A Log section
4. Discovery is complete when: problem is well-defined, goals are measurable, constraints are documented, and user confirms understanding
5. Update progress: `workflow_progress(phase_completed="Discovery", phase_started="Research")`

### Research Phase

When the task requires understanding unfamiliar domains or APIs:

1. Identify 2-4 research subtopics from discovery
2. For each topic, spawn a Sonnet-tier subagent (Task tool with `model: "sonnet"`) with specific research questions
3. Each subagent produces a markdown file saved to `.claude-project/research/<topic>.md`
4. After all research completes, synthesize findings into a summary
5. Use a two-pass approach: raw findings first, then structured synthesis
6. Skip this phase if the domain is well-understood and no external APIs are involved
7. Update progress: `workflow_progress(phase_completed="Research", phase_started="Planning")`

### Planning Phase

Synthesize discovery + research into an actionable plan:

1. Write `.claude-project/plan.md` with phases, tasks, and verification criteria
2. Each phase should specify:
   - `checkpoint: true/false` (whether to pause for user review)
   - `tools_required: [list]` (verify with `check_tools` before starting)
   - `verification_criteria: [list]` (what must pass before phase is complete)
3. Present the plan to the user for review and iterate until approved
4. Use `EnterPlanMode` for complex plans requiring user sign-off
5. Update progress: `workflow_progress(phase_completed="Planning", phase_started="Phase 1 - <name>")`

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
   - Suggest the user run `/verify-by-consensus` for high-stakes changes

### Auto-Continue Protocol

- After each phase completion, automatically proceed to the next phase
- EXCEPT when:
  - The phase has `checkpoint: true` in the plan
  - Verification fails after retries
  - The user explicitly asks to stop
  - A blocking issue is encountered that requires human judgment
- Always update `progress.md` before transitioning phases

### Model Tier Guidance

- **Research subagents**: Use Sonnet (`model: "sonnet"`) for cost efficiency
- **Exploration/search**: Use Haiku (`model: "haiku"`) for quick lookups
- **Implementation/planning**: Use Opus (default) for complex reasoning
- **Verification runner**: Use Haiku for fast pass/fail checks

### Context Recovery

If a session is compressed or restarted:
1. Read `.claude-project/progress.md` for current state
2. Read `.claude-project/plan.md` for the overall plan
3. Check git log for recent commits to understand what's been done
4. Resume from the current phase/task indicated in progress.md
