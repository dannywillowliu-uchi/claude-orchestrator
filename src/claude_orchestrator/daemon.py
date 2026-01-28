#!/usr/bin/env python3
"""
Orchestration Daemon - The heart of the Personal Agent system.

This daemon:
1. Polls Google Tasks for new tasks
2. Analyzes task feasibility
3. Sends Telegram notifications for approval
4. Invokes Claude Code CLI to execute approved tasks
5. Reports results back via Telegram

Run with: python -m claude_orchestrator.daemon
Or as a launchd service for auto-start on login.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .analyzer import TaskAnalyzer
from .database import Database, TaskRecord, TaskStatus

# Optional integrations - daemon degrades gracefully without these
try:
	from .google_tasks import GoogleTasksClient
	HAS_GOOGLE_TASKS = True
except ImportError:
	HAS_GOOGLE_TASKS = False

try:
	from .telegram_bot import ApprovalResponse, ApprovalStatus, TelegramBot
	HAS_TELEGRAM = True
except ImportError:
	HAS_TELEGRAM = False

try:
	from .gmail_client import GmailClient
	HAS_GMAIL = True
except ImportError:
	HAS_GMAIL = False

try:
	from .calendar_client import CalendarClient
	HAS_CALENDAR = True
except ImportError:
	HAS_CALENDAR = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/logs/daemon.log"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class DaemonConfig:
    """Daemon configuration."""
    poll_interval: int = 30  # seconds
    projects_path: str = ""  # Set from environment
    claude_timeout: int = 300  # 5 minutes per task
    require_approval: bool = True
    auto_execute_simple: bool = False  # Auto-execute simple tasks without approval

    def __post_init__(self):
        if not self.projects_path:
            self.projects_path = os.getenv(
                "PROJECTS_PATH",
                str(Path.home() / "personal_projects")
            )


class ExecutionDriver:
    """Invokes Claude Code CLI to execute tasks."""

    def __init__(self, projects_path: str, timeout: int = 300):
        self.projects_path = Path(projects_path)
        self.timeout = timeout

    async def execute_task(
        self,
        task: TaskRecord,
        working_dir: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Execute a task using Claude Code CLI.

        Returns (success, output_message)
        """
        # Build the prompt
        prompt = self._build_prompt(task)

        # Determine working directory
        if working_dir:
            cwd = Path(working_dir)
        else:
            # Try to infer from task
            cwd = self._infer_working_dir(task)

        logger.info(f"Executing task '{task.title}' in {cwd}")

        try:
            # Run claude CLI
            process = await asyncio.create_subprocess_exec(
                "claude",
                "--print",  # Non-interactive mode
                "--output-format", "json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode()),
                timeout=self.timeout,
            )

            output = stdout.decode()
            error = stderr.decode()

            if process.returncode == 0:
                # Parse output
                try:
                    result = json.loads(output)
                    message = result.get("result", output[:500])
                except json.JSONDecodeError:
                    message = output[:500] if output else "Task completed"

                return True, message
            else:
                return False, f"Claude exited with code {process.returncode}: {error[:500]}"

        except asyncio.TimeoutError:
            return False, f"Task timed out after {self.timeout} seconds"
        except FileNotFoundError:
            return False, "Claude CLI not found. Make sure 'claude' is in PATH."
        except Exception as e:
            return False, f"Execution error: {str(e)}"

    def _sanitize_input(self, text: str) -> str:
        """
        Sanitize user input to prevent prompt injection.

        Removes or escapes potentially dangerous patterns:
        - System prompt overrides
        - Instruction hijacking attempts
        - Delimiter manipulation
        """
        if not text:
            return ""

        # Remove common injection patterns
        dangerous_patterns = [
            "ignore previous instructions",
            "ignore all instructions",
            "disregard previous",
            "forget previous",
            "new instructions:",
            "system:",
            "assistant:",
            "human:",
            "</s>",
            "<|im_end|>",
            "<|endoftext|>",
        ]

        sanitized = text
        for pattern in dangerous_patterns:
            # Case-insensitive replacement
            import re
            sanitized = re.sub(re.escape(pattern), "[FILTERED]", sanitized, flags=re.IGNORECASE)

        return sanitized

    def _build_prompt(self, task: TaskRecord) -> str:
        """Build the prompt for Claude Code with safety boundaries."""
        # Sanitize user-provided content
        safe_title = self._sanitize_input(task.title)
        safe_notes = self._sanitize_input(task.notes) if task.notes else ""
        safe_plan = self._sanitize_input(task.execution_plan) if task.execution_plan else ""

        parts = [
            "# Task Execution Request",
            "",
            "## Safety Boundaries",
            "- Only perform actions within the user's projects directory",
            "- Do not access system files or sensitive directories",
            "- Do not execute destructive operations without explicit confirmation",
            "- Do not send emails or make external API calls without approval",
            "",
            "## Task Details",
            f"**Title:** {safe_title}",
            "",
        ]

        if safe_notes:
            parts.extend([
                "**Notes:**",
                safe_notes,
                "",
            ])

        if safe_plan:
            parts.extend([
                "## Suggested Plan",
                safe_plan,
                "",
            ])

        parts.extend([
            "## Instructions",
            "Execute this task completely within the safety boundaries above.",
            "When done, summarize what was accomplished.",
            "If you encounter any issues or the task seems unsafe, explain what went wrong.",
        ])

        return "\n".join(parts)

    def _infer_working_dir(self, task: TaskRecord) -> Path:
        """Try to infer the working directory from the task."""
        text = f"{task.title} {task.notes or ''}".lower()

        # Check for project mentions
        project_keywords = {
            "mlb": "mlb_kalshi",
            "kalshi": "mlb_kalshi",
            "trading": "self_learning_trading_agent",
            "health": "apple-health-dashboard",
            "blockchain": "blockchain network valuation",
            "resume": "latex-resume-mcp-public",
            "task automation": "task-automation-mcp",
        }

        for keyword, project in project_keywords.items():
            if keyword in text:
                project_path = self.projects_path / project
                if project_path.exists():
                    return project_path

        # Default to projects root
        return self.projects_path


class OrchestrationDaemon:
    """Main orchestration daemon."""

    def __init__(self, config: Optional[DaemonConfig] = None):
        self.config = config or DaemonConfig()
        self.running = False

        # Load environment
        load_dotenv()

        # Ensure log directory exists
        Path("data/logs").mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.db = Database("data/task_automation.db")
        self.google_tasks = GoogleTasksClient(
            credentials_file=os.getenv(
                "GOOGLE_CREDENTIALS_FILE", "data/credentials/credentials.json"
            ),
            token_file="data/credentials/token.json",
        )
        self.telegram = TelegramBot(
            token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        )
        self.analyzer = TaskAnalyzer()
        self.executor = ExecutionDriver(
            projects_path=self.config.projects_path,
            timeout=self.config.claude_timeout,
        )

        # Email clients (lazy init)
        self._gmail: Optional[GmailClient] = None
        self._calendar: Optional[CalendarClient] = None

    @property
    def gmail(self) -> GmailClient:
        if self._gmail is None:
            self._gmail = GmailClient()
        return self._gmail

    @property
    def calendar(self) -> CalendarClient:
        if self._calendar is None:
            self._calendar = CalendarClient()
        return self._calendar

    async def start(self):
        """Start the daemon."""
        logger.info("Starting orchestration daemon...")

        # Initialize database
        await self.db.init()

        # Authenticate Google Tasks
        if not self.google_tasks.authenticate():
            logger.error("Failed to authenticate with Google Tasks")
            return

        # Start Telegram bot
        await self.telegram.start()

        # Setup approval callback
        self.telegram.set_approval_callback(self._handle_approval)

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        self.running = True
        logger.info("Daemon started. Polling for tasks...")

        # Send startup notification
        await self.telegram.send_simple_notification(
            f"Task Automation Daemon Started\n\n"
            f"Polling interval: {self.config.poll_interval}s\n"
            f"Projects path: {self.config.projects_path}",
            project="daemon",
            level="success"
        )

        # Main loop
        await self._run_loop()

    async def stop(self):
        """Stop the daemon gracefully."""
        logger.info("Stopping daemon...")
        self.running = False

        await self.telegram.send_simple_notification("Task Automation Daemon Stopped", project="daemon", level="warning")
        await self.telegram.stop()

    async def _run_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                await self._poll_and_process()
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                await self.telegram.send_simple_notification(f"Daemon error: {str(e)[:200]}", project="daemon", level="error")

            await asyncio.sleep(self.config.poll_interval)

    async def _poll_and_process(self):
        """Poll for new tasks and process them."""
        # Get sync token
        sync_token = await self.db.get_sync_token("@default")

        # Fetch tasks
        tasks, new_sync_token = self.google_tasks.get_tasks(
            "@default", sync_token=sync_token
        )

        # Save new sync token
        if new_sync_token:
            await self.db.save_sync_token("@default", new_sync_token)

        # Process new tasks
        for google_task in tasks:
            if google_task.get("status") == "completed":
                continue

            await self._process_task(google_task)

        # Check for approved tasks waiting for execution
        approved_tasks = await self.db.get_tasks_by_status([TaskStatus.APPROVED.value])
        for task in approved_tasks:
            await self._execute_task(task)

    async def _process_task(self, google_task: dict):
        """Process a single task from Google Tasks."""
        task_id = google_task.get("id")
        title = google_task.get("title", "")
        notes = google_task.get("notes")

        # Check if already processed
        existing = await self.db.get_task_by_google_id(task_id)
        if existing:
            return

        logger.info(f"New task detected: {title}")

        # Analyze feasibility
        result = self.analyzer.analyze(title, notes)

        # Create task record
        task = TaskRecord(
            id=None,
            google_task_id=task_id,
            google_list_id="@default",
            title=title,
            notes=notes,
            due_date=google_task.get("due"),
            status=TaskStatus.ANALYZING.value,
            feasibility_score=result.score,
            feasibility_reason=result.reason,
            complexity=result.complexity.value,
            execution_plan=result.suggested_plan,
        )

        task = await self.db.create_task(task)

        if not result.can_do:
            # Task cannot be automated
            await self.db.update_task(task.id, status=TaskStatus.DENIED.value)
            await self.telegram.send_simple_notification(
                f"Task Cannot Be Automated: {title}\n\nReason: {result.reason}",
                project="daemon",
                level="warning"
            )
            return

        # Request approval
        if self.config.require_approval:
            await self.db.update_task(task.id, status=TaskStatus.AWAITING_APPROVAL.value)

            context = f"Task: {title}\n"
            if notes:
                context += f"Notes: {notes}\n"
            context += f"Feasibility: {result.score}/10 - {result.reason}\n"
            context += f"Complexity: {result.complexity.value}\n"
            if result.suggested_plan:
                context += f"Plan: {result.suggested_plan}"

            approved = await self.telegram.send_approval_request(
                action=f"Execute task: {title}",
                context=context,
                project="daemon",
                consequences=f"Will execute with complexity {result.complexity.value}",
                reversible=False,
            )

            if approved:
                await self.db.update_task(task.id, status=TaskStatus.APPROVED.value)
            else:
                await self.db.update_task(task.id, status=TaskStatus.DENIED.value)
        else:
            # Auto-execute if approval not required
            await self.db.update_task(task.id, status=TaskStatus.APPROVED.value)

    async def _handle_approval(self, response: ApprovalResponse):
        """Handle approval response from Telegram."""
        task = await self.db.get_task(response.task_id)
        if not task:
            return

        if response.status == ApprovalStatus.APPROVED:
            logger.info(f"Task approved: {task.title}")
            await self.db.update_task(task.id, status=TaskStatus.APPROVED.value)

        elif response.status == ApprovalStatus.DENIED:
            logger.info(f"Task denied: {task.title}")
            await self.db.update_task(task.id, status=TaskStatus.DENIED.value)

        elif response.status == ApprovalStatus.MODIFY:
            logger.info(f"Task modification requested: {task.title}")
            # Append modification instructions to notes
            new_notes = f"{task.notes or ''}\n\n[User modification]: {response.message}"
            await self.db.update_task(
                task.id,
                notes=new_notes,
                status=TaskStatus.APPROVED.value,
            )

    async def _execute_task(self, task: TaskRecord):
        """Execute an approved task."""
        logger.info(f"Executing task: {task.title}")

        await self.db.update_task(task.id, status=TaskStatus.EXECUTING.value)
        await self.telegram.send_simple_notification(
            f"Executing Task: {task.title}",
            project="daemon",
            level="info"
        )

        # Execute with Claude Code
        success, message = await self.executor.execute_task(task)

        if success:
            await self.db.update_task(task.id, status=TaskStatus.COMPLETED.value)

            # Mark complete in Google Tasks
            self.google_tasks.complete_task(task.google_list_id, task.google_task_id)

            await self.telegram.send_simple_notification(
                f"Task Completed: {task.title}\n\n{message[:500]}",
                level="success"
            )
        else:
            await self.db.update_task(task.id, status=TaskStatus.FAILED.value)
            await self.telegram.send_simple_notification(
                f"Task Failed: {task.title}\n\n{message[:500]}",
                level="error"
            )

        logger.info(f"Task {'completed' if success else 'failed'}: {task.title}")


def validate_environment() -> list[str]:
    """Validate required environment variables. Returns list of errors."""
    errors = []

    # Required
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        errors.append("TELEGRAM_BOT_TOKEN is required")

    # Check credentials file exists
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "data/credentials/credentials.json")
    if not Path(creds_file).exists():
        errors.append(f"Google credentials file not found: {creds_file}")

    return errors


async def main():
    """Main entry point."""
    # Change to project directory
    os.chdir(Path(__file__).parent.parent.parent)

    # Validate environment
    errors = validate_environment()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    config = DaemonConfig(
        poll_interval=int(os.getenv("POLL_INTERVAL", "30")),
    )

    daemon = OrchestrationDaemon(config)
    await daemon.start()


if __name__ == "__main__":
    asyncio.run(main())
