"""
Documentation Retriever - MCP tools for searching indexed documentation.

Provides semantic search over crawled and indexed documentation.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .indexer import DocIndexer

logger = logging.getLogger(__name__)

# Global indexer instance
_indexer: Optional[DocIndexer] = None

# Default paths
DEFAULT_DB_PATH = "data/docs_index"
DEFAULT_KNOWLEDGE_DIR = "data/knowledge"


def get_indexer(db_path: str = DEFAULT_DB_PATH) -> DocIndexer:
	"""Get or create the global indexer instance."""
	global _indexer
	if _indexer is None:
		_indexer = DocIndexer(db_path)
	return _indexer


async def search_docs(
	query: str,
	max_results: int = 5,
	source: Optional[str] = None,
) -> str:
	"""
	Semantic search over indexed documentation.

	Args:
		query: The search query (natural language)
		max_results: Maximum number of results to return (default: 5)
		source: Optional source filter (e.g., "claude-sdk", "claude-code")

	Returns:
		JSON string with search results including:
		- title: Document title
		- section: Section within the document
		- content: Matching content snippet
		- source_url: Original URL if available
		- source_file: Path to the indexed file

	Example:
		search_docs("how to use tools in Claude API")
		search_docs("error handling", source="claude-sdk")
	"""
	try:
		indexer = get_indexer()
		results = indexer.search(query, limit=max_results, source=source)

		if not results:
			return json.dumps({
				"results": [],
				"message": "No matching documents found. Try a different query or check if documentation has been indexed.",
			})

		# Format results
		formatted = []
		for r in results:
			formatted.append({
				"title": r.get("title", "Unknown"),
				"section": r.get("section", ""),
				"content": r.get("content", "")[:500] + "..." if len(r.get("content", "")) > 500 else r.get("content", ""),
				"source_url": r.get("source_url", ""),
				"source_file": r.get("source_file", ""),
				"relevance": r.get("_distance", 0),
			})

		return json.dumps({
			"results": formatted,
			"total": len(formatted),
			"query": query,
		}, indent=2)

	except Exception as e:
		logger.error(f"Search error: {e}")
		return json.dumps({"error": str(e)})


async def get_doc(path: str) -> str:
	"""
	Get the full content of a specific document.

	Args:
		path: Path to the document file (as returned by search_docs)

	Returns:
		The full document content as markdown, or error message if not found.

	Example:
		get_doc("data/knowledge/claude-sdk/api/tools.md")
	"""
	try:
		# First try to read the file directly
		file_path = Path(path)
		if file_path.exists():
			return file_path.read_text(encoding="utf-8")

		# Fall back to reconstructing from index
		indexer = get_indexer()
		content = indexer.get_document(path)

		if content:
			return content

		return json.dumps({
			"error": f"Document not found: {path}",
			"hint": "Use search_docs to find available documents",
		})

	except Exception as e:
		logger.error(f"Get doc error: {e}")
		return json.dumps({"error": str(e)})


async def list_doc_sources() -> str:
	"""
	List all indexed documentation sources.

	Returns:
		JSON string with available documentation sources including:
		- name: Source name (e.g., "claude-sdk")
		- files: Number of indexed files
		- chunks: Number of indexed chunks
		- last_indexed: When the source was last indexed

	Example:
		list_doc_sources()
	"""
	try:
		indexer = get_indexer()
		sources = indexer.list_sources()

		if not sources:
			return json.dumps({
				"sources": [],
				"message": "No documentation has been indexed yet. Use the crawler to index documentation.",
			})

		return json.dumps({
			"sources": sources,
			"total": len(sources),
		}, indent=2)

	except Exception as e:
		logger.error(f"List sources error: {e}")
		return json.dumps({"error": str(e)})


async def index_docs(
	source_dir: str,
	source_name: Optional[str] = None,
) -> str:
	"""
	Index markdown documentation files from a directory.

	Args:
		source_dir: Directory containing markdown files to index
		source_name: Optional name for this documentation source

	Returns:
		JSON string with indexing statistics

	Example:
		index_docs("data/knowledge/claude-sdk")
	"""
	try:
		indexer = get_indexer()
		source_path = Path(source_dir)

		if not source_path.exists():
			return json.dumps({
				"error": f"Directory not found: {source_dir}",
			})

		stats = await indexer.index_directory(source_path, source_name)

		return json.dumps({
			"success": True,
			"source": source_name or source_path.name,
			"stats": {
				"total_files": stats.total_files,
				"total_chunks": stats.total_chunks,
				"duration_seconds": round(stats.duration_seconds, 2),
			},
		}, indent=2)

	except Exception as e:
		logger.error(f"Index error: {e}")
		return json.dumps({"error": str(e)})


async def crawl_and_index(
	start_url: str,
	source_name: str,
	max_pages: int = 100,
	allowed_paths: Optional[list[str]] = None,
) -> str:
	"""
	Crawl a documentation site and index it.

	Args:
		start_url: URL to start crawling from
		source_name: Name for this documentation source
		max_pages: Maximum pages to crawl (default: 100)
		allowed_paths: Optional list of path prefixes to restrict crawling

	Returns:
		JSON string with crawl and index statistics

	Example:
		crawl_and_index(
			"https://docs.anthropic.com/claude/reference",
			"claude-sdk",
			max_pages=50
		)
	"""
	try:
		from .crawler import DocCrawler

		output_dir = Path(DEFAULT_KNOWLEDGE_DIR) / source_name

		# Crawl
		crawler = DocCrawler()
		crawl_stats = await crawler.crawl_site(
			start_url=start_url,
			output_dir=output_dir,
			max_pages=max_pages,
			allowed_paths=allowed_paths,
		)

		# Index
		indexer = get_indexer()
		index_stats = await indexer.index_directory(output_dir, source_name)

		return json.dumps({
			"success": True,
			"source": source_name,
			"crawl": {
				"total_pages": crawl_stats.total_pages,
				"successful": crawl_stats.successful,
				"failed": crawl_stats.failed,
				"duration_seconds": round(crawl_stats.duration_seconds, 2),
			},
			"index": {
				"total_files": index_stats.total_files,
				"total_chunks": index_stats.total_chunks,
				"duration_seconds": round(index_stats.duration_seconds, 2),
			},
		}, indent=2)

	except Exception as e:
		logger.error(f"Crawl and index error: {e}")
		return json.dumps({"error": str(e)})
