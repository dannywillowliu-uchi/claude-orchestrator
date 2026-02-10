"""Tool-to-phase mapping for progressive disclosure.

Defines which tools are relevant in each workflow phase so Claude can
focus on the right tools at the right time, reducing token overhead.
"""

# Canonical mapping: phase -> tool names relevant to that phase.
# Tools listed under "always" are available regardless of phase.
TOOL_GROUPS: dict[str, list[str]] = {
	"always": [
		"health_check",
		"get_phase_tools",
	],
	"discovery": [
		"init_project_workflow",
		"bootstrap_project",
		"find_project",
		"list_my_projects",
		"log_project_decision",
	],
	"research": [
		"check_tools",
		"workflow_progress",
	],
	"planning": [
		"check_tools",
		"workflow_progress",
		"log_project_decision",
	],
	"execution": [
		"check_tools",
		"replan",
		"run_verification",
		"suggest_fixes",
		"track_convergence",
		"workflow_progress",
		"update_project_status",
		"log_project_decision",
		"log_project_gotcha",
		"log_global_learning",
		"generate_review_artifact",
	],
	"verification": [
		"run_verification",
		"suggest_fixes",
		"track_convergence",
		"log_project_gotcha",
	],
}

# All known tool names (derived from groups for validation).
ALL_TOOLS: set[str] = set()
for _tools in TOOL_GROUPS.values():
	ALL_TOOLS.update(_tools)

VALID_PHASES: set[str] = set(TOOL_GROUPS.keys()) - {"always"}


def get_tools_for_phase(phase: str) -> list[str]:
	"""Return deduplicated tool list for a given phase, including 'always' tools."""
	phase_lower = phase.lower()
	if phase_lower not in VALID_PHASES:
		return sorted(ALL_TOOLS)
	tools = set(TOOL_GROUPS["always"])
	tools.update(TOOL_GROUPS[phase_lower])
	return sorted(tools)
