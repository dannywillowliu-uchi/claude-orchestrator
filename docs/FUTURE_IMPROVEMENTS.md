# Future Improvements

Features to implement after the core enhancement set (1-7) is complete.

---

## Feature 8: Knowledge Base Integration (SDK Docs)

### Description
Seed the existing knowledge base infrastructure with Claude SDK and MCP documentation.

### Current State
- `src/knowledge/crawler.py` - Fully functional web crawler
- `src/knowledge/indexer.py` - LanceDB-based document indexer
- `src/knowledge/retriever.py` - Semantic search MCP tool

### Implementation
```python
# Crawl and index Anthropic docs
crawler = DocCrawler()
await crawler.crawl_site("https://docs.anthropic.com/", "data/knowledge/claude-sdk")

indexer = DocIndexer("data/docs_index")
await indexer.index_directory("data/knowledge/claude-sdk", source_name="claude-sdk")
```

### Docs to Crawl
- `https://docs.anthropic.com/` - Claude API documentation
- `https://modelcontextprotocol.io/` - MCP specification
- `https://github.com/anthropics/anthropic-cookbook` - Code examples

### Effort
Low - infrastructure exists, just needs data seeding

---

## Feature 9: Enhanced Hooks Integration

### Description
Generate task-specific permission hooks instead of using `--dangerously-skip-permissions`.

### Current State
- Basic auto-approve/escalate in supervisor
- Security module with path validation

### Implementation
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit", "action": "allow"},
      {"matcher": "Bash(pytest:*)", "action": "allow"},
      {"matcher": "Bash(git:*)", "action": "require_approval"}
    ]
  }
}
```

### Files to Modify
- `src/orchestrator/supervisor.py` - Generate task-specific hooks
- `src/security.py` - Hook configuration builder

### Effort
Medium

---

## Feature 10: Structured Output Validation

### Description
Use JSON schemas to validate Claude responses for consistent parsing.

### Current State
- Pydantic models for plans
- Free-form text responses from tasks

### Implementation
```python
response = await bridge.send_prompt(
    prompt,
    json_schema={
        "type": "object",
        "properties": {
            "files_modified": {"type": "array"},
            "summary": {"type": "string"},
            "tests_passed": {"type": "boolean"}
        }
    }
)
```

### Files to Modify
- `src/claude_cli_bridge.py` - Add `--json-schema` flag support
- `src/orchestrator/delegator.py` - Define schemas per task type

### Effort
Medium

---

## Feature 11: Batch Processing / Fan-Out

### Description
Process large sets of similar tasks in parallel with rate limiting.

### Use Cases
- Migrate 50 files to new API
- Fix lint errors across codebase
- Update all test files

### Implementation
```python
class BatchProcessor:
    async def process_batch(
        self,
        items: list[str],
        task_template: str,
        max_concurrent: int = 5
    ) -> list[BatchResult]:
        """Process items in parallel with rate limiting."""
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [self._process_one(item, task_template, semaphore) for item in items]
        return await asyncio.gather(*tasks)
```

### Files to Create
- `src/orchestrator/batch.py` - Batch processor with fan-out/fan-in

### Effort
Medium

---

## Feature 12: Codebase Onboarding Mode

### Description
Automated exploration and documentation of unfamiliar codebases.

### Use Cases
- New developer joining project
- Understanding legacy codebase
- Architecture documentation

### Implementation
```python
await orchestrator.onboard_codebase(
    project_path="./my-project",
    questions=[
        "How does authentication work?",
        "What design patterns are used?",
        "What's the testing strategy?",
        "Where are the main entry points?"
    ]
)
# Generates ONBOARDING.md with answers
```

### Files to Create
- `src/orchestrator/onboarding.py` - Codebase explorer
- Templates for common onboarding questions

### Techniques
- AST parsing for code structure
- Dependency graph generation
- Entry point detection
- Test coverage analysis

### Effort
High

---

## Priority Matrix

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| 8. Knowledge Base | Low | High | P1 |
| 10. Structured Output | Medium | High | P2 |
| 9. Hooks Integration | Medium | Medium | P3 |
| 11. Batch Processing | Medium | Medium | P3 |
| 12. Codebase Onboarding | High | Medium | P4 |

---

## Dependencies

All features require core enhancement set (1-7) to be complete first.

Feature 8 (Knowledge Base) can be implemented independently at any time.
