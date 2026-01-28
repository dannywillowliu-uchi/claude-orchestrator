"""SQLite database for task state management."""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import aiosqlite


class TaskStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskComplexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class TaskRecord:
    id: str
    google_task_id: str
    google_list_id: str
    title: str
    notes: Optional[str]
    due_date: Optional[str]
    status: str
    feasibility_score: Optional[float] = None
    feasibility_reason: Optional[str] = None
    complexity: Optional[str] = None
    execution_plan: Optional[str] = None
    telegram_message_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "TaskRecord":
        return cls(
            id=row["id"],
            google_task_id=row["google_task_id"],
            google_list_id=row["google_list_id"],
            title=row["title"],
            notes=row["notes"],
            due_date=row["due_date"],
            status=row["status"],
            feasibility_score=row["feasibility_score"],
            feasibility_reason=row["feasibility_reason"],
            complexity=row["complexity"],
            execution_plan=row["execution_plan"],
            telegram_message_id=row["telegram_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class Database:
    # Allowlist of columns that can be updated (prevents SQL injection via column names)
    ALLOWED_UPDATE_COLUMNS = frozenset({
        'status', 'notes', 'feasibility_score', 'feasibility_reason',
        'complexity', 'execution_plan', 'telegram_message_id', 'updated_at'
    })

    def __init__(self, db_path: str = ""):
        if not db_path:
            from .config import get_config
            db_path = str(get_config().db_path)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self):
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    google_task_id TEXT UNIQUE NOT NULL,
                    google_list_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    notes TEXT,
                    due_date TEXT,
                    status TEXT DEFAULT 'pending',
                    feasibility_score REAL,
                    feasibility_reason TEXT,
                    complexity TEXT,
                    execution_plan TEXT,
                    telegram_message_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sync_tokens (
                    list_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS execution_logs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT REFERENCES tasks(id),
                    step_number INTEGER,
                    action TEXT,
                    result TEXT,
                    success INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_google_id ON tasks(google_task_id);
            """)
            await db.commit()

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get a task by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return TaskRecord.from_row(row) if row else None

    async def get_task_by_google_id(self, google_task_id: str) -> Optional[TaskRecord]:
        """Get a task by Google Task ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE google_task_id = ?", (google_task_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return TaskRecord.from_row(row) if row else None

    async def get_tasks_by_status(self, statuses: list[str]) -> list[TaskRecord]:
        """Get all tasks with given statuses."""
        placeholders = ",".join("?" * len(statuses))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY created_at DESC",
                statuses,
            ) as cursor:
                rows = await cursor.fetchall()
                return [TaskRecord.from_row(row) for row in rows]

    async def create_task(self, task: TaskRecord) -> TaskRecord:
        """Create a new task record."""
        import uuid
        task.id = task.id or str(uuid.uuid4())
        task.created_at = task.created_at or datetime.now().isoformat()
        task.updated_at = task.updated_at or datetime.now().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO tasks (id, google_task_id, google_list_id, title, notes,
                    due_date, status, feasibility_score, feasibility_reason, complexity,
                    execution_plan, telegram_message_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.google_task_id,
                    task.google_list_id,
                    task.title,
                    task.notes,
                    task.due_date,
                    task.status,
                    task.feasibility_score,
                    task.feasibility_reason,
                    task.complexity,
                    task.execution_plan,
                    task.telegram_message_id,
                    task.created_at,
                    task.updated_at,
                ),
            )
            await db.commit()
        return task

    async def update_task(self, task_id: str, **updates) -> Optional[TaskRecord]:
        """Update a task by ID."""
        # Validate column names to prevent SQL injection
        invalid_columns = set(updates.keys()) - self.ALLOWED_UPDATE_COLUMNS
        if invalid_columns:
            raise ValueError(f"Invalid columns for update: {invalid_columns}")

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [task_id]

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE tasks SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()

        return await self.get_task(task_id)

    async def get_sync_token(self, list_id: str) -> Optional[str]:
        """Get sync token for a task list."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT token FROM sync_tokens WHERE list_id = ?", (list_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def save_sync_token(self, list_id: str, token: str):
        """Save sync token for a task list."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO sync_tokens (list_id, token, updated_at)
                VALUES (?, ?, ?)
                """,
                (list_id, token, datetime.now().isoformat()),
            )
            await db.commit()

    async def add_execution_log(
        self, task_id: str, step_number: int, action: str, result: str, success: bool
    ):
        """Add an execution log entry."""
        import uuid
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO execution_logs (id, task_id, step_number, action, result, success)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), task_id, step_number, action, result, int(success)),
            )
            await db.commit()

    async def get_execution_logs(self, task_id: str) -> list[dict]:
        """Get execution logs for a task."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM execution_logs WHERE task_id = ? ORDER BY step_number",
                (task_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
