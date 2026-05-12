"""Chunkers for the v2 ingestion pipeline.

Three strategies are available:

    recursive  — original character-based recursive split (fast, no deps)
    element    — UnstructuredElementChunker: keeps Tables/Titles intact, splits prose
    semantic   — SemanticChunker: sentence-level, cosine-similarity breakpoints
                 (requires spacy and sentence-transformers)

Use get_chunker(settings) to select the right chunker automatically.
"""
from __future__ import annotations

import logging
from typing import Iterable, TYPE_CHECKING

from src.config import get_settings
from src.ingestion.interfaces import Block, Chunk

if TYPE_CHECKING:
    from src.config import Settings

log = logging.getLogger(__name__)

# Element types that must never be broken mid-chunk
_INTACT_TYPES = frozenset({"Table", "Title", "Header", "Footer", "Image"})

_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


def _split(text: str, size: int, overlap: int, seps: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    sep = seps[0] if seps else ""
    parts: list[str] = text.split(sep) if sep else list(text)
    out: list[str] = []
    buf = ""
    for part in parts:
        cand = buf + (sep if buf else "") + part
        if len(cand) <= size:
            buf = cand
        else:
            if buf:
                out.append(buf)
            if len(part) > size and len(seps) > 1:
                out.extend(_split(part, size, overlap, seps[1:]))
                buf = ""
            else:
                buf = part
    if buf:
        out.append(buf)

    if overlap > 0 and len(out) > 1:
        with_overlap: list[str] = []
        for i, piece in enumerate(out):
            if i == 0:
                with_overlap.append(piece)
            else:
                tail = out[i - 1][-overlap:]
                with_overlap.append(tail + piece)
        out = with_overlap
    return [p for p in out if p.strip()]


class RecursiveChunker:
    def __init__(self, size: int | None = None, overlap: int | None = None) -> None:
        s = get_settings()
        self.size = size or s.chunk_size
        self.overlap = overlap or s.chunk_overlap

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]:
        idx = 0
        for block in blocks:
            for piece in _split(block.text, self.size, self.overlap, _SEPARATORS):
                yield Chunk(
                    text=piece,
                    chunk_index=idx,
                    page=block.page,
                    section=block.section,
                    extra=dict(block.extra),
                )
                idx += 1


# ─────────────────────────────────────────────────────────────────────────────
# Element-aware chunker  (v2)
# ─────────────────────────────────────────────────────────────────────────────

class UnstructuredElementChunker:
    """Respect Unstructured element boundaries when splitting.

    Tables, Titles, Headers, Footers, and Images are kept as a single chunk
    even if they exceed ``size``.  All other elements are split with the same
    recursive algorithm as RecursiveChunker.
    """

    def __init__(self, size: int | None = None, overlap: int | None = None) -> None:
        s = get_settings()
        self.size    = size    or s.chunk_size
        self.overlap = overlap or s.chunk_overlap

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]:
        idx = 0
        for block in blocks:
            el_type = block.extra.get("element_type", "NarrativeText")
            if el_type in _INTACT_TYPES:
                # Emit as a single chunk regardless of size
                yield Chunk(
                    text=block.text,
                    chunk_index=idx,
                    page=block.page,
                    section=block.section,
                    extra={
                        **block.extra,
                        "heading_chain_texts": block.heading_chain_texts,
                    },
                )
                idx += 1
            else:
                for piece in _split(block.text, self.size, self.overlap, _SEPARATORS):
                    yield Chunk(
                        text=piece,
                        chunk_index=idx,
                        page=block.page,
                        section=block.section,
                        extra={
                            **block.extra,
                            "heading_chain_texts": block.heading_chain_texts,
                        },
                    )
                    idx += 1


# ─────────────────────────────────────────────────────────────────────────────
# Semantic chunker  (v2)
# ─────────────────────────────────────────────────────────────────────────────

class SemanticChunker:
    """Sentence-level chunker that merges sentences into chunks using cosine similarity.

    A new chunk starts whenever consecutive sentence similarity drops below
    *threshold*.  Requires spacy and sentence-transformers; falls back to
    ``RecursiveChunker`` if either is unavailable.
    """

    def __init__(
        self,
        size: int | None = None,
        overlap: int | None = None,
        threshold: float | None = None,
    ) -> None:
        s = get_settings()
        self.size      = size      or s.chunk_size
        self.overlap   = overlap   or s.chunk_overlap
        self.threshold = threshold if threshold is not None else s.semantic_chunk_threshold
        self._nlp      = None
        self._encoder  = None
        self._fallback: RecursiveChunker | None = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy  # type: ignore
                try:
                    self._nlp = spacy.load("en_core_web_sm")
                except OSError:
                    log.warning(
                        "spacy model 'en_core_web_sm' not found \u2014 "
                        "run: python -m spacy download en_core_web_sm"
                    )
                    self._nlp = False
            except ImportError:
                log.warning(
                    "spacy not installed \u2014 SemanticChunker will fall back to RecursiveChunker. "
                    "Run: pip install spacy"
                )
                self._nlp = False
        return self._nlp

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
                self._encoder = SentenceTransformer("BAAI/bge-m3")
                log.info("SemanticChunker: SentenceTransformer ready (BAAI/bge-m3)")
            except ImportError:
                log.warning(
                    "sentence-transformers not installed \u2014 SemanticChunker will fall back. "
                    "Run: pip install sentence-transformers"
                )
                self._encoder = False
        return self._encoder

    def _cosine(self, a, b) -> float:
        import numpy as np  # type: ignore
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def chunk(self, blocks: Iterable[Block]) -> Iterable[Chunk]:
        nlp     = self._get_nlp()
        encoder = self._get_encoder()

        if not nlp or not encoder:
            if self._fallback is None:
                self._fallback = RecursiveChunker(self.size, self.overlap)
            yield from self._fallback.chunk(blocks)
            return

        idx = 0
        import numpy as np  # type: ignore

        for block in blocks:
            el_type = block.extra.get("element_type", "NarrativeText")
            if el_type in _INTACT_TYPES:
                yield Chunk(
                    text=block.text,
                    chunk_index=idx,
                    page=block.page,
                    section=block.section,
                    extra={
                        **block.extra,
                        "heading_chain_texts": block.heading_chain_texts,
                    },
                )
                idx += 1
                continue

            doc       = nlp(block.text)
            sentences = [s.text.strip() for s in doc.sents if s.text.strip()]
            if not sentences:
                continue

            embeddings = encoder.encode(sentences, show_progress_bar=False)

            current_sents: list[str] = [sentences[0]]
            current_buf = sentences[0]

            for i in range(1, len(sentences)):
                sim = self._cosine(embeddings[i - 1], embeddings[i])
                candidate = current_buf + " " + sentences[i]

                if sim >= self.threshold and len(candidate) <= self.size:
                    current_sents.append(sentences[i])
                    current_buf = candidate
                else:
                    yield Chunk(
                        text=current_buf,
                        chunk_index=idx,
                        page=block.page,
                        section=block.section,
                        extra={
                            **block.extra,
                            "heading_chain_texts": block.heading_chain_texts,
                        },
                    )
                    idx += 1
                    current_sents = [sentences[i]]
                    current_buf   = sentences[i]

            if current_buf:
                yield Chunk(
                    text=current_buf,
                    chunk_index=idx,
                    page=block.page,
                    section=block.section,
                    extra={
                        **block.extra,
                        "heading_chain_texts": block.heading_chain_texts,
                    },
                )
                idx += 1


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_chunker(settings: "Settings | None" = None):
    """Return the chunker selected by *settings.chunk_strategy*.

    Strategy values:
        "element"   → UnstructuredElementChunker  (default, recommended)
        "semantic"  → SemanticChunker
        "recursive" → RecursiveChunker  (legacy)
    """
    s = settings or get_settings()
    strategy = getattr(s, "chunk_strategy", "element")
    if strategy == "semantic":
        return SemanticChunker(s.chunk_size, s.chunk_overlap, s.semantic_chunk_threshold)
    if strategy == "recursive":
        return RecursiveChunker(s.chunk_size, s.chunk_overlap)
    # Default: element
    return UnstructuredElementChunker(s.chunk_size, s.chunk_overlap)
