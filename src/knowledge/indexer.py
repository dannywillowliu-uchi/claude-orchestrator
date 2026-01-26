"""
Documentation Indexer - Indexes markdown files in LanceDB for semantic search.

Features:
- Chunk documents into manageable pieces
- Generate embeddings with sentence-transformers
- Store in LanceDB for fast vector search
- Track file modification times for staleness detection
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import lancedb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Default embedding model - small and efficient
DEFAULT_MODEL = "all-MiniLM-L6-v2"


@dataclass
class DocumentChunk:
	"""A chunk of a document for indexing."""
	id: str
	source_file: str
	source_url: str
	title: str
	content: str
	section: str
	chunk_index: int
	embedding: Optional[list[float]] = None


@dataclass
class IndexStats:
	"""Statistics from an indexing session."""
	total_files: int
	total_chunks: int
	new_chunks: int
	updated_chunks: int
	duration_seconds: float


class DocIndexer:
	"""
	Indexes documentation files in LanceDB for semantic search.

	Usage:
		indexer = DocIndexer("data/docs_index")
		stats = await indexer.index_directory(Path("data/knowledge/claude-sdk"))
	"""

	CHUNK_SIZE = 500  # Target tokens per chunk
	CHUNK_OVERLAP = 50  # Overlap between chunks
	TABLE_NAME = "documents"

	def __init__(
		self,
		db_path: str,
		model_name: str = DEFAULT_MODEL,
	):
		"""
		Initialize the indexer.

		Args:
			db_path: Path to LanceDB database
			model_name: Sentence transformer model name
		"""
		self.db_path = Path(db_path)
		self.db_path.mkdir(parents=True, exist_ok=True)

		self.model_name = model_name
		self._model: Optional[SentenceTransformer] = None
		self._db: Optional[lancedb.DBConnection] = None

	@property
	def model(self) -> SentenceTransformer:
		"""Lazy load the embedding model."""
		if self._model is None:
			logger.info(f"Loading embedding model: {self.model_name}")
			self._model = SentenceTransformer(self.model_name)
		return self._model

	@property
	def db(self) -> lancedb.DBConnection:
		"""Lazy connect to database."""
		if self._db is None:
			self._db = lancedb.connect(str(self.db_path))
		return self._db

	async def index_directory(
		self,
		docs_dir: Path,
		source_name: Optional[str] = None,
	) -> IndexStats:
		"""
		Index all markdown files in a directory.

		Args:
			docs_dir: Directory containing markdown files
			source_name: Optional name for this documentation source

		Returns:
			IndexStats with indexing results
		"""
		start_time = datetime.now()

		if not docs_dir.exists():
			raise ValueError(f"Directory not found: {docs_dir}")

		source_name = source_name or docs_dir.name

		# Find all markdown files
		md_files = list(docs_dir.rglob("*.md"))
		logger.info(f"Found {len(md_files)} markdown files in {docs_dir}")

		# Process each file
		all_chunks: list[dict] = []
		for md_file in md_files:
			chunks = self._process_file(md_file, source_name)
			all_chunks.extend(chunks)

		if not all_chunks:
			return IndexStats(
				total_files=len(md_files),
				total_chunks=0,
				new_chunks=0,
				updated_chunks=0,
				duration_seconds=(datetime.now() - start_time).total_seconds(),
			)

		# Generate embeddings
		logger.info(f"Generating embeddings for {len(all_chunks)} chunks...")
		texts = [c["content"] for c in all_chunks]
		embeddings = self.model.encode(texts, show_progress_bar=True)

		for chunk, embedding in zip(all_chunks, embeddings):
			chunk["vector"] = embedding.tolist()

		# Upsert to LanceDB
		self._upsert_chunks(all_chunks, source_name)

		duration = (datetime.now() - start_time).total_seconds()

		stats = IndexStats(
			total_files=len(md_files),
			total_chunks=len(all_chunks),
			new_chunks=len(all_chunks),  # Simplified - all treated as new
			updated_chunks=0,
			duration_seconds=duration,
		)

		logger.info(
			f"Indexed {stats.total_chunks} chunks from {stats.total_files} files "
			f"in {stats.duration_seconds:.1f}s"
		)
		return stats

	def _process_file(self, file_path: Path, source_name: str) -> list[dict]:
		"""Process a single markdown file into chunks."""
		content = file_path.read_text(encoding="utf-8")

		# Parse frontmatter
		title, url, body = self._parse_frontmatter(content)
		if not title:
			title = file_path.stem

		# Split into sections
		sections = self._split_sections(body)

		# Create chunks
		chunks = []
		for section_name, section_content in sections:
			section_chunks = self._chunk_text(section_content)

			for i, chunk_text in enumerate(section_chunks):
				chunk_id = self._generate_chunk_id(file_path, section_name, i)
				chunks.append({
					"id": chunk_id,
					"source": source_name,
					"source_file": str(file_path),
					"source_url": url or "",
					"title": title,
					"section": section_name,
					"chunk_index": i,
					"content": chunk_text,
					"indexed_at": datetime.now().isoformat(),
				})

		return chunks

	def _parse_frontmatter(self, content: str) -> tuple[str, str, str]:
		"""Parse YAML frontmatter from markdown."""
		title = ""
		url = ""
		body = content

		if content.startswith("---"):
			parts = content.split("---", 2)
			if len(parts) >= 3:
				frontmatter = parts[1]
				body = parts[2].strip()

				# Simple parsing of frontmatter
				for line in frontmatter.split("\n"):
					if line.startswith("title:"):
						title = line.split(":", 1)[1].strip().strip('"\'')
					elif line.startswith("url:"):
						url = line.split(":", 1)[1].strip().strip('"\'')

		return title, url, body

	def _split_sections(self, content: str) -> list[tuple[str, str]]:
		"""Split markdown into sections based on headings."""
		sections = []
		current_section = "Introduction"
		current_content = []

		for line in content.split("\n"):
			# Check for heading
			heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
			if heading_match:
				# Save previous section
				if current_content:
					text = "\n".join(current_content).strip()
					if text:
						sections.append((current_section, text))

				current_section = heading_match.group(2)
				current_content = []
			else:
				current_content.append(line)

		# Save last section
		if current_content:
			text = "\n".join(current_content).strip()
			if text:
				sections.append((current_section, text))

		return sections if sections else [("Content", content)]

	def _chunk_text(self, text: str) -> list[str]:
		"""Split text into chunks of roughly CHUNK_SIZE tokens."""
		# Approximate tokens as words * 1.3
		words = text.split()
		if not words:
			return []

		target_words = int(self.CHUNK_SIZE / 1.3)
		overlap_words = int(self.CHUNK_OVERLAP / 1.3)

		chunks = []
		i = 0
		while i < len(words):
			end = min(i + target_words, len(words))
			chunk = " ".join(words[i:end])
			chunks.append(chunk)

			# Move forward with overlap
			i = end - overlap_words if end < len(words) else end

		return chunks

	def _generate_chunk_id(self, file_path: Path, section: str, index: int) -> str:
		"""Generate a unique ID for a chunk."""
		key = f"{file_path}:{section}:{index}"
		return hashlib.md5(key.encode()).hexdigest()[:16]

	def _upsert_chunks(self, chunks: list[dict], source_name: str):
		"""Insert or update chunks in the database."""
		if not chunks:
			return

		# Check if table exists
		table_names = self.db.table_names()

		if self.TABLE_NAME in table_names:
			table = self.db.open_table(self.TABLE_NAME)
			# For simplicity, delete existing chunks from this source and re-add
			# A more sophisticated approach would do incremental updates
			try:
				table.delete(f"source = '{source_name}'")
			except Exception:
				pass  # Table might be empty
			table.add(chunks)
		else:
			# Create new table
			self.db.create_table(self.TABLE_NAME, chunks)

		logger.debug(f"Upserted {len(chunks)} chunks to {self.TABLE_NAME}")

	def search(
		self,
		query: str,
		limit: int = 5,
		source: Optional[str] = None,
	) -> list[dict]:
		"""
		Search for documents matching the query.

		Args:
			query: Search query
			limit: Maximum results to return
			source: Optional source filter

		Returns:
			List of matching document chunks
		"""
		if self.TABLE_NAME not in self.db.table_names():
			return []

		# Generate query embedding
		query_embedding = self.model.encode(query).tolist()

		table = self.db.open_table(self.TABLE_NAME)

		# Build search query
		search = table.search(query_embedding).limit(limit)

		if source:
			search = search.where(f"source = '{source}'")

		results = search.to_list()

		# Clean up results (remove vector field)
		for r in results:
			r.pop("vector", None)

		return results

	def list_sources(self) -> list[dict]:
		"""List all indexed documentation sources."""
		if self.TABLE_NAME not in self.db.table_names():
			return []

		table = self.db.open_table(self.TABLE_NAME)
		df = table.to_pandas()

		if df.empty:
			return []

		sources = df.groupby("source").agg({
			"source_file": "nunique",
			"id": "count",
			"indexed_at": "max",
		}).reset_index()

		return [
			{
				"name": row["source"],
				"files": int(row["source_file"]),
				"chunks": int(row["id"]),
				"last_indexed": row["indexed_at"],
			}
			for _, row in sources.iterrows()
		]

	def get_document(self, source_file: str) -> Optional[str]:
		"""Get the full content of a document by file path."""
		if self.TABLE_NAME not in self.db.table_names():
			return None

		table = self.db.open_table(self.TABLE_NAME)
		df = table.to_pandas()

		# Find all chunks for this file
		chunks = df[df["source_file"] == source_file].sort_values("chunk_index")

		if chunks.empty:
			return None

		# Reconstruct document
		content = "\n\n".join(chunks["content"].tolist())
		title = chunks.iloc[0]["title"]

		return f"# {title}\n\n{content}"
