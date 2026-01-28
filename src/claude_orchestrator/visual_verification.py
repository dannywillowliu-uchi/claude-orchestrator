"""Visual Verification Module using Playwright.

Provides screenshot capture and browser automation for UI verification.
Claude can analyze screenshots using its vision capabilities.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, async_playwright

logger = logging.getLogger(__name__)


@dataclass
class Screenshot:
	"""Screenshot metadata."""
	path: str
	url: str
	timestamp: str
	width: int
	height: int
	full_page: bool


class VisualVerifier:
	"""Browser automation for visual verification."""

	def __init__(self, screenshot_dir: str = "data/screenshots"):
		self.screenshot_dir = Path(screenshot_dir)
		self.screenshot_dir.mkdir(parents=True, exist_ok=True)
		self._browser: Browser | None = None
		self._context: BrowserContext | None = None

	async def _ensure_browser(self) -> BrowserContext:
		"""Ensure browser is launched and return context."""
		if self._context is None:
			playwright = await async_playwright().start()
			self._browser = await playwright.chromium.launch(headless=True)
			self._context = await self._browser.new_context(
				viewport={"width": 1920, "height": 1080}
			)
		return self._context

	async def close(self):
		"""Close browser resources."""
		if self._context:
			await self._context.close()
			self._context = None
		if self._browser:
			await self._browser.close()
			self._browser = None

	async def take_screenshot(
		self,
		url: str,
		name: str | None = None,
		full_page: bool = False,
		wait_for: str | None = None,
		wait_timeout: int = 30000,
	) -> Screenshot:
		"""
		Take a screenshot of a URL.

		Args:
			url: The URL to screenshot
			name: Optional filename (without extension). Auto-generated if not provided.
			full_page: Whether to capture the full scrollable page
			wait_for: CSS selector to wait for before screenshot
			wait_timeout: Timeout in ms for wait_for selector

		Returns:
			Screenshot object with path and metadata
		"""
		context = await self._ensure_browser()
		page = await context.new_page()

		try:
			await page.goto(url, wait_until="networkidle", timeout=wait_timeout)

			if wait_for:
				await page.wait_for_selector(wait_for, timeout=wait_timeout)

			# Generate filename
			timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
			if name:
				filename = f"{name}_{timestamp}.png"
			else:
				# Create name from URL
				safe_url = url.replace("https://", "").replace("http://", "")
				safe_url = "".join(c if c.isalnum() else "_" for c in safe_url)[:50]
				filename = f"{safe_url}_{timestamp}.png"

			filepath = self.screenshot_dir / filename

			# Take screenshot
			await page.screenshot(path=str(filepath), full_page=full_page)

			# Get viewport size
			viewport = page.viewport_size

			return Screenshot(
				path=str(filepath),
				url=url,
				timestamp=timestamp,
				width=viewport["width"] if viewport else 1920,
				height=viewport["height"] if viewport else 1080,
				full_page=full_page,
			)
		finally:
			await page.close()

	async def take_element_screenshot(
		self,
		url: str,
		selector: str,
		name: str | None = None,
		wait_timeout: int = 30000,
	) -> Screenshot:
		"""
		Take a screenshot of a specific element.

		Args:
			url: The URL to navigate to
			selector: CSS selector of element to screenshot
			name: Optional filename (without extension)
			wait_timeout: Timeout in ms

		Returns:
			Screenshot object with path and metadata
		"""
		context = await self._ensure_browser()
		page = await context.new_page()

		try:
			await page.goto(url, wait_until="networkidle", timeout=wait_timeout)
			element = await page.wait_for_selector(selector, timeout=wait_timeout)

			if not element:
				raise ValueError(f"Element not found: {selector}")

			# Generate filename
			timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
			if name:
				filename = f"{name}_{timestamp}.png"
			else:
				safe_selector = "".join(c if c.isalnum() else "_" for c in selector)[:30]
				filename = f"element_{safe_selector}_{timestamp}.png"

			filepath = self.screenshot_dir / filename

			# Take element screenshot
			await element.screenshot(path=str(filepath))

			# Get bounding box for dimensions
			box = await element.bounding_box()

			return Screenshot(
				path=str(filepath),
				url=url,
				timestamp=timestamp,
				width=int(box["width"]) if box else 0,
				height=int(box["height"]) if box else 0,
				full_page=False,
			)
		finally:
			await page.close()

	async def verify_element_exists(
		self,
		url: str,
		selector: str,
		timeout: int = 10000,
	) -> dict:
		"""
		Verify an element exists on a page.

		Args:
			url: The URL to check
			selector: CSS selector to find
			timeout: Timeout in ms

		Returns:
			Dict with exists, visible, and text properties
		"""
		context = await self._ensure_browser()
		page = await context.new_page()

		try:
			await page.goto(url, wait_until="networkidle", timeout=30000)

			try:
				element = await page.wait_for_selector(selector, timeout=timeout)
				if element:
					visible = await element.is_visible()
					text = await element.text_content()
					return {
						"exists": True,
						"visible": visible,
						"text": text.strip() if text else "",
						"selector": selector,
					}
			except Exception:
				pass

			return {
				"exists": False,
				"visible": False,
				"text": "",
				"selector": selector,
			}
		finally:
			await page.close()

	async def get_page_text(
		self,
		url: str,
		selector: str | None = None,
		timeout: int = 30000,
	) -> str:
		"""
		Get text content from a page or element.

		Args:
			url: The URL to navigate to
			selector: Optional CSS selector (gets body text if not provided)
			timeout: Timeout in ms

		Returns:
			Text content
		"""
		context = await self._ensure_browser()
		page = await context.new_page()

		try:
			await page.goto(url, wait_until="networkidle", timeout=timeout)

			if selector:
				element = await page.wait_for_selector(selector, timeout=timeout)
				if element:
					return await element.text_content() or ""
				return ""
			else:
				return await page.inner_text("body")
		finally:
			await page.close()

	async def list_screenshots(self) -> list[dict]:
		"""List all screenshots in the screenshot directory."""
		screenshots = []
		for path in sorted(self.screenshot_dir.glob("*.png"), reverse=True):
			screenshots.append({
				"path": str(path),
				"name": path.name,
				"size_kb": path.stat().st_size // 1024,
				"modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
			})
		return screenshots

	async def delete_screenshot(self, name: str) -> bool:
		"""Delete a screenshot by name."""
		path = self.screenshot_dir / name
		if path.exists() and path.suffix == ".png":
			path.unlink()
			return True
		return False


# Global instance
_verifier: VisualVerifier | None = None


async def get_verifier() -> VisualVerifier:
	"""Get or create the global verifier instance."""
	global _verifier
	if _verifier is None:
		_verifier = VisualVerifier()
	return _verifier
