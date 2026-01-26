#!/usr/bin/env python3
"""
Task Automation MCP Server
Connects Google Tasks to Claude Code for autonomous task completion.
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

from .database import Database, TaskRecord, TaskStatus
from .google_tasks import GoogleTasksClient
from .gmail_client import GmailClient
from .calendar_client import CalendarClient
from .telegram_bot import TelegramBot, ApprovalStatus
from .analyzer import TaskAnalyzer, TaskComplexity
from .executor import TaskExecutor
from .context import ContextManager
from .canvas_client import CanvasClient
from .github_client import GitHubClient
from .canvas_browser import CanvasBrowser
from . import project_memory
from .visual_verification import get_verifier
from .session_manager import get_session_manager
from .knowledge import retriever as knowledge_retriever
from .plans.store import get_plan_store, OptimisticLockError, PlanNotFoundError
from .plans.models import Plan, Phase, Task, Decision, PlanOverview, PlanStatus, TaskStatus
from .orchestrator.planner import get_planner
from .orchestrator.verifier import get_verifier as get_code_verifier

# Load environment variables
load_dotenv()

# Initialize MCP server
mcp = FastMCP("claude-orchestrator")

# Initialize components
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"

db = Database(str(DATA_DIR / "task_automation.db"))
google_client = GoogleTasksClient(
    credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", str(DATA_DIR / "credentials" / "credentials.json")),
    token_file=str(DATA_DIR / "credentials" / "token.json"),
)
gmail_client = GmailClient(
    credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", str(DATA_DIR / "credentials" / "credentials.json")),
    token_file=str(DATA_DIR / "credentials" / "gmail_token.json"),
)
calendar_client = CalendarClient(
    credentials_file=os.getenv("GOOGLE_CREDENTIALS_FILE", str(DATA_DIR / "credentials" / "credentials.json")),
    token_file=str(DATA_DIR / "credentials" / "calendar_token.json"),
)
telegram_bot: Optional[TelegramBot] = None
analyzer = TaskAnalyzer()
executor = TaskExecutor(db)
context_manager = ContextManager(str(DATA_DIR / "personal_context.json"))
canvas_client = CanvasClient(token_file=str(DATA_DIR / "credentials" / "canvas_token.txt"))
github_client = GitHubClient(token_file=str(DATA_DIR / "credentials" / "github_token.txt"))
canvas_browser = CanvasBrowser(headless=True, session_dir=str(DATA_DIR / "browser_sessions"))

# Pending email sends awaiting approval
_pending_email_sends: dict[str, dict] = {}

# Background task reference
_poller_task: Optional[asyncio.Task] = None
_initialized = False


async def ensure_initialized():
    """Ensure all components are initialized."""
    global _initialized, telegram_bot

    if _initialized:
        return

    # Initialize database
    await db.init()

    # Initialize Telegram bot if configured
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token:
        telegram_bot = TelegramBot(token, chat_id)

        # Set up callbacks
        async def on_approval(response):
            if response.status == ApprovalStatus.APPROVED:
                await db.update_task(response.task_id, status=TaskStatus.APPROVED.value)
            elif response.status == ApprovalStatus.DENIED:
                await db.update_task(response.task_id, status=TaskStatus.DENIED.value)
            elif response.status == ApprovalStatus.MODIFY:
                # Update notes with modification instructions
                task = await db.get_task(response.task_id)
                if task:
                    new_notes = f"{task.notes or ''}\n\n[User modification]: {response.message}"
                    await db.update_task(response.task_id, notes=new_notes, status=TaskStatus.APPROVED.value)

        telegram_bot.set_approval_callback(on_approval)

        # Set progress callback on executor
        async def on_progress(task_id: str, message: str):
            if telegram_bot:
                await telegram_bot.send_simple_notification(f"Progress: {message}", level="info")

        executor.set_progress_callback(on_progress)

        try:
            await telegram_bot.start()
        except Exception as e:
            print(f"Warning: Could not start Telegram bot: {e}")
            telegram_bot = None

    _initialized = True


async def process_new_task(google_task: dict, list_id: str) -> Optional[TaskRecord]:
    """Process a new task from Google Tasks."""
    await ensure_initialized()

    task_id = google_task.get("id")
    title = google_task.get("title", "")
    notes = google_task.get("notes")
    due = google_task.get("due")

    # Check if we already have this task
    existing = await db.get_task_by_google_id(task_id)
    if existing:
        return existing

    # Analyze the task
    result = analyzer.analyze(title, notes)

    # Create task record
    task = TaskRecord(
        id=None,
        google_task_id=task_id,
        google_list_id=list_id,
        title=title,
        notes=notes,
        due_date=due,
        status=TaskStatus.ANALYZING.value,
        feasibility_score=result.score,
        feasibility_reason=result.reason,
        complexity=result.complexity.value,
        execution_plan=result.suggested_plan,
    )

    task = await db.create_task(task)

    # If we have Telegram, send approval request
    if telegram_bot and result.can_do:
        await db.update_task(task.id, status=TaskStatus.AWAITING_APPROVAL.value)

        context = f"Task: {title}\n"
        if notes:
            context += f"Notes: {notes}\n"
        context += f"Feasibility: {result.score}/10 - {result.reason}\n"
        context += f"Complexity: {result.complexity.value}\n"
        if result.suggested_plan:
            context += f"Plan: {result.suggested_plan}"

        approved = await telegram_bot.send_approval_request(
            action=f"Execute task: {title}",
            context=context,
            project="claude-orchestrator",
            consequences=f"Will execute with complexity {result.complexity.value}",
            reversible=False,
        )

        if approved:
            await db.update_task(task.id, status=TaskStatus.APPROVED.value)
        else:
            await db.update_task(task.id, status=TaskStatus.DENIED.value)
    elif not result.can_do:
        await db.update_task(task.id, status=TaskStatus.DENIED.value)

    return task


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def health_check() -> str:
    """
    Check the health of the Task Automation server.
    Returns status of all components.
    """
    await ensure_initialized()

    status = {
        "server": "running",
        "database": "connected",
        "google_tasks": "not_authenticated",
        "telegram": "not_configured",
    }

    # Check Google Tasks
    if google_client.authenticate():
        status["google_tasks"] = "authenticated"

    # Check Telegram
    if telegram_bot:
        status["telegram"] = "connected" if telegram_bot.chat_id else "awaiting_start"

    return json.dumps(status, indent=2)


@mcp.tool()
async def list_task_lists() -> str:
    """
    List all Google Task lists available.
    Use this to find the list_id for other operations.
    """
    await ensure_initialized()

    lists = google_client.list_task_lists()
    return json.dumps([{"id": l["id"], "title": l["title"]} for l in lists], indent=2)


@mcp.tool()
async def poll_google_tasks(list_id: str = "@default") -> str:
    """
    Poll Google Tasks for new tasks.

    Args:
        list_id: The task list ID to poll (default: primary list)

    Returns new tasks found and their analysis.
    """
    await ensure_initialized()

    # Get sync token if we have one
    sync_token = await db.get_sync_token(list_id)

    # Fetch tasks
    tasks, new_sync_token = google_client.get_tasks(list_id, sync_token=sync_token)

    # Save new sync token
    if new_sync_token:
        await db.save_sync_token(list_id, new_sync_token)

    # Process each new task
    results = []
    for google_task in tasks:
        if google_task.get("status") == "completed":
            continue

        task = await process_new_task(google_task, list_id)
        if task:
            results.append({
                "id": task.id,
                "title": task.title,
                "feasibility": task.feasibility_score,
                "complexity": task.complexity,
                "status": task.status,
            })

    return json.dumps({
        "tasks_found": len(results),
        "tasks": results,
    }, indent=2)


@mcp.tool()
async def get_pending_tasks() -> str:
    """
    Get all tasks pending action (approval, execution, etc).
    Returns tasks grouped by status.
    """
    await ensure_initialized()

    statuses = [
        TaskStatus.PENDING.value,
        TaskStatus.ANALYZING.value,
        TaskStatus.AWAITING_APPROVAL.value,
        TaskStatus.APPROVED.value,
        TaskStatus.EXECUTING.value,
    ]

    tasks = await db.get_tasks_by_status(statuses)

    grouped = {}
    for task in tasks:
        if task.status not in grouped:
            grouped[task.status] = []
        grouped[task.status].append({
            "id": task.id,
            "title": task.title,
            "feasibility": task.feasibility_score,
            "complexity": task.complexity,
        })

    return json.dumps(grouped, indent=2)


@mcp.tool()
async def get_task_details(task_id: str) -> str:
    """
    Get full details of a specific task.

    Args:
        task_id: The task ID (our internal ID, not Google's)
    """
    await ensure_initialized()

    task = await db.get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task not found: {task_id}"})

    logs = await db.get_execution_logs(task_id)

    return json.dumps({
        "task": task.to_dict(),
        "execution_logs": logs,
    }, indent=2)


@mcp.tool()
async def check_feasibility(title: str, notes: str = "") -> str:
    """
    Check if a task is feasible for Claude to complete.

    Args:
        title: The task title/summary
        notes: Additional task details
    """
    result = analyzer.analyze(title, notes)

    return json.dumps({
        "can_do": result.can_do,
        "score": result.score,
        "reason": result.reason,
        "complexity": result.complexity.value,
        "required_tools": result.required_tools,
        "blockers": result.blockers,
        "suggested_plan": result.suggested_plan,
    }, indent=2)


@mcp.tool()
async def request_approval(task_id: str) -> str:
    """
    Send a Telegram approval request for a task.

    Args:
        task_id: The task ID to request approval for
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    task = await db.get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task not found: {task_id}"})

    context = f"Task: {task.title}\n"
    if task.notes:
        context += f"Notes: {task.notes}\n"
    if task.feasibility_score:
        context += f"Feasibility: {task.feasibility_score}/10\n"
    if task.feasibility_reason:
        context += f"Reason: {task.feasibility_reason}\n"
    if task.complexity:
        context += f"Complexity: {task.complexity}\n"
    if task.execution_plan:
        context += f"Plan: {task.execution_plan}"

    approved = await telegram_bot.send_approval_request(
        action=f"Execute task: {task.title}",
        context=context,
        project="claude-orchestrator",
        consequences=f"Will execute task with complexity {task.complexity or 'unknown'}",
        reversible=False,
    )

    if approved:
        await db.update_task(task_id, status=TaskStatus.APPROVED.value)
        return json.dumps({"success": True, "approved": True})
    else:
        await db.update_task(task_id, status=TaskStatus.DENIED.value)
        return json.dumps({"success": True, "approved": False})


@mcp.tool()
async def execute_task(task_id: str) -> str:
    """
    Prepare and execute an approved task.

    Returns the execution prompt and configuration for Claude to use.

    Args:
        task_id: The task ID to execute
    """
    await ensure_initialized()

    task = await db.get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task not found: {task_id}"})

    if task.status not in [TaskStatus.APPROVED.value, TaskStatus.PENDING.value]:
        return json.dumps({"error": f"Task not ready for execution. Status: {task.status}"})

    # Prepare execution
    config = await executor.prepare_execution(task_id)

    if telegram_bot:
        await telegram_bot.send_simple_notification(f"Starting execution: {task.title}", level="info")

    return json.dumps(config, indent=2)


@mcp.tool()
async def complete_task(task_id: str, success: bool, result_message: str) -> str:
    """
    Mark a task as completed (or failed) and update Google Tasks.

    Args:
        task_id: The task ID to complete
        success: Whether the task was successful
        result_message: Summary of what was done
    """
    await ensure_initialized()

    task = await db.get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task not found: {task_id}"})

    # Mark completed in our database
    await executor.mark_completed(task_id, success, result_message)

    # Mark completed in Google Tasks if successful
    if success:
        google_client.complete_task(task.google_list_id, task.google_task_id)

    # Notify via Telegram
    if telegram_bot:
        level = "success" if success else "error"
        await telegram_bot.send_simple_notification(
            f"Task {'Completed' if success else 'Failed'}: {task.title}\n\n{result_message}",
            level=level
        )

    return json.dumps({
        "success": True,
        "task_status": "completed" if success else "failed",
    })


@mcp.tool()
async def create_google_task(
    title: str,
    notes: str = "",
    due: str = "",
    list_id: str = "@default"
) -> str:
    """
    Create a new task in Google Tasks.

    Args:
        title: Task title
        notes: Task notes/description
        due: Due date in RFC 3339 format (e.g., "2025-01-15T00:00:00.000Z") or YYYY-MM-DD
        list_id: Which task list to add to (default: primary)
    """
    await ensure_initialized()

    # Convert YYYY-MM-DD to RFC 3339 if needed
    due_rfc3339 = None
    if due:
        if len(due) == 10 and "-" in due:  # YYYY-MM-DD format
            due_rfc3339 = f"{due}T00:00:00.000Z"
        else:
            due_rfc3339 = due

    result = google_client.create_task(list_id, title, notes, due_rfc3339)
    if result:
        response = {
            "success": True,
            "task_id": result["id"],
            "title": result["title"],
        }
        if result.get("due"):
            response["due"] = result["due"]
        return json.dumps(response)
    else:
        return json.dumps({"error": "Failed to create task"})


@mcp.tool()
async def start_background_poller(interval_seconds: int = 30) -> str:
    """
    Start background polling for new Google Tasks.

    Args:
        interval_seconds: How often to poll (default: 30)
    """
    global _poller_task
    await ensure_initialized()

    if _poller_task and not _poller_task.done():
        return json.dumps({"status": "already_running"})

    async def poll_loop():
        while True:
            try:
                # Poll default list
                await poll_google_tasks()
            except Exception as e:
                print(f"Polling error: {e}")
            await asyncio.sleep(interval_seconds)

    _poller_task = asyncio.create_task(poll_loop())

    return json.dumps({
        "status": "started",
        "interval_seconds": interval_seconds,
    })


@mcp.tool()
async def stop_background_poller() -> str:
    """Stop the background polling task."""
    global _poller_task

    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None
        return json.dumps({"status": "stopped"})

    return json.dumps({"status": "not_running"})


@mcp.tool()
async def get_telegram_status() -> str:
    """
    Get Telegram bot status and chat ID.
    If chat_id is empty, user needs to /start the bot.
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({
            "configured": False,
            "error": "TELEGRAM_BOT_TOKEN not set in .env",
        })

    return json.dumps({
        "configured": True,
        "chat_id": telegram_bot.chat_id,
        "needs_start": not telegram_bot.chat_id,
        "pending_approvals": len(telegram_bot.pending_approvals),
        "pending_questions": len(telegram_bot.pending_questions),
    })


# =============================================================================
# Telegram Communication Tools (for Claude Code MCP integration)
# =============================================================================

@mcp.tool()
async def telegram_notify(
    message: str,
    project: str = "",
    level: str = "info",
) -> str:
    """
    Send a one-way notification to Telegram. Does not wait for response.

    Use this for status updates, progress notifications, or informational messages.

    Args:
        message: The message to send
        project: Project name for header (e.g., "my-cli-tool")
        level: Notification level - "info", "warning", "error", or "success"

    Examples:
        - telegram_notify("Starting build process", project="my-app", level="info")
        - telegram_notify("Tests passed!", project="api-service", level="success")
        - telegram_notify("Memory usage high", level="warning")
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    success = await telegram_bot.send_simple_notification(
        message=message,
        project=project,
        level=level,
    )

    return json.dumps({
        "success": success,
        "message": "Notification sent" if success else "Failed to send notification",
    })


@mcp.tool()
async def telegram_ask(
    question: str,
    options: str,
    project: str = "",
    context: str = "",
    allow_other: bool = True,
) -> str:
    """
    Ask user a question with predefined options. BLOCKS until user responds.

    Sends inline buttons to Telegram. User can tap an option or reply with custom text.

    Args:
        question: The question to ask
        options: Comma-separated list of options (e.g., "FastAPI,Flask,Django")
        project: Project name for header
        context: Additional context explaining why you're asking
        allow_other: Allow user to provide custom text response (default: True)

    Returns:
        The selected option or user's custom text response

    Examples:
        - telegram_ask("Which framework?", "FastAPI,Flask,Django", project="api")
        - telegram_ask("Database choice?", "PostgreSQL,SQLite,MongoDB", context="We need persistence")
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    # Parse options
    option_list = [opt.strip() for opt in options.split(",") if opt.strip()]

    if len(option_list) < 2:
        return json.dumps({"error": "At least 2 options required"})

    response = await telegram_bot.send_question_with_options(
        question=question,
        options=option_list,
        project=project,
        context=context,
        allow_other=allow_other,
    )

    return json.dumps({
        "response": response,
        "question": question,
    })


@mcp.tool()
async def telegram_ask_freeform(
    question: str,
    project: str = "",
    context: str = "",
    hint: str = "",
) -> str:
    """
    Ask user an open-ended question. BLOCKS until user replies.

    User must reply to the question message in Telegram.

    Args:
        question: The question to ask
        project: Project name for header
        context: Additional context
        hint: Example of expected response format

    Returns:
        User's text response

    Examples:
        - telegram_ask_freeform("What should the API endpoint name be?", project="api")
        - telegram_ask_freeform("Describe the feature", hint="e.g., 'A button that exports data to CSV'")
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    response = await telegram_bot.send_question_freeform(
        question=question,
        project=project,
        context=context,
        hint=hint,
    )

    return json.dumps({
        "response": response,
        "question": question,
    })


@mcp.tool()
async def telegram_phase_update(
    project: str,
    phase_number: int,
    total_phases: int,
    phase_name: str,
    summary: str,
    tests_passed: int = 0,
    tests_failed: int = 0,
    tests_skipped: int = 0,
    commit_hash: str = "",
    concerns: str = "",
    next_phase: str = "",
) -> str:
    """
    Send a structured phase completion update. One-way notification.

    Use this after completing a significant phase of implementation.

    Args:
        project: Project name
        phase_number: Current phase (1-indexed)
        total_phases: Total phases planned
        phase_name: Name of completed phase (e.g., "Implement OCR Pipeline")
        summary: What was implemented (bullet points work well)
        tests_passed: Number of tests passed
        tests_failed: Number of tests failed
        tests_skipped: Number of tests skipped
        commit_hash: Git commit hash if committed
        concerns: Comma-separated list of concerns
        next_phase: Description of next phase

    Example:
        telegram_phase_update(
            project="geoguessr-ai",
            phase_number=2,
            total_phases=5,
            phase_name="Implement OCR Pipeline",
            summary="- Added EasyOCR wrapper\\n- Integrated with vision pipeline",
            tests_passed=12,
            tests_failed=0,
            commit_hash="abc123f",
            next_phase="Geographic reasoning module"
        )
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    test_results = None
    if tests_passed or tests_failed or tests_skipped:
        test_results = {
            "passed": tests_passed,
            "failed": tests_failed,
            "skipped": tests_skipped,
        }

    concerns_list = None
    if concerns:
        concerns_list = [c.strip() for c in concerns.split(",") if c.strip()]

    success = await telegram_bot.send_phase_update(
        project=project,
        phase_number=phase_number,
        total_phases=total_phases,
        phase_name=phase_name,
        summary=summary,
        test_results=test_results,
        commit_hash=commit_hash,
        concerns=concerns_list,
        next_phase=next_phase,
    )

    return json.dumps({
        "success": success,
        "phase": f"{phase_number}/{total_phases}",
    })


@mcp.tool()
async def telegram_request_approval(
    action: str,
    context: str,
    project: str = "",
    consequences: str = "",
    reversible: bool = True,
) -> str:
    """
    Request yes/no approval for an action. BLOCKS until user responds.

    Use this for destructive operations, significant changes, or actions that need explicit consent.

    Args:
        action: What action needs approval (e.g., "Delete deprecated test files")
        context: Why this action is needed
        project: Project name for header
        consequences: What happens if approved (e.g., "15 files will be deleted")
        reversible: Whether action can be undone (default: True)

    Returns:
        JSON with "approved" boolean

    Example:
        telegram_request_approval(
            action="Delete deprecated test files",
            context="These tests are for removed features and are failing",
            project="my-app",
            consequences="15 files will be deleted from tests/deprecated/",
            reversible=True
        )
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    approved = await telegram_bot.send_approval_request(
        action=action,
        context=context,
        project=project,
        consequences=consequences,
        reversible=reversible,
    )

    return json.dumps({
        "approved": approved,
        "action": action,
    })


@mcp.tool()
async def telegram_escalate(
    error_type: str,
    description: str,
    context: str,
    attempts: int,
    project: str = "",
    suggestions: str = "",
) -> str:
    """
    Escalate an issue that needs human intervention. BLOCKS until user responds.

    Use this after multiple failed attempts to fix an issue (default: 5 attempts).

    Args:
        error_type: Category of error - "test_failure", "build_error", "unclear_requirement",
                    "external_auth", "dependency_issue", "other"
        description: What went wrong
        context: Full context including stack traces, what was tried
        attempts: How many times you tried to fix it
        project: Project name
        suggestions: Comma-separated suggestions for resolution

    Returns:
        User's guidance/instructions

    Example:
        telegram_escalate(
            error_type="test_failure",
            description="test_user_auth keeps failing with 'connection refused'",
            context="Tried mocking connection, using SQLite, checking docker-compose",
            attempts=5,
            project="my-app",
            suggestions="Start PostgreSQL locally,Provide test database credentials,Switch to SQLite"
        )
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    suggestions_list = None
    if suggestions:
        suggestions_list = [s.strip() for s in suggestions.split(",") if s.strip()]

    response = await telegram_bot.send_escalation(
        error_type=error_type,
        description=description,
        context=context,
        attempts=attempts,
        project=project,
        suggestions=suggestions_list,
    )

    return json.dumps({
        "response": response,
        "error_type": error_type,
    })


# =============================================================================
# Dual-Input Tools (Terminal + Telegram)
# =============================================================================

@mcp.tool()
async def ask_dual(
    question: str,
    options: str,
    project: str = "",
    context: str = "",
) -> str:
    """
    Send a question to Telegram and return immediately. Does NOT block.

    Use this for dual-input: question appears on Telegram with buttons,
    and Claude can also accept the answer via terminal.

    Flow:
    1. Call ask_dual() - sends to Telegram, returns question_id
    2. Show same question in terminal to user
    3. User responds via EITHER Telegram button OR terminal
    4. If terminal: call respond_dual(question_id, answer)
    5. If Telegram: call check_dual(question_id) to get the answer

    Args:
        question: The question to ask
        options: Comma-separated list of options (e.g., "Option A,Option B,Option C")
        project: Project name for header
        context: Additional context explaining why you're asking

    Returns:
        JSON with question_id for tracking
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured", "question_id": ""})

    # Parse options
    option_list = [opt.strip() for opt in options.split(",") if opt.strip()]

    if len(option_list) < 2:
        return json.dumps({"error": "At least 2 options required", "question_id": ""})

    question_id = await telegram_bot.send_question_non_blocking(
        question=question,
        options=option_list,
        project=project,
        context=context,
        allow_other=True,
    )

    if not question_id:
        return json.dumps({"error": "Failed to send question", "question_id": ""})

    return json.dumps({
        "question_id": question_id,
        "question": question,
        "options": option_list,
        "status": "pending",
    })


@mcp.tool()
async def respond_dual(question_id: str, answer: str) -> str:
    """
    Submit an answer to a pending dual-input question (from terminal).

    Call this when the user responds in the terminal instead of Telegram.

    Args:
        question_id: The question ID from ask_dual
        answer: The user's answer

    Returns:
        JSON with success status
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    success = await telegram_bot.answer_question(question_id, answer)

    if success:
        return json.dumps({
            "success": True,
            "message": "Answer submitted",
            "answer": answer,
        })
    else:
        return json.dumps({
            "success": False,
            "error": "Question not found or already answered",
        })


@mcp.tool()
async def check_dual(question_id: str) -> str:
    """
    Check if a dual-input question was answered via Telegram.

    Call this to see if the user clicked a button in Telegram.

    Args:
        question_id: The question ID from ask_dual

    Returns:
        JSON with answered status and response if available
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    status = telegram_bot.check_question_status(question_id)

    return json.dumps(status)


@mcp.tool()
async def cancel_dual(question_id: str) -> str:
    """
    Cancel a pending dual-input question.

    Args:
        question_id: The question ID to cancel

    Returns:
        JSON with success status
    """
    await ensure_initialized()

    if not telegram_bot:
        return json.dumps({"error": "Telegram bot not configured"})

    success = await telegram_bot.cancel_question(question_id)

    return json.dumps({
        "success": success,
        "message": "Question cancelled" if success else "Question not found",
    })


# =============================================================================
# Secrets Management Tools
# =============================================================================

SECRETS_FILE = Path.home() / "personal_projects" / ".secrets.json"


def _load_secrets() -> dict:
    """Load secrets from file."""
    if not SECRETS_FILE.exists():
        return {"keys": {}, "last_updated": None}
    try:
        with open(SECRETS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"keys": {}, "last_updated": None}


def _save_secrets(data: dict):
    """Save secrets to file."""
    data["last_updated"] = datetime.now().isoformat()
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SECRETS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@mcp.tool()
async def get_secret(key_name: str) -> str:
    """
    Get a secret value by name.

    Args:
        key_name: Name of the secret (e.g., "openai", "telegram_bot")

    Returns:
        The secret value or error if not found/inactive

    Example:
        get_secret("openai")  # Returns the OpenAI API key
    """
    secrets = _load_secrets()
    keys = secrets.get("keys", {})

    if key_name not in keys:
        return json.dumps({
            "error": f"Secret '{key_name}' not found",
            "available": list(keys.keys()),
        })

    secret = keys[key_name]
    if not secret.get("active", True):
        return json.dumps({
            "error": f"Secret '{key_name}' is inactive",
            "notes": secret.get("notes", ""),
        })

    return json.dumps({
        "key": secret["key"],
        "notes": secret.get("notes", ""),
    })


@mcp.tool()
async def list_secrets() -> str:
    """
    List all secrets with their status. Does NOT show actual values.

    Returns list of secret names, active status, and notes.
    """
    secrets = _load_secrets()
    keys = secrets.get("keys", {})

    result = []
    for name, data in keys.items():
        result.append({
            "name": name,
            "active": data.get("active", True),
            "notes": data.get("notes", ""),
            "has_value": bool(data.get("key")),
        })

    return json.dumps({
        "secrets": result,
        "last_updated": secrets.get("last_updated"),
        "file": str(SECRETS_FILE),
    }, indent=2)


@mcp.tool()
async def set_secret(
    key_name: str,
    value: str,
    notes: str = "",
) -> str:
    """
    Add or update a secret.

    Args:
        key_name: Name of the secret (e.g., "openai", "postgres_test")
        value: The secret value (API key, connection string, etc.)
        notes: Optional notes about this secret

    Example:
        set_secret("openai", "sk-...", notes="GPT-4 API access")
    """
    secrets = _load_secrets()

    if "keys" not in secrets:
        secrets["keys"] = {}

    secrets["keys"][key_name] = {
        "key": value,
        "active": True,
        "notes": notes,
    }

    _save_secrets(secrets)

    return json.dumps({
        "success": True,
        "message": f"Secret '{key_name}' saved",
    })


@mcp.tool()
async def deactivate_secret(key_name: str) -> str:
    """
    Mark a secret as inactive (without deleting it).

    Args:
        key_name: Name of the secret to deactivate
    """
    secrets = _load_secrets()
    keys = secrets.get("keys", {})

    if key_name not in keys:
        return json.dumps({
            "error": f"Secret '{key_name}' not found",
        })

    keys[key_name]["active"] = False
    _save_secrets(secrets)

    return json.dumps({
        "success": True,
        "message": f"Secret '{key_name}' deactivated",
    })


@mcp.tool()
async def activate_secret(key_name: str) -> str:
    """
    Reactivate a previously deactivated secret.

    Args:
        key_name: Name of the secret to activate
    """
    secrets = _load_secrets()
    keys = secrets.get("keys", {})

    if key_name not in keys:
        return json.dumps({
            "error": f"Secret '{key_name}' not found",
        })

    keys[key_name]["active"] = True
    _save_secrets(secrets)

    return json.dumps({
        "success": True,
        "message": f"Secret '{key_name}' activated",
    })


# =============================================================================
# Gmail Tools
# =============================================================================

@mcp.tool()
async def search_emails(query: str, max_results: int = 10) -> str:
    """
    Search emails using Gmail query syntax.

    Args:
        query: Gmail search query (e.g., "from:someone@example.com", "subject:meeting", "is:unread")
        max_results: Maximum number of emails to return

    Examples:
        - "from:professor@university.edu"
        - "subject:internship newer_than:30d"
        - "is:unread"
    """
    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    emails = gmail_client.search_emails(query, max_results)

    return json.dumps([{
        "id": e.id,
        "subject": e.subject,
        "from": e.sender,
        "date": e.date,
        "snippet": e.snippet,
    } for e in emails], indent=2)


@mcp.tool()
async def read_email(email_id: str) -> str:
    """
    Read the full content of an email.

    Args:
        email_id: The email ID from search_emails
    """
    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    email = gmail_client.get_email(email_id, include_body=True)
    if not email:
        return json.dumps({"error": f"Email not found: {email_id}"})

    return json.dumps({
        "id": email.id,
        "subject": email.subject,
        "from": email.sender,
        "to": email.to,
        "date": email.date,
        "body": email.body,
    }, indent=2)


@mcp.tool()
async def draft_email(to: str, subject: str, body: str, reply_to_id: str = "") -> str:
    """
    Create an email draft (does NOT send).

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body text
        reply_to_id: Optional email ID to reply to
    """
    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    draft = gmail_client.create_draft(
        to=to,
        subject=subject,
        body=body,
        reply_to_id=reply_to_id if reply_to_id else None,
    )

    if not draft:
        return json.dumps({"error": "Failed to create draft"})

    return json.dumps({
        "success": True,
        "draft_id": draft.id,
        "message": f"Draft created. Use send_email_with_approval to send.",
    })


@mcp.tool()
async def send_email_with_approval(draft_id: str) -> str:
    """
    Request approval to send an email draft via Telegram.

    IMPORTANT: This does NOT send immediately. It sends a Telegram notification
    asking for approval. The email will only be sent if you approve via Telegram.

    Args:
        draft_id: The draft ID from draft_email
    """
    await ensure_initialized()

    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    if not telegram_bot:
        return json.dumps({"error": "Telegram not configured - cannot request approval"})

    # Get draft details
    drafts = gmail_client.list_drafts(max_results=50)
    draft = next((d for d in drafts if d.id == draft_id), None)

    if not draft:
        return json.dumps({"error": f"Draft not found: {draft_id}"})

    # Store pending send
    import uuid
    approval_id = str(uuid.uuid4())[:8]
    _pending_email_sends[approval_id] = {
        "draft_id": draft_id,
        "to": draft.to,
        "subject": draft.subject,
        "body": draft.body[:500],
    }

    # Send Telegram approval request
    message = (
        f"Email Send Request\n\n"
        f"To: {draft.to}\n"
        f"Subject: {draft.subject}\n\n"
        f"Preview:\n{draft.body[:300]}{'...' if len(draft.body) > 300 else ''}\n\n"
        f"Reply with 'send {approval_id}' to send, or 'cancel {approval_id}' to cancel."
    )

    await telegram_bot.send_simple_notification(message, project="gmail", level="info")

    return json.dumps({
        "status": "awaiting_approval",
        "approval_id": approval_id,
        "message": "Telegram notification sent. Reply 'send {approval_id}' to approve.",
    })


@mcp.tool()
async def confirm_send_email(approval_id: str) -> str:
    """
    Actually send an email after approval.

    Args:
        approval_id: The approval ID from send_email_with_approval
    """
    if approval_id not in _pending_email_sends:
        return json.dumps({"error": f"No pending email with approval ID: {approval_id}"})

    pending = _pending_email_sends.pop(approval_id)
    draft_id = pending["draft_id"]

    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    success = gmail_client.send_draft(draft_id)

    if success:
        if telegram_bot:
            await telegram_bot.send_simple_notification(
                f"Email Sent\n\nTo: {pending['to']}\nSubject: {pending['subject']}",
                project="gmail",
                level="success"
            )
        return json.dumps({"success": True, "message": "Email sent!"})
    else:
        return json.dumps({"error": "Failed to send email"})


@mcp.tool()
async def list_drafts() -> str:
    """List all email drafts."""
    if not gmail_client.authenticate():
        return json.dumps({"error": "Gmail not authenticated"})

    drafts = gmail_client.list_drafts()

    return json.dumps([{
        "id": d.id,
        "to": d.to,
        "subject": d.subject,
    } for d in drafts], indent=2)


# =============================================================================
# Calendar Tools
# =============================================================================

@mcp.tool()
async def get_upcoming_events(days: int = 7) -> str:
    """
    Get upcoming calendar events.

    Args:
        days: Number of days to look ahead (default: 7)
    """
    if not calendar_client.authenticate():
        return json.dumps({"error": "Calendar not authenticated"})

    events = calendar_client.get_upcoming_events(days=days)

    return json.dumps([{
        "id": e.id,
        "summary": e.summary,
        "start": e.start,
        "end": e.end,
        "location": e.location,
    } for e in events], indent=2)


@mcp.tool()
async def get_todays_schedule() -> str:
    """Get today's calendar events."""
    if not calendar_client.authenticate():
        return json.dumps({"error": "Calendar not authenticated"})

    from datetime import datetime
    events = calendar_client.get_events_on_date(datetime.now())

    if not events:
        return json.dumps({"message": "No events scheduled for today", "events": []})

    return json.dumps({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "events": [{
            "summary": e.summary,
            "start": e.start,
            "end": e.end,
            "location": e.location,
        } for e in events],
    }, indent=2)


@mcp.tool()
async def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    recurrence: str = "",
    recurrence_count: int = 0,
    recurrence_until: str = "",
) -> str:
    """
    Create a new calendar event with optional recurrence.

    Args:
        summary: Event title
        start_time: Start time in ISO format (e.g., "2024-01-15T14:00:00")
        end_time: End time in ISO format
        description: Event description (optional)
        location: Event location (optional)
        recurrence: Recurrence frequency - "daily", "weekly", "monthly", "yearly" (optional)
        recurrence_count: Number of occurrences, e.g., 10 for "repeat 10 times" (optional)
        recurrence_until: End date for recurrence in ISO format (optional, alternative to count)

    Examples:
        - Weekly meeting for 10 weeks: recurrence="weekly", recurrence_count=10
        - Daily standup until end of month: recurrence="daily", recurrence_until="2024-01-31T23:59:59"
        - Monthly review forever: recurrence="monthly" (no end specified)
    """
    if not calendar_client.authenticate():
        return json.dumps({"error": "Calendar not authenticated"})

    from datetime import datetime

    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except ValueError as e:
        return json.dumps({"error": f"Invalid datetime format: {e}"})

    # Parse recurrence_until if provided
    until_dt = None
    if recurrence_until:
        try:
            until_dt = datetime.fromisoformat(recurrence_until)
        except ValueError as e:
            return json.dumps({"error": f"Invalid recurrence_until format: {e}"})

    event = calendar_client.create_event(
        summary=summary,
        start=start,
        end=end,
        description=description if description else None,
        location=location if location else None,
        recurrence=recurrence if recurrence else None,
        recurrence_count=recurrence_count if recurrence_count > 0 else None,
        recurrence_until=until_dt,
    )

    if not event:
        return json.dumps({"error": "Failed to create event"})

    result = {
        "success": True,
        "event_id": event.id,
        "summary": event.summary,
        "start": event.start,
        "link": event.html_link,
    }

    if recurrence:
        result["recurrence"] = recurrence
        if recurrence_count > 0:
            result["repeats"] = recurrence_count
        elif until_dt:
            result["until"] = recurrence_until

    return json.dumps(result)


@mcp.tool()
async def delete_calendar_event(event_id: str) -> str:
    """
    Delete a calendar event.

    Args:
        event_id: The event ID to delete (get this from get_upcoming_events or get_todays_schedule)
    """
    if not calendar_client.authenticate():
        return json.dumps({"error": "Calendar not authenticated"})

    success = calendar_client.delete_event(event_id)

    if success:
        return json.dumps({
            "success": True,
            "message": f"Event {event_id} deleted successfully",
        })
    else:
        return json.dumps({
            "success": False,
            "error": f"Failed to delete event {event_id}. It may not exist or you don't have permission.",
        })


@mcp.tool()
async def find_free_time(duration_minutes: int = 60, days_ahead: int = 7) -> str:
    """
    Find available time slots in your calendar.

    Args:
        duration_minutes: How long the slot needs to be (default: 60)
        days_ahead: How many days to search (default: 7)
    """
    if not calendar_client.authenticate():
        return json.dumps({"error": "Calendar not authenticated"})

    slots = calendar_client.find_free_slots(
        duration_minutes=duration_minutes,
        days_ahead=days_ahead,
    )

    return json.dumps({
        "available_slots": [{
            "start": start.isoformat(),
            "end": end.isoformat(),
        } for start, end in slots],
    }, indent=2)


# =============================================================================
# Personal Context Tools
# =============================================================================

@mcp.tool()
async def get_my_context() -> str:
    """
    Get Danny's personal context including preferences, projects, and style.
    Use this to personalize responses and understand the user's background.
    """
    return context_manager.get_full_context()


@mcp.tool()
async def find_project(query: str) -> str:
    """
    Find a project by name or alias.

    Args:
        query: Project name, partial name, or alias (e.g., "mlb", "health", "trading")

    Returns project details including path, description, and technologies.
    """
    project = context_manager.find_project(query)

    if not project:
        # List available projects as suggestions
        context = context_manager.load()
        available = [p.name for p in context.projects]
        return json.dumps({
            "error": f"Project '{query}' not found",
            "available_projects": available,
        })

    return json.dumps({
        "name": project.name,
        "path": project.path,
        "description": project.description,
        "technologies": project.technologies,
        "aliases": project.aliases,
    }, indent=2)


@mcp.tool()
async def list_my_projects() -> str:
    """List all of Danny's personal projects with descriptions."""
    context = context_manager.load()

    return json.dumps([{
        "name": p.name,
        "description": p.description,
        "technologies": p.technologies,
    } for p in context.projects], indent=2)


@mcp.tool()
async def update_context_notes(notes: str) -> str:
    """
    Update personal context notes with important information to remember.

    Args:
        notes: Notes to store (replaces existing notes)
    """
    context_manager.update_notes(notes)
    return json.dumps({"success": True, "message": "Notes updated"})


# =============================================================================
# Canvas LMS Tools (UChicago)
# =============================================================================

@mcp.tool()
async def setup_canvas(api_token: str) -> str:
    """
    Configure Canvas LMS with your API token.

    To get a token:
    1. Go to canvas.uchicago.edu
    2. Click Account -> Settings
    3. Scroll to "Approved Integrations"
    4. Click "+ New Access Token"
    5. Give it a name and copy the token

    Args:
        api_token: Your Canvas API access token
    """
    canvas_client.save_token(api_token)

    try:
        user = canvas_client.get_current_user()
        return json.dumps({
            "success": True,
            "message": f"Canvas configured for {user['name']}",
            "user": user,
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to verify token: {str(e)}"})


@mcp.tool()
async def get_canvas_courses(include_past: bool = False) -> str:
    """
    Get your Canvas courses.

    Args:
        include_past: Include past/completed courses (default: False)
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        courses = canvas_client.get_courses(include_past=include_past)
        return json.dumps([{
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "term": c.term,
        } for c in courses], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_assignments(
    course_id: int = 0,
    upcoming_only: bool = True,
    days_ahead: int = 14,
) -> str:
    """
    Get Canvas assignments and deadlines.

    Args:
        course_id: Specific course ID (0 for all courses)
        upcoming_only: Only show upcoming assignments (default: True)
        days_ahead: Number of days to look ahead (default: 14)
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        assignments = canvas_client.get_assignments(
            course_id=course_id if course_id else None,
            upcoming_only=upcoming_only,
            days_ahead=days_ahead,
        )

        return json.dumps([{
            "id": a.id,
            "name": a.name,
            "course": a.course_name,
            "due_at": a.due_at,
            "points": a.points_possible,
            "submitted": a.is_submitted,
            "score": a.score,
            "grade": a.grade,
        } for a in assignments], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_deadlines(days: int = 7) -> str:
    """
    Get upcoming assignment deadlines.

    Args:
        days: Number of days to look ahead (default: 7)
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        assignments = canvas_client.get_upcoming_deadlines(days=days)

        if not assignments:
            return json.dumps({
                "message": f"No assignments due in the next {days} days!",
                "deadlines": [],
            })

        return json.dumps({
            "days_ahead": days,
            "deadlines": [{
                "name": a.name,
                "course": a.course_name,
                "due_at": a.due_at,
                "points": a.points_possible,
                "submitted": a.is_submitted,
            } for a in assignments],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_announcements(course_id: int = 0, days_back: int = 7) -> str:
    """
    Get recent Canvas announcements.

    Args:
        course_id: Specific course ID (0 for all courses)
        days_back: Number of days to look back (default: 7)
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        announcements = canvas_client.get_announcements(
            course_id=course_id if course_id else None,
            days_back=days_back,
        )

        return json.dumps([{
            "title": a.title,
            "course": a.course_name,
            "author": a.author,
            "posted_at": a.posted_at,
            "message": a.message[:500] + "..." if len(a.message) > 500 else a.message,
        } for a in announcements], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_grades(course_id: int = 0) -> str:
    """
    Get your grades from Canvas.

    Args:
        course_id: Specific course ID (0 for all courses)
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        grades = canvas_client.get_grades(
            course_id=course_id if course_id else None
        )

        return json.dumps(grades, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_todos() -> str:
    """Get your Canvas todo items (assignments needing action)."""
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        todos = canvas_client.get_todo_items()

        if not todos:
            return json.dumps({"message": "No pending todo items!", "todos": []})

        return json.dumps(todos, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_canvas_modules(course_id: int) -> str:
    """
    Get course modules and content.

    Args:
        course_id: The course ID to get modules for
    """
    if not canvas_client.is_configured():
        return json.dumps({
            "error": "Canvas not configured. Use setup_canvas with your API token.",
        })

    try:
        modules = canvas_client.get_course_modules(course_id)
        return json.dumps(modules, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# GitHub Tools
# =============================================================================

@mcp.tool()
async def setup_github(token: str) -> str:
    """
    Configure GitHub with your personal access token.

    To get a token:
    1. Go to github.com/settings/tokens
    2. Click "Generate new token (classic)"
    3. Select scopes: repo, read:user, notifications
    4. Copy the token

    Args:
        token: Your GitHub personal access token
    """
    github_client.save_token(token)

    try:
        user = github_client.get_current_user()
        return json.dumps({
            "success": True,
            "message": f"GitHub configured for {user['login']}",
            "user": user,
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to verify token: {str(e)}"})


@mcp.tool()
async def get_github_repos(
    include_private: bool = True,
    include_forks: bool = False,
) -> str:
    """
    Get your GitHub repositories.

    Args:
        include_private: Include private repos (default: True)
        include_forks: Include forked repos (default: False)
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        repos = github_client.get_repos(
            include_private=include_private,
            include_forks=include_forks,
        )
        return json.dumps([{
            "name": r.name,
            "full_name": r.full_name,
            "description": r.description,
            "url": r.url,
            "private": r.private,
            "language": r.language,
            "stars": r.stars,
            "open_issues": r.open_issues,
        } for r in repos], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_github_issues(
    repo_name: str,
    state: str = "open",
    limit: int = 20,
) -> str:
    """
    Get issues for a GitHub repository.

    Args:
        repo_name: Repository name (e.g., 'owner/repo' or just 'repo' for yours)
        state: Issue state - 'open', 'closed', or 'all'
        limit: Maximum number to return
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        issues = github_client.get_issues(repo_name, state=state, limit=limit)
        return json.dumps([{
            "number": i.number,
            "title": i.title,
            "state": i.state,
            "labels": i.labels,
            "url": i.url,
            "is_pr": i.is_pull_request,
        } for i in issues], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def create_github_issue(
    repo_name: str,
    title: str,
    body: str = "",
    labels: str = "",
) -> str:
    """
    Create a new GitHub issue.

    Args:
        repo_name: Repository name
        title: Issue title
        body: Issue body/description
        labels: Comma-separated labels (e.g., "bug,enhancement")
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels else []
        issue = github_client.create_issue(
            repo_name=repo_name,
            title=title,
            body=body,
            labels=label_list,
        )
        if issue:
            return json.dumps({
                "success": True,
                "issue_number": issue.number,
                "url": issue.url,
            })
        return json.dumps({"error": "Failed to create issue"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_github_prs(
    repo_name: str,
    state: str = "open",
    limit: int = 20,
) -> str:
    """
    Get pull requests for a repository.

    Args:
        repo_name: Repository name
        state: PR state - 'open', 'closed', or 'all'
        limit: Maximum number to return
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        prs = github_client.get_pull_requests(repo_name, state=state, limit=limit)
        return json.dumps([{
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "head": pr.head_branch,
            "base": pr.base_branch,
            "mergeable": pr.mergeable,
            "url": pr.url,
            "additions": pr.additions,
            "deletions": pr.deletions,
        } for pr in prs], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_github_notifications(unread_only: bool = True) -> str:
    """
    Get your GitHub notifications.

    Args:
        unread_only: Only show unread notifications (default: True)
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        notifications = github_client.get_notifications(unread_only=unread_only)
        return json.dumps(notifications, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def search_github_repos(query: str, limit: int = 10) -> str:
    """
    Search for GitHub repositories.

    Args:
        query: Search query (e.g., "machine learning python", "language:rust stars:>1000")
        limit: Maximum results to return
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        repos = github_client.search_repos(query=query, limit=limit)
        return json.dumps([{
            "name": r.full_name,
            "description": r.description,
            "url": r.url,
            "stars": r.stars,
            "language": r.language,
        } for r in repos], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_github_file(repo_name: str, file_path: str) -> str:
    """
    Get content of a file from a GitHub repository.

    Args:
        repo_name: Repository name
        file_path: Path to file (e.g., "README.md", "src/main.py")
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        content = github_client.get_file_content(repo_name, file_path)
        if content:
            return json.dumps({
                "file": file_path,
                "content": content,
            })
        return json.dumps({"error": f"File not found: {file_path}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def comment_on_github_issue(
    repo_name: str,
    issue_number: int,
    comment: str,
) -> str:
    """
    Add a comment to a GitHub issue or PR.

    Args:
        repo_name: Repository name
        issue_number: Issue or PR number
        comment: Comment text
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        success = github_client.add_comment_to_issue(repo_name, issue_number, comment)
        if success:
            return json.dumps({"success": True, "message": "Comment added"})
        return json.dumps({"error": "Failed to add comment"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_github_rate_limit() -> str:
    """Check your GitHub API rate limit status."""
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        return json.dumps(github_client.get_rate_limit(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def check_github_security() -> str:
    """
    Check GitHub token security and permissions.

    Returns information about:
    - Current token scopes
    - Warnings about dangerous permissions
    - Recommendations for minimal scopes
    - Rate limit status
    """
    if not github_client.is_configured():
        return json.dumps({
            "error": "GitHub not configured. Use setup_github with your token.",
        })

    try:
        return json.dumps(github_client.check_token_scopes(), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# Canvas Browser Tools (when API is disabled)
# =============================================================================

@mcp.tool()
async def canvas_browser_login() -> str:
    """
    Login to Canvas via browser automation.

    Opens a browser window for UChicago SSO + Duo 2FA authentication.
    After logging in once, your session is saved for future use.

    IMPORTANT: A browser window will open. Complete the login including Duo 2FA.
    """
    try:
        # Use non-headless for login
        await canvas_browser.stop()  # Stop any existing session
        canvas_browser.headless = False
        await canvas_browser.start()

        success = await canvas_browser.login(timeout=180)

        if success:
            return json.dumps({
                "success": True,
                "message": "Logged in to Canvas. Session saved for future use.",
            })
        else:
            return json.dumps({
                "success": False,
                "error": "Login timed out. Please try again.",
            })
    except Exception as e:
        return json.dumps({"error": str(e)})
    finally:
        # Switch back to headless mode
        canvas_browser.headless = True


@mcp.tool()
async def canvas_browser_status() -> str:
    """Check if you're logged into Canvas via browser."""
    try:
        await canvas_browser.start()
        logged_in = await canvas_browser.is_logged_in()

        return json.dumps({
            "logged_in": logged_in,
            "message": "Ready to use" if logged_in else "Need to login with canvas_browser_login",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_courses() -> str:
    """Get your Canvas courses via browser scraping."""
    try:
        await canvas_browser.start()
        courses = await canvas_browser.get_courses()

        return json.dumps([{
            "name": c.name,
            "url": c.url,
        } for c in courses], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_assignments(upcoming_only: bool = True) -> str:
    """
    Get Canvas assignments via browser scraping.

    Args:
        upcoming_only: Only show upcoming/todo assignments (default: True)
    """
    try:
        await canvas_browser.start()
        assignments = await canvas_browser.get_assignments(upcoming_only=upcoming_only)

        return json.dumps([{
            "name": a.name,
            "course": a.course,
            "due_date": a.due_date,
            "status": a.status,
            "url": a.url,
        } for a in assignments], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_assignment_details(assignment_url: str) -> str:
    """
    Get detailed information from a specific Canvas assignment page.

    Use this after getting the assignment list to fetch full descriptions,
    rubrics, and other details for a specific assignment.

    Args:
        assignment_url: Full URL or path to the assignment
                       (e.g., https://canvas.uchicago.edu/courses/69273/assignments/844402
                        or /courses/69273/assignments/844402)
    """
    try:
        await canvas_browser.start()
        details = await canvas_browser.get_assignment_details(assignment_url)

        return json.dumps({
            "name": details.name,
            "course": details.course,
            "url": details.url,
            "description": details.description,
            "due_date": details.due_date,
            "points": details.points,
            "submission_types": details.submission_types,
            "available_from": details.available_from,
            "available_until": details.available_until,
            "attempts_allowed": details.attempts_allowed,
            "grading_type": details.grading_type,
            "rubric": details.rubric,
        }, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_announcements(limit: int = 10) -> str:
    """
    Get Canvas announcements via browser scraping.

    Args:
        limit: Maximum announcements to return
    """
    try:
        await canvas_browser.start()
        announcements = await canvas_browser.get_announcements(limit=limit)

        return json.dumps([{
            "title": a.title,
            "course": a.course,
            "date": a.date,
            "preview": a.preview,
            "url": a.url,
        } for a in announcements], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_grades() -> str:
    """Get your Canvas grades via browser scraping."""
    try:
        await canvas_browser.start()
        grades = await canvas_browser.get_grades()

        return json.dumps(grades, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_calendar() -> str:
    """Get Canvas calendar events via browser scraping."""
    try:
        await canvas_browser.start()
        events = await canvas_browser.get_calendar_events()

        return json.dumps(events, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_files(course_url: str) -> str:
    """
    Get files from a Canvas course.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
    """
    try:
        await canvas_browser.start()
        files = await canvas_browser.get_course_files(course_url)

        return json.dumps([{
            "name": f.name,
            "type": f.file_type,
            "size": f.size,
            "modified": f.modified,
            "url": f.url,
        } for f in files], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_download(
    file_url: str,
    save_dir: str = "data/downloads",
    filename: str = ""
) -> str:
    """
    Download a file from Canvas.

    Handles Canvas file preview pages, PDF viewers, and direct download links.
    Uses Playwright's download handling for reliable downloads.

    Args:
        file_url: URL of the file or file preview page
        save_dir: Directory to save the file (default: data/downloads)
        filename: Optional filename (auto-detected if not provided)
    """
    try:
        await canvas_browser.start()
        result = await canvas_browser.download_file(
            file_url,
            save_dir,
            filename if filename else None
        )

        if result:
            return json.dumps({
                "success": True,
                "path": result,
                "message": f"File downloaded to {result}"
            })
        else:
            return json.dumps({
                "success": False,
                "error": "Download failed - could not retrieve file"
            })
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_download_by_name(
    course_url: str,
    file_name: str,
    save_dir: str = "data/downloads"
) -> str:
    """
    Download a file from a Canvas course by searching for its name.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
        file_name: Name of the file to download (partial match supported)
        save_dir: Directory to save the file (default: data/downloads)
    """
    try:
        await canvas_browser.start()
        result = await canvas_browser.download_course_file(course_url, file_name, save_dir)

        if result:
            return json.dumps({
                "success": True,
                "path": result,
                "message": f"File downloaded to {result}"
            })
        else:
            return json.dumps({
                "success": False,
                "error": f"Could not find or download file matching '{file_name}'"
            })
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_discussions(course_url: str) -> str:
    """
    Get discussions from a Canvas course.

    Args:
        course_url: The course URL
    """
    try:
        await canvas_browser.start()
        discussions = await canvas_browser.get_course_discussions(course_url)

        return json.dumps([{
            "title": d.title,
            "author": d.author,
            "date": d.date,
            "replies": d.replies,
            "unread": d.unread,
            "url": d.url,
        } for d in discussions], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_modules(course_url: str) -> str:
    """
    Get modules from a Canvas course.

    Args:
        course_url: The course URL
    """
    try:
        await canvas_browser.start()
        modules = await canvas_browser.get_course_modules(course_url)

        return json.dumps([{
            "name": m.name,
            "status": m.status,
            "items": m.items,
        } for m in modules], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_syllabus(course_url: str) -> str:
    """
    Get syllabus from a Canvas course.

    Args:
        course_url: The course URL
    """
    try:
        await canvas_browser.start()
        syllabus = await canvas_browser.get_course_syllabus(course_url)

        return json.dumps(syllabus, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_course_assignments(course_url: str) -> str:
    """
    Get all assignments for a specific Canvas course.

    Returns assignment names, due dates, points, and submission status.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
    """
    try:
        await canvas_browser.start()
        assignments = await canvas_browser.get_course_assignments(course_url)

        return json.dumps([{
            "name": a.name,
            "due_date": a.due_date,
            "points": a.points,
            "status": a.status,
            "url": a.url,
        } for a in assignments], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_course_announcements(course_url: str, limit: int = 20) -> str:
    """
    Get announcements for a specific Canvas course.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
        limit: Maximum announcements to return (default: 20)
    """
    try:
        await canvas_browser.start()
        announcements = await canvas_browser.get_course_announcements(course_url, limit)

        return json.dumps([{
            "title": a.title,
            "date": a.date,
            "preview": a.preview,
            "url": a.url,
        } for a in announcements], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_course_schedule(course_url: str) -> str:
    """
    Get course schedule/meeting times from Canvas.

    Scrapes the course home and syllabus to find meeting days, times, location, and instructor.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
    """
    try:
        await canvas_browser.start()
        schedule = await canvas_browser.get_course_schedule(course_url)

        return json.dumps(schedule, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_course_people(course_url: str) -> str:
    """
    Get instructors, TAs, and student count from a Canvas course.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
    """
    try:
        await canvas_browser.start()
        people = await canvas_browser.get_course_people(course_url)

        return json.dumps(people, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_course_grades(course_url: str) -> str:
    """
    Get grades for a specific Canvas course.

    Returns individual assignment scores and overall grade.

    Args:
        course_url: The course URL (e.g., https://canvas.uchicago.edu/courses/12345)
    """
    try:
        await canvas_browser.start()
        grades = await canvas_browser.get_course_grades(course_url)

        return json.dumps(grades, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_inbox(unread_only: bool = False) -> str:
    """
    Get Canvas inbox messages.

    Args:
        unread_only: Only show unread messages (default: False)
    """
    try:
        await canvas_browser.start()
        messages = await canvas_browser.get_inbox(unread_only=unread_only)

        return json.dumps([{
            "subject": m.subject,
            "sender": m.sender,
            "date": m.date,
            "preview": m.preview,
            "unread": m.unread,
            "url": m.url,
        } for m in messages], indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def canvas_browser_pages(course_url: str) -> str:
    """
    Get wiki pages from a Canvas course.

    Args:
        course_url: The course URL
    """
    try:
        await canvas_browser.start()
        pages = await canvas_browser.get_course_pages(course_url)

        return json.dumps(pages, indent=2)
    except RuntimeError as e:
        return json.dumps({"error": str(e), "hint": "Run canvas_browser_login first"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# =============================================================================
# Project Memory Tools (CLAUDE.md management)
# =============================================================================

@mcp.tool()
async def update_project_status(
	project_path: str,
	phase_completed: str = "",
	phase_started: str = "",
	commit_hash: str = "",
) -> str:
	"""
	Update the Implementation Status section of a project CLAUDE.md.

	Use this after completing a phase to mark it done and optionally start a new phase.

	Args:
		project_path: Path to the project directory (e.g., "~/personal_projects/my-app")
		phase_completed: Phase that was just completed (e.g., "Phase 3: Vision Pipeline")
		phase_started: Phase that is now starting (optional)
		commit_hash: Git commit hash for the completed phase (optional)

	Example:
		update_project_status(
			project_path="~/personal_projects/geoguessr-ai",
			phase_completed="Phase 2: Browser Automation",
			phase_started="Phase 3: Vision Pipeline",
			commit_hash="abc123f"
		)
	"""
	# Expand ~ in path
	expanded_path = str(Path(project_path).expanduser())
	result = project_memory.update_implementation_status(
		expanded_path, phase_completed, phase_started, commit_hash
	)
	return json.dumps(result)


@mcp.tool()
async def log_project_decision(
	project_path: str,
	decision: str,
	rationale: str,
	alternatives: str = "",
) -> str:
	"""
	Log a significant decision to a project's CLAUDE.md Decisions Log.

	Use this when making architectural choices or significant implementation decisions.

	Args:
		project_path: Path to the project directory
		decision: What was decided (e.g., "Use SQLite instead of PostgreSQL")
		rationale: Why this decision was made (e.g., "Simpler setup, sufficient for MVP")
		alternatives: What alternatives were rejected (e.g., "PostgreSQL (overkill), MongoDB (wrong fit)")

	Example:
		log_project_decision(
			project_path="~/personal_projects/my-app",
			decision="Use FastAPI",
			rationale="Async support, automatic OpenAPI docs",
			alternatives="Flask (sync only), Django (too heavy)"
		)
	"""
	expanded_path = str(Path(project_path).expanduser())
	result = project_memory.log_decision(expanded_path, decision, rationale, alternatives)
	return json.dumps(result)


@mcp.tool()
async def log_project_gotcha(
	project_path: str,
	gotcha_type: str,
	description: str,
) -> str:
	"""
	Log a gotcha or learning to a project's CLAUDE.md.

	Use this when discovering something that should be remembered for future sessions.

	Args:
		project_path: Path to the project directory
		gotcha_type: Type of gotcha - "dont" (avoid), "do" (best practice), or "note" (info)
		description: Description of the gotcha

	Examples:
		log_project_gotcha("~/personal_projects/my-app", "dont", "Use raw SQL - causes injection risks")
		log_project_gotcha("~/personal_projects/my-app", "do", "Always validate user input before processing")
		log_project_gotcha("~/personal_projects/my-app", "note", "API returns UTC timestamps, not local time")
	"""
	expanded_path = str(Path(project_path).expanduser())
	result = project_memory.log_gotcha(expanded_path, gotcha_type, description)
	return json.dumps(result)


@mcp.tool()
async def log_global_learning(
	category: str,
	content: str,
) -> str:
	"""
	Add a learning to the global learnings file (~/.claude/global-learnings.md).

	Use this for learnings that apply across ALL projects, not just the current one.

	Args:
		category: Category of learning:
			- "preference" - Danny's preferences/style
			- "pattern" - Technical patterns that work well
			- "gotcha" - Common issues to avoid
			- "decision" - Decision-making patterns
		content: The learning to add (will be formatted as a bullet point)

	Examples:
		log_global_learning("pattern", "Use `pathlib.Path` instead of string concatenation for paths")
		log_global_learning("gotcha", "Pydantic V2 uses `model_config` instead of `Config` class")
		log_global_learning("decision", "For simple CLIs, prefer Typer over argparse")
	"""
	result = project_memory.log_global_learning(category, content)
	return json.dumps(result)


# =============================================================================
# Session Management Tools
# =============================================================================


@mcp.tool()
async def list_claude_sessions() -> str:
	"""
	List all active Claude Code sessions.

	Returns information about each session including:
	- Session ID
	- Project name and path
	- Current state (ready, busy, waiting_input, stopped)
	- Last activity timestamp
	- Current task (if busy)

	Example:
		list_claude_sessions()
	"""
	await ensure_initialized()
	manager = await get_session_manager()
	sessions = manager.list_sessions()

	return json.dumps({
		"success": True,
		"count": len(sessions),
		"sessions": sessions,
	})


@mcp.tool()
async def start_claude_session(
	project_path: str,
	initial_prompt: str = "",
) -> str:
	"""
	Start a new Claude Code session in a project directory.

	This creates a new Claude CLI process in the specified project.
	The session can then be controlled via Telegram or other MCP tools.

	Args:
		project_path: Path to project directory (e.g., "~/personal_projects/my-app")
		initial_prompt: Optional initial prompt to start working on

	Returns:
		Session ID and status message

	Example:
		start_claude_session("~/personal_projects/claude-orchestrator")
		start_claude_session("~/personal_projects/my-app", initial_prompt="Fix the login bug")
	"""
	await ensure_initialized()
	manager = await get_session_manager()

	session_id, message = await manager.start_session(
		project_path=project_path,
		initial_prompt=initial_prompt if initial_prompt else None,
	)

	if session_id:
		return json.dumps({
			"success": True,
			"session_id": session_id,
			"message": message,
		})
	else:
		return json.dumps({
			"success": False,
			"error": message,
		})


@mcp.tool()
async def stop_claude_session(session_id: str) -> str:
	"""
	Stop a Claude Code session.

	Args:
		session_id: The session ID to stop (from list_claude_sessions)

	Returns:
		Status message

	Example:
		stop_claude_session("abc123")
	"""
	await ensure_initialized()
	manager = await get_session_manager()

	message = await manager.stop_session(session_id)

	return json.dumps({
		"success": True,
		"message": message,
	})


@mcp.tool()
async def send_to_claude_session(
	session_id: str,
	prompt: str,
) -> str:
	"""
	Send a prompt to a Claude session.

	Args:
		session_id: The session ID to send to
		prompt: The prompt or command to send

	Returns:
		Response from Claude

	Example:
		send_to_claude_session("abc123", "What files are in this project?")
	"""
	await ensure_initialized()
	manager = await get_session_manager()

	response = await manager.send_prompt(session_id, prompt)

	return json.dumps({
		"success": True,
		"response": response,
	})


@mcp.tool()
async def get_session_output(
	session_id: str,
	lines: int = 50,
) -> str:
	"""
	Get recent output from a Claude session.

	Args:
		session_id: The session ID
		lines: Number of output lines to retrieve (default: 50)

	Returns:
		Recent output lines from the session

	Example:
		get_session_output("abc123", lines=100)
	"""
	await ensure_initialized()
	manager = await get_session_manager()

	session = manager.get_session(session_id)
	if not session:
		return json.dumps({
			"success": False,
			"error": f"Session not found: {session_id}",
		})

	output = manager.get_session_output(session_id, lines=lines)

	return json.dumps({
		"success": True,
		"session": session,
		"output": output,
		"line_count": len(output),
	})


@mcp.tool()
async def approve_session_action(
	session_id: str,
	approved: bool = True,
) -> str:
	"""
	Approve or deny a pending action in a Claude session.

	Use this when a session is in 'waiting_input' state and needs
	approval for a permission request.

	Args:
		session_id: The session ID
		approved: True to approve, False to deny

	Returns:
		Status message

	Example:
		approve_session_action("abc123", approved=True)
	"""
	await ensure_initialized()
	manager = await get_session_manager()

	response = "y" if approved else "n"
	message = await manager.send_input(session_id, response)

	return json.dumps({
		"success": True,
		"message": message,
		"approved": approved,
	})


# =============================================================================
# Visual Verification Tools
# =============================================================================


@mcp.tool()
async def take_screenshot(
	url: str,
	name: str = "",
	full_page: bool = False,
	wait_for: str = "",
) -> str:
	"""
	Take a screenshot of a webpage for visual verification.

	The screenshot is saved to data/screenshots/ and can be analyzed using Claude's vision.

	Args:
		url: The URL to screenshot
		name: Optional filename (without extension). Auto-generated if not provided.
		full_page: Whether to capture the full scrollable page (default: False)
		wait_for: CSS selector to wait for before taking screenshot (optional)

	Returns:
		JSON with screenshot path and metadata

	Example:
		take_screenshot("https://example.com", name="homepage", full_page=True)
		take_screenshot("https://app.example.com/dashboard", wait_for=".dashboard-loaded")
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	screenshot = await verifier.take_screenshot(
		url=url,
		name=name if name else None,
		full_page=full_page,
		wait_for=wait_for if wait_for else None,
	)

	return json.dumps({
		"success": True,
		"path": screenshot.path,
		"url": screenshot.url,
		"timestamp": screenshot.timestamp,
		"dimensions": f"{screenshot.width}x{screenshot.height}",
		"full_page": screenshot.full_page,
		"message": f"Screenshot saved to {screenshot.path}. Use Read tool to view and analyze it.",
	})


@mcp.tool()
async def take_element_screenshot(
	url: str,
	selector: str,
	name: str = "",
) -> str:
	"""
	Take a screenshot of a specific element on a webpage.

	Useful for capturing buttons, forms, or other specific UI components.

	Args:
		url: The URL to navigate to
		selector: CSS selector of the element to screenshot
		name: Optional filename (without extension)

	Returns:
		JSON with screenshot path and metadata

	Example:
		take_element_screenshot("https://app.example.com", selector="#login-form", name="login_form")
		take_element_screenshot("https://app.example.com", selector=".header-nav")
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	try:
		screenshot = await verifier.take_element_screenshot(
			url=url,
			selector=selector,
			name=name if name else None,
		)

		return json.dumps({
			"success": True,
			"path": screenshot.path,
			"url": screenshot.url,
			"selector": selector,
			"timestamp": screenshot.timestamp,
			"dimensions": f"{screenshot.width}x{screenshot.height}",
			"message": f"Element screenshot saved to {screenshot.path}",
		})
	except ValueError as e:
		return json.dumps({
			"success": False,
			"error": str(e),
		})


@mcp.tool()
async def verify_element(
	url: str,
	selector: str,
	timeout: int = 10000,
) -> str:
	"""
	Verify that an element exists on a webpage.

	Useful for automated UI testing - checking if elements are present and visible.

	Args:
		url: The URL to check
		selector: CSS selector to find
		timeout: How long to wait for element in ms (default: 10000)

	Returns:
		JSON with exists, visible, and text properties

	Example:
		verify_element("https://app.example.com", selector="#login-button")
		verify_element("https://app.example.com", selector=".error-message", timeout=5000)
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	result = await verifier.verify_element_exists(
		url=url,
		selector=selector,
		timeout=timeout,
	)

	return json.dumps({
		"success": True,
		**result,
	})


@mcp.tool()
async def get_page_content(
	url: str,
	selector: str = "",
) -> str:
	"""
	Get text content from a webpage or specific element.

	Useful for extracting content without taking a screenshot.

	Args:
		url: The URL to navigate to
		selector: CSS selector for specific element (gets full body text if not provided)

	Returns:
		JSON with text content

	Example:
		get_page_content("https://example.com")  # Full page text
		get_page_content("https://example.com", selector=".article-body")  # Specific element
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	text = await verifier.get_page_text(
		url=url,
		selector=selector if selector else None,
	)

	# Truncate if very long
	truncated = len(text) > 10000
	if truncated:
		text = text[:10000] + "\n\n[Content truncated - showing first 10000 characters]"

	return json.dumps({
		"success": True,
		"url": url,
		"selector": selector or "body",
		"text": text,
		"truncated": truncated,
	})


@mcp.tool()
async def list_screenshots() -> str:
	"""
	List all screenshots in the screenshots directory.

	Returns a list of screenshot files with their metadata.

	Returns:
		JSON with list of screenshots (path, name, size, modified date)
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	screenshots = await verifier.list_screenshots()

	return json.dumps({
		"success": True,
		"count": len(screenshots),
		"screenshots": screenshots,
	})


@mcp.tool()
async def delete_screenshot(name: str) -> str:
	"""
	Delete a screenshot by filename.

	Args:
		name: The filename of the screenshot to delete (e.g., "homepage_20260113_120000.png")

	Returns:
		JSON with success status
	"""
	await ensure_initialized()
	verifier = await get_verifier()

	deleted = await verifier.delete_screenshot(name)

	if deleted:
		return json.dumps({
			"success": True,
			"message": f"Deleted screenshot: {name}",
		})
	else:
		return json.dumps({
			"success": False,
			"error": f"Screenshot not found: {name}",
		})


# ==================== Knowledge/Documentation Tools ====================


@mcp.tool()
async def search_docs(query: str, max_results: int = 5, source: str = "") -> str:
	"""
	Semantic search over indexed documentation.

	Args:
		query: The search query (natural language)
		max_results: Maximum number of results to return (default: 5)
		source: Optional source filter (e.g., "claude-sdk", "claude-code")

	Returns:
		JSON with search results including title, section, content snippet, and source URL

	Example:
		search_docs("how to use tools in Claude API")
		search_docs("error handling", source="claude-sdk")
	"""
	await ensure_initialized()
	return await knowledge_retriever.search_docs(
		query=query,
		max_results=max_results,
		source=source if source else None,
	)


@mcp.tool()
async def get_doc(path: str) -> str:
	"""
	Get the full content of a specific document.

	Args:
		path: Path to the document file (as returned by search_docs)

	Returns:
		The full document content as markdown, or error message if not found

	Example:
		get_doc("data/knowledge/claude-sdk/api/tools.md")
	"""
	await ensure_initialized()
	return await knowledge_retriever.get_doc(path)


@mcp.tool()
async def list_doc_sources() -> str:
	"""
	List all indexed documentation sources.

	Returns:
		JSON with available documentation sources including name, file count, chunk count

	Example:
		list_doc_sources()
	"""
	await ensure_initialized()
	return await knowledge_retriever.list_doc_sources()


@mcp.tool()
async def index_docs(source_dir: str, source_name: str = "") -> str:
	"""
	Index markdown documentation files from a directory.

	Args:
		source_dir: Directory containing markdown files to index
		source_name: Optional name for this documentation source

	Returns:
		JSON with indexing statistics

	Example:
		index_docs("data/knowledge/claude-sdk")
	"""
	await ensure_initialized()
	return await knowledge_retriever.index_docs(
		source_dir=source_dir,
		source_name=source_name if source_name else None,
	)


@mcp.tool()
async def crawl_and_index_docs(
	start_url: str,
	source_name: str,
	max_pages: int = 100,
) -> str:
	"""
	Crawl a documentation site and index it for semantic search.

	Args:
		start_url: URL to start crawling from
		source_name: Name for this documentation source
		max_pages: Maximum pages to crawl (default: 100)

	Returns:
		JSON with crawl and index statistics

	Example:
		crawl_and_index_docs(
			"https://docs.anthropic.com/claude/reference",
			"claude-sdk",
			max_pages=50
		)
	"""
	await ensure_initialized()
	return await knowledge_retriever.crawl_and_index(
		start_url=start_url,
		source_name=source_name,
		max_pages=max_pages,
	)


# ==================== Plan Management Tools ====================


@mcp.tool()
async def create_plan(
	project: str,
	goal: str,
	success_criteria: str = "",
	constraints: str = "",
) -> str:
	"""
	Create a new implementation plan for a project.

	Args:
		project: Project name (e.g., "my-app")
		goal: What the plan achieves
		success_criteria: Comma-separated success criteria
		constraints: Comma-separated constraints

	Returns:
		JSON with plan_id and status

	Example:
		create_plan(
			"my-app",
			"Add user authentication",
			"Login works, sessions persist, tests pass",
			"Must use existing DB schema"
		)
	"""
	await ensure_initialized()

	store = await get_plan_store()

	overview = PlanOverview(
		goal=goal,
		success_criteria=[c.strip() for c in success_criteria.split(",") if c.strip()],
		constraints=[c.strip() for c in constraints.split(",") if c.strip()],
	)

	plan = Plan(
		id="",
		project=project,
		overview=overview,
	)

	plan_id = await store.create_plan(project, plan)

	return json.dumps({
		"success": True,
		"plan_id": plan_id,
		"project": project,
		"status": plan.status.value,
	}, indent=2)


@mcp.tool()
async def get_plan(plan_id: str, version: int = 0) -> str:
	"""
	Get a plan by ID.

	Args:
		plan_id: The plan ID
		version: Optional version number (0 = current)

	Returns:
		JSON with plan details or error

	Example:
		get_plan("abc123")
		get_plan("abc123", version=2)
	"""
	await ensure_initialized()

	store = await get_plan_store()
	plan = await store.get_plan(plan_id, version if version > 0 else None)

	if not plan:
		return json.dumps({"error": f"Plan not found: {plan_id}"})

	return json.dumps({
		"plan": plan.model_dump(),
		"progress": plan.get_progress(),
		"markdown": plan.to_markdown(),
	}, indent=2)


@mcp.tool()
async def get_project_plan(project: str) -> str:
	"""
	Get the current plan for a project.

	Args:
		project: Project name

	Returns:
		JSON with plan details or error

	Example:
		get_project_plan("my-app")
	"""
	await ensure_initialized()

	store = await get_plan_store()
	plan = await store.get_current_plan(project)

	if not plan:
		return json.dumps({
			"error": f"No plan found for project: {project}",
			"hint": "Use create_plan to create one",
		})

	return json.dumps({
		"plan": plan.model_dump(),
		"progress": plan.get_progress(),
	}, indent=2)


@mcp.tool()
async def add_phase_to_plan(
	plan_id: str,
	phase_name: str,
	description: str,
	tasks: str,
	expected_version: int,
) -> str:
	"""
	Add a phase to an existing plan.

	Args:
		plan_id: Plan ID
		phase_name: Name of the phase
		description: What this phase accomplishes
		tasks: Semicolon-separated list of task descriptions
		expected_version: Current plan version (for optimistic locking)

	Returns:
		JSON with updated plan or error

	Example:
		add_phase_to_plan(
			"abc123",
			"Phase 1: Setup",
			"Initialize project structure",
			"Create directories; Add config file; Write tests",
			1
		)
	"""
	await ensure_initialized()

	store = await get_plan_store()

	# Get current plan
	plan = await store.get_plan(plan_id)
	if not plan:
		return json.dumps({"error": f"Plan not found: {plan_id}"})

	# Create phase with tasks
	phase_id = f"phase-{len(plan.phases) + 1}"
	task_list = [
		Task(
			id=f"{phase_id}-task-{i+1}",
			description=t.strip(),
		)
		for i, t in enumerate(tasks.split(";")) if t.strip()
	]

	phase = Phase(
		id=phase_id,
		name=phase_name,
		description=description,
		tasks=task_list,
	)

	# Update plan
	try:
		updated = await store.update_plan(
			plan_id,
			{"phases": plan.phases + [phase]},
			expected_version,
		)
		return json.dumps({
			"success": True,
			"plan_id": plan_id,
			"new_version": updated.version,
			"phase_added": phase_name,
			"task_count": len(task_list),
		}, indent=2)
	except OptimisticLockError as e:
		return json.dumps({"error": str(e)})


@mcp.tool()
async def update_task_status(
	plan_id: str,
	phase_id: str,
	task_id: str,
	status: str,
	expected_version: int,
) -> str:
	"""
	Update a task's status in a plan.

	Args:
		plan_id: Plan ID
		phase_id: Phase ID (e.g., "phase-1")
		task_id: Task ID (e.g., "phase-1-task-1")
		status: New status (pending, in_progress, completed, blocked, skipped)
		expected_version: Current plan version

	Returns:
		JSON with updated plan or error

	Example:
		update_task_status("abc123", "phase-1", "phase-1-task-1", "completed", 2)
	"""
	await ensure_initialized()

	store = await get_plan_store()

	try:
		task_status = TaskStatus(status)
	except ValueError:
		return json.dumps({
			"error": f"Invalid status: {status}",
			"valid_statuses": [s.value for s in TaskStatus],
		})

	try:
		updated = await store.update_task_status(
			plan_id, phase_id, task_id, task_status, expected_version
		)
		return json.dumps({
			"success": True,
			"plan_id": plan_id,
			"new_version": updated.version,
			"progress": updated.get_progress(),
		}, indent=2)
	except (OptimisticLockError, PlanNotFoundError, ValueError) as e:
		return json.dumps({"error": str(e)})


@mcp.tool()
async def add_decision_to_plan(
	plan_id: str,
	decision: str,
	rationale: str,
	alternatives: str = "",
	expected_version: int = 0,
) -> str:
	"""
	Add a decision to a plan.

	Args:
		plan_id: Plan ID
		decision: What was decided
		rationale: Why this decision was made
		alternatives: Comma-separated rejected alternatives
		expected_version: Current plan version

	Returns:
		JSON with updated plan or error

	Example:
		add_decision_to_plan(
			"abc123",
			"Use SQLite",
			"Lightweight, no setup required",
			"PostgreSQL (overkill), MongoDB (wrong fit)",
			2
		)
	"""
	await ensure_initialized()

	store = await get_plan_store()

	plan = await store.get_plan(plan_id)
	if not plan:
		return json.dumps({"error": f"Plan not found: {plan_id}"})

	new_decision = Decision(
		id=f"decision-{len(plan.decisions) + 1}",
		decision=decision,
		rationale=rationale,
		alternatives=[a.strip() for a in alternatives.split(",") if a.strip()],
	)

	try:
		updated = await store.update_plan(
			plan_id,
			{"decisions": plan.decisions + [new_decision]},
			expected_version,
		)
		return json.dumps({
			"success": True,
			"plan_id": plan_id,
			"new_version": updated.version,
			"decision_count": len(updated.decisions),
		}, indent=2)
	except OptimisticLockError as e:
		return json.dumps({"error": str(e)})


@mcp.tool()
async def list_plans(project: str = "", status: str = "") -> str:
	"""
	List plans, optionally filtered by project or status.

	Args:
		project: Filter by project name (empty = all)
		status: Filter by status (draft, approved, in_progress, completed)

	Returns:
		JSON with list of plans

	Example:
		list_plans()
		list_plans(project="my-app")
		list_plans(status="in_progress")
	"""
	await ensure_initialized()

	store = await get_plan_store()

	plan_status = None
	if status:
		try:
			plan_status = PlanStatus(status)
		except ValueError:
			return json.dumps({
				"error": f"Invalid status: {status}",
				"valid_statuses": [s.value for s in PlanStatus],
			})

	plans = await store.search_plans(
		project=project if project else None,
		status=plan_status,
	)

	return json.dumps({
		"plans": [
			{
				"id": p.id,
				"project": p.project,
				"version": p.version,
				"status": p.status.value,
				"goal": p.overview.goal,
				"progress": p.get_progress(),
				"updated_at": p.updated_at,
			}
			for p in plans
		],
		"total": len(plans),
	}, indent=2)


@mcp.tool()
async def get_plan_history(plan_id: str) -> str:
	"""
	Get all versions of a plan.

	Args:
		plan_id: Plan ID

	Returns:
		JSON with version history

	Example:
		get_plan_history("abc123")
	"""
	await ensure_initialized()

	store = await get_plan_store()
	versions = await store.get_plan_history(plan_id)

	if not versions:
		return json.dumps({"error": f"Plan not found: {plan_id}"})

	return json.dumps({
		"plan_id": plan_id,
		"versions": [
			{
				"version": p.version,
				"status": p.status.value,
				"updated_at": p.updated_at,
				"progress": p.get_progress(),
			}
			for p in versions
		],
		"total_versions": len(versions),
	}, indent=2)


# ==================== Orchestrator Tools ====================


@mcp.tool()
async def start_planning_session(project: str, goal: str, context: str = "") -> str:
	"""
	Start a new interactive planning session.

	Planning sessions conduct thorough Q&A until complete clarity
	is achieved before any implementation begins.

	Args:
		project: Project name
		goal: What needs to be accomplished
		context: Optional additional context

	Returns:
		JSON with session_id and initial questions

	Example:
		start_planning_session("my-app", "Add user authentication")
	"""
	await ensure_initialized()

	planner = get_planner()
	session = await planner.start_planning_session(project, goal, context or None)

	pending = session.get_pending_questions()

	return json.dumps({
		"session_id": session.id,
		"project": project,
		"goal": goal,
		"phase": session.phase.value,
		"questions": [
			{
				"id": q.id,
				"category": q.category,
				"question": q.question,
				"options": q.options,
			}
			for q in pending
		],
	}, indent=2)


@mcp.tool()
async def answer_planning_question(
	session_id: str,
	question_id: str,
	answer: str,
) -> str:
	"""
	Answer a question in a planning session.

	Args:
		session_id: Planning session ID
		question_id: Question ID (e.g., "q1")
		answer: Your answer

	Returns:
		JSON with next questions or draft plan status

	Example:
		answer_planning_question("plan-my-app-...", "q1", "User login with email/password")
	"""
	await ensure_initialized()

	planner = get_planner()
	result = await planner.process_answer(session_id, question_id, answer)

	return json.dumps(result, indent=2)


@mcp.tool()
async def get_planning_session(session_id: str) -> str:
	"""
	Get the current state of a planning session.

	Args:
		session_id: Planning session ID

	Returns:
		JSON with session summary and pending questions
	"""
	await ensure_initialized()

	planner = get_planner()
	session = planner.get_session(session_id)

	if not session:
		return json.dumps({"error": f"Session not found: {session_id}"})

	return json.dumps({
		"summary": session.get_summary(),
		"pending_questions": [
			{
				"id": q.id,
				"category": q.category,
				"question": q.question,
				"options": q.options,
			}
			for q in session.get_pending_questions()
		],
		"answered_questions": [
			{
				"id": q.id,
				"category": q.category,
				"question": q.question,
				"answer": q.answer,
			}
			for q in session.answered_questions
		],
		"has_draft_plan": session.draft_plan is not None,
	}, indent=2)


@mcp.tool()
async def approve_planning_session(session_id: str) -> str:
	"""
	Approve a planning session's draft plan and save it.

	Args:
		session_id: Planning session ID

	Returns:
		JSON with plan_id and status
	"""
	await ensure_initialized()

	planner = get_planner()
	result = await planner.approve_plan(session_id)

	return json.dumps(result, indent=2)


@mcp.tool()
async def list_planning_sessions() -> str:
	"""
	List all active planning sessions.

	Returns:
		JSON with list of session summaries
	"""
	await ensure_initialized()

	planner = get_planner()
	sessions = planner.list_sessions()

	return json.dumps({
		"sessions": sessions,
		"total": len(sessions),
	}, indent=2)


@mcp.tool()
async def run_verification(
	project_path: str = "",
	checks: str = "",
	files_changed: str = "",
) -> str:
	"""
	Run verification suite (tests, lint, type check, security).

	Args:
		project_path: Path to project (default: current directory)
		checks: Comma-separated checks to run (default: pytest,ruff,mypy,bandit)
		files_changed: Comma-separated list of changed files for targeted checks

	Returns:
		JSON with verification results

	Example:
		run_verification()
		run_verification(checks="pytest,ruff")
		run_verification(files_changed="src/foo.py,src/bar.py")
	"""
	await ensure_initialized()

	from .orchestrator.verifier import Verifier

	verifier = Verifier(
		project_path=project_path if project_path else None,
		venv_path=".venv",
	)

	check_list = [c.strip() for c in checks.split(",")] if checks else None
	files_list = [f.strip() for f in files_changed.split(",")] if files_changed else None

	result = await verifier.verify(
		checks=check_list,
		files_changed=files_list,
	)

	return json.dumps({
		"passed": result.passed,
		"summary": result.summary,
		"can_retry": result.can_retry,
		"checks": [
			{
				"name": c.name,
				"status": c.status.value,
				"duration_seconds": round(c.duration_seconds, 2),
				"output_preview": c.output[:500] if c.output else "",
			}
			for c in result.checks
		],
		"verified_at": result.verified_at,
	}, indent=2)


# ==================== Skills Tools ====================


@mcp.tool()
async def list_skills(project_path: str = "") -> str:
	"""
	List all available skills.

	Skills are discovered from:
	- Global: ~/.claude/skills/
	- Project: .claude/skills/

	Args:
		project_path: Project path for project-specific skills (default: current directory)

	Returns:
		JSON with list of available skills
	"""
	await ensure_initialized()

	from .skills import get_skill_loader

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

	Returns:
		JSON with skill details and full instructions
	"""
	await ensure_initialized()

	from .skills import get_skill_loader

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

	Returns:
		JSON with path to created SKILL.md file
	"""
	await ensure_initialized()

	from .skills import get_skill_loader

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

	This prepares the skill but doesn't actually execute it.
	Use the returned prompt to guide Claude through the skill.

	Args:
		skill_name: Name of the skill to execute
		context: JSON string of context variables to pass to the skill
		project_path: Project path for skill discovery

	Returns:
		JSON with execution_id and formatted prompt

	Example:
		execute_skill("code-review", context='{"file": "src/main.py"}')
	"""
	await ensure_initialized()

	from .skills import get_skill_executor

	executor = get_skill_executor(project_path if project_path else None)

	# Parse context if provided
	context_dict = {}
	if context:
		try:
			context_dict = json.loads(context)
		except json.JSONDecodeError:
			return json.dumps({"error": "Invalid JSON in context parameter"}, indent=2)

	execution = executor.prepare_execution(skill_name, context_dict)
	if not execution:
		return json.dumps({
			"error": f"Skill not found: {skill_name}",
		}, indent=2)

	prompt = executor.get_execution_prompt(execution.id)

	return json.dumps({
		"execution_id": execution.id,
		"skill_name": skill_name,
		"status": execution.status.value,
		"prompt": prompt,
	}, indent=2)


@mcp.tool()
async def list_skill_executions(
	status: str = "",
	skill_name: str = "",
) -> str:
	"""
	List skill executions with optional filters.

	Args:
		status: Filter by status (pending, running, completed, failed, cancelled)
		skill_name: Filter by skill name

	Returns:
		JSON with list of executions
	"""
	await ensure_initialized()

	from .skills import get_skill_executor, ExecutionStatus

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


if __name__ == "__main__":
	mcp.run()
