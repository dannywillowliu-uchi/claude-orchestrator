"""Documentation knowledge base tools - search, index, crawl."""


from mcp.server.fastmcp import FastMCP

from ..config import Config
from ..knowledge import retriever as knowledge_retriever


def register_knowledge_tools(mcp: FastMCP, config: Config) -> None:
	"""Register knowledge/documentation tools."""

	@mcp.tool()
	async def search_docs(query: str, max_results: int = 5, source: str = "") -> str:
		"""
		Semantic search over indexed documentation.

		Args:
			query: The search query (natural language)
			max_results: Maximum number of results to return (default: 5)
			source: Optional source filter (e.g., "claude-sdk", "claude-code")
		"""
		return await knowledge_retriever.search_docs(
			query=query, max_results=max_results, source=source if source else None,
		)

	@mcp.tool()
	async def get_doc(path: str) -> str:
		"""
		Get the full content of a specific document.

		Args:
			path: Path to the document file (as returned by search_docs)
		"""
		return await knowledge_retriever.get_doc(path)

	@mcp.tool()
	async def list_doc_sources() -> str:
		"""List all indexed documentation sources."""
		return await knowledge_retriever.list_doc_sources()

	@mcp.tool()
	async def index_docs(source_dir: str, source_name: str = "") -> str:
		"""
		Index markdown documentation files from a directory.

		Args:
			source_dir: Directory containing markdown files to index
			source_name: Optional name for this documentation source
		"""
		return await knowledge_retriever.index_docs(
			source_dir=source_dir, source_name=source_name if source_name else None,
		)

	@mcp.tool()
	async def crawl_and_index_docs(start_url: str, source_name: str, max_pages: int = 100) -> str:
		"""
		Crawl a documentation site and index it for semantic search.

		Args:
			start_url: URL to start crawling from
			source_name: Name for this documentation source
			max_pages: Maximum pages to crawl (default: 100)
		"""
		return await knowledge_retriever.crawl_and_index(
			start_url=start_url, source_name=source_name, max_pages=max_pages,
		)
