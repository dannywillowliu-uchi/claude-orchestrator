"""Task executor - handles task execution with optional subagent support."""

import json
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable
from enum import Enum

from .database import Database, TaskRecord, TaskStatus
from .analyzer import TaskComplexity


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExecutionResult:
    success: bool
    message: str
    details: Optional[str] = None
    steps_completed: int = 0
    total_steps: int = 0


class TaskExecutor:
    """
    Executes tasks by generating prompts for Claude Code.

    This executor doesn't run tasks directly - it generates prompts and plans
    that Claude Code can use to execute tasks through its normal tool use.
    """

    def __init__(self, db: Database):
        self.db = db
        self._progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

    def set_progress_callback(self, callback: Callable[[str, str], Awaitable[None]]):
        """Set callback for progress updates (task_id, message)."""
        self._progress_callback = callback

    async def _report_progress(self, task_id: str, message: str):
        """Report progress via callback."""
        if self._progress_callback:
            await self._progress_callback(task_id, message)

    def generate_execution_prompt(self, task: TaskRecord) -> str:
        """
        Generate a prompt for Claude Code to execute this task.

        This is the main output - Claude Code will use this prompt
        to actually perform the task using its available tools.
        """
        prompt_parts = [
            f"# Task: {task.title}",
            "",
        ]

        if task.notes:
            prompt_parts.extend([
                "## Description",
                task.notes,
                "",
            ])

        if task.execution_plan:
            prompt_parts.extend([
                "## Execution Plan",
                task.execution_plan,
                "",
            ])

        # Add complexity-specific instructions
        if task.complexity == TaskComplexity.COMPLEX.value:
            prompt_parts.extend([
                "## Approach",
                "This is a complex task. Please:",
                "1. Use the Task tool with 'Plan' subagent to create a detailed plan",
                "2. Execute each step methodically",
                "3. Use code-reviewer agent after significant code changes",
                "4. Report progress after each major step",
                "",
            ])
        elif task.complexity == TaskComplexity.MODERATE.value:
            prompt_parts.extend([
                "## Approach",
                "This is a moderate complexity task. Please:",
                "1. Create a todo list to track progress",
                "2. Execute steps in order",
                "3. Verify each step before proceeding",
                "",
            ])
        else:
            prompt_parts.extend([
                "## Approach",
                "This is a straightforward task. Execute directly.",
                "",
            ])

        prompt_parts.extend([
            "## Completion Criteria",
            "When done, confirm what was accomplished and any relevant details.",
            "",
            "Please proceed with this task now.",
        ])

        return "\n".join(prompt_parts)

    def generate_subagent_config(self, task: TaskRecord) -> dict:
        """
        Generate configuration for subagent execution.

        Returns a dict specifying which agents to use and in what order.
        """
        config = {
            "task_id": task.id,
            "title": task.title,
            "agents": [],
        }

        complexity = TaskComplexity(task.complexity) if task.complexity else TaskComplexity.SIMPLE

        if complexity == TaskComplexity.COMPLEX:
            config["agents"] = [
                {
                    "type": "Plan",
                    "purpose": "Create detailed implementation plan",
                    "prompt": f"Plan the implementation for: {task.title}\n\n{task.notes or ''}",
                },
                {
                    "type": "Explore",
                    "purpose": "Understand codebase context",
                    "prompt": f"Explore the codebase to understand what's needed for: {task.title}",
                },
                {
                    "type": "general-purpose",
                    "purpose": "Execute the implementation",
                    "prompt": self.generate_execution_prompt(task),
                },
                {
                    "type": "code-reviewer",
                    "purpose": "Review the changes",
                    "prompt": "Review the code changes just made for correctness and quality.",
                },
            ]
        elif complexity == TaskComplexity.MODERATE:
            config["agents"] = [
                {
                    "type": "Explore",
                    "purpose": "Understand codebase context",
                    "prompt": f"Explore relevant files for: {task.title}",
                },
                {
                    "type": "general-purpose",
                    "purpose": "Execute the task",
                    "prompt": self.generate_execution_prompt(task),
                },
            ]
        else:
            config["agents"] = [
                {
                    "type": "general-purpose",
                    "purpose": "Execute the task",
                    "prompt": self.generate_execution_prompt(task),
                },
            ]

        return config

    async def prepare_execution(self, task_id: str) -> Optional[dict]:
        """
        Prepare task for execution.

        Returns execution configuration dict or None if task not found.
        """
        task = await self.db.get_task(task_id)
        if not task:
            return None

        # Update status to executing
        await self.db.update_task(task_id, status=TaskStatus.EXECUTING.value)
        await self._report_progress(task_id, "Starting task execution...")

        # Generate execution config
        config = self.generate_subagent_config(task)
        config["prompt"] = self.generate_execution_prompt(task)

        return config

    async def mark_completed(
        self, task_id: str, success: bool, result_message: str
    ) -> Optional[TaskRecord]:
        """Mark a task as completed or failed."""
        status = TaskStatus.COMPLETED.value if success else TaskStatus.FAILED.value

        task = await self.db.update_task(
            task_id,
            status=status,
        )

        await self.db.add_execution_log(
            task_id=task_id,
            step_number=0,
            action="completion",
            result=result_message,
            success=success,
        )

        return task

    async def log_step(
        self, task_id: str, step_number: int, action: str, result: str, success: bool
    ):
        """Log an execution step."""
        await self.db.add_execution_log(
            task_id=task_id,
            step_number=step_number,
            action=action,
            result=result,
            success=success,
        )
        await self._report_progress(task_id, f"Step {step_number}: {action} - {'✓' if success else '✗'}")
