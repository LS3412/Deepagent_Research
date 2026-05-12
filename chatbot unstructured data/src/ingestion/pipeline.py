"""End-to-end ingestion pipeline (v2).

    load → sha256 dedupe → parse → chunk → enrich → dedup → embed → sink

All ingestion entrypoints (CLI, watcher, UI upload) call `ingest_path()` /
`ingest_bytes()` so idempotency + format handling live in one place.

v2 additions:
    - UnstructuredParser selected when chunk_strategy != "recursive"
    - EnricherChain: hierarchy, keywords, language, confidence per chunk
    - MinHashDeduplicator: near-duplicate detection (skips embed for dupes)
    - AsyncOllamaBatchEmbedder: concurrent batches (~3-4x faster)
    - 9 new IngestRecord fields mapped to Weaviate properties
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from src.config import get_settings
from src.ingestion.chunker import get_chunker
from src.ingestion.deduplicator import MinHashDeduplicator
from src.ingestion.embedder import AsyncOllamaBatchEmbedder, OllamaBatchEmbedder
from src.ingestion.enricher import build_enricher_chain
from src.ingestion.interfaces import (
    Chunk,
    IngestRecord,
    RawDocument,
    now_utc,
)
from src.ingestion.registry import load_builtin_parsers, select_parser
from src.ingestion.sink import WeaviateSink

log = logging.getLogger(__name__)

# Self-register all built-in parsers exactly once (includes UnstructuredParser).
load_builtin_parsers()


@dataclass
class IngestResult:
    file_name: str
    doc_sha256: str
    chunks_indexed: int
    skipped: bool
    reason: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_bytes(
    *,
    content: bytes,
    file_name: str,
    source_uri: str | None = None,
    tenant_id: str | None = None,
    tags: list[str] | None = None,
    parser_hint: str | None = None,
    sink: WeaviateSink | None = None,
    chunker=None,
    embedder=None,
) -> IngestResult:
    s = get_settings()
    tenant_id = tenant_id or s.default_tenant_id
    tags = tags or []
    source_uri = source_uri or f"upload://{file_name}"

    sink = sink or WeaviateSink()
    sink.ensure_schema()

    sha = _sha256(content)
    if sink.already_indexed(sha, tenant_id):
        return IngestResult(
            file_name=file_name,
            doc_sha256=sha,
            chunks_indexed=0,
            skipped=True,
            reason="already indexed",
        )

    mime, _ = mimetypes.guess_type(file_name)
    mime = mime or "application/octet-stream"

    raw = RawDocument(
        source_uri=source_uri,
        file_name=file_name,
        mime_type=mime,
        content=content,
        tenant_id=tenant_id,
        tags=tags,
    )

    # ── Stage 1: Parse ─────────────────────────────────────────────────────
    # Use UnstructuredParser for element/semantic strategies; else registry
    strategy = getattr(s, "chunk_strategy", "element")
    if strategy in ("element", "semantic"):
        try:
            from src.ingestion.parsers.unstructured_parser import UnstructuredParser
            parser = UnstructuredParser()
        except ImportError:
            log.warning("unstructured not installed; falling back to registry parser")
            parser = select_parser(file_name, mime, parser_hint)
    else:
        parser = select_parser(file_name, mime, parser_hint)

    blocks = list(parser.parse(raw))
    if not blocks:
        return IngestResult(
            file_name=file_name,
            doc_sha256=sha,
            chunks_indexed=0,
            skipped=True,
            reason="empty parse output",
        )

    # ── Stage 2: Chunk ─────────────────────────────────────────────────────
    active_chunker = chunker or get_chunker(s)
    chunks: list[Chunk] = list(active_chunker.chunk(blocks))
    if not chunks:
        return IngestResult(
            file_name=file_name,
            doc_sha256=sha,
            chunks_indexed=0,
            skipped=True,
            reason="no chunks produced",
        )

    # ── Stage 3: Enrich ────────────────────────────────────────────────────
    if getattr(s, "enrich_enabled", True):
        enricher_chain = build_enricher_chain(
            top_n_keywords=getattr(s, "enrich_keywords_top_n", 5)
        )
        chunks = enricher_chain.enrich_all(chunks, raw)

    # ── Stage 4: Near-duplicate detection ──────────────────────────────────
    dedup_enabled = getattr(s, "dedup_enabled", True)
    deduplicator: MinHashDeduplicator | None = None
    if dedup_enabled:
        deduplicator = MinHashDeduplicator(
            threshold=getattr(s, "dedup_threshold", 0.85),
            num_perm=getattr(s, "dedup_num_perm", 128),
            index_path=getattr(s, "dedup_index_path", "./data/lsh_index.pkl"),
        )
        chunks = deduplicator.process(chunks, sha)

    # ── Stage 5: Embed (skip near-duplicates) ──────────────────────────────
    embed_chunks = [c for c in chunks if not c.extra.get("is_duplicate", False)]
    dupe_chunks  = [c for c in chunks if c.extra.get("is_duplicate", False)]
    log.info(
        "%s: %d chunks total, %d unique, %d near-duplicates skipped",
        file_name, len(chunks), len(embed_chunks), len(dupe_chunks),
    )

    if embed_chunks:
        if embedder is None:
            embed_strategy = getattr(s, "embed_strategy", "async")
            if embed_strategy == "async":
                embedder = AsyncOllamaBatchEmbedder(
                    batch_size=s.embed_batch_size,
                    max_concurrent=getattr(s, "embed_max_concurrent_batches", 4),
                )
            else:
                embedder = OllamaBatchEmbedder(batch_size=s.embed_batch_size)

        vectors = embedder.embed([c.text for c in embed_chunks])
    else:
        vectors = []

    # ── Stage 6: Build IngestRecords + sink ────────────────────────────────
    created  = now_utc()
    ingested = created
    records: list[IngestRecord] = []

    # Unique chunks with vectors
    for c, v in zip(embed_chunks, vectors):
        records.append(_build_record(
            c, v, tenant_id, sha, source_uri, file_name, mime,
            parser.name, tags, created, ingested,
        ))

    # Duplicate chunks: store with empty vector (no embedding cost)
    for c in dupe_chunks:
        records.append(_build_record(
            c, [], tenant_id, sha, source_uri, file_name, mime,
            parser.name, tags, created, ingested,
        ))

    written = sink.upsert(records)

    # Persist LSH index after successful upsert
    if deduplicator is not None:
        deduplicator.save()

    log.info("ingested %s: %d/%d chunks written (%s)", file_name, written, len(chunks), sha[:12])
    return IngestResult(
        file_name=file_name,
        doc_sha256=sha,
        chunks_indexed=written,
        skipped=False,
    )


def _build_record(
    c: Chunk,
    vector: list[float],
    tenant_id: str,
    sha: str,
    source_uri: str,
    file_name: str,
    mime: str,
    parser_name: str,
    tags: list,
    created,
    ingested,
) -> IngestRecord:
    """Build a fully-populated IngestRecord from a Chunk and its vector."""
    ex = c.extra
    return IngestRecord(
        text=c.text,
        vector=vector,
        tenant_id=tenant_id,
        doc_sha256=sha,
        source_uri=source_uri,
        file_name=file_name,
        mime_type=mime,
        format=parser_name,
        chunk_index=c.chunk_index,
        page=c.page,
        section=c.section,
        language=ex.get("language"),
        tags=tags,
        created_at=created,
        ingested_at=ingested,
        extra=ex,
        # v2 enriched fields
        element_type=ex.get("element_type"),
        hierarchy_path=ex.get("hierarchy_path"),
        ancestral_headings=ex.get("ancestral_headings", []),
        breadcrumb=ex.get("breadcrumb"),
        hierarchy_depth=ex.get("hierarchy_depth", 0),
        keywords=ex.get("keywords", []),
        confidence_score=ex.get("confidence_score", 0.75),
        is_duplicate=ex.get("is_duplicate", False),
        duplicate_of=ex.get("duplicate_of"),
    )


def ingest_path(
    path: str | Path,
    *,
    tenant_id: str | None = None,
    tags: list[str] | None = None,
    parser_hint: str | None = None,
    sink: WeaviateSink | None = None,
    chunker=None,
    embedder=None,
) -> IngestResult:
    p = Path(path)
    content = p.read_bytes()
    return ingest_bytes(
        content=content,
        file_name=p.name,
        source_uri=p.resolve().as_uri(),
        tenant_id=tenant_id,
        tags=tags,
        parser_hint=parser_hint,
        sink=sink,
        chunker=chunker,
        embedder=embedder,
    )


def ingest_directory(
    directory: str | Path,
    *,
    tenant_id: str | None = None,
    tags: list[str] | None = None,
    recursive: bool = True,
    sink: WeaviateSink | None = None,
) -> list[IngestResult]:
    d = Path(directory)
    if not d.exists():
        raise FileNotFoundError(d)
    iterator = d.rglob("*") if recursive else d.glob("*")
    s = get_settings()
    sink = sink or WeaviateSink()
    chunker  = get_chunker(s)
    if getattr(s, "embed_strategy", "async") == "async":
        embedder = AsyncOllamaBatchEmbedder(
            batch_size=s.embed_batch_size,
            max_concurrent=getattr(s, "embed_max_concurrent_batches", 4),
        )
    else:
        embedder = OllamaBatchEmbedder(batch_size=s.embed_batch_size)

    results: list[IngestResult] = []
    for p in iterator:
        if not p.is_file():
            continue
        try:
            results.append(
                ingest_path(
                    p,
                    tenant_id=tenant_id,
                    tags=tags,
                    sink=sink,
                    chunker=chunker,
                    embedder=embedder,
                )
            )
        except Exception as e:
            log.exception("failed to ingest %s", p)
            results.append(
                IngestResult(
                    file_name=p.name,
                    doc_sha256="",
                    chunks_indexed=0,
                    skipped=True,
                    reason=f"error: {e}",
                )
            )
    return results

