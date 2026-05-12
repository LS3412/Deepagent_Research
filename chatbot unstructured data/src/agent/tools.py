"""LangChain tools wrapping the retrieval layer.

Tenant ID is bound at agent-build time via a closure so the LLM never has to
pass it (and can't override it).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.tools import tool

from src.config import get_settings
from src.retrieval import search as r

log = logging.getLogger(__name__)


def make_tools(tenant_id: str | None = None, slim: bool = False) -> list[Callable]:
    """Build LangChain tools for the given tenant.

    Args:
        tenant_id: Weaviate tenant to scope searches to.
        slim: When True (GitHub Models mode), return only ``hybrid_search`` with
              a minimal docstring to stay within the 4 000-token request limit.
    """
    s = get_settings()
    tid = tenant_id or s.default_tenant_id

    if slim:
        @tool
        def hybrid_search(query: str, k: int = 6) -> list[dict[str, Any]]:
            """Search the knowledge base. Returns list of text chunks with source metadata."""
            log.info("hybrid_search  tenant=%s  query=%r  k=%d", tid, query, k)
            results = r.hybrid_search(query=query, tenant_id=tid, k=k)
            log.debug("hybrid_search returned %d hits (after score filter)", len(results))
            if not results:
                return "NO_RELEVANT_RESULTS: The knowledge base contains no chunks relevant to this query. Use the standard not-found reply."
            return results

        return [hybrid_search]

    @tool
    def hybrid_search(
        query: str,
        k: int = 6,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid (BM25 + vector) search over the knowledge base.

        Args:
            query: Natural-language search query.
            k: Number of hits to return (default 6).
            filters: Optional dict with any of:
                file_name (str), doc_sha256 (str), format (str),
                language (str), tags (list[str]), page_range ([lo, hi]).

        Returns:
            List of hits: text, file_name, page, section, chunk_index, format,
            tags, doc_sha256, source_uri, score.
        """
        log.info("hybrid_search  tenant=%s  query=%r  k=%d  filters=%s", tid, query, k, filters)
        results = r.hybrid_search(query=query, tenant_id=tid, k=k, filters=filters)
        log.debug("hybrid_search returned %d hits (after score filter)", len(results))
        if not results:
            return "NO_RELEVANT_RESULTS: The knowledge base contains no chunks relevant to this query. Use the standard not-found reply."
        return results

    @tool
    def list_documents(prefix: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """List indexed documents (deduped by doc_sha256). Optionally filter by file_name prefix."""
        log.info("list_documents  tenant=%s  prefix=%r  limit=%d", tid, prefix, limit)
        results = r.list_documents(tenant_id=tid, prefix=prefix, limit=limit)
        log.debug("list_documents returned %d docs", len(results))
        return results

    @tool
    def get_chunk(doc_sha256: str, chunk_index: int) -> dict[str, Any] | None:
        """Fetch a specific chunk by document hash + chunk index for context expansion."""
        log.info("get_chunk  tenant=%s  sha=%s  chunk=%d", tid, doc_sha256[:12], chunk_index)
        result = r.get_chunk(doc_sha256=doc_sha256, chunk_index=chunk_index, tenant_id=tid)
        log.debug("get_chunk hit=%s", result is not None)
        return result

    return [hybrid_search, list_documents, get_chunk]
