# Contributing to claude-orchestrator

## Git Workflow

### Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` -- new feature or capability
- `fix:` -- bug fix
- `refactor:` -- code restructuring without behavior change
- `docs:` -- documentation only
- `test:` -- adding or updating tests
- `chore:` -- maintenance (deps, CI, configs)

Examples:

```
feat: add batch processor with fan-out/fan-in
fix: add beautifulsoup4 to knowledge dependencies
refactor: extract hooks config into dedicated module
test: add hooks generation tests
docs: add CONTRIBUTING.md
```

### Branch Naming

- `feat/<short-description>` -- feature branches
- `fix/<short-description>` -- bug fix branches

### Commit Discipline

- Commit at logical completion points (end of a phase, working feature, passing tests)
- Commit before starting a new phase or destructive change
- Each commit should leave the codebase in a working state
- Run the full verification suite before committing (tests, lint, type check, security)

## Development Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Optional extras
pip install -e ".[knowledge]"  # doc crawling/indexing
pip install -e ".[visual]"     # screenshot verification
pip install -e ".[all]"        # everything
```

## Verification

Before every commit, run:

```bash
pytest                              # tests
ruff check src/claude_orchestrator/ # lint
mypy src/claude_orchestrator/       # type check
bandit -r src/claude_orchestrator/  # security
```

## Code Style

- Indentation: tabs
- Line length: 120
- Type hints: use where beneficial
- Quotes: double quotes
- Minimal comments (only when logic is complex)
