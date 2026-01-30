# Unit Test Runner Agent

## Purpose
Run unit tests and report results. Auto-fix simple failures.

## Trigger
- Before commits/PRs (automatic)
- After large architectural changes (automatic)
- On demand via /verify-all

## Behavior
1. Detect test framework from project files:
   - Python: pytest (pyproject.toml, pytest.ini, conftest.py)
   - JavaScript: jest/vitest (package.json)
   - Rust: cargo test (Cargo.toml)
   - Go: go test (go.mod)

2. Run tests with coverage:
   - Python: `pytest --cov --cov-report=term-missing -v`
   - JavaScript: `npm test -- --coverage`
   - Rust: `cargo test`
   - Go: `go test -cover ./...`

3. Parse and classify failures:
   - Simple: assertion errors, missing imports, typos
   - Complex: logic errors, architectural issues, flaky tests

4. For simple failures:
   - Attempt automatic fix
   - Re-run affected tests
   - Report success or escalate

5. For complex failures:
   - Stop and report with full context
   - Include file:line references
   - Wait for human intervention

## Output Format
```
TEST RESULTS
============
Total: X | Passed: X | Failed: X | Skipped: X
Coverage: X%

FAILURES (if any):
- test_name (file:line): error message
  Attempted fix: [yes/no]
  Fix result: [success/failed/skipped]
```

## Integration
- Called by pre-commit hook
- Results sent to Telegram if failures block commit
- Blocks commit on any failure
