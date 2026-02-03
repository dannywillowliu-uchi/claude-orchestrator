"""JSON API endpoints and SSE stream for the web dashboard."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from ..instrumentation import ToolCallStore
from .templates import DASHBOARD_HTML


def get_store(request: Request) -> ToolCallStore:
	"""Get the ToolCallStore from app state."""
	return request.app.state.store


async def index(request: Request) -> HTMLResponse:
	"""Serve the dashboard HTML page."""
	return HTMLResponse(DASHBOARD_HTML)


async def api_stats(request: Request) -> JSONResponse:
	"""Per-tool aggregates: call count, avg duration, success rate."""
	store = get_store(request)
	stats = await asyncio.to_thread(store.get_stats)
	return JSONResponse([
		{
			"tool_name": s.tool_name,
			"call_count": s.call_count,
			"avg_duration": round(s.avg_duration, 4),
			"success_rate": round(s.success_rate, 1),
			"last_called": s.last_called,
		}
		for s in stats
	])


async def api_registered_tools(request: Request) -> JSONResponse:
	"""All registered MCP tools with usage status."""
	store = get_store(request)
	registered = request.app.state.registered_tools
	stats = await asyncio.to_thread(store.get_stats)
	called_names = {s.tool_name for s in stats}

	tools = []
	for name in registered:
		stat = next((s for s in stats if s.tool_name == name), None)
		tools.append({
			"tool_name": name,
			"called": name in called_names,
			"call_count": stat.call_count if stat else 0,
			"avg_duration": round(stat.avg_duration, 4) if stat else 0,
			"success_rate": round(stat.success_rate, 1) if stat else 0,
		})
	return JSONResponse(tools)


async def api_calls(request: Request) -> JSONResponse:
	"""Recent tool call records with optional filters."""
	store = get_store(request)
	since = request.query_params.get("since")
	limit = int(request.query_params.get("limit", "50"))
	session_id = request.query_params.get("session_id")

	records = await asyncio.to_thread(
		store.query, None, session_id, since, limit
	)
	return JSONResponse([
		{
			"tool_name": r.tool_name,
			"args_json": r.args_json,
			"result_summary": r.result_summary,
			"duration_seconds": r.duration_seconds,
			"timestamp": r.timestamp,
			"session_id": r.session_id,
			"success": r.success,
		}
		for r in records
	])


async def api_sessions(request: Request) -> JSONResponse:
	"""Session list with aggregated stats."""
	store = get_store(request)
	records = await asyncio.to_thread(store.query, None, None, None, 10000)

	sessions: dict[str, dict] = {}
	for r in records:
		sid = r.session_id or "(no session)"
		if sid not in sessions:
			sessions[sid] = {
				"session_id": sid,
				"call_count": 0,
				"first_call": r.timestamp,
				"last_call": r.timestamp,
				"successes": 0,
			}
		s = sessions[sid]
		s["call_count"] += 1
		if r.success:
			s["successes"] += 1
		if r.timestamp < s["first_call"]:
			s["first_call"] = r.timestamp
		if r.timestamp > s["last_call"]:
			s["last_call"] = r.timestamp

	result = sorted(sessions.values(), key=lambda x: x["last_call"], reverse=True)
	return JSONResponse(result)


async def api_session_detail(request: Request) -> JSONResponse:
	"""All calls for a single session."""
	store = get_store(request)
	session_id = request.path_params["id"]
	records = await asyncio.to_thread(store.query, None, session_id, None, 500)
	return JSONResponse([
		{
			"tool_name": r.tool_name,
			"args_json": r.args_json,
			"result_summary": r.result_summary,
			"duration_seconds": r.duration_seconds,
			"timestamp": r.timestamp,
			"session_id": r.session_id,
			"success": r.success,
		}
		for r in records
	])


async def _sse_generator(store: ToolCallStore) -> AsyncGenerator[str, None]:
	"""Poll SQLite every 2s and yield new tool calls as SSE events."""
	last_timestamp = ""
	# Seed with the latest timestamp
	initial = await asyncio.to_thread(store.query, None, None, None, 1)
	if initial:
		last_timestamp = initial[0].timestamp

	# Send an initial event so the browser fires onopen reliably
	yield "event: connected\ndata: {}\n\n"

	while True:
		await asyncio.sleep(2)
		try:
			if last_timestamp:
				new_records = await asyncio.to_thread(
					store.query, None, None, last_timestamp, 50
				)
				# Filter out records with the exact same timestamp we already sent
				new_records = [r for r in new_records if r.timestamp > last_timestamp]
			else:
				new_records = await asyncio.to_thread(store.query, None, None, None, 1)

			if new_records:
				last_timestamp = new_records[0].timestamp
				data = json.dumps([
					{
						"tool_name": r.tool_name,
						"duration_seconds": r.duration_seconds,
						"timestamp": r.timestamp,
						"session_id": r.session_id,
						"success": r.success,
					}
					for r in new_records
				])
				yield f"event: new_calls\ndata: {data}\n\n"
			else:
				# Heartbeat to keep connection alive
				yield ": heartbeat\n\n"
		except Exception:
			yield ": error\n\n"


async def api_stream(request: Request) -> StreamingResponse:
	"""SSE endpoint - streams new tool calls as they arrive."""
	store = get_store(request)
	return StreamingResponse(
		_sse_generator(store),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)
