---
name: verify-by-consensus
description: Multi-perspective code review using agent teams. Dispatches 2-3 reviewers with different focus areas and collates findings by consensus ratio.
user_invocable: true
---

# Verify by Consensus

Perform a multi-perspective code review using an agent team.

## Usage

```
/verify-by-consensus [files] [--count N]
```

- `files`: Files or directories to review (default: staged/changed files)
- `--count N`: Number of reviewers to spawn (default: 3, max: 4)

## Workflow

1. **Identify changes**: Determine which files to review from arguments or git diff
2. **Create review team**: `TeamCreate(team_name="{project}-consensus-review")`
3. **Create review tasks** from different angles:
   - **Security reviewer**: Focus on vulnerabilities, injection risks, auth issues, secret exposure
   - **Architecture reviewer**: Focus on design patterns, coupling, SOLID principles, extensibility
   - **Correctness reviewer**: Focus on logic errors, edge cases, error handling, race conditions
4. **Spawn reviewer teammates**: Use Task tool with `team_name`, `subagent_type: "code-reviewer"`, `model: "sonnet"`
5. **Wait for completion**: Monitor `TaskList` until all review tasks are completed
6. **Collate findings** by consensus:
   - **Common** (found by all): High confidence -- must address before merge
   - **Majority** (found by 2+): Likely valid -- investigate further
   - **Exclusive** (found by 1): Cross-check -- may be false positive or genuine insight
7. **Cross-check exclusives**: Message the finding reviewer and ask others to confirm or deny
8. **Shutdown team**: `SendMessage(type: "shutdown_request")` to each teammate, then `TeamDelete`
9. **Generate report**: Save to `.work/consensus-review-{timestamp}.md`

## Report Format

```markdown
# Consensus Review Report

## Summary
- Reviewers: N
- Files reviewed: [list]
- Issues found: X (Y common, Z majority, W exclusive)

## Common Issues (High Confidence)
Issues found by all reviewers.

## Majority Issues (Likely Valid)
Issues found by 2+ reviewers.

## Exclusive Issues (Investigated)
Issues found by one reviewer, with cross-check results.

## Recommendation
READY TO MERGE / NEEDS FIXES / NEEDS REARCHITECTING
```
