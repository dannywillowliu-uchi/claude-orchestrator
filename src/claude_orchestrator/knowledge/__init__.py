"""
Knowledge module - Documentation storage and retrieval.

Provides:
- DocCrawler: Crawl documentation sites and save as markdown
- DocIndexer: Index documents in LanceDB for semantic search
- DocRetriever: MCP tools for searching documentation
"""

from .crawler import DocCrawler
from .indexer import DocIndexer
from .retriever import search_docs, get_doc, list_doc_sources

__all__ = [
	"DocCrawler",
	"DocIndexer",
	"search_docs",
	"get_doc",
	"list_doc_sources",
]
