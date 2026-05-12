"""Format-agnostic ingestion contracts.

The pipeline is wired together from objects implementing these protocols:

    SourceLoader -> Parser -> Chunker -> Enricher* -> Embedder -> Sink

A new file format means writing one Parser. Nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol


@dataclass
class RawDocument:
    """Bytes loaded from somewhere, plus addressing metadata."""

    source_uri: str               # file:///..., s3://..., https://...
    file_name: str
    mime_type: str
    content: bytes
    tenant_id: str = "default"
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Block:
    """A normalized text block emitted by a Parser."""

    text: str
    page: int | None = None       # None for non-paginated formats
    section: str | None = None    # heading / slide title / table id / etc.
    extra: dict[str, Any] = field(default_factory=dict)
    # v2: populated by UnstructuredParser for HierarchyEnricher
    heading_chain: list[str] = field(default_factory=list)        # ancestor heading IDs
    heading_chain_texts: list[str] = field(default_factory=list)  # ancestor heading texts


@dataclass
class Chunk:
    """A retrieval-sized unit, ready to embed and upsert."""

    text: str
    chunk_index: int
    page: int | None = None
    section: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestRecord:
    """One row destined for the vector store."""

    text: str
    vector: list[float]
    tenant_id: str
    doc_sha256: str
    source_uri: str
    file_name: str
    mime_type: str
    format: str
    chunk_index: int
    page: int | None
    section: str | None
    language: str | None
    tags: list[str]
    created_at: datetime
    ingested_at: datetime
    extra: dict[str, Any]
    # v2: enriched metadata fields (all optional with safe defaults)
    element_type: str | None = None
    hierarchy_path: str | None = None
    ancestral_headings: list[dict] = field(default_factory=list)
    breadcrumb: str | None = None
    hierarchy_depth: int = 0
    keywords: list[str] = field(default_factory=list)
    confidence_score: float = 0.75
    is_duplicate: bool = False
    duplicate_of: str | None = None


# ---------- Protocols ----------

class SourceLoader(Protocol):
    """Resolve a URI to bytes + metadata."""

    def can_load(self, uri: str) -> bool: ...
    def load(self, uri: str, **kw: Any) -> RawDocument: ...


class Parser(Protocol):
    """Turn raw bytes into normalized text blocks."""

    name: str
    mime_types: tuple[str, ...]
    extensions: tuple[str, ...]

    def parse(self, doc: RawDocument) -> Iterable[Block]: ...


class Chunker(Protocol):
    """Group blocks into retrieval-sized chunks."""

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]: ...


class Enricher(Protocol):
    """Optionally add fields to a chunk (language, tags, summary, etc.)."""

    def enrich(self, chunk: Chunk, doc: RawDocument) -> Chunk: ...


class Embedder(Protocol):
    """Batch-embed text."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Sink(Protocol):
    """Persist records to a vector store."""

    def ensure_schema(self) -> None: ...
    def already_indexed(self, doc_sha256: str, tenant_id: str) -> bool: ...
    def upsert(self, records: list[IngestRecord]) -> int: ...


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
