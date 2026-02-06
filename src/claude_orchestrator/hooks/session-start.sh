#!/bin/bash
# Session start hook: injects workflow state into Claude Code session context.
# Installed by: claude-orchestrator install

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PROGRESS_FILE="$PROJECT_DIR/.claude-project/progress.md"

# Update Ghostty tab title if the script exists
if [ -f "$HOME/.claude/scripts/ghostty-status.sh" ]; then
	"$HOME/.claude/scripts/ghostty-status.sh" "$(basename "$PROJECT_DIR")" running 2>/dev/null
fi

# Inject workflow state if .claude-project exists
if [ -f "$PROGRESS_FILE" ]; then
	echo "--- Workflow State ---"
	# Output Current State section (stop at Phase History)
	sed -n '/^## Current State/,/^## Phase History/p' "$PROGRESS_FILE" | head -20 | sed '$d'

	# Show active team info if any
	TEAM_DIR="$HOME/.claude/teams"
	if [ -d "$TEAM_DIR" ] && [ "$(ls -A "$TEAM_DIR" 2>/dev/null)" ]; then
		echo "Active Teams: $(ls "$TEAM_DIR" | tr '\n' ', ' | sed 's/,$//')"
	fi

	echo "---"
fi
