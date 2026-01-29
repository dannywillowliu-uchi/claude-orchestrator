# Future Improvements

Features to implement after the core enhancement set (1-7) is complete.

**Last updated**: 2026-01-28

---

## Status Overview

| Feature | Status | Notes |
|---------|--------|-------|
| 8. Knowledge Base Seeding | **Done** | CLI `seed-docs` command, setup wizard integration |
| 9. Enhanced Hooks | **Done** | `hooks.py` with 4 profiles, bridge + supervisor integration |
| 10. Structured Output | **Done (scaffold)** | `schemas.py` with validation, bridge `--output-format json` stub |
| 11. Batch Processing | **Done** | `batch.py` with semaphore concurrency, full test coverage |
| 12. Codebase Onboarding | **Done (scaffold)** | `onboarding.py` with heuristic detection, AST/prompt stubs |

---

## Feature 8: Knowledge Base Integration (SDK Docs) -- DONE

### What was built
- `claude-orchestrator seed-docs` CLI command with `--source` flag
- `DEFAULT_SEED_SOURCES`: anthropic-docs (100 pages), mcp-docs (50 pages)
- Setup wizard step 4/5 prompts for knowledge base seeding
- Graceful handling when `[knowledge]` extras are not installed

### Remaining work
- Add more default sources (anthropic-cookbook, etc.)
- Auto-re-index on schedule
- Cache invalidation for stale docs

---

## Feature 9: Enhanced Hooks Integration -- DONE

### What was built
- `src/claude_orchestrator/hooks.py` with `HooksConfig` dataclass
- 4 predefined profiles: `read_only`, `code_edit`, `test_run`, `full_access`
- Keyword-based `generate_hooks_for_task()` for automatic profile selection
- Bridge uses `--allowedTools` instead of `--dangerously-skip-permissions` for non-full-access profiles
- Supervisor has `select_hooks_profile()` method

### Remaining work
- Per-command Bash pattern matching (e.g., allow `pytest` but deny `rm -rf`)
- User-configurable profiles
- Profile override via plan task metadata

---

## Feature 10: Structured Output Validation -- SCAFFOLD

### What was built
- `src/claude_orchestrator/schemas.py` with `ResponseSchema` dataclass
- JSON type validation (string, integer, boolean, array, object)
- Required key enforcement
- Predefined schemas: `CODE_REVIEW_SCHEMA`, `TASK_RESULT_SCHEMA`, `PLAN_SCHEMA`
- Bridge adds `--output-format json` when schema is provided
- Best-effort validation (logs warning, returns raw response on mismatch)

### Remaining work
- Nested object validation
- Array item type validation
- Schema-per-task-type in delegator
- Retry on validation failure (re-prompt with "respond as valid JSON")

---

## Feature 11: Batch Processing / Fan-Out -- DONE

### What was built
- `src/claude_orchestrator/orchestrator/batch.py`
- `BatchProcessor` with `asyncio.Semaphore` concurrency control
- `BatchItem`, `BatchResult`, `BatchSummary` dataclasses
- Individual failure isolation (one item failing doesn't abort batch)
- `on_item_complete` callback per item
- `BatchSummary.success_rate` property

### Remaining work
- Wire into MCP tools (expose as `batch_process` tool)
- Integrate with delegator for plan-based batch execution
- Priority ordering (process high-priority items first)
- Retry failed items with exponential backoff

---

## Feature 12: Codebase Onboarding Mode -- SCAFFOLD

### What was built
- `src/claude_orchestrator/orchestrator/onboarding.py`
- `ProjectProfile` dataclass with detected attributes
- `CodebaseOnboarder.analyze_project()` -- working heuristics:
  - Language detection (Python, JS, TS, Rust, Go, Java, Ruby, C, C++)
  - Entry point detection (main.py, index.js, app.py, etc.)
  - Key file detection (README, pyproject.toml, Dockerfile, CI configs)
  - Test detection (tests/ directory, test_*.py, *.test.js)
  - CI detection (GitHub Actions, GitLab CI, CircleCI, Jenkins)
  - Docker detection
  - File/directory counting

### Remaining work
- `generate_ast_summary()` -- parse source files for class/function signatures
- `generate_onboarding_prompt()` -- combine profile + AST + docs into Claude prompt
- Dependency graph generation
- Test coverage analysis
- Wire into MCP tools (expose as `onboard_project` tool)
- Generate ONBOARDING.md output file

---

## Next Priority: Deeper Integration

Now that scaffolds exist for all 5 features, the next priorities are:

1. **Wire batch processing into MCP tools** -- expose as a tool Claude can call
2. **Implement AST summary for onboarding** -- Python AST parsing first, then JS/TS
3. **Add nested schema validation** -- needed for real-world structured output
4. **Per-command Bash hooks** -- granular control over what shell commands subagents can run
5. **Auto-re-index knowledge base** -- detect stale docs and re-crawl

---

## Dependencies

All features require core enhancement set (1-7) to be complete first. (Done.)

Features 8-12 are now all implemented at minimum scaffold level. Further deepening can happen in any order.
