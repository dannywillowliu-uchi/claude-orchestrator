"""Shared utilities for visualizer views."""

from datetime import datetime


def format_duration(seconds: float) -> str:
	"""Format a duration for display. e.g. '1.2s', '45ms', '2m 3s'."""
	if seconds < 0.001:
		return "<1ms"
	if seconds < 1.0:
		return f"{seconds * 1000:.0f}ms"
	if seconds < 60.0:
		return f"{seconds:.1f}s"
	minutes = int(seconds // 60)
	secs = seconds % 60
	return f"{minutes}m {secs:.0f}s"


def format_timestamp(iso_str: str) -> str:
	"""Format an ISO timestamp as relative time (e.g. '2m ago') or absolute."""
	try:
		dt = datetime.fromisoformat(iso_str)
		delta = datetime.now() - dt
		total_secs = int(delta.total_seconds())

		if total_secs < 0:
			return iso_str[:19]
		if total_secs < 60:
			return f"{total_secs}s ago"
		if total_secs < 3600:
			return f"{total_secs // 60}m ago"
		if total_secs < 86400:
			return f"{total_secs // 3600}h ago"
		days = total_secs // 86400
		return f"{days}d ago"
	except (ValueError, TypeError):
		return str(iso_str)[:19]


def truncate_args(args_json: str, max_len: int = 60) -> str:
	"""Shorten an args JSON string for table display."""
	if not args_json:
		return ""
	text = args_json.strip()
	if len(text) <= max_len:
		return text
	return text[:max_len - 3] + "..."


def status_style(success: bool) -> str:
	"""Return a Rich style string for pass/fail."""
	return "green" if success else "red"


def status_text(success: bool) -> str:
	"""Return pass/fail text."""
	return "OK" if success else "FAIL"
