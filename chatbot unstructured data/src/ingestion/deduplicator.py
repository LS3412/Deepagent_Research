"""MinHash LSH near-duplicate detection for the v2 ingestion pipeline.

Uses datasketch MinHash + LSH for O(1) near-duplicate lookup.
Scales to 100K+ documents without slowdown.

The LSH index is persisted to disk so deduplication is cross-session:
    First ingest:  build index, save to lsh_index.pkl
    Next ingest:   load index, detect dupes against all previously indexed chunks

Near-duplicate chunks (Jaccard similarity >= threshold) are flagged with:
    chunk.extra["is_duplicate"] = True
    chunk.extra["duplicate_of"] = "<original_chunk_key>"

Duplicate chunks are NOT embedded, saving compute and storage.
Degrades gracefully if datasketch is not installed.
"""
from __future__ import annotations

import logging
import os
import pickle

from src.ingestion.interfaces import Chunk

log = logging.getLogger(__name__)


class MinHashDeduplicator:
    """Near-duplicate chunk detection via MinHash Locality-Sensitive Hashing."""

    def __init__(
        self,
        threshold: float = 0.85,
        num_perm: int = 128,
        index_path: str = "./data/lsh_index.pkl",
    ) -> None:
        self.threshold  = threshold
        self.num_perm   = num_perm
        self.index_path = index_path
        self._lsh       = None
        self._available: bool | None = None

    # ── availability ──────────────────────────────────────────────────────────

    def _is_available(self) -> bool:
        if self._available is None:
            try:
                import datasketch  # noqa: F401
                self._available = True
            except ImportError:
                log.warning(
                    "datasketch not installed — near-duplicate detection disabled. "
                    "Run: pip install datasketch"
                )
                self._available = False
        return self._available

    # ── LSH index ─────────────────────────────────────────────────────────────

    def _get_lsh(self):
        if self._lsh is None:
            from datasketch import MinHashLSH  # type: ignore
            if os.path.exists(self.index_path):
                try:
                    with open(self.index_path, "rb") as fh:
                        self._lsh = pickle.load(fh)
                    log.info("LSH index loaded from %s", self.index_path)
                except Exception as exc:
                    log.warning("could not load LSH index (%s) — creating fresh", exc)
                    self._lsh = MinHashLSH(
                        threshold=self.threshold, num_perm=self.num_perm
                    )
            else:
                self._lsh = MinHashLSH(
                    threshold=self.threshold, num_perm=self.num_perm
                )
        return self._lsh

    # ── MinHash computation ───────────────────────────────────────────────────

    def _minhash(self, text: str):
        from datasketch import MinHash  # type: ignore
        m = MinHash(num_perm=self.num_perm)
        t = text.lower()
        for i in range(max(len(t) - 2, 1)):
            m.update(t[i:i + 3].encode("utf-8"))
        return m

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, chunks: list[Chunk], doc_sha256: str = "") -> list[Chunk]:
        """Flag near-duplicate chunks; non-duplicates are added to the index.

        Args:
            chunks:     Enriched chunks to check.
            doc_sha256: SHA256 of the parent document (used to build unique keys).

        Returns:
            Same list with ``is_duplicate`` and ``duplicate_of`` set in extra.
        """
        if not self._is_available():
            for c in chunks:
                c.extra.setdefault("is_duplicate", False)
                c.extra.setdefault("duplicate_of", None)
            return chunks

        lsh = self._get_lsh()
        result: list[Chunk] = []

        for chunk in chunks:
            mh  = self._minhash(chunk.text)
            key = f"{doc_sha256}_{chunk.chunk_index}"

            try:
                candidates = lsh.query(mh)
                # Exclude matches from the same document — re-ingesting the
                # same file after deletion must not self-deduplicate.
                candidates = [c for c in candidates if not c.startswith(doc_sha256)]
            except Exception as exc:
                log.debug("LSH query failed for %s: %s", key, exc)
                candidates = []

            if candidates:
                chunk.extra["is_duplicate"] = True
                chunk.extra["duplicate_of"] = candidates[0]
                log.debug("near-duplicate: chunk %s ≈ %s", key, candidates[0])
            else:
                chunk.extra["is_duplicate"] = False
                chunk.extra["duplicate_of"] = None
                try:
                    lsh.insert(key, mh)
                except Exception as exc:
                    log.debug("LSH insert failed for %s: %s", key, exc)

            result.append(chunk)

        return result

    def save(self) -> None:
        """Persist the LSH index to disk for cross-session deduplication."""
        if self._lsh is None:
            return
        try:
            parent = os.path.dirname(self.index_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.index_path, "wb") as fh:
                pickle.dump(self._lsh, fh)
            log.debug("LSH index saved → %s", self.index_path)
        except Exception as exc:
            log.warning("could not save LSH index: %s", exc)
