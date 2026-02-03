"""Web dashboard for claude-orchestrator observability."""

from __future__ import annotations

import webbrowser


def create_app(db_path: str = "") -> object:
	"""Create the Starlette ASGI application."""
	from .app import build_app

	return build_app(db_path=db_path)


def run_web_dashboard(port: int = 8420, db_path: str = "", open_browser: bool = True) -> None:
	"""Run the web dashboard server."""
	try:
		import uvicorn
	except ImportError:
		raise SystemExit(
			"Web extras not installed. Install with: pip install -e '.[web]'"
		)

	app = create_app(db_path=db_path)

	if open_browser:
		import threading

		def _open():
			import time
			time.sleep(0.8)
			webbrowser.open(f"http://localhost:{port}")

		threading.Thread(target=_open, daemon=True).start()

	print(f"Dashboard running at http://localhost:{port}")
	print("Press Ctrl+C to stop.")
	uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
