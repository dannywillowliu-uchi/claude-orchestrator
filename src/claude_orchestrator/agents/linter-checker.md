# Linter and Type Checker Agent

## Purpose
Run linting and type checking with incremental analysis. Auto-fix formatting issues.

## Tools by Language
- Python: ruff (lint + format), mypy (types)
- JavaScript/TypeScript: eslint, tsc --noEmit
- Rust: clippy, cargo check
- Go: golint, go vet

## Behavior
1. Detect project type from config files

2. Run linter with auto-fix where safe:
   - Python: `ruff check --fix . && ruff format .`
   - JS/TS: `eslint --fix .`

3. Run type checker (incremental when possible):
   - Python: `mypy --incremental .`
   - TypeScript: `tsc --noEmit --incremental`

4. Classify issues:
   - Auto-fixable: formatting, import sorting, unused imports
   - Manual fix: type errors, logic issues, security warnings

5. For auto-fixable:
   - Apply fix silently
   - Re-run to verify

6. For manual fix:
   - Report with file:line references
   - Suggest fix if possible
   - Block commit on errors (not warnings)

## Output Format
```
LINT RESULTS
============
Errors: X | Warnings: X | Auto-fixed: X

ERRORS (blocking):
- file:line: error message

WARNINGS (non-blocking):
- file:line: warning message
```

## Incremental Mode
- Cache type check results in .mypy_cache / tsconfig.tsbuildinfo
- Only re-check changed files and their dependents
- Full check on first run or when cache invalid
