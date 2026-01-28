"""Skills management tools."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..skills import ExecutionStatus, get_skill_executor, get_skill_loader


def register_skills_tools(mcp: FastMCP, config: Config) -> None:
	"""Register skills tools."""

	@mcp.tool()
	async def list_skills(project_path: str = "") -> str:
		"""
		List all available skills.

		Skills are discovered from:
		- Global: ~/.claude/skills/
		- Project: .claude/skills/

		Args:
			project_path: Project path for project-specific skills (default: current directory)
		"""
		loader = get_skill_loader(project_path if project_path else None)
		skills = loader.list_skills()

		return json.dumps({
			"skills": skills,
			"total": len(skills),
			"global_path": str(loader.global_skills_path),
			"project_path": str(loader.project_skills_path),
		}, indent=2)

	@mcp.tool()
	async def get_skill_details(skill_name: str, project_path: str = "") -> str:
		"""
		Get full details of a skill including its instructions.

		Args:
			skill_name: Name of the skill
			project_path: Project path for project-specific skills
		"""
		loader = get_skill_loader(project_path if project_path else None)
		skill = loader.get_skill(skill_name)

		if not skill:
			return json.dumps({
				"error": f"Skill not found: {skill_name}",
				"available_skills": [s["name"] for s in loader.list_skills()],
			}, indent=2)

		return json.dumps({
			"name": skill.name,
			"description": skill.description,
			"allowed_tools": skill.allowed_tools,
			"auto_invoke": skill.auto_invoke,
			"tags": skill.tags,
			"version": skill.version,
			"author": skill.author,
			"source_path": skill.source_path,
			"instructions": skill.instructions,
		}, indent=2)

	@mcp.tool()
	async def create_skill_template(
		skill_name: str,
		global_skill: bool = False,
		project_path: str = "",
	) -> str:
		"""
		Create a new skill template.

		Args:
			skill_name: Name for the new skill (used as directory name)
			global_skill: If True, create in ~/.claude/skills/; otherwise in project's .claude/skills/
			project_path: Project path (only used if global_skill=False)
		"""
		loader = get_skill_loader(project_path if project_path else None)
		skill_file = loader.create_skill_template(skill_name, global_skill)

		return json.dumps({
			"created": True,
			"skill_file": str(skill_file),
			"skill_name": skill_name,
			"location": "global" if global_skill else "project",
		}, indent=2)

	@mcp.tool()
	async def execute_skill(
		skill_name: str,
		context: str = "",
		project_path: str = "",
	) -> str:
		"""
		Prepare a skill for execution and get its formatted prompt.

		Args:
			skill_name: Name of the skill to execute
			context: JSON string of context variables to pass to the skill
			project_path: Project path for skill discovery
		"""
		executor = get_skill_executor(project_path if project_path else None)

		context_dict = {}
		if context:
			try:
				context_dict = json.loads(context)
			except json.JSONDecodeError:
				return json.dumps({"error": "Invalid JSON in context parameter"}, indent=2)

		execution = executor.prepare_execution(skill_name, context_dict)
		if not execution:
			return json.dumps({"error": f"Skill not found: {skill_name}"}, indent=2)

		prompt = executor.get_execution_prompt(execution.id)

		return json.dumps({
			"execution_id": execution.id,
			"skill_name": skill_name,
			"status": execution.status.value,
			"prompt": prompt,
		}, indent=2)

	@mcp.tool()
	async def list_skill_executions(status: str = "", skill_name: str = "") -> str:
		"""
		List skill executions with optional filters.

		Args:
			status: Filter by status (pending, running, completed, failed, cancelled)
			skill_name: Filter by skill name
		"""
		executor = get_skill_executor()

		status_filter = None
		if status:
			try:
				status_filter = ExecutionStatus(status)
			except ValueError:
				return json.dumps({
					"error": f"Invalid status: {status}",
					"valid_statuses": [s.value for s in ExecutionStatus],
				}, indent=2)

		executions = executor.list_executions(
			status=status_filter,
			skill_name=skill_name if skill_name else None,
		)

		return json.dumps({
			"executions": executions,
			"total": len(executions),
		}, indent=2)
