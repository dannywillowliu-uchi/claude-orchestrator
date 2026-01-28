"""Visual verification tools - screenshots and element checking."""

import json

from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..visual_verification import get_verifier


def register_visual_tools(mcp: FastMCP, config: Config) -> None:
	"""Register visual verification tools."""

	@mcp.tool()
	async def take_screenshot(
		url: str, name: str = "", full_page: bool = False, wait_for: str = "",
	) -> str:
		"""
		Take a screenshot of a webpage for visual verification.

		The screenshot is saved to data/screenshots/ and can be analyzed using Claude's vision.

		Args:
			url: The URL to screenshot
			name: Optional filename (without extension). Auto-generated if not provided.
			full_page: Whether to capture the full scrollable page (default: False)
			wait_for: CSS selector to wait for before taking screenshot (optional)
		"""
		verifier = await get_verifier()
		screenshot = await verifier.take_screenshot(
			url=url,
			name=name if name else None,
			full_page=full_page,
			wait_for=wait_for if wait_for else None,
		)
		return json.dumps({
			"success": True, "path": screenshot.path, "url": screenshot.url,
			"timestamp": screenshot.timestamp,
			"dimensions": f"{screenshot.width}x{screenshot.height}",
			"full_page": screenshot.full_page,
			"message": f"Screenshot saved to {screenshot.path}. Use Read tool to view and analyze it.",
		})

	@mcp.tool()
	async def take_element_screenshot(url: str, selector: str, name: str = "") -> str:
		"""
		Take a screenshot of a specific element on a webpage.

		Args:
			url: The URL to navigate to
			selector: CSS selector of the element to screenshot
			name: Optional filename (without extension)
		"""
		verifier = await get_verifier()
		try:
			screenshot = await verifier.take_element_screenshot(
				url=url, selector=selector, name=name if name else None,
			)
			return json.dumps({
				"success": True, "path": screenshot.path, "url": screenshot.url,
				"selector": selector, "timestamp": screenshot.timestamp,
				"dimensions": f"{screenshot.width}x{screenshot.height}",
				"message": f"Element screenshot saved to {screenshot.path}",
			})
		except ValueError as e:
			return json.dumps({"success": False, "error": str(e)})

	@mcp.tool()
	async def verify_element(url: str, selector: str, timeout: int = 10000) -> str:
		"""
		Verify that an element exists on a webpage.

		Args:
			url: The URL to check
			selector: CSS selector to find
			timeout: How long to wait for element in ms (default: 10000)
		"""
		verifier = await get_verifier()
		result = await verifier.verify_element_exists(url=url, selector=selector, timeout=timeout)
		return json.dumps({"success": True, **result})

	@mcp.tool()
	async def get_page_content(url: str, selector: str = "") -> str:
		"""
		Get text content from a webpage or specific element.

		Args:
			url: The URL to navigate to
			selector: CSS selector for specific element (gets full body text if not provided)
		"""
		verifier = await get_verifier()
		text = await verifier.get_page_text(url=url, selector=selector if selector else None)
		truncated = len(text) > 10000
		if truncated:
			text = text[:10000] + "\n\n[Content truncated - showing first 10000 characters]"
		return json.dumps({
			"success": True, "url": url, "selector": selector or "body",
			"text": text, "truncated": truncated,
		})

	@mcp.tool()
	async def list_screenshots() -> str:
		"""List all screenshots in the screenshots directory."""
		verifier = await get_verifier()
		screenshots = await verifier.list_screenshots()
		return json.dumps({"success": True, "count": len(screenshots), "screenshots": screenshots})

	@mcp.tool()
	async def delete_screenshot(name: str) -> str:
		"""
		Delete a screenshot by filename.

		Args:
			name: The filename of the screenshot to delete (e.g., "homepage_20260113_120000.png")
		"""
		verifier = await get_verifier()
		deleted = await verifier.delete_screenshot(name)
		if deleted:
			return json.dumps({"success": True, "message": f"Deleted screenshot: {name}"})
		else:
			return json.dumps({"success": False, "error": f"Screenshot not found: {name}"})
