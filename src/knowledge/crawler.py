"""
Documentation Crawler - Crawls doc sites and saves as markdown.

Features:
- Async crawling with aiohttp
- HTML to markdown conversion
- Internal link following
- Metadata preservation
- Rate limiting
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from markdownify import markdownify as md

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
	"""Result of crawling a single page."""
	url: str
	title: str
	content: str
	markdown: str
	links: list[str]
	crawled_at: str


@dataclass
class CrawlStats:
	"""Statistics from a crawl session."""
	total_pages: int
	successful: int
	failed: int
	skipped: int
	duration_seconds: float


class DocCrawler:
	"""
	Crawls documentation sites and saves pages as markdown files.

	Usage:
		crawler = DocCrawler()
		stats = await crawler.crawl_site(
			start_url="https://docs.anthropic.com/",
			output_dir=Path("data/knowledge/claude-sdk"),
			max_pages=100
		)
	"""

	# Default selectors for extracting main content
	CONTENT_SELECTORS = [
		"main",
		"article",
		".content",
		".documentation",
		".docs-content",
		"#main-content",
		"[role='main']",
	]

	# Elements to remove before conversion
	REMOVE_SELECTORS = [
		"nav",
		"header",
		"footer",
		".sidebar",
		".navigation",
		".breadcrumb",
		".edit-page",
		"script",
		"style",
	]

	def __init__(
		self,
		rate_limit: float = 0.5,
		max_concurrent: int = 5,
		timeout: int = 30,
		user_agent: str = "DocCrawler/1.0 (Claude Orchestrator)",
	):
		"""
		Initialize the crawler.

		Args:
			rate_limit: Seconds between requests to same domain
			max_concurrent: Maximum concurrent requests
			timeout: Request timeout in seconds
			user_agent: User agent string
		"""
		self.rate_limit = rate_limit
		self.max_concurrent = max_concurrent
		self.timeout = timeout
		self.user_agent = user_agent

		self._crawled_urls: set[str] = set()
		self._failed_urls: set[str] = set()
		self._queue: asyncio.Queue[str] = asyncio.Queue()
		self._semaphore: Optional[asyncio.Semaphore] = None

	async def crawl_site(
		self,
		start_url: str,
		output_dir: Path,
		max_pages: int = 100,
		allowed_paths: Optional[list[str]] = None,
	) -> CrawlStats:
		"""
		Crawl a documentation site starting from the given URL.

		Args:
			start_url: URL to start crawling from
			output_dir: Directory to save markdown files
			max_pages: Maximum number of pages to crawl
			allowed_paths: Optional list of path prefixes to restrict crawling

		Returns:
			CrawlStats with crawl results
		"""
		start_time = datetime.now()
		output_dir.mkdir(parents=True, exist_ok=True)

		# Parse start URL to get base domain
		parsed = urlparse(start_url)
		base_domain = f"{parsed.scheme}://{parsed.netloc}"

		# Reset state
		self._crawled_urls = set()
		self._failed_urls = set()
		self._queue = asyncio.Queue()
		self._semaphore = asyncio.Semaphore(self.max_concurrent)

		# Add start URL to queue
		await self._queue.put(start_url)

		# Create session and start crawling
		async with aiohttp.ClientSession(
			headers={"User-Agent": self.user_agent},
			timeout=aiohttp.ClientTimeout(total=self.timeout),
		) as session:
			tasks = []
			while (
				not self._queue.empty() or tasks
			) and len(self._crawled_urls) < max_pages:
				# Start new tasks if queue has items and we have capacity
				while not self._queue.empty() and len(tasks) < self.max_concurrent:
					url = await self._queue.get()
					if url not in self._crawled_urls and url not in self._failed_urls:
						task = asyncio.create_task(
							self._crawl_page(
								session,
								url,
								base_domain,
								output_dir,
								allowed_paths,
							)
						)
						tasks.append(task)

				if tasks:
					# Wait for at least one task to complete
					done, pending = await asyncio.wait(
						tasks, return_when=asyncio.FIRST_COMPLETED
					)
					tasks = list(pending)

					# Process completed tasks
					for task in done:
						try:
							result = task.result()
							if result:
								# Add discovered links to queue
								for link in result.links:
									if (
										link not in self._crawled_urls
										and link not in self._failed_urls
										and len(self._crawled_urls) < max_pages
									):
										await self._queue.put(link)
						except Exception as e:
							logger.error(f"Task error: {e}")

				# Rate limiting
				await asyncio.sleep(self.rate_limit)

		duration = (datetime.now() - start_time).total_seconds()

		stats = CrawlStats(
			total_pages=len(self._crawled_urls) + len(self._failed_urls),
			successful=len(self._crawled_urls),
			failed=len(self._failed_urls),
			skipped=0,
			duration_seconds=duration,
		)

		logger.info(
			f"Crawl complete: {stats.successful} pages in {stats.duration_seconds:.1f}s"
		)
		return stats

	async def _crawl_page(
		self,
		session: aiohttp.ClientSession,
		url: str,
		base_domain: str,
		output_dir: Path,
		allowed_paths: Optional[list[str]],
	) -> Optional[CrawlResult]:
		"""Crawl a single page and save as markdown."""
		async with self._semaphore:
			try:
				# Check if URL is allowed
				parsed = urlparse(url)
				if allowed_paths:
					if not any(parsed.path.startswith(p) for p in allowed_paths):
						return None

				logger.debug(f"Crawling: {url}")

				async with session.get(url) as response:
					if response.status != 200:
						self._failed_urls.add(url)
						logger.warning(f"Failed to fetch {url}: {response.status}")
						return None

					html = await response.text()

				# Parse and extract content
				result = self._parse_page(url, html, base_domain)
				self._crawled_urls.add(url)

				# Save to file
				self._save_page(result, output_dir)

				return result

			except Exception as e:
				self._failed_urls.add(url)
				logger.error(f"Error crawling {url}: {e}")
				return None

	def _parse_page(self, url: str, html: str, base_domain: str) -> CrawlResult:
		"""Parse HTML and extract content."""
		from bs4 import BeautifulSoup

		soup = BeautifulSoup(html, "html.parser")

		# Extract title
		title_tag = soup.find("title")
		title = title_tag.get_text().strip() if title_tag else url

		# Remove unwanted elements
		for selector in self.REMOVE_SELECTORS:
			for element in soup.select(selector):
				element.decompose()

		# Find main content
		content_element = None
		for selector in self.CONTENT_SELECTORS:
			content_element = soup.select_one(selector)
			if content_element:
				break

		if not content_element:
			content_element = soup.body if soup.body else soup

		# Extract links before conversion
		links = []
		for a_tag in content_element.find_all("a", href=True):
			href = a_tag["href"]
			# Convert relative URLs to absolute
			full_url = urljoin(url, href)
			parsed = urlparse(full_url)

			# Only include internal links
			if full_url.startswith(base_domain):
				# Remove fragments and query params for deduplication
				clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
				if clean_url not in links:
					links.append(clean_url)

		# Convert to markdown
		markdown = md(str(content_element), heading_style="ATX", strip=["script", "style"])

		# Clean up markdown
		markdown = self._clean_markdown(markdown)

		return CrawlResult(
			url=url,
			title=title,
			content=str(content_element),
			markdown=markdown,
			links=links,
			crawled_at=datetime.now().isoformat(),
		)

	def _clean_markdown(self, markdown: str) -> str:
		"""Clean up converted markdown."""
		# Remove excessive blank lines
		markdown = re.sub(r"\n{3,}", "\n\n", markdown)

		# Remove trailing whitespace
		lines = [line.rstrip() for line in markdown.split("\n")]
		markdown = "\n".join(lines)

		return markdown.strip()

	def _save_page(self, result: CrawlResult, output_dir: Path):
		"""Save a crawled page as markdown with frontmatter."""
		# Generate filename from URL
		parsed = urlparse(result.url)
		path = parsed.path.strip("/")
		if not path:
			path = "index"

		# Sanitize path for filesystem
		safe_path = re.sub(r"[^\w\-/]", "_", path)
		filename = f"{safe_path}.md"

		# Create subdirectories if needed
		file_path = output_dir / filename
		file_path.parent.mkdir(parents=True, exist_ok=True)

		# Build frontmatter
		frontmatter = f"""---
title: "{result.title}"
url: "{result.url}"
crawled_at: "{result.crawled_at}"
---

"""

		# Write file
		file_path.write_text(frontmatter + result.markdown, encoding="utf-8")
		logger.debug(f"Saved: {file_path}")

	def _url_to_hash(self, url: str) -> str:
		"""Generate a short hash for a URL."""
		return hashlib.md5(url.encode()).hexdigest()[:8]
