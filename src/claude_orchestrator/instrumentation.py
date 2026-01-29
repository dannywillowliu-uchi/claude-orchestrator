"""
Instrumentation layer for MCP tool call tracking.

Records tool calls to SQLite for observability, debugging, and performance analysis.
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
	"""A single recorded tool call."""
	tool_name: str
	args_json: str = ""
	result_summary: str = ""
	duration_seconds: float = 0.0
	timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
	session_id: str = ""
	success: bool = True


@dataclass
class ToolStats:
	"""Aggregate stats for a tool."""
	tool_name: str
	call_count: int
	avg_duration: float
	success_rate: float
	last_called: str


class ToolCallStore:
	"""SQLite-backed storage for tool call records."""

	def __init__(self, db_path: str = ""):
		if not db_path:
			from .config import get_config
			db_path = str(get_config().data_dir / "tool_calls.db")
		self.db_path = Path(db_path)
		self.db_path.parent.mkdir(parents=True, exist_ok=True)
		self._ensure_table()

	def _ensure_table(self) -> None:
		"""Create the tool_calls table if it doesn't exist."""
		with sqlite3.connect(str(self.db_path)) as conn:
			conn.execute("""
				CREATE TABLE IF NOT EXISTS tool_calls (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					tool_name TEXT NOT NULL,
					args_json TEXT DEFAULT '',
					result_summary TEXT DEFAULT '',
					duration_seconds REAL DEFAULT 0.0,
					timestamp TEXT NOT NULL,
					session_id TEXT DEFAULT '',
					success INTEGER DEFAULT 1
				)
			""")
			conn.execute("""
				CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name)
			""")
			conn.execute("""
				CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id)
			""")
			conn.execute("""
				CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp ON tool_calls(timestamp)
			""")

	def _connect(self) -> sqlite3.Connection:
		conn = sqlite3.connect(str(self.db_path))
		conn.row_factory = sqlite3.Row
		return conn

	def record(self, record: ToolCallRecord) -> None:
		"""Insert a tool call record."""
		with self._connect() as conn:
			conn.execute(
				"""
				INSERT INTO tool_calls
				(tool_name, args_json, result_summary, duration_seconds, timestamp, session_id, success)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				""",
				(
					record.tool_name,
					record.args_json,
					record.result_summary,
					record.duration_seconds,
					record.timestamp,
					record.session_id,
					1 if record.success else 0,
				),
			)

	def query(
		self,
		tool_name: Optional[str] = None,
		session_id: Optional[str] = None,
		since: Optional[str] = None,
		limit: int = 100,
	) -> list[ToolCallRecord]:
		"""Query tool call records with optional filters."""
		conditions: list[str] = []
		params: list[Any] = []

		if tool_name:
			conditions.append("tool_name = ?")
			params.append(tool_name)
		if session_id:
			conditions.append("session_id = ?")
			params.append(session_id)
		if since:
			conditions.append("timestamp >= ?")
			params.append(since)

		where = " AND ".join(conditions) if conditions else "1=1"

		with self._connect() as conn:
			cursor = conn.execute(
				f"SELECT * FROM tool_calls WHERE {where} ORDER BY timestamp DESC LIMIT ?",
				[*params, limit],
			)
			rows = cursor.fetchall()

		return [
			ToolCallRecord(
				tool_name=row["tool_name"],
				args_json=row["args_json"],
				result_summary=row["result_summary"],
				duration_seconds=row["duration_seconds"],
				timestamp=row["timestamp"],
				session_id=row["session_id"],
				success=bool(row["success"]),
			)
			for row in rows
		]

	def get_stats(self) -> list[ToolStats]:
		"""Get aggregate stats per tool."""
		with self._connect() as conn:
			cursor = conn.execute("""
				SELECT
					tool_name,
					COUNT(*) as call_count,
					AVG(duration_seconds) as avg_duration,
					SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
					MAX(timestamp) as last_called
				FROM tool_calls
				GROUP BY tool_name
				ORDER BY call_count DESC
			""")
			rows = cursor.fetchall()

		return [
			ToolStats(
				tool_name=row["tool_name"],
				call_count=row["call_count"],
				avg_duration=row["avg_duration"],
				success_rate=row["success_rate"],
				last_called=row["last_called"],
			)
			for row in rows
		]

	def clear(self, before: Optional[str] = None) -> int:
		"""Delete records, optionally only those before a timestamp. Returns count deleted."""
		with self._connect() as conn:
			if before:
				cursor = conn.execute("DELETE FROM tool_calls WHERE timestamp < ?", (before,))
			else:
				cursor = conn.execute("DELETE FROM tool_calls")
			return cursor.rowcount


def _summarize_result(result: Any, max_len: int = 200) -> str:
	"""Create a short summary of a tool result."""
	text = str(result)
	if len(text) > max_len:
		return text[:max_len] + "..."
	return text


def instrument_mcp_server(server: Any) -> None:
	"""
	Wrap a FastMCP server's tool handler to auto-record calls.

	Patches the server's internal tool dispatch to record every call.
	"""
	store = ToolCallStore()

	# FastMCP stores tools in _tool_manager.tools dict
	# Each tool has a .fn attribute that is the actual callable
	tool_manager = getattr(server, "_tool_manager", None)
	if tool_manager is None:
		logger.warning("Could not find _tool_manager on server, skipping instrumentation")
		return

	tools = getattr(tool_manager, "tools", None)
	if tools is None:
		logger.warning("Could not find tools dict on tool_manager, skipping instrumentation")
		return

	for tool_name, tool_obj in tools.items():
		original_fn = tool_obj.fn

		@wraps(original_fn)
		async def instrumented(*args, _orig=original_fn, _name=tool_name, **kwargs):
			start = time.monotonic()
			success = True
			result = None
			try:
				result = await _orig(*args, **kwargs)
				return result
			except Exception as exc:
				success = False
				result = str(exc)
				raise
			finally:
				duration = time.monotonic() - start
				try:
					args_str = json.dumps(kwargs, default=str)[:500] if kwargs else ""
					record = ToolCallRecord(
						tool_name=_name,
						args_json=args_str,
						result_summary=_summarize_result(result),
						duration_seconds=round(duration, 4),
						success=success,
					)
					store.record(record)
				except Exception:
					logger.debug(f"Failed to record tool call for {_name}", exc_info=True)

		tool_obj.fn = instrumented

	logger.info(f"Instrumented {len(tools)} MCP tools")


# Global store singleton
_store: Optional[ToolCallStore] = None


def get_tool_call_store(db_path: str = "") -> ToolCallStore:
	"""Get or create the global tool call store."""
	global _store
	if _store is None:
		_store = ToolCallStore(db_path)
	return _store
