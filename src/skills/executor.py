"""
Skill Executor - Executes skills within Claude sessions.

Responsibilities:
- Format skill instructions for Claude
- Track skill execution state
- Validate tool usage against allowed-tools
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .loader import Skill, SkillLoader, get_skill_loader

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
	"""Status of a skill execution."""
	PENDING = "pending"
	RUNNING = "running"
	COMPLETED = "completed"
	FAILED = "failed"
	CANCELLED = "cancelled"


@dataclass
class SkillExecution:
	"""Tracks a skill execution instance."""
	id: str
	skill_name: str
	status: ExecutionStatus
	started_at: str
	session_id: str | None = None
	completed_at: str | None = None
	result: str | None = None
	error: str | None = None
	tools_used: list[str] = field(default_factory=list)
	context: dict = field(default_factory=dict)


class SkillExecutor:
	"""
	Executes skills by formatting instructions and tracking state.

	Skills are executed by:
	1. Loading skill definition
	2. Formatting instructions with context
	3. Sending to Claude session
	4. Tracking tool usage
	5. Validating completion
	"""

	def __init__(
		self,
		loader: SkillLoader | None = None,
		project_path: str | None = None,
	):
		"""
		Initialize the executor.

		Args:
			loader: Skill loader instance
			project_path: Project path for skill discovery
		"""
		self.loader = loader or get_skill_loader(project_path)
		self._executions: dict[str, SkillExecution] = {}
		self._execution_counter = 0

	def prepare_execution(
		self,
		skill_name: str,
		context: dict | None = None,
	) -> SkillExecution | None:
		"""
		Prepare a skill for execution.

		Args:
			skill_name: Name of skill to execute
			context: Additional context variables

		Returns:
			SkillExecution object or None if skill not found
		"""
		skill = self.loader.get_skill(skill_name)
		if not skill:
			logger.warning(f"Skill not found: {skill_name}")
			return None

		self._execution_counter += 1
		execution_id = f"exec-{skill_name}-{self._execution_counter}"

		execution = SkillExecution(
			id=execution_id,
			skill_name=skill_name,
			status=ExecutionStatus.PENDING,
			started_at=datetime.now().isoformat(),
			context=context or {},
		)

		self._executions[execution_id] = execution
		logger.info(f"Prepared skill execution: {execution_id}")

		return execution

	def get_execution_prompt(
		self,
		execution_id: str,
		additional_context: str | None = None,
	) -> str | None:
		"""
		Get the formatted prompt for a skill execution.

		Args:
			execution_id: Execution ID
			additional_context: Extra context to append

		Returns:
			Formatted prompt string or None
		"""
		execution = self._executions.get(execution_id)
		if not execution:
			logger.warning(f"Execution not found: {execution_id}")
			return None

		skill = self.loader.get_skill(execution.skill_name)
		if not skill:
			return None

		# Build the prompt
		prompt_parts = [
			f"# Executing Skill: {skill.name}",
			"",
			f"**Description**: {skill.description}",
			"",
		]

		# Add allowed tools constraint
		if skill.allowed_tools:
			tools_list = ", ".join(skill.allowed_tools)
			prompt_parts.extend([
				"## Allowed Tools",
				f"You may ONLY use the following tools for this skill: {tools_list}",
				"",
			])

		# Add context variables if provided
		if execution.context:
			prompt_parts.extend([
				"## Context",
				"The following context is provided:",
				"",
			])
			for key, value in execution.context.items():
				prompt_parts.append(f"- **{key}**: {value}")
			prompt_parts.append("")

		# Add the skill instructions
		prompt_parts.extend([
			"## Instructions",
			"",
			skill.instructions,
		])

		# Add additional context if provided
		if additional_context:
			prompt_parts.extend([
				"",
				"## Additional Context",
				additional_context,
			])

		return "\n".join(prompt_parts)

	def start_execution(
		self,
		execution_id: str,
		session_id: str,
	) -> bool:
		"""
		Mark an execution as started.

		Args:
			execution_id: Execution ID
			session_id: Claude session ID

		Returns:
			True if started successfully
		"""
		execution = self._executions.get(execution_id)
		if not execution:
			return False

		if execution.status != ExecutionStatus.PENDING:
			logger.warning(f"Cannot start execution {execution_id}: status is {execution.status}")
			return False

		execution.status = ExecutionStatus.RUNNING
		execution.session_id = session_id
		execution.started_at = datetime.now().isoformat()

		logger.info(f"Started skill execution: {execution_id} in session {session_id}")
		return True

	def record_tool_use(
		self,
		execution_id: str,
		tool_name: str,
	) -> dict:
		"""
		Record a tool use during skill execution.

		Args:
			execution_id: Execution ID
			tool_name: Name of tool used

		Returns:
			Dict with validation result
		"""
		execution = self._executions.get(execution_id)
		if not execution:
			return {"valid": False, "error": "Execution not found"}

		skill = self.loader.get_skill(execution.skill_name)
		if not skill:
			return {"valid": False, "error": "Skill not found"}

		execution.tools_used.append(tool_name)

		# Validate against allowed tools
		if skill.allowed_tools and tool_name not in skill.allowed_tools:
			return {
				"valid": False,
				"error": f"Tool '{tool_name}' not in allowed tools: {skill.allowed_tools}",
				"warning": True,
			}

		return {"valid": True}

	def complete_execution(
		self,
		execution_id: str,
		result: str,
		success: bool = True,
	) -> bool:
		"""
		Mark an execution as completed.

		Args:
			execution_id: Execution ID
			result: Execution result/output
			success: Whether execution succeeded

		Returns:
			True if marked successfully
		"""
		execution = self._executions.get(execution_id)
		if not execution:
			return False

		execution.status = ExecutionStatus.COMPLETED if success else ExecutionStatus.FAILED
		execution.completed_at = datetime.now().isoformat()
		execution.result = result

		logger.info(
			f"Completed skill execution: {execution_id} "
			f"(success={success}, tools_used={len(execution.tools_used)})"
		)
		return True

	def fail_execution(
		self,
		execution_id: str,
		error: str,
	) -> bool:
		"""
		Mark an execution as failed.

		Args:
			execution_id: Execution ID
			error: Error message

		Returns:
			True if marked successfully
		"""
		execution = self._executions.get(execution_id)
		if not execution:
			return False

		execution.status = ExecutionStatus.FAILED
		execution.completed_at = datetime.now().isoformat()
		execution.error = error

		logger.warning(f"Failed skill execution: {execution_id}: {error}")
		return True

	def cancel_execution(self, execution_id: str) -> bool:
		"""Cancel a pending or running execution."""
		execution = self._executions.get(execution_id)
		if not execution:
			return False

		if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]:
			return False

		execution.status = ExecutionStatus.CANCELLED
		execution.completed_at = datetime.now().isoformat()

		logger.info(f"Cancelled skill execution: {execution_id}")
		return True

	def get_execution(self, execution_id: str) -> SkillExecution | None:
		"""Get an execution by ID."""
		return self._executions.get(execution_id)

	def list_executions(
		self,
		status: ExecutionStatus | None = None,
		skill_name: str | None = None,
	) -> list[dict]:
		"""
		List skill executions.

		Args:
			status: Filter by status
			skill_name: Filter by skill name

		Returns:
			List of execution summaries
		"""
		executions = list(self._executions.values())

		if status:
			executions = [e for e in executions if e.status == status]

		if skill_name:
			executions = [e for e in executions if e.skill_name == skill_name]

		return [
			{
				"id": e.id,
				"skill_name": e.skill_name,
				"status": e.status.value,
				"started_at": e.started_at,
				"completed_at": e.completed_at,
				"tools_used_count": len(e.tools_used),
				"has_error": e.error is not None,
			}
			for e in executions
		]

	def get_auto_invoke_skills(self) -> list[Skill]:
		"""
		Get skills marked for auto-invocation.

		Returns:
			List of auto-invoke skills
		"""
		skills = self.loader.discover_skills()
		return [s for s in skills.values() if s.auto_invoke]


# Global executor instance
_executor: SkillExecutor | None = None


def get_skill_executor(project_path: str | None = None) -> SkillExecutor:
	"""Get or create the global skill executor instance."""
	global _executor
	if _executor is None:
		_executor = SkillExecutor(project_path=project_path)
	return _executor
